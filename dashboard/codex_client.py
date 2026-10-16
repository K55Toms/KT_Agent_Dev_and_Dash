"""Small JSONL App Server client. No transcripts, stderr or raw payload logging."""

import json
import subprocess
import threading


class ProtocolError(Exception):
    """A deliberately payload-free transport failure."""


class RequestRejected(ProtocolError):
    """The server returned an explicit JSON-RPC error, without exposing its content."""


class CodexClient:
    def __init__(self, on_message, on_disconnect, process_factory=subprocess.Popen):
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.process_factory = process_factory
        self.process = None
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.pending = {}
        self.sequence = 0
        self.closed = False

    def connect(self):
        # Fixed argv. The user CLI retains authentication and administrator policy.
        self.process = self.process_factory(
            ["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        response = self.request("initialize", {
            "clientInfo": {"name": "engineering_dashboard", "title": "Engineering dashboard", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        })
        self._write({"method": "initialized", "params": {}})
        return response

    def _write(self, message):
        with self.write_lock:
            if self.closed or not self.process:
                raise ProtocolError("Codex connection is unavailable")
            try:
                self.process.stdin.write(json.dumps(message, allow_nan=False) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise ProtocolError("Codex connection is unavailable") from None

    def request(self, method, params, timeout=30):
        with self.lock:
            self.sequence += 1
            key = "dashboard-" + str(self.sequence)
            waiter = {"event": threading.Event()}
            self.pending[key] = waiter
        try:
            self._write({"id": key, "method": method, "params": params})
            if not waiter["event"].wait(timeout):
                # A timed-out mutation may have executed. Disconnect instead of retrying it.
                self.close()
                raise ProtocolError("Codex response timed out; no run will be replayed")
            if waiter.get("rejected"):
                raise RequestRejected("Codex rejected the request; raw details are withheld")
            if "result" not in waiter:
                raise ProtocolError("Codex response was lost; execution state is unknown")
            return waiter["result"]
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def respond(self, request_id, result):
        self._write({"id": request_id, "result": result})

    def reject(self, request_id):
        self._write({"id": request_id, "error": {"code": -32601, "message": "Unsupported dashboard request"}})

    def _read(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(16 * 1024 * 1024 + 1)
                if not line or len(line) > 16 * 1024 * 1024:
                    break
                message = json.loads(line)
                if not isinstance(message, dict):
                    break
                if "method" not in message and "id" in message:
                    with self.lock:
                        waiter = self.pending.get(message["id"])
                        if waiter:
                            if "result" in message:
                                waiter["result"] = message["result"]
                            elif isinstance(message.get("error"), dict):
                                error = message["error"]
                                if type(error.get("code")) is int and isinstance(error.get("message"), str):
                                    waiter["rejected"] = True
                            waiter["event"].set()
                elif "method" in message:
                    self.on_message(message)
        except Exception:
            # Malformed/unexpected protocol shapes fail closed without payload disclosure.
            pass
        finally:
            self.close()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for waiter in self.pending.values():
                waiter["event"].set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            except OSError:
                pass
            for pipe in (self.process.stdin, self.process.stdout):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
        self.on_disconnect()

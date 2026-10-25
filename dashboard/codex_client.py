"""Small JSONL App Server client. No transcripts, stderr or raw payload logging."""

import errno
import json
import os
import re
import select
import time
import subprocess
import threading

from .diagnostics import classify_error, DETAILS


class ProtocolError(Exception):
    """A deliberately payload-free transport failure."""


class RequestRejected(ProtocolError):
    """The server returned an explicit JSON-RPC error, without exposing its content."""

    def __init__(self, message=None, *, code="request_rejected"):
        self.diagnostic_code = code if code in DETAILS else "request_rejected"
        # Ignore caller/upstream strings. Exceptions remain safe even when inspected.
        super().__init__(DETAILS[self.diagnostic_code][0])


MAX_WRITE_BYTES = 16 * 1024 * 1024
WRITE_TIMEOUT = 3.0


class _WireFailure(Exception):
    """Internal fixed marker; never retain OS errors or partial payloads."""


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
        self.cleanup_complete = threading.Event()
        self.cleanup_worker = None

    def connect(self):
        # Fixed argv. The user CLI retains authentication and administrator policy.
        with self.lock:
            if self.closed or self.process is not None:
                raise ProtocolError('A native client cannot be reconnected or reused')
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

    def _write(self, message, guard=None):
        deadline = time.monotonic() + WRITE_TIMEOUT
        try:
            frame = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise ProtocolError("Native request could not be encoded") from None
        if len(frame) > MAX_WRITE_BYTES:
            raise ProtocolError("Native request exceeds the transport limit")
        try:
            if guard is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.write_lock.acquire(timeout=remaining):
                    raise ProtocolError("Native writer is busy; no request was sent")
                try:
                    self._bounded_frame_write(frame, deadline)
                finally:
                    self.write_lock.release()
                return
            while True:
                if deadline - time.monotonic() <= 0:
                    raise ProtocolError("Native writer is busy; no request was sent")
                # The caller may hold the dashboard lock. Never wait for the writer
                # while holding that guard: callbacks use dashboard -> writer too.
                with guard() as validate:
                    if not callable(validate):
                        raise TypeError("A request guard must yield its final validator")
                    if self.write_lock.acquire(blocking=False):
                        try:
                            if deadline - time.monotonic() <= 0:
                                raise ProtocolError("Native writer is busy; no request was sent")
                            validate()
                            self._bounded_frame_write(frame, deadline)
                            return
                        finally:
                            self.write_lock.release()
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.write_lock.acquire(timeout=remaining):
                    raise ProtocolError("Native writer is busy; no request was sent")
                self.write_lock.release()
        except _WireFailure:
            # A partial frame is ambiguous. Close only after BOTH authority and
            # writer locks are released, so disconnect callbacks cannot deadlock.
            self.close(wait=False)
            raise ProtocolError("Native write failed; delivery is unknown and will not be retried") from None

    def _bounded_frame_write(self, frame, deadline):
        if self.closed or not self.process:
            raise ProtocolError("Codex connection is unavailable")
        descriptor, blocking = None, None
        try:
            descriptor = self.process.stdin.fileno()
            blocking = os.get_blocking(descriptor)
            os.set_blocking(descriptor, False)
            view = memoryview(frame)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _WireFailure()
                try:
                    with self.lock:
                        if self.closed:
                            raise _WireFailure()
                        written = os.write(descriptor, view[:65536])
                    if written <= 0:
                        raise _WireFailure()
                    view = view[written:]
                except OSError as error:
                    if error.errno == errno.EINTR:
                        continue
                    if error.errno not in {errno.EAGAIN, errno.EWOULDBLOCK}:
                        raise _WireFailure() from None
                    try:
                        select.select([], [descriptor], [], remaining)
                    except OSError as interrupted:
                        if interrupted.errno != errno.EINTR:
                            raise _WireFailure() from None
        except (OSError, ValueError, AttributeError):
            raise _WireFailure() from None
        finally:
            if descriptor is not None and blocking is not None:
                try:
                    os.set_blocking(descriptor, blocking)
                except (OSError, ValueError):
                    raise _WireFailure() from None

    def request(self, method, params, timeout=30):
        return self._request(method, params, timeout=timeout)

    def request_readonly(self, method, params, timeout=30):
        """Only bounded metadata reads may time out without stopping shared work."""
        shapes = {
            'thread/read': ({'threadId', 'includeTurns'}, set()),
            'thread/list': ({'ancestorThreadId', 'archived', 'useStateDbOnly', 'limit'}, {'cursor'}),
            'thread/turns/list': ({'threadId', 'itemsView', 'sortDirection', 'limit'}, {'cursor'}),
            'thread/goal/get': ({'threadId'}, set()),
            'thread/backgroundTerminals/list': ({'threadId', 'limit'}, {'cursor'}),
            'thread/loaded/list': ({'limit'}, {'cursor'}),
        }
        shape = shapes.get(method) if isinstance(method, str) else None
        if shape is None or not isinstance(params, dict):
            raise ProtocolError('Unsupported read-only metadata request')
        params = params.copy()
        required, optional = shape
        if not required <= params.keys() or params.keys() - required - optional:
            raise ProtocolError('Unsupported read-only metadata parameters')
        for key, value in params.items():
            if key in {'threadId', 'ancestorThreadId'}:
                valid = isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', value)
            elif key == 'limit':
                valid = type(value) is int and 1 <= value <= (256 if method == 'thread/loaded/list' else 100)
            elif key == 'cursor':
                valid = isinstance(value, str) and 1 <= len(value) <= 4096
            elif key == 'archived':
                valid = type(value) is bool
            else:
                expected = {'includeTurns': False, 'useStateDbOnly': True,
                            'itemsView': 'notLoaded', 'sortDirection': 'desc'}[key]
                valid = type(value) is type(expected) and value == expected
            if not valid:
                raise ProtocolError('Unsupported read-only metadata parameters')
        return self._request(method, params, timeout=timeout, readonly=True)

    def request_guarded(self, method, params, guard, timeout=30):
        """Guard the final bounded wire write, never the response wait.

        The context-manager factory acquires caller authority and yields a final
        validator. Only after a nonblocking writer acquisition is that validator
        called; guard entry must not journal dispatch. Writer contention releases
        the guard before waiting and retrying. Entry/validation failures send no
        bytes and propagate unchanged. A partial IPC frame is never retried.
        """
        if not callable(guard):
            raise TypeError("A request guard factory is required")
        return self._request(method, params, timeout=timeout, guard=guard)

    def _request(self, method, params, timeout, guard=None, readonly=False):
        deadline = time.monotonic() + timeout
        with self.lock:
            self.sequence += 1
            key = "dashboard-" + str(self.sequence)
            waiter = {"event": threading.Event()}
            self.pending[key] = waiter
        try:
            message = {"id": key, "method": method, "params": params}
            if guard is None:
                self._write(message)
            else:
                self._write(message, guard=guard)
            if not waiter["event"].wait(max(0, deadline - time.monotonic())):
                if readonly:
                    raise ProtocolError('Codex metadata response timed out; shared work was not interrupted')
                # A timed-out mutation may have executed. Disconnect instead of retrying it.
                self.close()
                raise ProtocolError("Codex response timed out; no run will be replayed")
            if waiter.get("rejected"):
                raise RequestRejected(code=waiter.get("diagnostic_code", "request_rejected"))
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
                                    waiter["diagnostic_code"] = classify_error(error)
                            waiter["event"].set()
                elif "method" in message:
                    self.on_message(message)
        except Exception:
            # Malformed/unexpected protocol shapes fail closed without payload disclosure.
            pass
        finally:
            self.close(wait=False)
            # The reader closes its own TextIO wrapper after readline returns.
            # Another thread must never wait on that wrapper's internal read lock.
            try:
                self.process.stdout.close()
            except (OSError, ValueError, AttributeError):
                pass

    def close(self, wait=True):
        """Revoke writes immediately; explicit callers await bounded cleanup attempts.

        Reader and writer failure paths use ``wait=False`` because callers may
        hold application locks. A later explicit close still waits for cleanup.
        A descendant retaining stdout can keep the daemon reader alive until EOF;
        cleanup does not claim that descendant stopped or join its blocked reader.
        """
        with self.lock:
            first = not self.closed
            if first:
                self.closed = True
                for waiter in self.pending.values():
                    waiter["event"].set()
                self.cleanup_worker = threading.Thread(target=self._cleanup_process, daemon=True)
                self.cleanup_worker.start()
                threading.Thread(target=self._notify_disconnect, daemon=True).start()
        if wait:
            self.cleanup_complete.wait(7)

    def _notify_disconnect(self):
        try:
            self.on_disconnect()
        except Exception:
            # Application callback failure must not print payloads or prevent cleanup.
            pass

    def _cleanup_process(self):
        deadline = time.monotonic() + 6.5
        try:
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        self.process.kill()
                        self.process.wait(timeout=3)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
                except OSError:
                    pass
                remaining = max(0, deadline - time.monotonic())
                if self.write_lock.acquire(timeout=remaining):
                    try:
                        self._close_stdin()
                    finally:
                        self.write_lock.release()
                else:
                    # A caller-supplied validator can outlast the IPC deadline.
                    # Retain ownership of its descriptor until that writer exits.
                    threading.Thread(target=self._close_stdin_after_writer, daemon=True).start()
                reader = getattr(self, 'reader', None)
                if reader is None or not reader.is_alive():
                    try:
                        self.process.stdout.close()
                    except (OSError, ValueError):
                        pass
        finally:
            self.cleanup_complete.set()

    def _close_stdin(self):
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass

    def _close_stdin_after_writer(self):
        with self.write_lock:
            self._close_stdin()

"""Loopback receiver for Claude PermissionRequest hooks of dashboard-managed runs.

A separate ThreadingHTTPServer on 127.0.0.1 (ephemeral port) serving only
``POST /hook/managed/<run token>``. Every request is held until the dashboard resolves it. The reply
is allow only when ``HeldRequest.resolve("allow")`` won the race before any other ending; timeout,
a closed client connection, stop(), unregister_run(), a callback error, a parse failure and the
caps all end in a deny reply (or a dropped connection). Never allow.

Locking: one receiver lock guards the token table and the pending sets; it is never held while the
callback runs, while waiting, or while writing a reply. Handler threads are daemon threads.

No log line, error body or exception text carries the token, the path or any request text.
"""
import hmac
import re
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Optional, Set

import secrets

from .backends.claude_hook import (DEFAULT_WAIT_SECONDS, MAX_BODY, HookRejected, HookRequest,
                                   allow_reply, deny_reply, parse_request)

MAX_PENDING_PER_RUN = 16
MAX_PENDING_TOTAL = 64
MAX_UNHELD = 64
_PATH = re.compile(r"/hook/managed/([A-Za-z0-9_-]{1,128})\Z")
_LENGTH = re.compile(r"[0-9]{1,9}\Z")


class HeldRequest:
    """One hook request awaiting an answer. The first resolve() wins; later calls are no-ops."""

    def __init__(self):
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._decision: Optional[str] = None
        self._closed = False
        self._expired = False

    def resolve(self, decision: str) -> bool:
        """Record the answer if none was recorded yet. Anything but "allow" counts as deny."""
        with self._lock:
            if self._decision is not None:
                return False
            self._decision = "allow" if decision == "allow" else "deny"
        self._event.set()
        return True

    @property
    def decision(self) -> Optional[str]:
        with self._lock:
            return self._decision

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def expired(self) -> bool:
        """True only when the wait ran out before any answer (the reply was then deny)."""
        with self._lock:
            return self._expired

    def mark_closed(self):
        with self._lock:
            self._closed = True
        self.resolve("deny")

    def wait(self, seconds: float, probe: Optional[Callable[[], bool]] = None,
             interval: float = 1.0) -> str:
        """Block until resolved, the time is up, or probe() reports the client gone.

        Returns "allow" only if resolve("allow") came first; every other ending returns "deny".
        """
        deadline = time.monotonic() + seconds
        while not self._event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    if self._decision is None:
                        self._decision, self._expired = "deny", True
                self._event.set()
                break
            self._event.wait(min(interval, remaining))
            if self._event.is_set():
                break
            if probe is not None and probe():
                self.mark_closed()
                break
        self.resolve("deny")
        return self.decision or "deny"


def _client_gone(conn) -> bool:
    try:
        # the connection has a socket timeout, so poll first (poll has no fd-number limit, unlike
        # select); peek only when readable (data or EOF)
        poller = select.poll()
        poller.register(conn.fileno(), select.POLLIN)
        events = poller.poll(0)
        if not events:
            return False
        if events[0][1] & select.POLLNVAL:
            return True
        return conn.recv(1, socket.MSG_PEEK) == b""
    except (BlockingIOError, InterruptedError):
        return False
    except (OSError, ValueError):
        return True


class _Handler(BaseHTTPRequestHandler):
    server_version = "Hook"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    timeout = 10

    # logging is off: paths and errors would carry the token
    def log_message(self, *args):
        pass

    def log_error(self, *args):
        pass

    def log_request(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self._status(code)

    def _status(self, code, body=b""):
        if self.request_version == "HTTP/0.9":
            # a line refused before its version was read: some Python versions would then send nothing
            self.request_version = "HTTP/1.0"
        try:
            self.send_response_only(code)
            if body:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)
        except OSError:
            pass
        self.close_connection = True

    def handle(self):
        receiver = self.server.receiver
        if not receiver._track(True, self.connection):
            return  # too many connections not yet holding a request: drop this one
        self._counted = True
        self._watchdog = threading.Timer(receiver._read_deadline, self._expire)
        self._watchdog.daemon = True
        self._watchdog.start()
        try:
            super().handle()
        finally:
            self._watchdog.cancel()
            receiver._track(False, self.connection, counted=self._counted)

    def _expire(self):
        """Overall deadline for receiving a request (headers and body together)."""
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _held(self):
        """The request is complete and parsed: stop the read deadline and the unheld count."""
        self._watchdog.cancel()
        if self._counted:
            self._counted = False
            self.server.receiver._uncount(self.connection)

    def _refuse(self):
        self._status(405)

    do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _refuse

    def do_POST(self):
        receiver = self.server.receiver
        authority = "127.0.0.1:" + str(self.server.server_port)
        if self.headers.get_all("Host") != [authority] or self.headers.get_all("Origin"):
            return self._status(403)
        match = _PATH.match(self.path)
        if not match:
            return self._status(404)
        if self.headers.get_content_type() != "application/json":
            return self._status(415)
        if self.headers.get("Transfer-Encoding") is not None:
            return self._status(400)
        lengths = self.headers.get_all("Content-Length")
        if not lengths:
            return self._status(411)
        if len(lengths) != 1 or not _LENGTH.match(lengths[0]):
            return self._status(400)
        size = int(lengths[0])
        if size > MAX_BODY:
            return self._status(413)
        token = match.group(1)
        if receiver._task_for(token) is None:
            return self._status(200, deny_reply())
        try:
            body = self.rfile.read(size)
        except OSError:
            return
        if len(body) != size:
            return
        try:
            request = parse_request(body)
        except HookRejected:
            return self._status(200, deny_reply())
        decision = receiver._hold(token, request, self.connection, self._held)
        self._status(200, allow_reply() if decision == "allow" else deny_reply())


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


class HookReceiver:
    def __init__(self, on_request: Callable[[str, HookRequest, HeldRequest], None],
                 wait_seconds: float = DEFAULT_WAIT_SECONDS, poll_interval: float = 1.0,
                 read_deadline: float = 10.0, max_unheld: int = MAX_UNHELD,
                 wait_limit: Optional[Callable[[str], float]] = None,
                 on_done: Optional[Callable[[str, HeldRequest], None]] = None):
        self._on_request = on_request
        # wait_limit(task_id) -> seconds: called at hold time, outside the receiver lock; the hold uses the
        # smaller of it and the run's own wait (it never lengthens a run's wait). An error or a value that is
        # not a positive finite number denies the request without calling on_request.
        self._wait_limit = wait_limit
        # on_done(task_id, held): told once a hold has ended (after the reply decision is fixed, before the
        # reply is written); its errors are ignored and never change the reply.
        self._on_done = on_done
        self._default_wait = self._check_wait(wait_seconds)
        self._poll = poll_interval
        self._read_deadline = read_deadline
        self._max_unheld = max_unheld
        self._unheld = 0
        self._conns: Set[socket.socket] = set()
        self._lock = threading.Lock()
        self._runs: Dict[str, tuple] = {}  # task_id -> (token bytes, wait seconds)
        self._pending: Dict[str, Set[HeldRequest]] = {}
        self._handlers: Set[threading.Thread] = set()
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = False

    @staticmethod
    def _check_wait(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            raise ValueError("wait_invalid")
        return value

    def start(self) -> int:
        with self._lock:
            if self._stopped:
                raise RuntimeError("stopped")
            if self._server is None:
                server = _Server(("127.0.0.1", 0), _Handler)
                server.receiver = self
                self._server = server
                self._thread = threading.Thread(target=server.serve_forever, args=(0.05,),
                                                name="hook-receiver", daemon=True)
                self._thread.start()
            return self._server.server_port

    def stop(self):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            server, thread = self._server, self._thread
            held = [h for items in self._pending.values() for h in items]
            conns = list(self._conns)
            self._runs.clear()
        for item in held:
            item.resolve("deny")
        for conn in conns:  # connections still reading a request
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        me = threading.current_thread()  # stop() may be called from inside the callback
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self._lock:
                handlers = [h for h in self._handlers if h is not me]
            if not handlers:
                break
            for handler in handlers:
                handler.join(max(0.0, deadline - time.monotonic()))
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not me:
            thread.join(3)

    def register_run(self, task_id: str, wait_seconds: Optional[float] = None) -> str:
        wait = self._default_wait if wait_seconds is None else self._check_wait(wait_seconds)
        token = secrets.token_urlsafe(32)
        with self._lock:
            if self._stopped:
                raise RuntimeError("stopped")
            old = list(self._pending.get(task_id, ()))
            self._runs[task_id] = (token.encode("ascii"), wait)
        for item in old:
            item.resolve("deny")
        return token

    def unregister_run(self, task_id: str):
        with self._lock:
            self._runs.pop(task_id, None)
            held = list(self._pending.get(task_id, ()))
        for item in held:
            item.resolve("deny")

    def url_for(self, token: str) -> str:
        with self._lock:
            if self._server is None:
                raise RuntimeError("not_started")
            port = self._server.server_port
        return "http://127.0.0.1:%d/hook/managed/%s" % (port, token)

    # --- handler side ---

    def _track(self, entering: bool, conn=None, counted: bool = False) -> bool:
        thread = threading.current_thread()
        with self._lock:
            if entering:
                if self._unheld >= self._max_unheld or self._stopped:
                    return False
                self._unheld += 1
                self._handlers.add(thread)
                self._conns.add(conn)
                return True
            self._handlers.discard(thread)
            self._conns.discard(conn)
            if counted:
                self._unheld -= 1
        return True

    def _uncount(self, conn):
        with self._lock:
            self._unheld -= 1
            self._conns.discard(conn)

    def _lookup(self, token: str):
        """Constant-time scan of every registered token; caller holds the lock."""
        candidate = token.encode("ascii", "replace")
        found = None
        for task_id, (known, wait) in self._runs.items():
            if hmac.compare_digest(known, candidate):
                found = (task_id, wait)
        return found

    def _task_for(self, token: str):
        with self._lock:
            found = None if self._stopped else self._lookup(token)
        return found[0] if found else None

    def _hold(self, token: str, request: HookRequest, conn, on_held=None) -> str:
        held = HeldRequest()
        with self._lock:
            found = None if self._stopped else self._lookup(token)
            if found is None:
                return "deny"
            task_id, wait = found
            total = sum(len(items) for items in self._pending.values())
            mine = self._pending.get(task_id, ())
            if len(mine) >= MAX_PENDING_PER_RUN or total >= MAX_PENDING_TOTAL:
                return "deny"
            self._pending.setdefault(task_id, set()).add(held)
        if on_held is not None:
            on_held()
        try:
            if self._wait_limit is not None:
                try:
                    limit = self._wait_limit(task_id)
                    if (isinstance(limit, bool) or not isinstance(limit, (int, float))
                            or not 0 < limit < float("inf")):
                        raise ValueError("wait_limit")
                    wait = min(wait, limit)
                except Exception:
                    held.resolve("deny")
                    return "deny"
            try:
                self._on_request(task_id, request, held)
            except Exception:
                held.resolve("deny")
            return held.wait(wait, lambda: _client_gone(conn), self._poll)
        finally:
            held.resolve("deny")  # no-op when already answered; nothing stays undecided after the hold
            with self._lock:
                items = self._pending.get(task_id)
                if items is not None:
                    items.discard(held)
                    if not items:
                        self._pending.pop(task_id, None)
            if self._on_done is not None:
                try:
                    self._on_done(task_id, held)
                except Exception:
                    pass

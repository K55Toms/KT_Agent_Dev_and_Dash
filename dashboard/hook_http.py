"""Shared pieces of the loopback hook listeners: the held request, the closed-connection probe, a
handler base with the Host/Origin guard and strict body reading, and a quiet threading server.

Nothing here logs, and no error body or exception text carries a path, a token or request text.
"""
import re
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

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


def client_gone(conn) -> bool:
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


class HookHandlerBase(BaseHTTPRequestHandler):
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

    def _status(self, code: int, body: bytes = b"") -> None:
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

    def _guard(self, authority: str) -> bool:
        """True when Host is exactly the single header ``authority`` and no Origin header exists.

        Otherwise sends 403 and returns False."""
        if self.headers.get_all("Host") != [authority] or self.headers.get_all("Origin"):
            self._status(403)
            return False
        return True

    def _body_size(self, limit: int) -> Optional[int]:
        """Check content type and length headers; return the declared size.

        Sends 415, 400, 411 or 413 itself and returns None when a check fails."""
        if self.headers.get_content_type() != "application/json":
            self._status(415)
            return None
        if self.headers.get("Transfer-Encoding") is not None:
            self._status(400)
            return None
        lengths = self.headers.get_all("Content-Length")
        if not lengths:
            self._status(411)
            return None
        if len(lengths) != 1 or not _LENGTH.match(lengths[0]):
            self._status(400)
            return None
        size = int(lengths[0])
        if size > limit:
            self._status(413)
            return None
        return size

    def _read_exact(self, size: int) -> Optional[bytes]:
        """Read exactly ``size`` bytes; None, without any reply, when the read fails or falls short."""
        try:
            body = self.rfile.read(size)
        except OSError:
            return None
        if len(body) != size:
            return None
        return body

    def _read_body(self, limit: int) -> Optional[bytes]:
        """Validate the headers (see _body_size) and read the body; None when no body is available."""
        size = self._body_size(limit)
        if size is None:
            return None
        return self._read_exact(size)


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass

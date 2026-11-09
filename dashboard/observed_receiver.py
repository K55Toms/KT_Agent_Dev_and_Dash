"""Loopback listener for the owner's own Claude Code sessions (observed sessions).

A separate ThreadingHTTPServer on 127.0.0.1 at a fixed port (the ``observed_port`` setting; 0 picks an
ephemeral port for tests) serving only ``POST /hook/observed/<install token>``. It shares the handler base
with the managed receiver but has its own token table (the install TokenFile) and never serves
``/hook/managed/...``.

Never block or overrule the terminal (spec 5.1): only the owner's Allow or Deny from the dashboard
(``ObservedSessions.answer``) produces ``allow_reply()`` or ``deny_reply()``. Every other ending of an
authenticated request (expiry, a closed client, the pending cap, stop(), a parse failure, an internal
error) gets the no-decision reply chosen by ``NO_DECISION_MODE``, so Claude Code's own prompt stays in
charge. Events other than PermissionRequest are recorded and answered 200 ``{}`` at once.

Managed runs (R17): dashboard-managed Claude runs load the owner's user-level settings, so observed hooks pasted
there fire for managed runs too. An authenticated event whose ``session_id`` the ``is_managed_session`` callback
reports as a dashboard-managed run is answered 200 ``{}`` at once: nothing is recorded, no card, no hold. The
callback is called outside the receiver lock; an error in it counts as "not managed".

Refusals: a wrong Host or any Origin gets 403; an unknown path or method, or a wrong token, a bare 404
(the token is checked from the headers alone, before the body is read); bad body headers 415/400/411/413.

Locking: one receiver lock guards the handler and hold sets; it is never held while calling the sessions
model, waiting, or writing a reply. No log line, error body or exception text carries the token, the path
or any request text.
"""
import math
import re
import socket
import threading
import time
from typing import Callable, Optional, Set

from .backends.claude_hook import HOOK_TIMEOUT_MARGIN, MAX_BODY, HookRejected, allow_reply, deny_reply
from .hook_http import HeldRequest, HookHandlerBase, QuietServer, client_gone
from .observed_hook import parse_observed
from .observed_token import TokenFileError

# The reply when the dashboard makes no decision (spike S11 picks it): "empty_object" (200 with {}),
# "status_204" (204, no body), "close" (drop the connection), "hold" (keep it open until the client gives up).
NO_DECISION_MODE = "empty_object"
NO_DECISION_MODES = ("empty_object", "status_204", "close", "hold")
EMPTY_OBJECT = b"{}"
MAX_UNHELD = 64
_PATH = re.compile(r"/hook/observed/([A-Za-z0-9_-]{1,128})\Z")


def _positive_finite(value) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and 0 < value < math.inf)  # NaN fails both comparisons


class PortInUse(Exception):
    """The listener port could not be bound. No fallback port is ever chosen."""

    def __init__(self):
        super().__init__("port_in_use")


class TokenUnavailable(Exception):
    """The install token file is unusable; ``reason`` is the TokenFile reason and nothing else."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _Handler(HookHandlerBase):
    def handle(self):
        receiver = self.server.receiver
        if not receiver._track(True, self.connection):
            return  # too many connections not yet holding a request, or stopping: drop this one
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
        """The request is complete and held: stop the read deadline and the unheld count."""
        self._watchdog.cancel()
        if self._counted:
            self._counted = False
            self.server.receiver._uncount(self.connection)

    def send_error(self, code, message=None, explain=None):
        self._status(404 if code == 501 else code)  # an unknown method is an unknown path here

    def _not_found(self):
        self._status(404)

    do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_found

    def do_POST(self):
        receiver = self.server.receiver
        if not self._guard("127.0.0.1:" + str(self.server.server_port)):
            return
        match = _PATH.match(self.path)
        if not match:
            return self._status(404)
        size = self._body_size(MAX_BODY)
        if size is None:
            return
        if not receiver._token_file.matches(match.group(1)):
            return self._status(404)
        data = self._read_exact(size)
        if data is None:
            return
        try:
            reply = receiver._dispatch(data, self.connection, self._held)
        except Exception:
            reply = None
        if reply is None:
            self._no_decision()
        else:
            self._status(200, reply)

    def _no_decision(self):
        mode = NO_DECISION_MODE  # read at call time so the S11 result (or a test) can switch it
        if mode == "status_204":
            self._status_204()
        elif mode == "close":
            self.close_connection = True
        elif mode == "hold":
            self._held()
            self.server.receiver._hold_open(self.connection)
            self.close_connection = True
        else:
            self._status(200, EMPTY_OBJECT)

    def _status_204(self):
        try:
            self.send_response_only(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
        except OSError:
            pass
        self.close_connection = True


class ObservedReceiver:
    def __init__(self, sessions, token_file, port: int, wait_seconds: float = 300, poll_interval: float = 1.0,
                 read_deadline: float = 10.0, max_unheld: int = MAX_UNHELD,
                 is_managed_session: Optional[Callable[[str], bool]] = None):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port_invalid")
        if not _positive_finite(wait_seconds):
            raise ValueError("wait_invalid")
        if not _positive_finite(poll_interval):  # 0 would busy-spin the hold and the "hold" mode loop
            raise ValueError("poll_invalid")
        if not _positive_finite(read_deadline):
            raise ValueError("deadline_invalid")
        if isinstance(max_unheld, bool) or not isinstance(max_unheld, int) or max_unheld < 1:
            raise ValueError("max_unheld_invalid")
        if is_managed_session is not None and not callable(is_managed_session):
            raise ValueError("managed_check_invalid")
        self._is_managed = is_managed_session if is_managed_session is not None else (lambda _session_id: False)
        self._sessions = sessions
        self._token_file = token_file
        self._requested_port = port
        self._wait = wait_seconds
        self._poll = poll_interval
        self._read_deadline = read_deadline
        self._max_unheld = max_unheld
        self._unheld = 0
        self._lock = threading.Lock()
        self._conns: Set[socket.socket] = set()
        self._handlers: Set[threading.Thread] = set()
        self._holds: Set[HeldRequest] = set()
        self._ended_by_stop: Set[HeldRequest] = set()
        self._stopping = threading.Event()
        self._server: Optional[QuietServer] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = False

    @property
    def port(self) -> int:
        """The bound port once started, else the configured one."""
        with self._lock:
            server = self._server
        return server.server_port if server is not None else self._requested_port

    def start(self) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("stopped")
            if self._server is not None:
                return
        try:
            self._token_file.token()  # creates the token on first run
        except TokenFileError as err:
            raise TokenUnavailable(err.reason) from None
        try:
            server = QuietServer(("127.0.0.1", self._requested_port), _Handler)
        except OSError:
            raise PortInUse() from None
        server.receiver = self
        with self._lock:
            if self._stopped or self._server is not None:  # lost a race with stop() or another start()
                server.server_close()
                if self._stopped:
                    raise RuntimeError("stopped")
                return
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, args=(0.05,),
                                            name="observed-receiver", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._stopping.set()
            server, thread = self._server, self._thread
            for held in self._holds:
                if held.resolve("deny"):  # the reply is still no-decision: stop is not the owner's Deny
                    self._ended_by_stop.add(held)
            conns = list(self._conns)
        for conn in conns:  # connections still reading a request
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        me = threading.current_thread()
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

    def _dispatch(self, data: bytes, conn, on_held) -> Optional[bytes]:
        """The reply body for an authenticated request; None means the no-decision reply."""
        try:
            event = parse_observed(data)
        except HookRejected:
            return None
        if self._managed(event.session_id):
            return EMPTY_OBJECT  # a dashboard-managed run: its own hook decides; nothing is shown here
        if event.kind != "permission_request":
            try:
                self._sessions.record(event)
            except Exception:
                pass  # a dashboard error never changes what the terminal sees
            return EMPTY_OBJECT
        return self._hold(event, conn, on_held)

    def _managed(self, session_id) -> bool:
        try:
            return self._is_managed(session_id) is True
        except Exception:  # noqa: BLE001 - never changes what the terminal sees
            return False

    def _hold(self, event, conn, on_held) -> Optional[bytes]:
        held = HeldRequest()
        with self._lock:
            if self._stopped:
                return None
            self._holds.add(held)
        try:
            approval_id = self._sessions.add_pending(event, held, time.time() + self._wait)
            if approval_id is None:
                return None  # pending cap: Claude's own prompt stays in charge
            try:
                on_held()
                held.wait(self._wait, lambda: client_gone(conn), self._poll)
            finally:
                self._sessions.finish(approval_id)  # every card must be finished or the cap fills
            with self._lock:
                by_stop = held in self._ended_by_stop
            # wait() also returns "deny" for expiry and a closed client: only an answer from the
            # dashboard, never one of those endings, may become an allow or a deny reply
            if by_stop or held.expired or held.closed:
                return None
            decision = held.decision
            if decision == "allow":
                return allow_reply()
            if decision == "deny":
                return deny_reply()
            return None
        finally:
            held.resolve("deny")  # no-op when already ended; a late answer then reports closed
            with self._lock:
                self._holds.discard(held)
                self._ended_by_stop.discard(held)

    def _hold_open(self, conn):
        """The "hold" no-decision mode: keep the connection open until the client gives up, stop(), or the
        longest hook timeout the dashboard configures has passed."""
        deadline = time.monotonic() + self._wait + HOOK_TIMEOUT_MARGIN
        while not self._stopping.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or client_gone(conn):
                return
            self._stopping.wait(min(self._poll, remaining))

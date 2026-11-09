"""Tests for the observed-sessions listener (dashboard/observed_receiver.py), using real loopback sockets.

Tokens come from a TokenFile in a temporary folder; every payload is synthetic.
"""
import http.client
import io
import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import observed_receiver  # noqa: E402
from dashboard.backends import claude_hook as hook  # noqa: E402
from dashboard.hook_receiver import HookReceiver  # noqa: E402
from dashboard.observed import ObservedSessions  # noqa: E402
from dashboard.observed_receiver import (NO_DECISION_MODE, ObservedReceiver, PortInUse,  # noqa: E402
                                         TokenUnavailable)
from dashboard.observed_token import TokenFile  # noqa: E402
from dashboard.project_files import SensitiveContentError  # noqa: E402
from dashboard.store import Store  # noqa: E402

ALLOW = hook.allow_reply()
DENY = hook.deny_reply()
EMPTY = b"{}"
MAIN = "00000000-0000-4000-8000-00000000b001"


def fake_scan(data):
    if b"sk-" in data:
        raise SensitiveContentError()


def body(name, session=MAIN, **extra):
    data = {"hook_event_name": name, "session_id": session, "cwd": "/synthetic/projects/alpha"}
    data.update(extra)
    return json.dumps(data).encode()


def permission(command="echo synthetic", **extra):
    return body("PermissionRequest", permission_mode="default", tool_name="Bash",
                tool_input={"command": command}, **extra)


def until(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class Base(unittest.TestCase):
    wait = 5
    max_pending = 32

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(os.path.realpath(temp.name))  # macOS temp folders sit under a symlinked /var
        scanner = patch("dashboard.conversation.scan_preview", side_effect=fake_scan)
        scanner.start()
        self.addCleanup(scanner.stop)
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.token_file = TokenFile(self.root / "config")
        self.threads = []
        self.receivers = []
        self.make()
        self.token = self.token_file.token()
        self.addCleanup(self.check_clean)

    def make(self, wait=None, max_pending=None, sessions=None, **extra):
        if getattr(self, "rx", None) is not None:
            self.rx.stop()
        self.sessions = sessions or ObservedSessions(self.store, max_pending=max_pending or self.max_pending)
        self.rx = ObservedReceiver(self.sessions, self.token_file, 0, wait_seconds=wait or self.wait,
                                   poll_interval=0.05, **extra)
        self.receivers.append(self.rx)
        self.rx.start()
        self.port = self.rx.port
        return self.rx

    def check_clean(self):
        for rx in self.receivers:
            rx.stop()
        for thread in self.threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        for rx in self.receivers:
            self.assertEqual(rx._handlers, set())
            self.assertFalse(rx._thread.is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()

    def path(self, token=None):
        return "/hook/observed/" + (self.token if token is None else token)

    def post(self, path, data=None, headers=None, method="POST", host=None, port=None, timeout=5):
        port = port or self.port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host or "127.0.0.1:%d" % port)
        hdrs = {"Content-Type": "application/json"}
        if data is not None:
            hdrs["Content-Length"] = str(len(data))
        hdrs.update(headers or {})
        for key, value in hdrs.items():
            if value is not None:
                conn.putheader(key, value)
        conn.endheaders(data)
        try:
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def async_post(self, data=None, **kwargs):
        out = {}

        def run():
            try:
                out["r"] = self.post(self.path(), data or permission(), **kwargs)
            except Exception as err:  # noqa: BLE001
                out["e"] = err
        thread = threading.Thread(target=run)
        thread.start()
        self.threads.append(thread)
        return thread, out

    def raw_exchange(self, data, port=None):
        sock = socket.create_connection(("127.0.0.1", port or self.port), timeout=3)
        received = b""
        self.reset = False
        try:
            sock.sendall(data)
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                received += chunk
        except OSError:
            self.reset = True
        finally:
            sock.close()
        return received

    def snap(self):
        return self.sessions.snapshot()

    def pending(self):
        return [a for a in self.snap()["approvals"] if a["status"] == "pending"]

    def wait_pending(self, count=1):
        self.assertTrue(until(lambda: len(self.pending()) >= count), "no pending card")
        return self.pending()

    def card(self, approval_id):
        return [a for a in self.snap()["approvals"] if a["id"] == approval_id][0]


class RoutingTests(Base):
    def test_default_mode_is_the_empty_object(self):
        self.assertEqual(NO_DECISION_MODE, "empty_object")

    def test_wrong_token_and_unknown_path_get_bare_404(self):
        wrong = "x" * 43
        for path in (self.path(wrong), "/hook/observed/", "/hook/observed/" + self.token + "/x",
                     "/hook/observed/" + self.token + "?q=1", "/hook/managed/" + self.token,
                     "/other/" + self.token, "/hook/observed/" + "a" * 129):
            self.assertEqual(self.post(path, permission()), (404, b""), path[:20])
        for method in ("GET", "PUT", "DELETE", "PATCH", "OPTIONS"):
            self.assertEqual(self.post(self.path(), None, method=method), (404, b""), method)
        # a wrong token is refused from the headers alone: the declared body is never awaited
        head = ("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                "Content-Length: 500\r\n\r\n" % (self.path(wrong), self.port)).encode()
        started = time.monotonic()
        reply = self.raw_exchange(head)
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(reply.startswith(b"HTTP/1.0 404"), reply[:40])
        self.assertEqual(reply.partition(b"\r\n\r\n")[2], b"")
        self.assertEqual(self.snap()["sessions"], [])

    def test_unsupported_method_line_gets_404(self):
        reply = self.raw_exchange(("FROB %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n"
                                   % (self.path(), self.port)).encode())
        self.assertTrue(reply.startswith(b"HTTP/1.0 404"), reply[:40])

    def test_managed_token_refused_on_observed_listener_and_install_token_refused_on_managed(self):
        calls = []
        managed = HookReceiver(lambda *a: calls.append(a), wait_seconds=5, poll_interval=0.05)
        managed_port = managed.start()
        self.addCleanup(managed.stop)
        run_token = managed.register_run("t1")
        # the managed token on the observed listener: bare 404 under either path
        self.assertEqual(self.post("/hook/managed/" + run_token, permission()), (404, b""))
        self.assertEqual(self.post(self.path(run_token), permission()), (404, b""))
        self.assertEqual(self.post(self.path(run_token), body("SessionStart")), (404, b""))
        # the install token on the managed receiver: never reaches its callback
        self.assertEqual(self.post("/hook/managed/" + self.token, permission(), port=managed_port), (200, DENY))
        self.assertEqual(self.post(self.path(), permission(), port=managed_port), (404, b""))
        self.assertEqual(calls, [])
        self.assertEqual(managed._pending, {})
        snap = self.snap()
        self.assertEqual((snap["sessions"], snap["approvals"]), ([], []))
        # both tokens still work on their own listener
        self.assertEqual(self.post(self.path(), body("SessionStart")), (200, EMPTY))


class EventTests(Base):
    def test_session_end_recorded_and_replied_empty_object(self):
        self.assertEqual(self.post(self.path(), body("SessionStart")), (200, EMPTY))
        self.assertEqual(self.snap()["sessions"][0]["status"], "active")
        self.assertEqual(self.post(self.path(), body("SessionEnd")), (200, EMPTY))
        session = self.snap()["sessions"][0]
        self.assertEqual((session["id"], session["status"], session["project"]), (MAIN, "ended", "alpha"))

    def test_post_tool_use_and_stop_events_recorded_and_replied_empty_object(self):
        for name, extra in (("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "ls"}}),
                            ("Stop", {}), ("SubagentStart", {"agent_id": "agent-1"}),
                            ("SubagentStop", {"agent_id": "agent-1"})):
            self.assertEqual(self.post(self.path(), body(name, **extra)), (200, EMPTY), name)
        session = self.snap()["sessions"][0]
        self.assertEqual(session["status"], "active")
        self.assertIsNotNone(session["subagent_seen_at"])

    def test_matching_post_tool_use_closes_card_by_inference_and_ends_the_hold_with_no_decision(self):
        thread, out = self.async_post(permission("echo one"))
        card = self.wait_pending()[0]
        post = body("PostToolUse", tool_name="Bash", tool_input={"command": "echo one"})
        self.assertEqual(self.post(self.path(), post), (200, EMPTY))
        self.assertEqual(self.card(card["id"])["decided_by"], "terminal (inferred)")
        thread.join(3)  # R21: inference never allows or denies; it ends the hold with the no-decision reply
        self.assertFalse(thread.is_alive())
        self.assertEqual(out["r"], (200, EMPTY))
        self.assertEqual(self.sessions.answer(card["id"], "allow"), "closed")


class DecisionTests(Base):
    def test_permission_request_allow_and_deny_replies(self):
        for decision, reply in (("allow", ALLOW), ("deny", DENY)):
            thread, out = self.async_post(permission("echo " + decision))
            card = self.wait_pending()[0]
            self.assertEqual(card["tool_name"], "Bash")
            self.assertTrue(thread.is_alive())
            self.assertNotIn("r", out)
            self.assertEqual(self.sessions.answer(card["id"], decision), "ok")
            thread.join(3)
            self.assertEqual(out["r"], (200, reply), decision)
            done = self.card(card["id"])
            self.assertEqual((done["status"], done["decided_by"], done["decision"]),
                             ("answered", "dashboard", decision))
            self.assertEqual(self.sessions.answer(card["id"], "allow"), "closed")

    def test_expiry_closed_cap_stop_and_parse_failure_reply_200_empty_object_never_deny(self):
        # parse failures of an authenticated request
        for bad in (b"not json", b"[]", b'{"hook_event_name":"Other","session_id":"s"}', b'{"a":1,"a":2}',
                    body("PermissionRequest", tool_name="Bash"), body("Stop", session="bad id")):
            self.assertEqual(self.post(self.path(), bad), (200, EMPTY), bad[:30])
        self.assertEqual(self.snap()["approvals"], [])
        # expiry
        self.make(wait=0.2)
        self.assertEqual(self.post(self.path(), permission()), (200, EMPTY))
        # pending cap
        self.make(wait=5, max_pending=1)
        thread, out = self.async_post()
        self.wait_pending()
        self.assertEqual(self.post(self.path(), permission("echo two")), (200, EMPTY))
        # stop
        self.rx.stop()
        thread.join(3)
        self.assertEqual(out["r"], (200, EMPTY))
        # closed client: nothing can be replied, and the card closes without a decision
        self.make(wait=5)
        sock = self.raw_post(permission())
        card = self.wait_pending()[0]
        sock.close()
        self.assertTrue(until(lambda: self.card(card["id"])["status"] == "closed"))
        self.assertIsNone(self.card(card["id"])["decision"])

    def raw_post(self, data):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        sock.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                      "Content-Length: %d\r\n\r\n" % (self.path(), self.port, len(data))).encode() + data)
        return sock

    def test_expiry_uses_no_decision_not_allow_or_deny(self):
        self.make(wait=0.2)
        self.assertEqual(self.post(self.path(), permission()), (200, EMPTY))
        card = self.snap()["approvals"][0]
        self.assertEqual((card["status"], card["decided_by"], card["decision"]), ("closed", "timed out", None))
        self.assertEqual(self.sessions.answer(card["id"], "allow"), "closed")

    def test_client_closed_marks_card_closed_and_late_answer_reports_closed(self):
        sock = self.raw_post(permission())
        card = self.wait_pending()[0]
        sock.close()
        self.assertTrue(until(lambda: self.card(card["id"])["status"] == "closed"))
        self.assertEqual(self.card(card["id"])["decided_by"], "unknown")
        self.assertEqual(self.sessions.answer(card["id"], "allow"), "closed")
        self.assertTrue(until(lambda: not self.rx._handlers and not self.rx._holds))

    def test_pending_cap_refusal_replies_no_decision_and_counts(self):
        self.make(max_pending=2)
        runs = [self.async_post(permission("echo %d" % n)) for n in range(2)]
        cards = self.wait_pending(2)
        started = time.monotonic()
        self.assertEqual(self.post(self.path(), permission("echo 3")), (200, EMPTY))
        self.assertLess(time.monotonic() - started, 2)
        snap = self.snap()
        self.assertEqual(snap["refused"], 1)
        self.assertEqual(len(snap["approvals"]), 2)
        for card in cards:
            self.assertEqual(self.sessions.answer(card["id"], "deny"), "ok")
        for thread, out in runs:
            thread.join(3)
            self.assertEqual(out["r"], (200, DENY))
        # every finished card frees its pending slot
        thread, out = self.async_post(permission("echo 4"))
        card = self.wait_pending()[0]
        self.sessions.answer(card["id"], "allow")
        thread.join(3)
        self.assertEqual(out["r"], (200, ALLOW))

    def test_dashboard_answer_racing_a_disconnect_keeps_card_and_reply_consistent(self):
        # H5: the probe sees the client gone just after the owner's Allow won; the reply is the Allow,
        # never the no-decision reply under an "answered" card.
        sessions = self.sessions

        def gone_after_answer(_conn):
            for card in sessions.snapshot()["approvals"]:
                if card["status"] == "pending":
                    sessions.answer(card["id"], "allow")
            return True
        with patch.object(observed_receiver, "client_gone", side_effect=gone_after_answer):
            reply = self.post(self.path(), permission())
        card = self.snap()["approvals"][0]
        self.assertEqual((card["status"], card["decided_by"], card["decision"]), ("answered", "dashboard", "allow"))
        self.assertEqual(reply, (200, ALLOW))

    def test_stop_ends_holds(self):
        runs = [self.async_post(permission("echo %d" % n)) for n in range(3)]
        cards = self.wait_pending(3)
        self.rx.stop()
        for thread, out in runs:
            thread.join(3)
            self.assertEqual(out.get("r"), (200, EMPTY))
        for card in cards:
            done = self.card(card["id"])
            self.assertEqual((done["status"], done["decision"]), ("closed", None))
            self.assertEqual(self.sessions.answer(card["id"], "allow"), "closed")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        self.rx.stop()  # idempotent
        with self.assertRaises(RuntimeError):
            self.rx.start()

    def test_internal_error_replies_no_decision(self):
        token = self.token

        class Broken:
            def record(self, event):
                raise RuntimeError("boom " + token)

            def add_pending(self, event, held, expires_at):
                raise RuntimeError("boom " + token)

        self.make(sessions=Broken())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(self.post(self.path(), permission()), (200, EMPTY))
            self.assertEqual(self.post(self.path(), body("Stop")), (200, EMPTY))
        self.assertNotIn(token, err.getvalue())


class ManagedSessionTests(Base):
    """R17: a dashboard-managed run can load the owner's user settings, so the observed hooks fire for it too.
    Its events are answered 200 {} at once and leave no trace on the observed page."""

    MANAGED = "00000000-0000-4000-8000-00000000b0ff"

    def test_managed_session_gets_empty_object_at_once_and_nothing_recorded(self):
        asked = []

        def is_managed(session_id):
            asked.append(session_id)
            return session_id == self.MANAGED
        self.make(wait=30, is_managed_session=is_managed)
        for data in (permission(session=self.MANAGED), body("PostToolUse", session=self.MANAGED),
                     body("Stop", session=self.MANAGED), body("SessionEnd", session=self.MANAGED),
                     permission(session=self.MANAGED, agent_id="agent-1", agent_type="synthetic-worker")):
            started = time.monotonic()
            self.assertEqual(self.post(self.path(), data), (200, EMPTY))
            self.assertLess(time.monotonic() - started, 2)
        snap = self.snap()
        self.assertEqual((snap["sessions"], snap["approvals"], snap["refused"]), ([], [], 0))
        self.assertEqual(self.rx._holds, set())
        self.assertEqual(asked, [self.MANAGED] * 5)
        # another session still works
        thread, out = self.async_post(permission())
        card = self.wait_pending()[0]
        self.assertEqual(self.sessions.answer(card["id"], "allow"), "ok")
        thread.join(3)
        self.assertEqual(out["r"], (200, ALLOW))
        self.assertEqual([s["id"] for s in self.snap()["sessions"]], [MAIN])

    def test_unauthenticated_request_never_reaches_the_callback(self):
        asked = []
        self.make(is_managed_session=lambda session_id: asked.append(session_id) or True)
        self.assertEqual(self.post(self.path("x" * 43), permission()), (404, b""))
        self.assertEqual(self.post(self.path(), b"not json"), (200, EMPTY))
        self.assertEqual(asked, [])

    def test_callback_error_fails_closed_as_managed(self):
        # R23: an error in the check counts as managed: 200 {} at once, nothing recorded, no card, no hold
        token = self.token

        def broken(session_id):
            raise RuntimeError("boom " + token)
        self.make(wait=30, is_managed_session=broken)
        err = io.StringIO()
        with redirect_stderr(err):
            for data in (body("Stop"), permission(), body("PostToolUse", tool_name="Bash",
                                                          tool_input={"command": "echo synthetic"})):
                started = time.monotonic()
                self.assertEqual(self.post(self.path(), data), (200, EMPTY))
                self.assertLess(time.monotonic() - started, 2)
        snap = self.snap()
        self.assertEqual((snap["sessions"], snap["approvals"], snap["refused"]), ([], [], 0))
        self.assertEqual(self.rx._holds, set())
        self.assertNotIn(token, err.getvalue())
        # a check that answers normally again lets other sessions through
        self.make(is_managed_session=lambda session_id: False)
        thread, out = self.async_post(permission())
        card = self.wait_pending()[0]
        self.sessions.answer(card["id"], "deny")
        thread.join(3)
        self.assertEqual(out["r"], (200, DENY))

    def test_default_is_not_managed_and_the_parameter_must_be_callable(self):
        self.assertEqual(self.post(self.path(), body("Stop")), (200, EMPTY))
        self.assertEqual(len(self.snap()["sessions"]), 1)
        with self.assertRaises(ValueError):
            ObservedReceiver(self.sessions, self.token_file, 0, is_managed_session="yes")


class InferenceReleaseTests(Base):
    def test_stop_settles_a_pending_card_and_the_hook_returns_empty_object_quickly(self):
        # R21: inference ends the open hold with no decision; the connection and the pending slot are freed
        self.make(wait=30, max_pending=1)
        thread, out = self.async_post(permission())
        card = self.wait_pending()[0]
        started = time.monotonic()
        self.assertEqual(self.post(self.path(), body("Stop")), (200, EMPTY))
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(out["r"], (200, EMPTY))
        done = self.card(card["id"])
        self.assertEqual((done["status"], done["decided_by"], done["decision"], done["outcome"]),
                         ("closed", "terminal (inferred)", None, "not run"))
        self.assertTrue(until(lambda: not self.rx._holds))
        self.assertEqual(self.pending(), [])
        # the single pending slot is free again
        thread, out = self.async_post(permission("echo next"))
        card = self.wait_pending()[0]
        self.assertEqual(self.sessions.answer(card["id"], "allow"), "ok")
        thread.join(3)
        self.assertEqual(out["r"], (200, ALLOW))
        self.assertEqual(self.snap()["refused"], 0)

    def test_matching_post_tool_use_also_releases_the_hold(self):
        thread, out = self.async_post(permission())
        card = self.wait_pending()[0]
        self.assertEqual(self.post(self.path(), body("PostToolUse", tool_name="Bash",
                                                      tool_input={"command": "echo synthetic"})), (200, EMPTY))
        thread.join(3)
        self.assertEqual(out["r"], (200, EMPTY))
        self.assertEqual(self.card(card["id"])["outcome"], "ran")


class ModeTests(Base):
    """The other S11 candidate replies, switched by the module constant."""

    def test_status_204_close_and_hold_modes(self):
        with patch.object(observed_receiver, "NO_DECISION_MODE", "status_204"):
            reply = self.raw_exchange(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json"
                                       "\r\nContent-Length: 1\r\n\r\nx" % (self.path(), self.port)).encode())
            head, _, rest = reply.partition(b"\r\n\r\n")
            self.assertTrue(head.startswith(b"HTTP/1.0 204"), head[:40])
            self.assertNotIn(b"content-length", head.lower())
            self.assertEqual(rest, b"")
            # other events still get the empty object
            self.assertEqual(self.post(self.path(), body("Stop")), (200, EMPTY))
        with patch.object(observed_receiver, "NO_DECISION_MODE", "close"):
            with self.assertRaises((http.client.RemoteDisconnected, ConnectionError)):
                self.post(self.path(), b"x")
        with patch.object(observed_receiver, "NO_DECISION_MODE", "hold"):
            with self.assertRaises((socket.timeout, TimeoutError)):
                self.post(self.path(), b"x", timeout=0.5)
            thread, out = self.async_post(b"x")
            time.sleep(0.3)
            self.assertTrue(thread.is_alive())
            self.rx.stop()  # stop ends a hold-mode no-decision too, without a reply
            thread.join(3)
            self.assertNotIn("r", out)


class GuardTests(Base):
    def test_host_and_origin_guard(self):
        for host in ("localhost:%d" % self.port, "127.0.0.1", "127.0.0.1:1", "evil.test"):
            self.assertEqual(self.post(self.path(), permission(), host=host), (403, b""), host)
            self.assertEqual(self.post("/nowhere", permission(), host=host), (403, b""), host)
        self.assertEqual(self.post(self.path(), permission(), {"Origin": "http://127.0.0.1:%d" % self.port}),
                         (403, b""))
        self.assertEqual(self.post(self.path(), body("Stop"), {"Origin": "null"}), (403, b""))
        snap = self.snap()
        self.assertEqual((snap["sessions"], snap["approvals"]), ([], []))

    def test_oversize_body_413(self):
        reply = self.raw_exchange(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                                   "Content-Length: %d\r\n\r\n" % (self.path(), self.port, hook.MAX_BODY + 1)).encode())
        head, _, rest = reply.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.0 413"), head[:40])
        self.assertEqual(rest, b"")
        p = self.path()
        self.assertEqual(self.post(p, permission(), {"Content-Type": "text/plain"}), (415, b""))
        self.assertEqual(self.post(p, permission(), {"Transfer-Encoding": "chunked"}), (400, b""))
        self.assertEqual(self.post(p, None), (411, b""))
        self.assertEqual(self.post(p, None, {"Content-Length": "abc"}), (400, b""))
        self.assertEqual(self.snap()["sessions"], [])

    def test_nothing_logged_carries_token(self):
        out, err = io.StringIO(), io.StringIO()
        p = self.path()
        with redirect_stdout(out), redirect_stderr(err), self.assertNoLogs(level=logging.DEBUG):
            replies = [self.post(p, None, method="GET"), self.post(p, permission(), {"Content-Type": "x/y"}),
                       self.post(p, b"{"), self.post(p, body("Stop")),
                       self.post("/nope/" + self.token, permission()),
                       self.post(p, permission(), host="evil.test"),
                       self.post(self.path(self.token[:-1] + ("B" if self.token.endswith("A") else "A")),
                                 permission())]
            self.make(wait=0.1)
            replies.append(self.post(self.path(), permission()))
            for line in (b"BAD " + self.token.encode() + b" x y\r\n\r\n",
                         b"GET " + p.encode() + b" HTTP/1.1 extra\r\n\r\n",
                         b"GET " + p.encode() + b"a" * 70000 + b" HTTP/1.1\r\n\r\n",
                         b"GET " + p.encode() + b" HTTP/9.9\r\n\r\n"):
                reply = self.raw_exchange(line)
                if reply or not self.reset:  # a reset can discard the refusal; nothing was echoed either
                    self.assertTrue(reply.startswith(b"HTTP/"), reply[:40])
                    self.assertEqual(reply.partition(b"\r\n\r\n")[2], b"")
                replies.append(reply)
        text = out.getvalue() + err.getvalue() + repr(replies)
        self.assertNotIn(self.token, text)
        self.assertNotIn("/hook/observed", text)
        self.assertNotIn("synthetic", text)


class StartTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(os.path.realpath(temp.name))
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.sessions = ObservedSessions(self.store)

    def test_port_in_use_raises_without_fallback(self):
        holder = socket.socket()
        self.addCleanup(holder.close)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        rx = ObservedReceiver(self.sessions, TokenFile(self.root / "config"), port)
        with self.assertRaises(PortInUse) as caught:
            rx.start()
        self.assertNotIn(str(port), str(caught.exception))
        self.assertIsNone(rx._server)
        self.assertEqual(rx.port, port)
        rx.stop()

    def test_ephemeral_port_reports_the_bound_port_and_start_creates_the_token(self):
        files = TokenFile(self.root / "config")
        self.assertIsNone(files.status())
        rx = ObservedReceiver(self.sessions, files, 0)
        rx.start()
        self.addCleanup(rx.stop)
        self.assertNotEqual(rx.port, 0)
        self.assertEqual(rx.port, rx._server.server_port)
        rx.start()  # a second start keeps the same listener
        self.assertEqual(rx.port, rx._server.server_port)
        self.assertTrue(files.matches(files.token()))

    def test_unusable_token_file_raises_token_unavailable_without_binding(self):
        config = self.root / "config"
        config.mkdir(mode=0o755)
        os.chmod(config, 0o755)
        rx = ObservedReceiver(self.sessions, TokenFile(config), 0)
        with self.assertRaises(TokenUnavailable) as caught:
            rx.start()
        self.assertEqual(caught.exception.reason, "permissions")
        self.assertEqual(str(caught.exception), "permissions")
        self.assertNotIn(str(config), repr(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(rx._server)

    def test_bad_arguments(self):
        files = TokenFile(self.root / "config")
        for port in (-1, 65536, True, "1", 1.5):
            with self.assertRaises(ValueError):
                ObservedReceiver(self.sessions, files, port)
        for wait in (0, -1, True, "5", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ObservedReceiver(self.sessions, files, 0, wait_seconds=wait)
        # H6: zero or non-finite timings would busy-spin; the unheld cap must be a positive integer
        for name in ("poll_interval", "read_deadline"):
            for value in (0, -1, 0.0, True, None, "1", float("nan"), float("inf")):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    ObservedReceiver(self.sessions, files, 0, **{name: value})
        for value in (0, -1, True, None, 1.5, "8", float("inf")):
            with self.subTest(max_unheld=value), self.assertRaises(ValueError):
                ObservedReceiver(self.sessions, files, 0, max_unheld=value)
        ObservedReceiver(self.sessions, files, 0, wait_seconds=0.5, poll_interval=0.01, read_deadline=0.5,
                         max_unheld=1)  # small positive values are fine


if __name__ == "__main__":
    unittest.main()

"""Tests for the loopback hook receiver (dashboard/hook_receiver.py), using real sockets."""
import http.client
import io
import json
import logging
import os
import socket
import sys
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.backends import claude_hook as hook  # noqa: E402
from dashboard.hook_receiver import HeldRequest, HookReceiver  # noqa: E402

ALLOW = hook.allow_reply()
DENY = hook.deny_reply()
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "claude")


def payload(command="ls"):
    return json.dumps({"hook_event_name": "PermissionRequest", "session_id": "sess-1",
                       "permission_mode": "default", "tool_name": "Bash",
                       "tool_input": {"command": command}}).encode()


class Base(unittest.TestCase):
    wait = 5
    rx_kwargs = {}

    def setUp(self):
        self.calls = []
        self.arrived = threading.Semaphore(0)
        self.on_request = self.record
        self.rx = HookReceiver(lambda *a: self.on_request(*a), wait_seconds=self.wait,
                               poll_interval=0.05, **self.rx_kwargs)
        self.port = self.rx.start()
        self.threads = []
        self.addCleanup(self.check_clean)

    def check_clean(self):
        self.rx.stop()
        for thread in self.threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertFalse(self.rx._thread.is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        self.assertEqual(self.rx._handlers, set())

    def record(self, task_id, request, held):
        self.calls.append((task_id, request, held))
        self.arrived.release()

    def post(self, token_path, body=None, headers=None, method="POST", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, token_path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host or "127.0.0.1:%d" % self.port)
        hdrs = {"Content-Type": "application/json"}
        if body is not None:
            hdrs["Content-Length"] = str(len(body))
        hdrs.update(headers or {})
        for key, value in hdrs.items():
            if value is not None:
                conn.putheader(key, value)
        conn.endheaders(body)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def path(self, token):
        return "/hook/managed/" + token

    def async_post(self, token, body=None):
        out = {}

        def run():
            try:
                out["r"] = self.post(self.path(token), body or payload())
            except Exception as err:  # noqa: BLE001
                out["e"] = err
        thread = threading.Thread(target=run)
        thread.start()
        self.threads.append(thread)
        return thread, out

    def wait_call(self):
        self.assertTrue(self.arrived.acquire(timeout=3))
        return self.calls[-1]


class TokenTests(Base):
    def test_unknown_token_denied_without_callback(self):
        self.rx.register_run("t1")
        status, body = self.post(self.path("x" * 43), payload())
        self.assertEqual((status, body), (200, DENY))
        self.assertEqual(self.calls, [])

    def test_finished_run_token_denied(self):
        token = self.rx.register_run("t1")
        self.rx.unregister_run("t1")
        self.assertEqual(self.post(self.path(token), payload()), (200, DENY))
        self.assertEqual(self.calls, [])

    def test_other_runs_token_cannot_resolve(self):
        ta = self.rx.register_run("A")
        tb = self.rx.register_run("B")
        self.assertNotEqual(ta, tb)
        thread, out = self.async_post(ta)
        task_id, _req, _held = self.wait_call()
        self.assertEqual(task_id, "A")
        self.rx.unregister_run("B")  # B's end does not touch A's request
        self.assertTrue(thread.is_alive())
        self.calls[-1][2].resolve("allow")
        thread.join(3)
        self.assertEqual(out["r"], (200, ALLOW))

    def test_token_shape_and_url(self):
        token = self.rx.register_run("t1")
        self.assertGreaterEqual(len(token), 43)
        self.assertEqual(self.rx.url_for(token),
                         "http://127.0.0.1:%d/hook/managed/%s" % (self.port, token))


class RefusalTests(Base):
    def setUp(self):
        super().setUp()
        self.token = self.rx.register_run("t1")

    def oversize(self, path):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        sock.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                      "Content-Length: %d\r\n\r\n" % (path, self.port, hook.MAX_BODY + 1)).encode())
        data = sock.recv(4096)
        sock.close()
        head, _, body = data.partition(b"\r\n\r\n")
        return int(head.split()[1]), body

    def test_wrong_method_content_type_oversize_and_bad_json_refused_before_callback(self):
        p = self.path(self.token)
        for method in ("GET", "PUT", "DELETE", "PATCH", "OPTIONS"):
            status, body = self.post(p, None, method=method)
            self.assertEqual((status, body), (405, b""), method)
        self.assertEqual(self.post("/hook/managed/", payload()), (404, b""))
        self.assertEqual(self.post("/other/" + self.token, payload()), (404, b""))
        self.assertEqual(self.post(p, payload(), {"Content-Type": "text/plain"}), (415, b""))
        self.assertEqual(self.post(p, payload(), {"Content-Type": None}), (415, b""))
        self.assertEqual(self.post(p, payload(), {"Transfer-Encoding": "chunked"}), (400, b""))
        self.assertEqual(self.post(p, None), (411, b""))
        self.assertEqual(self.post(p, None, {"Content-Length": "abc"}), (400, b""))
        self.assertEqual(self.oversize(p), (413, b""))
        # parse failures are a plain deny, no echo
        for bad in (b"not json", b"[]", b'{"hook_event_name":"Other"}', b'{"a":1,"a":2}'):
            self.assertEqual(self.post(p, bad), (200, DENY))
        self.assertEqual(self.calls, [])

    def test_host_must_be_the_loopback_authority(self):
        p = self.path(self.token)
        for host in ("localhost:%d" % self.port, "127.0.0.1", "127.0.0.1:1", "evil.test"):
            self.assertEqual(self.post(p, payload(), host=host), (403, b""), host)
        self.assertEqual(self.post(p, payload(), {"Origin": "http://127.0.0.1:%d" % self.port}),
                         (403, b""))
        self.assertEqual(self.calls, [])

    def test_token_never_in_error_bodies_or_logs(self):
        out, err = io.StringIO(), io.StringIO()
        p = self.path(self.token)
        with redirect_stdout(out), redirect_stderr(err), self.assertNoLogs(level=logging.DEBUG):
            bodies = [self.post(p, None, method="GET"), self.post(p, payload(), {"Content-Type": "x/y"}),
                      self.oversize(p), self.post(p, b"{"),
                      self.post("/nope/" + self.token, payload()),
                      self.post(p, payload(), host="evil.test")]
        text = out.getvalue() + err.getvalue() + repr(bodies)
        self.assertNotIn(self.token, text)
        self.assertNotIn("/hook/managed", text)

    def raw_exchange(self, data):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        received = b""
        try:
            sock.sendall(data)
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                received += chunk
        except OSError:
            pass
        finally:
            sock.close()
        return received

    def test_malformed_request_lines_never_echo_token_or_path(self):
        token = self.token.encode()
        cases = [
            b"BAD " + token + b" x y\r\n\r\n",  # four words: stdlib would echo the line
            b"GET /hook/managed/" + token + b" HTTP/1.1 extra\r\n\r\n",
            b"GET /hook/managed/" + token + b"a" * 70000 + b" HTTP/1.1\r\n\r\n",  # 414
            b"GET /hook/managed/" + token + b" HTTP/9.9\r\n\r\n",
        ]
        for data in cases:
            reply = self.raw_exchange(data)
            self.assertTrue(reply.startswith(b"HTTP/"), reply[:40])
            _head, _, body = reply.partition(b"\r\n\r\n")
            self.assertEqual(body, b"")
            self.assertNotIn(token, reply)
            self.assertNotIn(b"/hook/managed", reply)
        self.assertEqual(self.calls, [])


class HoldTests(Base):
    def test_allow_reply_only_after_resolve_allow(self):
        token = self.rx.register_run("t1")
        thread, out = self.async_post(token, payload("echo hi"))
        task_id, req, held = self.wait_call()
        self.assertEqual((task_id, req.tool_input), ("t1", {"command": "echo hi"}))
        self.assertTrue(thread.is_alive())
        self.assertNotIn("r", out)
        self.assertTrue(held.resolve("allow"))
        self.assertFalse(held.resolve("deny"))  # first resolve wins
        thread.join(3)
        self.assertEqual(out["r"], (200, ALLOW))

    def test_deny_wins_when_first(self):
        token = self.rx.register_run("t1")
        thread, out = self.async_post(token)
        _t, _r, held = self.wait_call()
        held.resolve("deny")
        held.resolve("allow")
        thread.join(3)
        self.assertEqual(out["r"], (200, DENY))

    def test_timeout_replies_deny(self):
        token = self.rx.register_run("t1", wait_seconds=0.15)
        self.assertEqual(self.post(self.path(token), payload()), (200, DENY))
        _t, _r, held = self.calls[0]
        self.assertEqual(held.decision, "deny")
        self.assertFalse(held.resolve("allow"))  # a late accept cannot allow

    def test_run_level_wait_overrides_default(self):
        short = self.rx.register_run("short", wait_seconds=0.1)
        self.assertEqual(self.post(self.path(short), payload()), (200, DENY))
        with self.assertRaises(ValueError):
            self.rx.register_run("bad", wait_seconds=0)

    def test_client_disconnect_marks_closed_and_frees_thread(self):
        token = self.rx.register_run("t1")
        body = payload()
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        sock.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                      "Content-Length: %d\r\n\r\n" % (self.path(token), self.port, len(body))).encode() + body)
        _t, _r, held = self.wait_call()
        self.assertFalse(held.closed)
        sock.close()
        for _ in range(100):
            if held.closed:
                break
            threading.Event().wait(0.05)
        self.assertTrue(held.closed)
        self.assertEqual(held.decision, "deny")
        for _ in range(100):
            if not self.rx._handlers and not self.rx._pending:
                break
            threading.Event().wait(0.05)
        self.assertEqual(self.rx._handlers, set())
        self.assertEqual(self.rx._pending, {})

    def test_stop_releases_all_held_requests(self):
        token = self.rx.register_run("t1")
        runs = [self.async_post(token) for _ in range(3)]
        for _ in runs:
            self.wait_call()
        self.rx.stop()
        for thread, out in runs:
            thread.join(3)
            self.assertEqual(out.get("r"), (200, DENY))
        self.assertTrue(all(c[2].decision == "deny" for c in self.calls))
        with self.assertRaises(RuntimeError):
            self.rx.register_run("again")

    def test_unregister_denies_pending_for_that_run(self):
        ta, tb = self.rx.register_run("A"), self.rx.register_run("B")
        a, out_a = self.async_post(ta)
        self.wait_call()
        b, out_b = self.async_post(tb)
        self.wait_call()
        self.rx.unregister_run("A")
        a.join(3)
        self.assertEqual(out_a["r"], (200, DENY))
        self.assertTrue(b.is_alive())
        self.calls[-1][2].resolve("allow")
        b.join(3)
        self.assertEqual(out_b["r"], (200, ALLOW))

    def test_callback_exception_denies(self):
        def boom(*_a):
            raise RuntimeError("secret-looking " + token)
        token = self.rx.register_run("t1")
        self.on_request = boom
        out = io.StringIO()
        with redirect_stderr(out):
            self.assertEqual(self.post(self.path(token), payload()), (200, DENY))
        self.assertNotIn(token, out.getvalue())

    def test_callback_resolving_inline_works_without_receiver_lock(self):
        token = self.rx.register_run("t1")

        def inline(task_id, req, held):
            self.rx.register_run("other")  # re-enters the receiver from the callback
            self.rx.url_for("x")
            held.resolve("allow")
        self.on_request = inline
        self.assertEqual(self.post(self.path(token), payload()), (200, ALLOW))

    def test_caps_deny_immediately(self):
        token = self.rx.register_run("t1")
        runs = [self.async_post(token) for _ in range(16)]
        for _ in runs:
            self.wait_call()
        self.assertEqual(self.post(self.path(token), payload()), (200, DENY))  # 17th
        self.assertEqual(len(self.calls), 16)
        for thread, _out in runs:
            self.assertTrue(thread.is_alive())
        for _t, _r, held in self.calls:
            held.resolve("deny")
        for thread, _out in runs:
            thread.join(3)
        # total cap: 4 runs x 16 = 64, then a fifth run is denied
        self.calls.clear()
        tokens = [self.rx.register_run("r%d" % i) for i in range(5)]
        runs = [self.async_post(tokens[i]) for i in range(4) for _ in range(16)]
        for _ in runs:
            self.wait_call()
        self.assertEqual(self.post(self.path(tokens[4]), payload()), (200, DENY))
        self.assertEqual(len(self.calls), 64)
        for _t, _r, held in self.calls:
            held.resolve("deny")


class StopAndRegisterTests(Base):
    def test_stop_from_inside_the_callback_closes_listener_and_denies(self):
        token = self.rx.register_run("t1")
        others = [self.async_post(token) for _ in range(2)]
        for _ in others:
            self.wait_call()
        errors = []

        def stopper(task_id, req, held):
            try:
                self.rx.stop()
            except BaseException as err:  # noqa: BLE001
                errors.append(repr(err))
        self.on_request = stopper
        thread, out = self.async_post(token)
        thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(out.get("r"), (200, DENY))
        for other, result in others:
            other.join(3)
            self.assertEqual(result.get("r"), (200, DENY))
        self.assertTrue(all(c[2].decision == "deny" for c in self.calls))
        self.assertFalse(self.rx._thread.is_alive())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
        self.rx.stop()  # idempotent

    def test_register_run_again_replaces_token_and_denies_old_pending(self):
        old = self.rx.register_run("A")
        thread, out = self.async_post(old)
        self.wait_call()
        new = self.rx.register_run("A")
        self.assertNotEqual(old, new)
        thread.join(3)
        self.assertEqual(out["r"], (200, DENY))
        self.assertEqual(self.post(self.path(old), payload()), (200, DENY))
        self.assertEqual(len(self.calls), 1)  # the old token never reached the callback again
        thread, out = self.async_post(new)
        self.wait_call()
        self.calls[-1][2].resolve("allow")
        thread.join(3)
        self.assertEqual(out["r"], (200, ALLOW))

    def test_refused_run_leaves_no_empty_pending_set(self):
        tokens = [self.rx.register_run("r%d" % i) for i in range(5)]
        runs = [self.async_post(tokens[i]) for i in range(4) for _ in range(16)]
        for _ in runs:
            self.wait_call()
        self.assertEqual(self.post(self.path(tokens[4]), payload()), (200, DENY))
        self.assertNotIn("r4", self.rx._pending)
        for _t, _r, held in self.calls:
            held.resolve("deny")


class ReadLimitTests(Base):
    rx_kwargs = {"read_deadline": 0.4, "max_unheld": 4}

    def test_dripping_client_is_cut_off_by_the_overall_deadline(self):
        token = self.rx.register_run("t1")
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        head = ("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Pad: " % (self.path(token), self.port)).encode()
        sock.sendall(head)
        closed = False
        for _ in range(60):  # a byte every 50 ms never completes the headers
            try:
                sock.sendall(b"a")
                threading.Event().wait(0.05)
            except OSError:
                closed = True
                break
        sock.close()
        self.assertTrue(closed)
        self.assertEqual(self.calls, [])

    def test_flood_of_idle_connections_is_capped(self):
        idle = [socket.create_connection(("127.0.0.1", self.port), timeout=3) for _ in range(4)]
        for _ in range(100):
            if len(self.rx._handlers) == 4:
                break
            threading.Event().wait(0.02)
        self.assertEqual(len(self.rx._handlers), 4)
        extra = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        self.assertEqual(extra.recv(10), b"")  # closed by the receiver
        extra.close()
        # a held request frees its slot: the cap counts only not-yet-held connections
        for sock in idle:
            sock.close()
        token = self.rx.register_run("t1")
        for _ in range(100):
            if not self.rx._handlers:
                break
            threading.Event().wait(0.02)
        runs = [self.async_post(token) for _ in range(5)]
        for _ in runs:
            self.wait_call()
        for _t, _r, held in self.calls:
            held.resolve("deny")


class HeldRequestTests(unittest.TestCase):
    def test_first_resolve_wins_and_wait_defaults_to_deny(self):
        held = HeldRequest()
        self.assertEqual(held.wait(0.05), "deny")
        self.assertFalse(held.resolve("allow"))
        held = HeldRequest()
        held.resolve("allow")
        self.assertEqual(held.wait(1), "allow")
        held = HeldRequest()
        held.resolve("bogus")
        self.assertEqual(held.decision, "deny")

    def test_wait_probe_closed(self):
        held = HeldRequest()
        self.assertEqual(held.wait(5, lambda: True, 0.01), "deny")
        self.assertTrue(held.closed)


if __name__ == "__main__":
    unittest.main()

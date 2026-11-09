"""Tests for the shared hook HTTP pieces (dashboard/hook_http.py), using real loopback sockets."""
import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.hook_http import HeldRequest, HookHandlerBase, QuietServer, client_gone  # noqa: E402

LIMIT = 100


class _Echo(HookHandlerBase):
    """POST /any: guard, then read the body, answer 200 with its length."""

    def do_POST(self):
        if not self._guard("127.0.0.1:" + str(self.server.server_port)):
            return
        body = self._read_body(LIMIT)
        if body is None:
            return
        self._status(200, b'{"n": %d}' % len(body))


def _exchange(port, request: bytes, shutdown_write=False) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
        conn.sendall(request)
        if shutdown_write:
            conn.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks)


class ServerCase(unittest.TestCase):
    def setUp(self):
        _Echo.timeout = 2
        self.server = QuietServer(("127.0.0.1", 0), _Echo)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def post(self, headers=None, body=b"{}", host=True, shutdown_write=False):
        lines = ["POST /any HTTP/1.1"]
        if host is True:
            lines.append("Host: 127.0.0.1:%d" % self.port)
        elif host:
            lines.append("Host: " + host)
        lines.extend(headers if headers is not None else
                     ["Content-Type: application/json", "Content-Length: %d" % len(body)])
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
        return _exchange(self.port, raw, shutdown_write)

    @staticmethod
    def status(reply: bytes) -> int:
        return int(reply.split(b" ", 2)[1]) if reply else 0


class GuardTests(ServerCase):
    def test_guard_refuses_wrong_host_and_any_origin(self):
        self.assertEqual(self.status(self.post()), 200)
        self.assertEqual(self.status(self.post(host="127.0.0.1:1")), 403)
        self.assertEqual(self.status(self.post(host="localhost:%d" % self.port)), 403)
        self.assertEqual(self.status(self.post(host=False)), 403)
        origin = ["Content-Type: application/json", "Content-Length: 2", "Origin: http://x"]
        self.assertEqual(self.status(self.post(headers=origin)), 403)
        two_hosts = ["Host: 127.0.0.1:%d" % self.port, "Content-Type: application/json",
                     "Content-Length: 2"]
        self.assertEqual(self.status(self.post(headers=two_hosts)), 403)

    def test_refusals_carry_no_request_text(self):
        reply = self.post(host="evil.example:9")
        self.assertNotIn(b"evil.example", reply)
        self.assertNotIn(b"/any", reply)


class ReadBodyTests(ServerCase):
    def test_read_body_status_codes(self):
        json_type = "Content-Type: application/json"
        self.assertEqual(self.status(self.post(headers=["Content-Type: text/plain",
                                                        "Content-Length: 2"])), 415)
        self.assertEqual(self.status(self.post(headers=[json_type, "Transfer-Encoding: chunked"])), 400)
        self.assertEqual(self.status(self.post(headers=[json_type])), 411)
        self.assertEqual(self.status(self.post(headers=[json_type, "Content-Length: 2",
                                                        "Content-Length: 2"])), 400)
        self.assertEqual(self.status(self.post(headers=[json_type, "Content-Length: abc"])), 400)
        self.assertEqual(self.status(self.post(headers=[json_type, "Content-Length: -1"])), 400)
        self.assertEqual(self.status(self.post(headers=[json_type, "Content-Length: %d" % (LIMIT + 1)],
                                               body=b"")), 413)
        ok = self.post(body=b"x" * LIMIT)
        self.assertEqual(self.status(ok), 200)
        self.assertTrue(ok.endswith(b'{"n": %d}' % LIMIT))

    def test_short_body_gets_no_reply(self):
        reply = self.post(headers=["Content-Type: application/json", "Content-Length: 50"],
                          body=b"short", shutdown_write=True)
        self.assertEqual(reply, b"")


class HeldRequestTests(unittest.TestCase):
    def test_held_request_first_resolve_wins(self):
        held = HeldRequest()
        self.assertTrue(held.resolve("allow"))
        self.assertFalse(held.resolve("deny"))
        self.assertEqual(held.decision, "allow")
        other = HeldRequest()
        other.resolve("whatever")
        self.assertEqual(other.decision, "deny")
        self.assertFalse(other.resolve("allow"))


class ClientGoneTests(unittest.TestCase):
    def test_client_gone_detects_closed_socket(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        client = socket.create_connection(listener.getsockname())
        server_side, _ = listener.accept()
        self.addCleanup(server_side.close)
        self.assertFalse(client_gone(server_side))
        client.close()
        deadline = threading.Event()
        for _ in range(100):
            if client_gone(server_side):
                break
            deadline.wait(0.02)
        self.assertTrue(client_gone(server_side))

    def test_client_gone_true_for_closed_local_socket(self):
        sock = socket.socket()
        sock.close()
        self.assertTrue(client_gone(sock))


if __name__ == "__main__":
    unittest.main()

"""Spike S11 stub listener: no-decision replies per mode; fake values only, loopback only."""
import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from scripts import spike_s11_stub

BODY = {'hook_event_name': 'PermissionRequest', 'session_id': 'fake-session', 'tool_name': 'Bash',
        'tool_input': {'command': 'echo FAKE-SECRET-VALUE-123'}}


class StubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log = Path(self.temp.name) / 'stub.log'
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def start(self, mode, **kw):
        server = spike_s11_stub.make_server(mode, 0, str(self.log), **kw)
        self.servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server.server_address[1]

    def post(self, port, timeout=3, body=BODY):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
        conn.request('POST', '/hook', json.dumps(body), {'Content-Type': 'application/json'})
        return conn, conn.getresponse()

    def test_stub_replies_per_mode(self):
        conn, resp = self.post(self.start('empty_object'))
        self.assertEqual((resp.status, resp.read()), (200, b'{}'))
        conn.close()
        conn, resp = self.post(self.start('status_204'))
        self.assertEqual((resp.status, resp.read()), (204, b''))
        conn.close()
        with self.assertRaises((http.client.RemoteDisconnected, ConnectionError)):
            self.post(self.start('close'))
        with self.assertRaises(socket.timeout):
            self.post(self.start('hold'), timeout=0.5)

    def test_stub_script_answers_after_delay(self):
        conn, resp = self.post(self.start('hold', script='deny', after=0.1))
        data = json.loads(resp.read())
        self.assertEqual(data['hookSpecificOutput']['decision']['behavior'], 'deny')
        conn.close()

    def test_stub_logs_no_body(self):
        conn, resp = self.post(self.start('empty_object'))
        resp.read()
        conn.close()
        text = self.log.read_text()
        self.assertIn('PermissionRequest', text)
        for name in ('tool_input', 'tool_name', 'session_id'):
            self.assertIn(name, text)
        for value in ('FAKE-SECRET-VALUE-123', 'echo', 'fake-session'):
            self.assertNotIn(value, text)

    def test_stub_binds_loopback_only(self):
        server = spike_s11_stub.make_server('empty_object', 0, str(self.log))
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_address[0], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()

"""Dashboard key (security finding F2, design A): every API request needs the launch key; the page shell does not."""
import contextlib
import http.client
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from dashboard import server
from dashboard.backends.base import NoBackend
from dashboard.backends.claude import ClaudeBackendStub
from dashboard.server import Dashboard, make_server
from tests.policy_fixtures import SyntheticPolicy

KEY = "Synthetic_dashboard_key_for_tests_only_0123456789"  # Test value, not a secret.
REFUSAL = {"error": "Dashboard key required"}
STATIC_PATHS = ("/", "/index.html", "/app.js", "/styles.css", "/designs", "/designs.html", "/designs.css",
                "/designs.js", "/brand-logo.png")
READ_ROUTES = ("/api/state", "/api/config", "/api/provider", "/api/team", "/api/recovery-auth")


def call(port, method, path, key=None, body=None, extra=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Origin": "http://127.0.0.1:" + str(port)}
    if key is not None:
        headers["X-Dashboard-Key"] = key
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body)
    headers.update(extra or {})
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


class Served:
    def __init__(self, app, dashboard_key):
        self.server = make_server(app, 0, dashboard_key=dashboard_key)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def close(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()


class DashboardKeyTests(unittest.TestCase):
    backend = NoBackend

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.app = Dashboard(Path(self.temp.name).resolve() / "state", policy_provider=SyntheticPolicy(),
                             backend=self.backend())
        self.served = Served(self.app, KEY)
        self.port = self.served.port

    def tearDown(self):
        self.served.close()
        self.app.close()
        self.temp.cleanup()

    def state(self):
        return self.app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()

    def wrong_keys(self):
        return {"missing": None, "empty": "", "wrong": "x" * len(KEY), "same-length": KEY[:-1] + "!",
                "case": KEY.swapcase(), "prefix": KEY[:-1], "longer": KEY + "0", "non-ascii": KEY[:-1] + "é"}

    def test_get_post_and_other_methods_need_the_key(self):
        before = self.state()
        requests = [("GET", path, None) for path in READ_ROUTES]
        requests += [("GET", "/api/logo/" + "a" * 64 + ".png", None), ("GET", "/api/unknown", None),
                     ("POST", "/api/projects", {"name": "x", "path": self.temp.name}),
                     ("POST", "/api/config", {}), ("POST", "/api/approvals/" + "a" * 32 + "/respond", {"decision": "accept"}),
                     ("POST", "/api/tasks/" + "a" * 32 + "/recovery/handoffs/" + "b" * 32 + "/accept", {}),
                     ("PUT", "/api/config", {}), ("PATCH", "/api/config", {}), ("DELETE", "/api/projects", None),
                     ("OPTIONS", "/api/state", None)]
        for method, path, body in requests:
            for label, key in self.wrong_keys().items():
                with self.subTest(method=method, path=path, key=label):
                    status, data = call(self.port, method, path, key, body)
                    self.assertEqual(403, status)
                    self.assertEqual(REFUSAL, json.loads(data))
                    self.assertNotIn(KEY[:12].encode(), data)
        self.assertEqual(before, self.state())
        self.assertEqual({}, self.app.projects)

    def test_refusal_comes_before_the_body_is_read(self):
        # A declared body that never arrives would time the handler out if it were read first.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("POST", "/api/projects", skip_host=True)
        connection.putheader("Host", "127.0.0.1:" + str(self.port))
        connection.putheader("Origin", "http://127.0.0.1:" + str(self.port))
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", "60000")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual((403, REFUSAL), (response.status, json.loads(response.read())))
        connection.close()

    def test_duplicate_key_headers_are_refused(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.putrequest("GET", "/api/state", skip_host=True)
        connection.putheader("Host", "127.0.0.1:" + str(self.port))
        connection.putheader("X-Dashboard-Key", KEY)
        connection.putheader("X-Dashboard-Key", KEY)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual((403, REFUSAL), (response.status, json.loads(response.read())))
        connection.close()

    def test_right_key_is_accepted_and_never_echoed(self):
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logging.getLogger().addHandler(handler)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                for path in READ_ROUTES:
                    with self.subTest(path=path):
                        status, data = call(self.port, "GET", path, KEY)
                        # Recovery sign-in is gated (409) where the provider lacks it; the key still let it through.
                        self.assertIn(status, (200, 409) if path == "/api/recovery-auth" else (200,), data)
                        self.assertNotIn(KEY.encode(), data)
                status, data = call(self.port, "POST", "/api/projects", KEY, {"name": "Keyed", "path": self.temp.name})
                self.assertEqual(200, status, data)
                self.assertNotIn(KEY.encode(), data)
                status, data = call(self.port, "GET", "/api/state", KEY)
                self.assertIn(b"Keyed", data)
                self.assertNotIn(KEY.encode(), data)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertNotIn(KEY, output.getvalue())
        self.assertFalse([r for r in records if KEY in r.getMessage()])
        self.assertFalse([row for row in self.state() if KEY in str(row)])

    def test_page_shell_is_served_without_a_key(self):
        for path in STATIC_PATHS:
            with self.subTest(path=path):
                status, _data = call(self.port, "GET", path)
                self.assertEqual(200, status)
        status, _data = call(self.port, "GET", "/team-portraits/chief_of_staff.svg")
        self.assertIn(status, (200, 404))
        self.assertNotEqual(403, status)
        # The page shell is not an open door for other methods or paths.
        self.assertEqual(403, call(self.port, "POST", "/", None, {})[0])
        self.assertEqual(403, call(self.port, "GET", "/index.html?x=1")[0])

    def test_host_and_origin_checks_still_apply_with_the_key(self):
        status, data = call(self.port, "GET", "/api/state", KEY, extra={"Origin": "http://evil.example"})
        self.assertEqual(403, status)
        self.assertEqual({"error": "Same-origin access is required"}, json.loads(data))


class ClaudeDashboardKeyTests(DashboardKeyTests):
    """The same gate applies under the Claude provider."""
    backend = ClaudeBackendStub


class CodexDashboardKeyTests(DashboardKeyTests):
    """The same gate applies under the Codex provider (the default backend; never started here)."""
    backend = staticmethod(lambda: None)


class ServerConstructionTests(unittest.TestCase):
    def test_make_server_requires_an_explicit_key_argument(self):
        app = mock.MagicMock()
        with self.assertRaises(TypeError):
            make_server(app, 0)

    def test_make_server_rejects_short_or_non_string_keys(self):
        app = mock.MagicMock()
        for bad in ("", "short", b"x" * 64, 12345):
            with self.subTest(bad=repr(bad)[:10]):
                with self.assertRaises(ValueError):
                    make_server(app, 0, dashboard_key=bad)

    def test_new_keys_are_long_random_and_url_safe(self):
        keys = {server.new_dashboard_key() for _ in range(20)}
        self.assertEqual(20, len(keys))
        for key in keys:
            self.assertGreaterEqual(len(key), 43)
            self.assertRegex(key, r"\A[A-Za-z0-9_-]+\Z")


class MainEnforcesKeyTests(unittest.TestCase):
    """The production path (main) always builds an enforcing server and prints the key only in the launch URL."""

    def test_main_enforces_a_fresh_key_and_prints_the_launch_url(self):
        temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(temp.cleanup)
        app = Dashboard(Path(temp.name).resolve() / "state", policy_provider=SyntheticPolicy(), backend=NoBackend())
        app.start = lambda: None
        seen = {}
        original = server.make_server

        def build(dashboard, port, **kwargs):
            seen["port"] = port
            seen["kwargs"] = dict(kwargs)
            built = original(dashboard, 0, **kwargs)
            real_serve = built.serve_forever

            def serve_forever():
                thread = threading.Thread(target=real_serve, daemon=True)
                thread.start()
                try:
                    key = kwargs["dashboard_key"]
                    seen["missing"] = call(built.server_port, "GET", "/api/state")
                    seen["wrong"] = call(built.server_port, "GET", "/api/state", key.swapcase())
                    seen["right"] = call(built.server_port, "GET", "/api/provider", key)
                    seen["page"] = call(built.server_port, "GET", "/")
                finally:
                    built.shutdown()
                    thread.join(3)

            built.serve_forever = serve_forever
            return built

        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["dashboard.server", "--port", "8799"]), \
                mock.patch.object(server, "dashboard_for_provider", lambda _provider, **_kw: app), \
                mock.patch.object(server, "RuntimeOwner", lambda _path: mock.MagicMock()), \
                mock.patch.object(server, "make_server", build), \
                mock.patch.object(server.signal, "signal"), \
                mock.patch.object(server.os, "umask"), \
                contextlib.redirect_stdout(output):
            server.main()
        key = seen["kwargs"]["dashboard_key"]
        self.assertIsInstance(key, str)
        self.assertGreaterEqual(len(key), 43)
        self.assertEqual(8799, seen["port"])
        self.assertEqual((403, REFUSAL), (seen["missing"][0], json.loads(seen["missing"][1])))
        self.assertEqual(403, seen["wrong"][0])
        self.assertEqual(200, seen["right"][0])
        self.assertNotIn(key.encode(), seen["right"][1])
        self.assertEqual(200, seen["page"][0])
        self.assertEqual("Dashboard: http://127.0.0.1:8799/#key=" + key + "\n", output.getvalue())
        self.assertFalse([value for value in os.environ.values() if key in value])
        self.assertNotIn(key, " ".join(sys.argv))

    def test_each_start_gets_a_different_key(self):
        self.assertNotEqual(server.new_dashboard_key(), server.new_dashboard_key())


class LaunchScriptTests(unittest.TestCase):
    def test_script_tells_the_user_to_open_the_printed_url(self):
        text = (Path(__file__).resolve().parent.parent / "scripts" / "run_dashboard.sh").read_text()
        self.assertIn("Open the dashboard with the URL printed below", text)
        self.assertNotIn("Starting local dashboard at http://127.0.0.1:8765/'", text)


if __name__ == "__main__":
    unittest.main()

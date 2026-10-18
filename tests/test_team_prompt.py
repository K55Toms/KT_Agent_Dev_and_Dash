"""On-demand configured role prompts and their read-only HTTP boundary."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard, load_roles, make_server


class TeamPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.app = Dashboard(Path(self.temp.name) / "state")
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.app.close()
        self.temp.cleanup()

    def request(self, path, headers=None, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    def test_returns_exact_configured_prompt_only_after_scan_without_mutation(self):
        prompt = "  Configured instructions.\n<script>Display as text.</script>\n\tKeep spacing.  "
        self.app.roles["backend_developer"]["instructions"] = prompt
        before = self.app.snapshot()
        with patch("dashboard.server.scan_preview") as scan:
            def checked(data):
                self.assertEqual(prompt.encode("utf-8"), data)
                # Scanning must not keep the state lock held across subprocess work.
                acquired = threading.Event()
                def take_lock():
                    with self.app.lock:
                        acquired.set()
                worker = threading.Thread(target=take_lock, daemon=True)
                worker.start()
                self.assertTrue(acquired.wait(1))
                worker.join(1)
            scan.side_effect = checked
            status, body, headers = self.request("/api/team/backend_developer/prompt")
            self.assertEqual(200, status)
            self.assertEqual({"role_id": "backend_developer", "prompt": prompt}, body)
            self.assertEqual("no-store", headers["Cache-Control"])
            self.assertEqual("application/json; charset=utf-8", headers["Content-Type"])
            scan.assert_called_once_with(prompt.encode("utf-8"))
        self.assertEqual(before, self.app.snapshot())
        self.assertEqual([], self.app.store.load("task"))
        self.assertEqual([], self.app.workers)
        self.assertIsNone(self.app.client)

    def test_state_and_roster_never_include_prompt_or_trigger_scan(self):
        marker = "CONFIGURED_ROLE_PROMPT_ONLY"
        for role in self.app.roles.values():
            role["instructions"] = marker
        with patch("dashboard.server.scan_preview") as scan:
            for path in ("/api/state", "/api/team"):
                status, body, _ = self.request(path)
                self.assertEqual(200, status)
                self.assertNotIn(marker, json.dumps(body))
                self.assertNotIn('"instructions"', json.dumps(body))
                self.assertNotIn('"prompt"', json.dumps(body))
            scan.assert_not_called()

    def test_unknown_roles_and_path_variants_never_scan_or_read_files(self):
        with patch("dashboard.server.scan_preview") as scan:
            for path in (
                "/api/team/unknown_role/prompt", "/api/team/../prompt",
                "/api/team/%2e%2e/prompt", "/api/team/backend_developer.toml/prompt",
                "/api/team/backend_developer/prompt?path=SECURITY.md",
                "/api/team/backend_developer/prompt/extra",
            ):
                with self.subTest(path=path):
                    status, body, _ = self.request(path)
                    self.assertEqual(404, status)
                    self.assertEqual({"error"}, set(body))
            scan.assert_not_called()

    def test_host_origin_and_cross_site_guards_apply_before_scanning(self):
        with patch("dashboard.server.scan_preview") as scan:
            for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                            {"Sec-Fetch-Site": "cross-site"}):
                with self.subTest(headers=headers):
                    status, body, _ = self.request("/api/team/backend_developer/prompt", headers)
                    self.assertEqual(403, status)
                    self.assertEqual({"error"}, set(body))
            scan.assert_not_called()

    def test_scanner_rejection_and_failure_withhold_prompt_and_internal_details(self):
        prompt = "CONFIGURED_ROLE_PROMPT_WITHHELD"
        self.app.roles["backend_developer"]["instructions"] = prompt
        for error, expected in ((FileAccessError(403, "PRIVATE_SCANNER_DETAIL"), 403),
                                (FileAccessError(503, "PRIVATE_SCANNER_DETAIL"), 503),
                                (OSError("PRIVATE_SCANNER_DETAIL"), 503),
                                (RuntimeError("PRIVATE_SCANNER_DETAIL"), 503)):
            with self.subTest(error=type(error).__name__, expected=expected):
                with patch("dashboard.server.scan_preview", side_effect=error):
                    status, body, _ = self.request("/api/team/backend_developer/prompt")
                    self.assertEqual(expected, status)
                    self.assertEqual({"error"}, set(body))
                    self.assertNotIn(prompt, json.dumps(body))
                    self.assertNotIn("PRIVATE_SCANNER_DETAIL", json.dumps(body))

    def test_invalid_configured_content_is_bounded_before_scanning(self):
        with patch("dashboard.server.scan_preview") as scan:
            for prompt in (None, "", "  ", "x" * 65537, "é" * 32769, "bad\x00text", "bad\ud800text"):
                self.app.roles["backend_developer"]["instructions"] = prompt
                status, body, _ = self.request("/api/team/backend_developer/prompt")
                self.assertEqual(503, status)
                self.assertEqual({"error": "Configured role prompt is unavailable"}, body)
            scan.assert_not_called()

    def test_real_scanner_accepts_configured_prompt_and_blocks_synthetic_credential(self):
        for role_id, role in load_roles().items():
            with self.subTest(role_id=role_id):
                status, body, _ = self.request(f"/api/team/{role_id}/prompt")
                self.assertEqual(200, status)
                self.assertEqual({"role_id": role_id, "prompt": role["instructions"]}, body)
        value = "constructed" + "-nonfunctional-" + "fixture"
        self.app.roles["backend_developer"]["instructions"] = "password" + " = '" + value + "'"
        status, body, _ = self.request("/api/team/backend_developer/prompt")
        self.assertEqual(403, status)
        self.assertEqual({"error"}, set(body))
        self.assertNotIn(value, json.dumps(body))
        self.assertNotIn(value.encode(), (Path(self.temp.name) / "state/dashboard.sqlite3").read_bytes())


if __name__ == "__main__":
    unittest.main()

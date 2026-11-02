"""Task 7: diagnostic wording, the bounded hook-denial summary in the snapshot, and the wait setting over HTTP."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from dashboard.backends.claude import ClaudeBackend
from dashboard.diagnostics import DETAILS
from dashboard.server import Dashboard, make_server
from dashboard.settings import SettingsStore
from tests.policy_fixtures import SyntheticPolicy


class DiagnosticTextTests(unittest.TestCase):
    def test_calls_denied_no_longer_promises_a_later_release(self):
        message, action = DETAILS["claude_calls_denied"]
        self.assertNotIn("later release", message + action)
        self.assertIn("not approved", message)
        for how in ("by you", "wait", "stop"):
            self.assertIn(how, message)
        self.assertIn("Approvals page", message + action)

    def test_permission_mode_text_says_what_happened(self):
        message, action = DETAILS["claude_permission_mode"]
        self.assertNotIn("Nothing the run asked for was answered", message + action)
        self.assertIn("default permission mode", message)
        self.assertIn("stopped", message)
        self.assertIn("denied", message)


class HookDenialSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.app = Dashboard(Path(self.temp.name).resolve() / "c", policy_provider=SyntheticPolicy(),
                             backend=ClaudeBackend(claude_path="/synthetic/bin/claude", runner=lambda a, t: None))
        self.addCleanup(self.app.close)

    def task(self, claude):
        with self.app.lock:
            self.app.tasks["t1"] = {"id": "t1", "project_id": "p", "title": "T", "status": "completed",
                                    "provider": "claude", "claude": claude}
        return self.app.snapshot()["tasks"][0]["claude"]

    def test_denial_records_are_projected_bounded_and_without_request_text(self):
        records = [{"code": "claude_hook_turn_inactive", "tool_name": "Bash"},
                   {"code": "claude_hook_limit", "tool_name": "Write", "tool_input": "SENTINEL_INPUT"},
                   {"code": "not_a_code", "tool_name": "Bash"},
                   {"code": "claude_hook_limit", "tool_name": "bad name"},
                   {"code": "claude_hook_limit", "tool_name": "x" * 65},
                   "text", None] + [{"code": "claude_hook_limit", "tool_name": "T%d" % i} for i in range(40)]
        shown = self.task({"pid": 7, "session_id": "s", "denied_count": 1, "denied_tools": ["Bash"],
                           "hook_denials": records})
        self.assertEqual({"denied_count", "denied_tools", "hook_denials"}, set(shown))
        self.assertEqual({"code": "claude_hook_turn_inactive", "tool_name": "Bash"}, shown["hook_denials"][0])
        self.assertEqual({"code": "claude_hook_limit", "tool_name": "Write"}, shown["hook_denials"][1])
        self.assertLessEqual(len(shown["hook_denials"]), 20)
        for item in shown["hook_denials"]:
            self.assertEqual({"code", "tool_name"}, set(item))
        self.assertNotIn("SENTINEL_INPUT", json.dumps(self.app.snapshot()))

    def test_no_records_means_no_key(self):
        self.assertEqual({"denied_count": 0, "denied_tools": []}, self.task({"denied_count": 0, "denied_tools": []}))
        self.assertEqual({"denied_count": 0, "denied_tools": []},
                         self.task({"denied_count": 0, "denied_tools": [], "hook_denials": []}))
        self.assertEqual({"denied_count": 0, "denied_tools": []},
                         self.task({"denied_count": 0, "denied_tools": [], "hook_denials": [{"code": "x", "tool_name": "Bash"}]}))


class WaitSettingRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "dashboard").mkdir()
        self.app = Dashboard(self.root / "state")
        self.app.settings = SettingsStore(self.root)
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()

    def call(self, method, data=None):
        port = self.server.server_port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, "/api/config", body=json.dumps(data) if data is not None else None,
                     headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:%d" % port})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body

    def test_wait_round_trips_and_is_strictly_validated(self):
        status, current = self.call("GET")
        self.assertEqual((200, 900), (status, current["claude_approval_wait_seconds"]))
        for good in (60, 3600, 125):
            self.assertEqual((200, good), (lambda r: (r[0], r[1]["claude_approval_wait_seconds"]))(
                self.call("POST", dict(current, claude_approval_wait_seconds=good))))
            self.assertEqual(good, self.call("GET")[1]["claude_approval_wait_seconds"])
        for bad in (59, 3601, 90.5, "900", None, True, [900], -1, 0):
            before = self.call("GET")[1]
            self.assertEqual(400, self.call("POST", dict(current, claude_approval_wait_seconds=bad))[0], bad)
            self.assertEqual(before, self.call("GET")[1])

    def test_older_client_may_omit_the_wait_and_unknown_keys_are_refused(self):
        _, current = self.call("GET")
        self.call("POST", dict(current, claude_approval_wait_seconds=300))
        older = {k: v for k, v in current.items() if k != "claude_approval_wait_seconds"}
        status, saved = self.call("POST", older)
        self.assertEqual((200, 300), (status, saved["claude_approval_wait_seconds"]))
        self.assertEqual(400, self.call("POST", dict(current, claude_approval_wait_secondz=300))[0])


if __name__ == "__main__":
    unittest.main()

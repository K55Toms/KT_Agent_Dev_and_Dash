"""Approval review and delivery decision routes never act on another provider's records (final review M1, M2, M9)."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from dashboard.approval_review import ReviewError
from dashboard.backends.base import NoBackend
from dashboard.backends.claude import ClaudeBackendStub
from dashboard.server import Dashboard, make_server
from tests.characterization import ScriptedDashboard, require_scanner
from tests.policy_fixtures import SyntheticPolicy

MISMATCH = {"error": "recorded under a different provider"}
# The alternative route is gated by capability before the handler runs, so a deployment without that
# capability answers with the gate's text; the handler's own guard is then pinned by a direct call.
GATED = {"error": "not available for this provider"}
REFUSAL = "recorded under a different provider"


class Served:
    """Serve one Dashboard on an ephemeral port and answer raw requests."""

    def __init__(self, app):
        self.server = make_server(app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def close(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()

    def raw(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Origin": "http://127.0.0.1:" + str(self.port)}
        payload = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body if body is not None else {})
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def request(self, method, path, body=None):
        status, data = self.raw(method, path, body)
        return status, json.loads(data)


@require_scanner()
class ApprovalReviewGuardTests(ScriptedDashboard):
    """The record's provider must be the active one before a review route reads or writes the approval."""

    def setUp(self):
        super().setUp()
        task = self.task()
        self.task_id = task["id"]
        self.app.on_message({"id": 17, "method": "item/commandExecution/requestApproval", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "itemId": "item-one", "startedAtMs": 1,
            "command": "SYNTHETIC_PRIVATE_COMMAND", "cwd": str(self.root), "reason": "SYNTHETIC_PRIVATE_REASON",
            "availableDecisions": ["accept", "decline", "cancel"]}})
        self.approval_id = list(self.app.approvals)[-1]
        self.served = None

    def tearDown(self):
        if self.served is not None:
            self.served.close()
        super().tearDown()

    def serve(self):
        self.served = Served(self.app)

    def state(self):
        rows = self.app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()
        return {"rows": rows, "approvals": deepcopy(self.app.approvals), "tasks": deepcopy(self.app.tasks),
                "pending": {key: (id(value), value.get("busy"), value.get("receipt"), value.get("params"))
                    for key, value in self.app.pending.items()},
                "requests": list(self.fake.requests), "responses": list(self.fake.responses)}

    def routes(self):
        base = "/api/approvals/" + self.approval_id
        return [
            ("review", "GET", base + "/review", None),
            ("sensitive-review", "POST", base + "/sensitive-review", {"confirmed": True}),
            ("alternative", "POST", base + "/alternative", {"text": "smaller"}),
            # The guard comes before the text check, so a bad body must not write a review failure either.
            ("alternative-oversized", "POST", base + "/alternative", {"text": "x" * 12001}),
            # An invalid body must meet the provider guard first, not a field or confirmation error.
            ("sensitive-review-empty-body", "POST", base + "/sensitive-review", {}),
            ("sensitive-review-unconfirmed", "POST", base + "/sensitive-review", {"confirmed": False}),
        ]

    def assert_refused_and_untouched(self, gated=()):
        before = self.state()
        for name, method, path, body in self.routes():
            with self.subTest(route=name):
                expected = GATED if name in gated else MISMATCH
                self.assertEqual((409, expected), self.served.request(method, path, body))
        for text in ("smaller", "x" * 12001):
            with self.subTest(direct_alternative=len(text)):
                with self.assertRaises(ValueError) as caught:
                    self.app.request_approval_alternative(self.approval_id, {"text": text})
                self.assertEqual(REFUSAL, str(caught.exception))
        after = self.state()
        self.assertEqual(before, after)
        self.assertNotIn("review_failure", self.app.approvals[self.approval_id])

    def test_claude_recorded_approval_under_codex_is_refused_and_unchanged(self):
        self.app.tasks[self.task_id]["provider"] = "claude"
        self.app.store.put("task", self.app.tasks[self.task_id])
        self.fake.requests.clear()
        self.fake.responses.clear()
        self.serve()
        self.assert_refused_and_untouched()

    def test_codex_recorded_approval_under_claude_stub_is_refused_and_unchanged(self):
        self.app.close()
        app = Dashboard(self.root / "state", policy_provider=SyntheticPolicy(), backend=ClaudeBackendStub())
        self.addCleanup(app.close)
        self.app = app
        self.assertEqual("codex", app.tasks[self.task_id]["provider"])
        self.assertIn(self.approval_id, app.approvals)
        self.serve()
        self.assert_refused_and_untouched(gated=("alternative", "alternative-oversized"))

    def test_record_review_failure_does_not_write_on_other_provider_approval(self):
        self.app.tasks[self.task_id]["provider"] = "claude"
        self.app.store.put("task", self.app.tasks[self.task_id])
        before = self.state()
        public = self.app.record_review_failure(self.approval_id, ReviewError("request_unavailable"))
        self.assertEqual("request_unavailable", public["code"])
        self.assertEqual(before, self.state())
        self.assertNotIn("review_failure", self.app.approvals[self.approval_id])

    def test_record_review_failure_still_writes_for_the_active_provider(self):
        self.app.record_review_failure(self.approval_id, ReviewError("request_unavailable"))
        self.assertEqual("request_unavailable", self.app.approvals[self.approval_id]["review_failure"]["code"])

    def test_matching_provider_review_is_not_refused(self):
        self.serve()
        status, body = self.served.request("GET", "/api/approvals/" + self.approval_id + "/review")
        self.assertEqual(200, status)
        self.assertEqual(self.approval_id, body["id"])


@require_scanner()
class DeliveryReviewDecisionGuardTests(ScriptedDashboard):
    def decision(self):
        return {"review_id": "a" * 32, "receipt_id": "b" * 32, "review_digest": "c" * 64,
                "expected_snapshot": "d" * 64, "decision": "accept", "confirmed": True}

    def test_other_provider_run_is_refused_before_anything_else(self):
        task = self.task()
        self.app.tasks[task["id"]]["provider"] = "claude"
        self.app.store.put("task", self.app.tasks[task["id"]])
        rows = self.app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()
        tasks = deepcopy(self.app.tasks)
        # Valid and invalid bodies get the same refusal: the guard is the first statement.
        for data in (self.decision(), {}, {**self.decision(), "decision": "maybe"}):
            with self.subTest(data=sorted(data)):
                with self.assertRaises(ValueError) as caught:
                    self.app.delivery_review_decision(task["id"], data)
                self.assertEqual(REFUSAL, str(caught.exception))
        self.assertEqual(rows, self.app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall())
        self.assertEqual(tasks, self.app.tasks)
        self.assertEqual({}, self.app.delivery_receipts)

    def test_matching_provider_reaches_the_normal_validation(self):
        task = self.task()
        with self.assertRaises(ValueError) as caught:
            self.app.delivery_review_decision(task["id"], {})
        self.assertNotEqual(REFUSAL, str(caught.exception))


class NoBackendServesItsPageTests(unittest.TestCase):
    """Review Focus 1: with no provider the dashboard still serves its page."""

    def test_get_root_answers_200_html_under_no_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Dashboard(Path(directory).resolve() / "state", policy_provider=SyntheticPolicy(), backend=NoBackend())
            served = Served(app)
            try:
                status, body = served.raw("GET", "/")
            finally:
                served.close()
                app.close()
        self.assertEqual(200, status)
        self.assertIn(b"<html", body.lower())


if __name__ == "__main__":
    unittest.main()

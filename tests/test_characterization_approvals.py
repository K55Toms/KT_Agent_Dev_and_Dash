"""Characterization of the Codex approval flows as projected by Dashboard.snapshot().

These tests pin today's behaviour (golden file tests/fixtures/characterization/approvals.json) and the
replies the dashboard sends to the native client, so a later refactor of the Codex-shaped code in
dashboard/server.py can be proven behaviour-preserving. They describe what the dashboard does now; they
do not assert that it is the desired design.
"""
import json
import os
import unittest
from unittest.mock import patch

from dashboard.project_files import FileAccessError
from tests import characterization
from tests.characterization import ScriptedDashboard, check_golden, normalize, require_scanner

GOLDEN = "approvals"
TURN = {"id": "turn-one"}
FILE_CHANGE = "item/fileChange/requestApproval"


class ApprovalProjectionTests(ScriptedDashboard):
    def check(self, name):
        snapshot = normalize(self.app.snapshot())
        check_golden(self, GOLDEN, name, snapshot)
        return snapshot

    def check_replies(self, name, expected):
        """Pin what the dashboard sent to the native client (exact list and normalized golden)."""
        self.assertEqual(expected, self.fake.responses)
        check_golden(self, GOLDEN, name, normalize([list(reply) for reply in self.fake.responses]))

    @require_scanner()
    def test_command_approval_pending_then_accepted(self):
        task = self.task()
        # Accepting needs a complete checked context (item id, start time, cwd, offered decisions).
        self.app.on_message({"id": 17, "method": "item/commandExecution/requestApproval", "params": {
            "threadId": task["thread_id"], "turnId": task["turn_id"], "itemId": "item-one", "startedAtMs": 1,
            "command": "SYNTHETIC_PRIVATE_COMMAND", "cwd": str(self.root), "reason": "SYNTHETIC_PRIVATE_REASON",
            "availableDecisions": ["accept", "decline", "cancel"]}})
        approval = list(self.app.approvals.values())[-1]
        pending = self.check("command_accept.pending")
        self.assertEqual("waiting_approval", pending["tasks"][0]["status"])
        self.assertEqual("pending", pending["approvals"][0]["status"])
        self.assertEqual([], self.fake.responses)
        review = self.app.review_approval(approval["id"])
        reviewed = self.check("command_accept.reviewed")
        self.assertEqual(["decline", "cancel", "accept"], reviewed["approvals"][0]["available_decisions"])
        self.assertNotIn(review["review_id"], json.dumps(self.app.snapshot()))
        self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        resolved = self.check("command_accept.accepted")
        self.assertEqual("resolved", resolved["approvals"][0]["status"])
        self.assertEqual("running", resolved["tasks"][0]["status"])
        self.check_replies("command_accept.replies", [(17, {"decision": "accept"})])

    def test_command_approval_declined(self):
        task = self.task()
        approval = self.approval(task)
        self.check("command_decline.pending")
        self.app.respond_approval(approval["id"], {"decision": "decline"})
        resolved = self.check("command_decline.declined")
        self.assertEqual("resolved", resolved["approvals"][0]["status"])
        self.assertEqual("running", resolved["tasks"][0]["status"])
        self.check_replies("command_decline.replies", [(17, {"decision": "decline"})])

    def test_file_change_approval_pending_then_resolved_by_server_request_resolved(self):
        task = self.task()
        self.approval(task, rpc_id=21, method=FILE_CHANGE)
        pending = self.check("file_change.pending")
        self.assertEqual("waiting_approval", pending["tasks"][0]["status"])
        self.event("serverRequest/resolved", requestId=21)
        resolved = self.check("file_change.resolved")
        self.assertEqual("resolved", resolved["approvals"][0]["status"])
        self.assertEqual("running", resolved["tasks"][0]["status"])
        self.assertEqual([], self.fake.responses)
        self.assertEqual([], self.fake.rejections)

    def test_pending_approval_finished_when_turn_completes(self):
        task = self.task()
        self.approval(task)
        self.check("turn_completed.pending")
        self.event("turn/completed", turn={**TURN, "status": "completed"})
        final = self.check("turn_completed.finished")
        # Stale, not declined: the turn ended before anyone answered.
        self.assertEqual("unavailable", final["approvals"][0]["status"])
        self.assertNotIn("decision", final["approvals"][0])
        self.assertEqual("completed", final["tasks"][0]["status"])
        self.assertFalse(self.app.pending)
        self.assertEqual([], self.fake.responses)

    def test_approval_for_unknown_thread_is_rejected(self):
        self.task()
        self.app.on_message({"id": 31, "method": "item/commandExecution/requestApproval", "params": {
            "threadId": "thread-unknown", "turnId": "turn-one",
            "command": "SYNTHETIC_PRIVATE_COMMAND", "reason": "SYNTHETIC_PRIVATE_REASON"}})
        self.assertEqual([31], self.fake.rejections)
        self.assertEqual([], self.fake.responses)
        snapshot = self.check("unknown_thread.after_request")
        self.assertEqual([], snapshot["approvals"])
        self.assertEqual("running", snapshot["tasks"][0]["status"])

    def test_snapshot_never_contains_command_text(self):
        task = self.task()
        self.approval(task, rpc_id=17)
        self.approval(task, rpc_id=18, method=FILE_CHANGE)
        text = json.dumps(self.app.snapshot())
        self.assertEqual(2, len(self.app.snapshot()["approvals"]))
        for private in ("SYNTHETIC_PRIVATE_COMMAND", "SYNTHETIC_PRIVATE_REASON"):
            self.assertNotIn(private, text)
        self.assertNotIn("SYNTHETIC_PRIVATE_COMMAND", json.dumps(normalize(self.app.snapshot())))


class CharacterizeNeedsScannerTests(unittest.TestCase):
    def test_characterize_fails_clearly_without_the_secret_scanner(self):
        with patch.dict(os.environ, {"CHARACTERIZE": "1"}), \
                patch.dict(characterization._scanner_state, {}, clear=True), \
                patch.object(characterization, "scan_preview", side_effect=FileAccessError(503, "scanner missing")):
            with self.assertRaisesRegex(AssertionError, "secret scanner"):
                normalize({"tasks": []})
            with self.assertRaisesRegex(AssertionError, "secret scanner"):
                check_golden(self, GOLDEN, "unused", {})

    def test_normal_run_without_the_scanner_still_normalizes(self):
        env = {key: value for key, value in os.environ.items() if key != "CHARACTERIZE"}
        with patch.dict(os.environ, env, clear=True), \
                patch.dict(characterization._scanner_state, {}, clear=True), \
                patch.object(characterization, "scan_preview", side_effect=FileAccessError(503, "scanner missing")):
            self.assertEqual({"tasks": []}, normalize({"tasks": []}))


if __name__ == "__main__":
    unittest.main()

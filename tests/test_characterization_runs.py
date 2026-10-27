"""Characterization of the Codex run lifecycle as projected by Dashboard.snapshot().

These tests pin today's behaviour (golden file tests/fixtures/characterization/runs.json) so a later
refactor of the Codex-shaped code in dashboard/server.py can be proven behaviour-preserving. They
describe what the dashboard does now; they do not assert that it is the desired design.
"""
import json
import unittest

from tests.characterization import ScriptedDashboard, check_golden, normalize, scanner_available

GOLDEN = "runs"
TURN = {"id": "turn-one"}


class RunLifecycleProjectionTests(ScriptedDashboard):
    def check(self, name):
        snapshot = normalize(self.app.snapshot())
        check_golden(self, GOLDEN, name, snapshot)
        return snapshot

    def start(self, prefix):
        self.task()
        self.check(prefix + ".task_started")
        self.event("turn/started", turn={**TURN, "status": "inProgress"})
        self.check(prefix + ".turn_started")

    def test_start_to_completed_projection(self):
        self.start("completed")
        self.event("turn/plan/updated", plan=[{"step": "SYNTHETIC_STEP_ONE", "status": "completed"},
                                              {"step": "SYNTHETIC_STEP_TWO", "status": "inProgress"}])
        self.check("completed.plan_updated")
        self.event("thread/tokenUsage/updated", tokenUsage={"total": {
            "inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
            "reasoningOutputTokens": 40, "totalTokens": 1100}})
        self.check("completed.token_usage_updated")
        self.event("turn/completed", turn={**TURN, "status": "completed"})
        final = self.check("completed.turn_completed")
        self.assertEqual("completed", final["tasks"][0]["status"])

    def test_failed_turn_projection(self):
        self.start("failed")
        self.event("turn/completed", turn={**TURN, "status": "failed",
                                           "error": {"message": "SYNTHETIC_FAILURE_MESSAGE"}})
        final = self.check("failed.turn_completed")
        self.assertEqual("failed", final["tasks"][0]["status"])

    def test_interrupted_turn_projection(self):
        task = self.task()
        self.event("turn/started", turn={**TURN, "status": "inProgress"})
        result = self.app.interrupt(task["id"], {})
        self.assertEqual("interrupt_requested", result["status"])
        self.assertIn(("turn/interrupt", {"threadId": "thread-one", "turnId": "turn-one"}), self.fake.requests)
        pending = self.check("interrupted.interrupt_requested")
        self.assertEqual("running", pending["tasks"][0]["status"])
        self.event("turn/completed", turn={**TURN, "status": "interrupted"})
        final = self.check("interrupted.turn_completed")
        self.assertEqual("interrupted", final["tasks"][0]["status"])

    def test_unknown_terminal_status_projection(self):
        self.start("unknown_status")
        self.event("turn/completed", turn={**TURN, "status": "weird"})
        final = self.check("unknown_status.turn_completed")
        self.assertEqual("unknown", final["tasks"][0]["status"])

    def test_stale_turn_event_is_ignored(self):
        self.start("stale")
        before = self.check("stale.before_stale_events")
        stale = {"turnId": "turn-stale"}
        self.event("turn/plan/updated", plan=[{"step": "SYNTHETIC_STALE_STEP", "status": "completed"}], **stale)
        self.event("thread/tokenUsage/updated", tokenUsage={"total": {
            "inputTokens": 5, "cachedInputTokens": 0, "outputTokens": 5,
            "reasoningOutputTokens": 0, "totalTokens": 10}}, **stale)
        self.event("turn/completed", turn={"id": "turn-stale", "status": "failed"}, **stale)
        after = self.check("stale.after_stale_events")
        self.assertEqual(before, after)
        self.assertEqual("running", after["tasks"][0]["status"])


class GoldenHygieneTests(ScriptedDashboard):
    def test_normalized_golden_has_stable_ids_and_no_volatile_values(self):
        task = self.task()
        text = json.dumps(normalize(self.app.snapshot()), sort_keys=True)
        self.assertIn('"task-1"', text)
        self.assertIn('"project-1"', text)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(task["id"], text)
        self.assertNotRegex(text, r"\b20\d\d-\d\d-\d\dT")
        self.assertNotRegex(text, r"\b[0-9a-f]{32}\b")

    @unittest.skipUnless(scanner_available(), "reviewed secret scanner (gitleaks) is unavailable; secret-pattern assertion skipped")
    def test_normalize_rejects_secret_looking_values(self):
        # Built at run time so no secret-looking literal exists in this source file.
        secret = "pass" + "word = " + '"' + "x7Qm2" + "Lp9Zr4Tv8" + '"'
        with self.assertRaises(AssertionError):
            normalize({"tasks": [{"id": "a" * 32, "error": secret}]})


if __name__ == "__main__":
    unittest.main()

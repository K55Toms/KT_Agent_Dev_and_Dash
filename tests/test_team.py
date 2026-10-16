"""Recognition authority, persistence and limits without paid Codex runs."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.project_files import FileAccessError, scan_preview
from dashboard.server import load_roles
from dashboard.store import Store
from dashboard.team import PROFILES, Team, TeamError


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.directory = Path(self.temp.name) / "state"
        self.store = Store(self.directory)
        self.team = Team(self.store, load_roles())
        self.tasks = {
            "chief-task": self.task("chief-task", "chief_of_staff", "running"),
            "backend-task": self.task("backend-task", "backend_developer", "completed"),
            "ui-task": self.task("ui-task", "ui_designer", "completed"),
        }
        self.clock = patch("dashboard.team._now", return_value=datetime(2026, 10, 16, 12, tzinfo=timezone.utc))
        self.clock.start()
        self.scanner = patch("dashboard.team.scan_preview")
        self.scan = self.scanner.start()

    def tearDown(self):
        self.scanner.stop()
        self.clock.stop()
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def task(task_id, role, status):
        return {"id": task_id, "role": role, "status": status, "title": "Observed implementation task",
                "thread_id": "thread-" + task_id, "turn_id": "turn-" + task_id,
                "created_at": "2026-10-16T10:00:00+00:00", "updated_at": "2026-10-16T11:00:00+00:00"}

    def award(self, **changes):
        arguments = {"source_task": self.tasks["chief-task"], "recipient_id": "backend_developer",
                     "kind": "rebel_coins", "coins": 10, "reason": "Thank you for the completed task.",
                     "source_event_id": "call-1", "tasks": self.tasks}
        arguments.update(changes)
        return self.team.issue_award(**arguments)

    def test_empty_roster_has_no_fabricated_work_or_rewards_and_all_profiles(self):
        snapshot = self.team.snapshot({})
        self.assertEqual(14, len(snapshot["members"]))
        self.assertEqual(set(PROFILES), {member["id"] for member in snapshot["members"]})
        self.assertEqual([], snapshot["awards"])
        for member in snapshot["members"]:
            self.assertIsNone(member["last_task"])
            self.assertEqual(0, member["coins"])
            self.assertFalse(member["agent_of_week"])
            self.assertEqual(f'/team-portraits/{member["id"]}.svg', member["portrait"])
            self.assertTrue(member["description"])
            self.assertNotIn("instructions", member)
        self.scan.assert_not_called()

    def test_snapshot_only_reports_latest_observed_task_and_status(self):
        self.tasks["later"] = self.task("later", "backend_developer", "failed")
        self.tasks["later"]["updated_at"] = "2026-10-16T13:00:00+00:00"
        member = next(member for member in self.team.snapshot(self.tasks)["members"] if member["id"] == "backend_developer")
        self.assertEqual({"id", "title", "status", "updated_at", "last_summary", "parent_task_id"}, set(member["last_task"]))
        self.assertIsNone(member["last_task"]["last_summary"])
        self.assertEqual("failed", member["last_task"]["status"])
        self.assertEqual("later", member["last_task"]["id"])
        self.assertEqual(0, member["coins"])
        self.tasks["later"].update(last_summary="Reported the integration result.", last_summary_source="model-reported")
        updated = next(member for member in self.team.snapshot(self.tasks)["members"] if member["id"] == "backend_developer")
        self.assertEqual("Reported the integration result.", updated["last_task"]["last_summary"])

    def test_scanned_award_is_immutable_idempotent_and_survives_restart(self):
        award = self.award()
        self.scan.assert_called_once_with(b"Thank you for the completed task.")
        self.assertEqual("chief_of_staff", award["issuer"])
        self.assertEqual("2026-W42", award["week"])
        self.assertEqual(award, self.award())
        with self.assertRaises(TeamError):
            self.award(coins=11)
        award["coins"] = 999
        self.store.close()
        self.store = Store(self.directory)
        self.team = Team(self.store, load_roles())
        snapshot = self.team.snapshot(self.tasks)
        member = next(member for member in snapshot["members"] if member["id"] == "backend_developer")
        self.assertEqual(10, member["coins"])
        self.assertEqual(1, len(snapshot["awards"]))
        self.assertEqual(10, snapshot["awards"][0]["coins"])

    def test_authority_rechecked_from_trusted_task_map(self):
        for status in ("queued", "completed", "failed", "interrupted", "unknown"):
            self.tasks["chief-task"]["status"] = status
            with self.assertRaises(TeamError):
                self.award()
        self.tasks["chief-task"]["status"] = "running"
        for role in ("product_manager", "backend_developer", "unknown"):
            self.tasks["chief-task"]["role"] = role
            forged = dict(self.tasks["chief-task"], role="chief_of_staff")
            with self.assertRaises(TeamError):
                self.award(source_task=forged)
        self.assertEqual([], self.store.load("team_award"))
        self.scan.assert_not_called()

    def test_unknown_source_or_stale_turn_cannot_issue(self):
        forged = dict(self.tasks["chief-task"], id="not-recorded")
        with self.assertRaises(TeamError):
            self.award(source_task=forged)
        forged = dict(self.tasks["chief-task"], turn_id="old-turn")
        with self.assertRaises(TeamError):
            self.award(source_task=forged)
        self.tasks["chief-task"]["turn_id"] = None
        with self.assertRaises(TeamError):
            self.award()
        self.assertEqual([], self.store.load("team_award"))

    def test_only_known_teammates_with_real_completed_tasks_receive_awards(self):
        for recipient in ("unknown", "chief_of_staff", "qa_engineer", [], None):
            with self.assertRaises(TeamError):
                self.award(recipient_id=recipient)
        self.tasks["backend-task"]["status"] = "running"
        with self.assertRaises(TeamError):
            self.award()
        self.assertEqual([], self.store.load("team_award"))
        self.scan.assert_not_called()

    def test_bounds_and_kinds_reject_invalid_payloads(self):
        for coins in (0, -1, 21, True, "10", 1.5):
            with self.assertRaises(TeamError):
                self.award(coins=coins)
        for reason in ("", " ", "x" * 501, "line\nsecret", "x\x00x"):
            with self.assertRaises(TeamError):
                self.award(reason=reason)
        for kind in ("bonus", None, []):
            with self.assertRaises(TeamError):
                self.award(kind=kind)
        for event in ("", "contains spaces", "x" * 161, None):
            with self.assertRaises(TeamError):
                self.award(source_event_id=event)
        self.assertEqual([], self.store.load("team_award"))

    def test_scanner_failure_withholds_reason_and_all_records(self):
        self.scan.side_effect = FileAccessError(503, "Internal scan detail")
        with self.assertRaisesRegex(TeamError, "sensitive-content checks did not pass"):
            self.award()
        self.assertEqual([], self.store.load("team_award"))
        self.assertNotIn(b"Thank you for the completed task.", (self.directory / "dashboard.sqlite3").read_bytes())

    def test_prepared_reason_avoids_lock_time_scan_but_never_grants_authority(self):
        reason = "Thank you for the completed task."
        proof = self.team.prepare_reason(reason)
        self.assertNotIn(reason, repr(proof))
        self.assertEqual(1, self.scan.call_count)
        self.award(prepared_reason=proof)
        self.assertEqual(1, self.scan.call_count)
        self.tasks["chief-task"]["status"] = "completed"
        with self.assertRaises(TeamError):
            self.award(recipient_id="ui_designer", source_event_id="another", prepared_reason=proof)
        self.assertEqual(1, len(self.store.load("team_award")))

    def test_prepared_reason_is_bound_to_text_and_team_instance(self):
        proof = self.team.prepare_reason("Scanned appreciation.")
        for fake in (True, {"reason": "anything"}, object(), proof):
            with self.assertRaises(TeamError):
                self.award(prepared_reason=fake)
        other = Team(self.store, load_roles())
        with self.assertRaises(TeamError):
            self.award(prepared_reason=other.prepare_reason("Thank you for the completed task."))
        self.assertEqual([], self.store.load("team_award"))

    def test_real_scanner_rejects_constructed_sensitive_reason_without_persistence(self):
        self.scan.side_effect = scan_preview
        value = "constructed" + "-nonfunctional-" + "fixture"
        reason = "password" + " = '" + value + "'"
        with self.assertRaisesRegex(TeamError, "sensitive-content checks did not pass"):
            self.award(reason=reason)
        self.assertEqual([], self.store.load("team_award"))
        self.assertNotIn(value.encode(), (self.directory / "dashboard.sqlite3").read_bytes())

    def test_semantic_duplicate_different_call_cannot_mint_twice(self):
        self.award()
        for kind in ("rebel_coins", "agent_of_week"):
            with self.assertRaisesRegex(TeamError, "already recognized"):
                self.award(source_event_id="call-2", kind=kind)
        self.assertEqual(1, len(self.store.load("team_award")))

    def test_weekly_coin_cap_cannot_be_bypassed_by_new_chief_tasks(self):
        for index in range(5):
            chief = self.task(f"chief-{index}", "chief_of_staff", "running")
            self.tasks[chief["id"]] = chief
            self.award(source_task=chief, coins=20)
        with self.assertRaisesRegex(TeamError, "weekly Rebel coin limit"):
            self.award(coins=1)
        with patch("dashboard.team._now", return_value=datetime(2026, 10, 19, 0, tzinfo=timezone.utc)):
            self.award(coins=1)
        member = next(member for member in self.team.snapshot(self.tasks)["members"] if member["id"] == "backend_developer")
        self.assertEqual(101, member["coins"])

    def test_agent_of_week_unique_teamwide_utc_week_and_expires(self):
        self.award(kind="agent_of_week", coins=20)
        with self.assertRaisesRegex(TeamError, "already issued this UTC week"):
            self.award(recipient_id="ui_designer", kind="agent_of_week", source_event_id="call-2")
        member = next(member for member in self.team.snapshot(self.tasks)["members"] if member["id"] == "backend_developer")
        self.assertTrue(member["agent_of_week"])
        with patch("dashboard.team._now", return_value=datetime(2026, 10, 19, 0, tzinfo=timezone.utc)):
            self.award(recipient_id="ui_designer", kind="agent_of_week", source_event_id="call-2")
            members = {member["id"]: member for member in self.team.snapshot(self.tasks)["members"]}
            self.assertFalse(members["backend_developer"]["agent_of_week"])
            self.assertTrue(members["ui_designer"]["agent_of_week"])

    def test_two_store_instances_share_atomic_award_constraints(self):
        second_store = Store(self.directory)
        try:
            second = Team(second_store, load_roles())
            self.award()
            with self.assertRaisesRegex(TeamError, "already recognized"):
                second.issue_award(self.tasks["chief-task"], "backend_developer", "rebel_coins", 10,
                                   "Another thank you.", "call-2", self.tasks)
            self.assertEqual(1, len(second.snapshot(self.tasks)["awards"]))
        finally:
            second_store.close()

    def test_corrupt_ledger_fails_closed(self):
        self.store.put("team_award", {"id": "malformed", "unexpected": True})
        with self.assertRaisesRegex(TeamError, "could not be read safely"):
            self.team.snapshot(self.tasks)
        with self.assertRaises(TeamError):
            self.award()


if __name__ == "__main__":
    unittest.main()

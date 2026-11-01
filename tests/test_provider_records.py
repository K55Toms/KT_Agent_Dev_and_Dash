"""Projects and runs record their provider (Review Focus 3 and 4)."""
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest

from dashboard.backends.base import NoBackend
from dashboard.backends.claude import ClaudeBackendStub
from dashboard.server import Dashboard
from dashboard.store import Store
from tests.characterization import ScriptedDashboard, require_scanner
from tests.policy_fixtures import SyntheticPolicy

REFUSAL = "recorded under a different provider"
ID_A = "a" * 32
ID_B = "b" * 32


def legacy_rows(directory):
    """Write a project and a task the way every database before this change holds them: no provider."""
    store = Store(Path(directory))
    store.put("project", {"id": ID_A, "name": "Legacy", "path": "/private/tmp/legacy-project",
                          "created_at": "2026-01-01T00:00:00+00:00"})
    store.put("task", {"id": ID_B, "project_id": ID_A, "title": "Legacy run", "role": "backend_developer",
                       "model": "m", "profile_model": "m", "reasoning": "high", "status": "completed",
                       "thread_id": "thread-one", "turn_id": "turn-one", "plan": [], "compliance_policy": {},
                       "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
                       "error": None, "diagnostics": [], "usage": None, "cost": {}})
    store.close()


class RecordedProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.directory = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def stored(self, kind):
        store = Store(self.directory / "state")
        try:
            return {row["id"]: row for row in store.load(kind)}
        finally:
            store.close()

    def test_legacy_records_load_as_codex(self):
        legacy_rows(self.directory / "state")
        for row in self.stored("project").values():
            self.assertNotIn("provider", row)
        for row in self.stored("task").values():
            self.assertNotIn("provider", row)
        app = Dashboard(self.directory / "state", policy_provider=SyntheticPolicy())
        self.addCleanup(app.close)
        self.assertEqual("codex", app.projects[ID_A]["provider"])
        self.assertEqual("codex", app.tasks[ID_B]["provider"])
        snapshot = app.snapshot()
        self.assertNotIn("provider", snapshot["projects"][0])
        self.assertNotIn("provider", snapshot["tasks"][0])

    def test_legacy_records_load_as_codex_under_other_deployments(self):
        for backend in (ClaudeBackendStub(), NoBackend()):
            directory = self.directory / backend.capabilities.provider
            legacy_rows(directory)
            app = Dashboard(directory, policy_provider=SyntheticPolicy(), backend=backend)
            self.addCleanup(app.close)
            self.assertEqual("codex", app.projects[ID_A]["provider"])
            self.assertEqual("codex", app.tasks[ID_B]["provider"])
            self.assertEqual("codex", app.snapshot()["tasks"][0].get("provider", "codex"))

    def test_other_provider_rows_survive_reload_and_show_in_snapshot(self):
        legacy_rows(self.directory / "state")
        store = Store(self.directory / "state")
        for kind, identifier in (("project", ID_A), ("task", ID_B)):
            row = store.load(kind)[0]
            row["provider"] = "claude"
            store.put(kind, row)
        store.close()
        app = Dashboard(self.directory / "state", policy_provider=SyntheticPolicy())
        self.addCleanup(app.close)
        self.assertEqual("claude", app.projects[ID_A]["provider"])
        self.assertEqual("claude", app.tasks[ID_B]["provider"])
        snapshot = app.snapshot()
        self.assertEqual("claude", snapshot["projects"][0]["provider"])
        self.assertEqual("claude", snapshot["tasks"][0]["provider"])
        self.assertEqual("claude", self.stored("task")[ID_B]["provider"])


class CreatedRecordTests(ScriptedDashboard):
    def test_new_records_carry_active_provider(self):
        task = self.task()
        self.assertEqual("codex", self.project["provider"])
        self.assertEqual("codex", task["provider"])
        store = Store(self.root / "state")
        try:
            self.assertEqual(["codex"], [row["provider"] for row in store.load("project")])
            self.assertEqual(["codex"], [row["provider"] for row in store.load("task")])
        finally:
            store.close()

    def test_no_provider_dashboard_never_writes_none(self):
        app = Dashboard(self.root / "none-state", policy_provider=SyntheticPolicy(), backend=NoBackend())
        self.addCleanup(app.close)
        project = app.add_project({"name": "Folder", "path": str(self.root)})
        self.assertIn(project["provider"], {"codex", "claude"})

    def test_snapshot_omits_provider_for_codex_and_shows_others(self):
        task = self.task()
        snapshot = self.app.snapshot()
        self.assertNotIn("provider", snapshot["projects"][0])
        self.assertNotIn("provider", snapshot["tasks"][0])
        self.assertEqual("codex", self.app.tasks[task["id"]]["provider"])
        self.app.tasks[task["id"]]["provider"] = "claude"
        self.app.projects[self.project["id"]]["provider"] = "claude"
        snapshot = self.app.snapshot()
        self.assertEqual("claude", snapshot["projects"][0]["provider"])
        self.assertEqual("claude", snapshot["tasks"][0]["provider"])
        # The snapshot is a copy: building it never changes the stored record.
        self.assertEqual("claude", self.app.tasks[task["id"]]["provider"])


@require_scanner()
class OtherProviderRunTests(ScriptedDashboard):
    """A run recorded under another provider is shown, read and deleted, but never acted on."""

    def setUp(self):
        super().setUp()
        self.task_record = self.task()
        self.task_id = self.task_record["id"]
        self.app.on_message({"id": 17, "method": "item/commandExecution/requestApproval", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "itemId": "item-one", "startedAtMs": 1,
            "command": "SYNTHETIC_PRIVATE_COMMAND", "cwd": str(self.root), "reason": "SYNTHETIC_PRIVATE_REASON",
            "availableDecisions": ["accept", "decline", "cancel"]}})
        self.approval_id = list(self.app.approvals)[-1]
        self.app.on_message({"id": 71, "method": "item/tool/requestUserInput", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "itemId": "question-item",
            "questions": [{"id": "layout", "header": "Layout", "question": "Which layout should we use?",
                           "options": [{"label": "Compact", "description": "Use less space"},
                                       {"label": "Roomy", "description": "Use more space"}]}]}})
        self.app.wait_conversations()
        self.question_id = list(self.app.questions)[-1]
        self.assertIn(self.question_id, self.app.question_requests)

    def record_under_claude(self):
        self.app.tasks[self.task_id]["provider"] = "claude"
        self.app.store.put("task", self.app.tasks[self.task_id])
        self.fake.requests.clear()
        self.fake.responses.clear()
        self.before = {"tasks": deepcopy(self.app.tasks), "approvals": deepcopy(self.app.approvals),
                       "questions": deepcopy(self.app.questions), "pending": set(self.app.pending),
                       "question_requests": set(self.app.question_requests),
                       "stored_tasks": self.app.store.load("task"), "stored_approvals": self.app.store.load("approval")}

    def assert_untouched(self):
        self.assertEqual([], self.fake.requests)
        self.assertEqual([], self.fake.responses)
        self.assertEqual([], self.fake.rejections)
        self.assertEqual(self.before["tasks"], self.app.tasks)
        self.assertEqual(self.before["approvals"], self.app.approvals)
        self.assertEqual(self.before["questions"], self.app.questions)
        self.assertEqual(self.before["pending"], set(self.app.pending))
        self.assertEqual(self.before["question_requests"], set(self.app.question_requests))
        self.assertEqual(self.before["stored_tasks"], self.app.store.load("task"))
        self.assertEqual(self.before["stored_approvals"], self.app.store.load("approval"))
        self.assertFalse(any(request.get("busy") for request in self.app.pending.values()))
        self.assertEqual(set(), self.app.message_busy)

    def refused(self, call, *args):
        with self.assertRaises(ValueError) as caught:
            call(*args)
        self.assertEqual(REFUSAL, str(caught.exception))
        self.assert_untouched()

    def delivery_payload(self, kind):
        extra = {"expected_plan_version": 1} if kind == "checks" else {"check_operation_id": "c" * 32}
        return {"expected_snapshot": "d" * 64, "operation_id": "e" * 32, "confirmed": True, **extra}

    def test_actions_on_other_provider_run_are_refused(self):
        self.record_under_claude()
        app, task_id = self.app, self.task_id
        calls = {
            "send_message": (app.send_message, task_id, {"text": "hello", "expected_turn_id": "turn-one"}),
            "interrupt": (app.interrupt, task_id, {}),
            "respond_approval": (app.respond_approval, self.approval_id, {"decision": "decline"}),
            "respond_question": (app.respond_question, self.question_id, {"answers": {"layout": ["Compact"]}}),
            "request_approval_alternative": (app.request_approval_alternative, self.approval_id, {"text": "smaller"}),
            "start_delivery_checks": (app.start_delivery_checks, task_id, self.delivery_payload("checks")),
            "start_delivery_review": (app.start_delivery_review, task_id, self.delivery_payload("reviews")),
            "recovery_check": (app.recovery_check, task_id, {"expected_revision": 1}),
            "recovery_assess": (app.recovery_assess, task_id, {
                "receipt_id": "r", "operation_id": "f" * 32, "selected_message_ids": [], "text": "x", "confirmed": True}),
            "recovery_continue": (app.recovery_continue, task_id, {
                "receipt_id": "r", "operation_id": "f" * 32, "assessment_task_id": "a" * 32,
                "plan_id": "p", "plan_digest": "d", "confirmed": True}),
            "recovery_cancel": (app.recovery_cancel, task_id, "f" * 32, {"expected_revision": 1, "confirmed": True}),
        }
        self.assertEqual("waiting_approval", app.tasks[task_id]["status"])
        for name, (call, *args) in calls.items():
            with self.subTest(handler=name):
                self.refused(call, *args)
        self.assertEqual("pending", app.approvals[self.approval_id]["status"])
        self.assertIn(self.approval_id, app.pending)
        self.assertEqual("pending", app.questions[self.question_id]["status"])

    def test_approval_authority_is_not_consumed_before_the_guard(self):
        self.record_under_claude()
        request = self.app.pending[self.approval_id]
        self.refused(self.app.respond_approval, self.approval_id, {"decision": "decline"})
        self.assertIs(request, self.app.pending[self.approval_id])
        self.refused(self.app.request_approval_alternative, self.approval_id, {"text": "smaller"})
        self.assertIs(request, self.app.pending[self.approval_id])

    def test_run_recorded_under_codex_is_refused_by_a_claude_deployment(self):
        """Review Focus 4: a deployment switched from Codex to Claude still holds Codex runs."""
        self.app.close()
        state = self.root / "state"
        app = Dashboard(state, policy_provider=SyntheticPolicy(), backend=ClaudeBackendStub())
        self.addCleanup(app.close)
        self.app = app
        task = app.tasks[self.task_id]
        self.assertEqual("codex", task["provider"])
        for name, call, args in (
                ("send_message", app.send_message, (self.task_id, {"text": "hello", "expected_turn_id": "turn-one"})),
                ("interrupt", app.interrupt, (self.task_id, {})),
                ("respond_approval", app.respond_approval, (self.approval_id, {"decision": "decline"})),
                ("request_approval_alternative", app.request_approval_alternative, (self.approval_id, {"text": "x"})),
                ("start_delivery_checks", app.start_delivery_checks, (self.task_id, self.delivery_payload("checks"))),
                ("start_delivery_review", app.start_delivery_review, (self.task_id, self.delivery_payload("reviews")))):
            with self.subTest(handler=name):
                before = deepcopy(app.tasks), deepcopy(app.approvals)
                with self.assertRaises(ValueError) as caught:
                    call(*args)
                self.assertEqual(REFUSAL, str(caught.exception))
                self.assertEqual(before, (app.tasks, app.approvals))

    def test_matching_provider_is_not_refused_by_the_guard(self):
        self.fake.requests.clear()
        self.app.interrupt(self.task_id, {})
        self.assertEqual("turn/interrupt", self.fake.requests[0][0])

    def test_read_routes_and_delete_work_for_other_provider_run(self):
        self.record_under_claude()
        app, task_id = self.app, self.task_id
        snapshot = app.snapshot()
        self.assertEqual("claude", snapshot["tasks"][0]["provider"])
        self.assertEqual(task_id, app.conversation(task_id)["task_id"])
        app.delivery(task_id)
        app.output_metadata(app.tasks[task_id])
        self.assertEqual([], self.fake.responses)
        # A running run cannot be deleted whatever its provider; the native completion event ends it.
        self.event("turn/completed", turn={"id": "turn-one", "status": "completed"})
        task = app.tasks[task_id]
        self.assertEqual("completed", task["status"])
        self.assertEqual("claude", task["provider"])
        version = app.task_deletion_state(task)["deletion_version"]
        app.delete_task(task_id, {"expected_version": version, "confirmed": True})
        self.assertNotIn(task_id, app.tasks)
        self.assertEqual([], self.fake.requests)
        self.assertEqual([], self.fake.responses)


if __name__ == "__main__":
    unittest.main()

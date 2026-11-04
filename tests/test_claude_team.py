"""Plan 5 Task 4: the team view of a Claude deployment over the fake binary (fake-binary evidence).

Summary text is the stored main-session reply of the latest turn, bounded; rewards do not exist in a Claude deployment.
"""
from dashboard.backends.base import NeutralEvent
from dashboard.server import CLAUDE_SUMMARY_LIMIT
from tests import test_claude_slice2b_baseline as baseline

SID = baseline.SESSION


class ClaudeTeamServerTests(baseline.Slice2bHarness):
    def live_task(self):
        task = self.finished_task()
        with self.app.lock:
            real = self.app.tasks[task["id"]]
            real["status"] = "running"
            owned = self.app.owned_threads[SID]
            owned.update(active=True, current_turn=real["turn_id"])
            owned["turns"].add(real["turn_id"])
        return real

    def send(self, task, kind, turn_id, **data):
        run = object()
        with self.app.lock:
            self.app.runs[task["id"]] = run
        try:
            with self.app.lock:
                self.app._claude_event_locked(task["id"], run, NeutralEvent(kind, SID, turn_id, data), SID)
        finally:
            with self.app.lock:
                self.app.runs.pop(task["id"], None)

    def member(self, role="backend_developer"):
        status, team = self.http("GET", "/api/team")
        self.assertEqual(200, status)
        return next(m for m in team["members"] if m["id"] == role)

    def test_final_reply_becomes_the_model_reported_summary(self):
        task = self.finished_task()
        self.assertEqual("SENSITIVE_ASSISTANT_TEXT_MARKER", self.app.tasks[task["id"]]["last_summary"])
        self.assertEqual("model-reported", self.app.tasks[task["id"]]["last_summary_source"])
        self.assertEqual("SENSITIVE_ASSISTANT_TEXT_MARKER", self.member()["last_task"]["last_summary"])
        self.assertEqual("SENSITIVE_ASSISTANT_TEXT_MARKER", self.store_task(task)["last_summary"])

    def store_task(self, task):
        return next(r for r in self.app.store.load("task") if r["id"] == task["id"])

    def test_claude_last_summary_is_model_reported_and_bounded(self):
        task = self.live_task()
        turn = task["turn_id"]
        self.send(task, "message", turn, event_id="m-1", text="first reply")
        self.send(task, "message", turn, event_id="m-2", text="x" * 900)
        summary = self.app.tasks[task["id"]]["last_summary"]
        self.assertEqual(CLAUDE_SUMMARY_LIMIT, len(summary))
        self.assertTrue(summary.endswith("…"))
        self.assertEqual("model-reported", self.app.tasks[task["id"]]["last_summary_source"])

    def test_withheld_or_other_turn_reply_never_sets_a_summary(self):
        task = self.live_task()
        self.app.tasks[task["id"]]["last_summary"] = None
        self.send(task, "message", task["turn_id"], event_id="m-s", text="unsafe \x01 text")
        self.send(task, "message", "another-turn", event_id="m-o", text="belongs elsewhere")
        self.assertIsNone(self.app.tasks[task["id"]]["last_summary"])

    def test_new_turn_without_reply_clears_the_previous_summary(self):
        task = self.live_task()
        self.assertEqual("SENSITIVE_ASSISTANT_TEXT_MARKER", self.app.tasks[task["id"]]["last_summary"])
        self.send(task, "turn_started", "turn-two", version="1", model_id="m", permission_mode="default")
        self.assertIsNone(self.app.tasks[task["id"]]["last_summary"])
        self.assertIsNone(self.member()["last_task"]["last_summary"])

    def test_no_awards_in_claude_deployment(self):
        self.finished_task()
        status, team = self.http("GET", "/api/team")
        self.assertEqual(200, status)
        self.assertEqual([], team["awards"])
        self.assertIs(False, team["rewards"])
        for member in team["members"]:
            self.assertNotIn("coins", member)
            self.assertNotIn("agent_of_week", member)

    def test_snapshot_ignores_other_provider_tasks(self):
        task = self.finished_task()
        with self.app.lock:
            self.app.tasks["codex-x"] = {**self.app.tasks[task["id"]], "id": "codex-x", "provider": "codex",
                                         "title": "Codex task", "parent_task_id": None}
            self.app.tasks["legacy-y"] = {**self.app.tasks["codex-x"], "id": "legacy-y"}
            del self.app.tasks["legacy-y"]["provider"]
        ids = [a["id"] for a in self.member()["activities"]]
        self.assertEqual([task["id"]], ids)

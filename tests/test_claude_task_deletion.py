"""Plan 5 Task 6: deleting a Claude task, edge cases (held approval, live or launching run, restart flag, follow-up).

Evidence kind: fake-binary evidence, not a live run. Every run executes tests/fake_claude.py through the real argv
builder, the real ClaudeRun, the real loopback hook receiver and the real HTTP handler (keyed test server); the run
factory refuses any other executable. This is a new module, not an addition to tests/test_task_deletion.py: that file
builds Codex fixtures by hand (FakeClient, thread ids), while these tests need the fake-claude harness.
"""
from copy import deepcopy
import json
import unittest
from unittest import mock

from dashboard.diagnostics import DETAILS
from dashboard.hook_receiver import HeldRequest
from tests.test_claude_slice2b_baseline import (FOLLOWUP, INSTRUCTION, SESSION, TERMINAL, Slice2bHarness,
                                                stray_fakes, wait_for)

LIVE_BLOCKER = "Stop the run and its active agents before deleting it."
REQUEST_BLOCKER = "Resolve the pending request or stop the run before deleting it."
BUSY_BLOCKER = "Wait for the current operation to finish or stop it before deleting this run."
STALE = "Run changed. Refresh and confirm deletion again."
CONFIRM = "Confirm deletion using the current run version"
NOT_FOUND = "Run was not found. Refresh the dashboard."
GENERIC = "Request rejected. Check fields, connection, project and action availability."  # HTTP text of any ValueError


class ClaudeDeletionTests(Slice2bHarness):
    # ---- helpers -----------------------------------------------------------------------------------
    def delete_body(self, task_id, **changes):
        with self.app.lock:
            state = self.app.task_deletion_state(self.app.tasks[task_id])
        body = {"expected_version": state["deletion_version"], "confirmed": True}
        body.update(changes)
        return body

    def delete(self, task_id, body=None):
        return self.http("POST", f"/api/tasks/{task_id}/delete", self.delete_body(task_id) if body is None else body)

    def project(self):
        status, project = self.http("POST", "/api/projects", {"name": "project", "path": str(self.project_dir)})
        self.assertEqual(200, status, project)
        return project

    def start(self, fixture, **env):
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, **env)
        project = next(iter(self.app.projects.values()), None) or self.project()
        status, task = self.http("POST", "/api/tasks", {"project_id": project["id"], "title": "Synthetic run",
                                                       "instruction": INSTRUCTION, "role": "backend_developer"})
        self.assertEqual(200, status, task)
        return task["id"]

    def live(self):
        task_id = self.start("no_result", FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "running"
                                 and self.app.tasks[task_id]["claude"]["session_id"] == SESSION))
        return task_id

    def stop(self, task_id):
        status, answer = self.http("POST", f"/api/tasks/{task_id}/interrupt", {})
        self.assertEqual(200, status, answer)
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL and task_id not in self.app.runs
                                 and task_id not in self.app.launching_tasks))

    def pending(self, task_id):
        def rows():
            with self.app.lock:
                return [a for a in self.app.approvals.values() if a["task_id"] == task_id
                        and a["status"] == "pending" and a["kind"] == "tool_call"]
        self.assertTrue(wait_for(lambda: len(rows()) == 1), "no pending approval")
        return rows()[0]

    def held_run(self):
        """A live run whose own PermissionRequest hook request is held (a pending tool_call approval)."""
        record = self.root / "record.jsonl"
        gate = self.root / "gate"
        task_id = self.start("success", FAKE_CLAUDE_HOOK="ask_silent", FAKE_CLAUDE_HOOK_GATE=str(gate),
                             FAKE_CLAUDE_IGNORE_SIGINT="1", FAKE_CLAUDE_RECORD=str(record))
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["claude"]["session_id"] == SESSION))
        gate.write_text("go")
        approval = self.pending(task_id)
        with self.app.lock:
            held = self.app.pending[approval["id"]]["held"]
        return task_id, approval, held, record

    def hook_record(self, record):
        lines = [json.loads(x) for x in record.read_text().splitlines() if x.strip()]
        return [x["hook"] for x in lines if "hook" in x]

    def assert_gone(self, task_id, approval_ids=()):
        self.assertNotIn(task_id, self.app.tasks)
        self.assertEqual([], [r for r in self.app.store.load("task") if r["id"] == task_id])
        self.assertEqual([], [m for m in self.app.messages if m.get("task_id") == task_id])
        self.assertEqual([], [m for m in self.app.store.load("conversation") if m.get("task_id") == task_id])
        self.assertEqual([], [o for o in self.app.owned_threads.values() if o.get("task_id") == task_id])
        self.assertEqual([], [o for o in self.app.observed_tasks.values() if o.get("parent_task_id") == task_id])
        self.assertEqual([], [o for o in self.app.store.load("team_activity") if o.get("parent_task_id") == task_id])
        self.assertEqual({}, {k: v for k, v in self.app.pending.items() if v.get("task_id") == task_id})
        for approval_id in approval_ids:
            self.assertNotIn(approval_id, self.app.approvals)
            self.assertEqual([], [a for a in self.app.store.load("approval") if a["id"] == approval_id])
        self.assertNotIn(task_id, json.dumps(self.state()))

    # ---- held approval -----------------------------------------------------------------------------
    def test_delete_with_held_approval_denies_it_and_releases_everything(self):
        task_id, approval, held, record = self.held_run()
        review = self.app.review_approval(approval["id"])  # a review exists for the card
        # While the request is held the run is live: deletion is refused and decides nothing.
        status, answer = self.delete(task_id)
        self.assertEqual((409, LIVE_BLOCKER), (status, answer["error"]))
        self.assertIsNone(held.decision)
        self.assertEqual("pending", self.app.approvals[approval["id"]]["status"])
        self.assertEqual("waiting_approval", self.app.tasks[task_id]["status"])
        self.stop(task_id)
        # The stop denied the hook request (the fake was told deny, never allow) and withdrew the card.
        self.assertEqual("deny", held.decision)
        self.assertTrue(wait_for(lambda: bool(self.hook_record(record)), 10), "the fake was never answered")
        self.assertEqual([{"scenario": "ask_silent", "calls": 1, "told": ["deny"]}], self.hook_record(record))
        self.assertNotIn("SENTINEL_TOOL_RESULT", json.dumps(self.app.messages))  # the tool never ran
        self.assertEqual("unavailable", self.app.approvals[approval["id"]]["status"])
        status, answer = self.delete(task_id)
        self.assertEqual((200, {"task_id": task_id, "deleted": True}), (status, answer))
        self.assert_gone(task_id, [approval["id"]])
        self.assertTrue(wait_for(lambda: not self.app.hook_runs, 5))
        with self.assertRaises(ValueError):  # neither the card nor its review can be used any more
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        with self.assertRaises(ValueError):
            self.app.review_approval(approval["id"])
        self.assertEqual("deny", held.decision)
        self.assertEqual([], [p for p in (self.app.state_dir / "claude-runs").iterdir()])
        self.assertEqual([], self.app.active_project_roots())
        self.assertEqual([], stray_fakes())

    def test_delete_denies_a_left_over_held_request_and_removes_its_card(self):
        task_id = self.start("success")
        self.wait_finished(task_id)
        held = HeldRequest()
        approval = {"id": "a" * 32, "task_id": task_id, "kind": "tool_call", "status": "pending",
                    "available_decisions": ["accept", "decline"]}
        with self.app.lock:  # a pending card and its held request left behind for a finished task
            self.app.approvals[approval["id"]] = approval
            self.app.store.put("approval", approval)
            self.app.pending[approval["id"]] = {"provider": "claude", "task_id": task_id, "held": held}
        # A live request blocks deletion with its own message, and changes nothing.
        status, answer = self.delete(task_id)
        self.assertEqual((409, REQUEST_BLOCKER), (status, answer["error"]))
        self.assertIsNone(held.decision)
        self.assertIn(approval["id"], self.app.approvals)
        with self.app.lock:  # the card is resolved but the held request is still there
            approval.update(status="unavailable", available_decisions=[])
            self.app.store.put("approval", approval)
        status, answer = self.delete(task_id)
        self.assertEqual((200, {"task_id": task_id, "deleted": True}), (status, answer))
        self.assertEqual("deny", held.decision)  # released with deny; never allow
        self.assert_gone(task_id, [approval["id"]])
        # The approval route no longer knows it.
        status, answer = self.http("POST", f"/api/approvals/{approval['id']}/respond", {"decision": "decline"})
        self.assertGreaterEqual(status, 400)

    # ---- live or launching -------------------------------------------------------------------------
    def test_delete_refused_while_run_live_or_launching(self):
        task_id = self.live()
        before = deepcopy(self.app.tasks[task_id])
        status, answer = self.delete(task_id)
        self.assertEqual((409, LIVE_BLOCKER), (status, answer["error"]))
        view = self.task_state(task_id)
        self.assertEqual((False, LIVE_BLOCKER), (view["can_delete"], view["deletion_blocker"]))
        self.assertIn(task_id, self.app.runs)
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        self.assertEqual(before["claude"]["pid"], self.app.tasks[task_id]["claude"]["pid"])
        self.stop(task_id)
        # Launching: a follow-up worker has been started and has not reached a run yet.
        view = self.task_state(task_id)
        self.assertTrue(view["can_delete"])
        with self.app.lock:
            self.app.launching_tasks.add(task_id)
        status, answer = self.delete(task_id)
        self.assertEqual((409, BUSY_BLOCKER), (status, answer["error"]))
        view = self.task_state(task_id)
        self.assertEqual((False, BUSY_BLOCKER), (view["can_delete"], view["deletion_blocker"]))
        self.assertIn(task_id, self.app.tasks)
        with self.app.lock:
            self.app.launching_tasks.discard(task_id)
            self.app.message_busy.add(task_id)
        status, answer = self.delete(task_id)
        self.assertEqual((409, BUSY_BLOCKER), (status, answer["error"]))
        with self.app.lock:
            self.app.message_busy.discard(task_id)
        status, answer = self.delete(task_id)
        self.assertEqual((200, {"task_id": task_id, "deleted": True}), (status, answer))

    def test_delete_refused_while_a_followup_is_queued_or_running(self):
        task_id = self.start("success")
        self.wait_finished(task_id)
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE="no_result", FAKE_CLAUDE_IGNORE_SIGINT="1")
        turn = self.app.tasks[task_id]["turn_id"]
        status, answer = self.http("POST", f"/api/tasks/{task_id}/message", {"text": FOLLOWUP, "expected_turn_id": turn})
        self.assertEqual((200, {"status": "sent", "mode": "followup"}), (status, answer))
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "running"))
        status, answer = self.delete(task_id)
        self.assertEqual((409, LIVE_BLOCKER), (status, answer["error"]))
        self.assertIn(task_id, self.app.tasks)
        self.stop(task_id)
        status, _ = self.delete(task_id)
        self.assertEqual(200, status)

    # ---- possibly running old process (carry-list item e) ------------------------------------------
    def flag_possibly_running(self, task_id):
        with self.app.lock:
            task = self.app.tasks[task_id]
            task["claude"].update(pid=4242, pid_started="Thu Oct 29 10:00:00 2026")
            task.update(status="unknown")
            self.app._record_diagnostic(task, "transport", "claude_possibly_running")
            self.app.store.put("task", task)
        self.app.process_probe = lambda pid: "Thu Oct 29 10:00:00 2026"  # the old process still looks alive

    def test_delete_possibly_running_task_drops_hold_only_after_confirmation(self):
        """Pins CURRENT behaviour (carry-list item e): a flagged `claude_possibly_running` task is deletable (status
        unknown), the delete needs the usual confirmation and version, and deleting it drops the project hold even
        though the old process may still run. The old process is never signalled."""
        task_id = self.start("success")
        self.wait_finished(task_id)
        self.flag_possibly_running(task_id)
        message = DETAILS["claude_possibly_running"][0]
        project_id = self.app.tasks[task_id]["project_id"]
        # The flag holds the project: new work and a follow-up are refused.
        with self.app.lock:
            self.assertEqual([self.project_dir.resolve()], [p.resolve() for p in self.app.active_project_roots()])
        request = {"project_id": project_id, "title": "Second", "instruction": INSTRUCTION, "role": "backend_developer"}
        with self.assertRaises(ValueError) as caught:
            self.app.start_task(request)
        self.assertEqual(message, str(caught.exception))
        status, answer = self.http("POST", "/api/tasks", request)  # the route turns a ValueError into one text
        self.assertEqual((400, GENERIC), (status, answer["error"]))
        self.assertTrue(self.task_state(task_id)["can_delete"])
        # Without confirmation, or with a wrong or stale version, nothing is deleted and the hold stays.
        for body, expected in (
                ({"expected_version": self.delete_body(task_id)["expected_version"]}, (400, GENERIC)),
                ({"expected_version": self.delete_body(task_id)["expected_version"], "confirmed": False}, (400, GENERIC)),
                ({"expected_version": "0" * 64, "confirmed": True}, (409, STALE))):
            status, answer = self.delete(task_id, body)
            self.assertEqual(expected, (status, answer["error"]), body)
            self.assertIn(task_id, self.app.tasks)
            with self.app.lock:
                self.assertEqual(1, len(self.app.active_project_roots()))
        # With confirmation the task and its hold go; the old process is not touched.
        kills = []
        with mock.patch("os.kill", side_effect=lambda *a: kills.append(a)), \
                mock.patch("os.killpg", side_effect=lambda *a: kills.append(a)):
            status, answer = self.delete(task_id)
        self.assertEqual((200, {"task_id": task_id, "deleted": True}), (status, answer))
        self.assertEqual([], kills)
        self.assert_gone(task_id)
        with self.app.lock:
            self.assertEqual([], self.app.active_project_roots())
        # Consequence of the pinned behaviour: a new run in the project is now allowed although the probe still
        # reports the old pid alive (the owner confirmed the deletion). Reported as a risk, not changed.
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE="success")
        status, answer = self.http("POST", "/api/tasks", {"project_id": project_id, "title": "Second",
                                                         "instruction": INSTRUCTION, "role": "backend_developer"})
        self.assertEqual(200, status, answer)
        self.wait_finished(answer["id"])

    # ---- cascade and session registration ----------------------------------------------------------
    def test_delete_removes_messages_child_rows_and_session_registration(self):
        task_id = self.start("success")
        self.wait_finished(task_id)
        with self.app.lock:
            task = self.app.tasks[task_id]
            session = task["claude"]["session_id"]
            self.assertIn(session, self.app.owned_threads)  # registered while the run lasted
            self.assertEqual(task_id, self.app.owned_threads[session]["task_id"])
            self.assertTrue(any(m.get("task_id") == task_id for m in self.app.messages))
            child = {"id": "c" * 32, "parent_task_id": task_id, "project_id": task["project_id"],
                     "thread_id": "agent-synthetic-1", "role": None, "status": "completed", "updated_at": "2026-11-04"}
            self.app.observed_tasks[child["id"]] = child
            self.app.store.put("team_activity", child)
            self.app.owned_threads["agent-synthetic-1"] = {"task_id": task_id, "parent": session, "active": False,
                                                           "turns": set()}
            approval = {"id": "b" * 32, "task_id": task_id, "kind": "tool_call", "status": "unavailable",
                        "available_decisions": []}
            self.app.approvals[approval["id"]] = approval
            self.app.store.put("approval", approval)
        self.write_report()
        status, answer = self.attach(self.task_state(task_id))
        self.assertEqual(200, status, answer)
        status, answer = self.delete(task_id)
        self.assertEqual((200, {"task_id": task_id, "deleted": True}), (status, answer))
        self.assert_gone(task_id, [approval["id"]])
        self.assertNotIn(session, self.app.owned_threads)
        self.assertNotIn("agent-synthetic-1", self.app.owned_threads)
        self.assertNotIn(session, json.dumps(self.state()))
        self.assertEqual([], self.app.store.load("approval"))

    def test_deleted_task_session_cannot_be_followed_up(self):
        task_id = self.start("success")
        self.wait_finished(task_id)
        turn = self.app.tasks[task_id]["turn_id"]
        session = self.app.tasks[task_id]["claude"]["session_id"]
        status, _ = self.delete(task_id)
        self.assertEqual(200, status)
        spawned = len(self.created)
        for expected in (turn, "turn-1", "turn-2"):
            status, answer = self.http("POST", f"/api/tasks/{task_id}/message", {"text": FOLLOWUP,
                                                                                 "expected_turn_id": expected})
            self.assertEqual(400, status, answer)
            self.assertNotIn(session, json.dumps(answer))
        self.assertEqual(spawned, len(self.created))  # no process was started
        self.assertEqual([], stray_fakes())
        self.assertEqual({}, {k: v for k, v in self.app.owned_threads.items() if k == session})
        self.assertNotIn(task_id, self.app.launching_tasks)
        # Reading it is a 404 too.
        status, answer = self.http("GET", f"/api/tasks/{task_id}/conversation")
        self.assertEqual((404, "Task was not found"), (status, answer["error"]))
        status, answer = self.delete(task_id, {"expected_version": "0" * 64, "confirmed": True})
        self.assertEqual((404, NOT_FOUND), (status, answer["error"]))

    # ---- confirmation and version ------------------------------------------------------------------
    def test_delete_confirmation_and_expected_version_rules(self):
        task_id = self.start("success")
        self.wait_finished(task_id)
        good = self.delete_body(task_id)["expected_version"]
        bad_shapes = [{}, {"confirmed": True}, {"expected_version": good}, {"expected_version": good, "confirmed": False},
                      {"expected_version": good, "confirmed": "true"}, {"expected_version": good, "confirmed": 1},
                      {"expected_version": good.upper(), "confirmed": True}, {"expected_version": 5, "confirmed": True},
                      {"expected_version": "short", "confirmed": True},
                      {"expected_version": good, "confirmed": True, "extra": 1}]
        for body in bad_shapes:
            status, answer = self.delete(task_id, body)
            self.assertEqual((400, GENERIC), (status, answer["error"]), body)
            with self.assertRaises(ValueError) as caught:  # the method itself names the reason
                self.app.delete_task(task_id, body)
            self.assertEqual(CONFIRM, str(caught.exception), body)
            self.assertIn(task_id, self.app.tasks)
        # a well-formed but stale version
        status, answer = self.delete(task_id, {"expected_version": "f" * 64, "confirmed": True})
        self.assertEqual((409, STALE), (status, answer["error"]))
        # the task changed after the version was taken
        with self.app.lock:
            self.app.tasks[task_id]["updated_at"] = "2099-01-01T00:00:00Z"
        status, answer = self.delete(task_id, {"expected_version": good, "confirmed": True})
        self.assertEqual((409, STALE), (status, answer["error"]))
        self.assertIn(task_id, self.app.tasks)
        self.assertEqual(1, len(self.app.store.load("task")))
        status, answer = self.delete(task_id)
        self.assertEqual((200, {"task_id": task_id, "deleted": True}), (status, answer))


if __name__ == "__main__":
    unittest.main()

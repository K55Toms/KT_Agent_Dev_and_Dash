"""Plan 5 Task 3: Claude subagent lineage is recorded as delegated activity (no subagent text, ever).

Evidence kind: fake-binary evidence plus parsed fixture lines (tests/fixtures/claude/subagent.jsonl is sanitized from a
real CLI capture with synthetic ids). The stream gives an explicit start (system/task_started, task_type local_agent)
and stop (task_updated patch.status or task_notification status); a child with no stop is finished with the parent run.
"""
import json

from dashboard.backends.claude_stream import MAX_AGENTS, StreamState, translate_stream_line
from tests import test_claude_slice2b_baseline as baseline
from tests.test_claude_approvals import DENY, Harness, payload, wait_for

SID = baseline.SESSION


def started(agent_id, agent_type="Explore", task_type="local_agent"):
    return json.dumps({"type": "system", "subtype": "task_started", "task_id": agent_id, "run_id": "run-synth",
                       "subagent_type": agent_type, "task_type": task_type})


def stopped(agent_id, status="completed"):
    return json.dumps({"type": "system", "subtype": "task_updated", "task_id": agent_id, "patch": {"status": status}})


RESULT = json.dumps({"type": "result", "subtype": "success", "is_error": False, "terminal_reason": "completed",
                     "modelUsage": {}})


class SubagentTests(baseline.Slice2bHarness):
    def rows(self, task):
        return [r for r in self.app.observed_tasks.values() if r["parent_task_id"] == task["id"]]

    def live_task(self):
        """A finished fake run made live again, so lines can be fed as if the run were running."""
        task = self.finished_task()
        with self.app.lock:
            real = self.app.tasks[task["id"]]
            real["status"] = "running"
            owned = self.app.owned_threads[SID]
            owned.update(active=True, current_turn=real["turn_id"])
            owned["turns"].add(real["turn_id"])
        return real

    def feed(self, task, *lines):
        state = StreamState(turn_id=task["turn_id"])
        state.session_id = SID
        run = object()
        with self.app.lock:
            self.app.runs[task["id"]] = run
        try:
            for line in lines:
                for event in translate_stream_line(line, state):
                    self.app._claude_event_locked(task["id"], run, event, SID)
        finally:
            with self.app.lock:
                self.app.runs.pop(task["id"], None)

    def test_subagent_lines_make_one_child_row_with_lineage(self):
        task = self.finished_task("subagent")
        [row] = self.rows(task)
        self.assertEqual(("agent-synth-1", SID, "completed"), (row["thread_id"], row["parent_thread_id"], row["status"]))
        self.assertEqual(task["id"], row["parent_task_id"])
        self.assertIsNone(row["role"])
        self.assertEqual(["agent-synth-1"], [a["thread_id"] for a in self.app.delegated_activities()])
        status, view = self.http("GET", f"/api/tasks/{task['id']}/conversation")
        self.assertNotIn("SENSITIVE_SUBAGENT_TEXT_MARKER", json.dumps(view) + json.dumps(self.app.delegated_activities()))

    def test_child_row_ends_with_parent_run(self):
        task = self.live_task()
        self.feed(task, started("agent-a"))
        [row] = self.rows(task)
        self.assertEqual("running", row["status"])
        self.assertEqual(1, len(self.app.active_children(task["id"])))
        self.feed(task, RESULT)  # no stop signal ever came for agent-a
        self.assertEqual("completed", self.rows(task)[0]["status"])
        self.assertEqual([], self.app.active_children(task["id"]))

    def test_malformed_agent_id_makes_no_row(self):
        task = self.live_task()
        state = StreamState(turn_id="t")
        state.session_id = SID
        for bad in ("", "a b", "../x", "x" * 101, 5, None, ["a"], "-lead"):
            self.assertEqual([], translate_stream_line(started(bad), state), repr(bad))
            self.assertEqual([], translate_stream_line(json.dumps(
                {"type": "assistant", "agent_id": bad, "message": {"content": []}}), state))
        self.assertEqual([], translate_stream_line(started("agent-x", task_type="local_bash"), state))
        self.feed(task, started("x" * 101), started("a b"), started("agent-x", task_type="local_bash"))
        self.assertEqual([], self.rows(task))

    def test_subagent_text_never_becomes_a_message(self):
        state = StreamState(turn_id="t")
        state.session_id = SID
        line = json.dumps({"type": "assistant", "agent_id": "agent-a", "parent_tool_use_id": "tu",
                           "message": {"content": [{"type": "text", "text": "SECRET_SUB"}]}})
        events = translate_stream_line(line, state)
        self.assertEqual(["subagent"], [e.kind for e in events])
        self.assertNotIn("SECRET_SUB", repr(events))

    def test_child_rows_are_capped_at_64(self):
        task = self.live_task()
        for index in range(MAX_AGENTS + 6):  # fresh parser states: only the server cap can hold the line
            self.feed(task, started(f"agent-{index}"))
        self.assertEqual(64, len(self.rows(task)))
        state = StreamState(turn_id="t")
        state.session_id = SID
        kinds = [e.kind for i in range(80) for e in translate_stream_line(started(f"b{i}"), state)]
        self.assertEqual(MAX_AGENTS, len(kinds))

    def test_unknown_agent_type_is_unnamed_delegate_of_parent_role(self):
        task = self.live_task()
        self.feed(task, started("agent-u", "totally-unknown-type"))
        [row] = self.rows(task)
        self.assertIsNone(row["role"])
        self.assertEqual(task["id"], row["parent_task_id"])
        self.assertEqual("backend_developer", task["role"])
        self.assertNotIn("totally-unknown-type", json.dumps(row))

    def test_known_agent_type_maps_to_its_team_role(self):
        task = self.live_task()
        self.assertIn("qa_engineer", self.app.roles)
        self.feed(task, started("agent-q", "qa_engineer"), stopped("agent-q", "completed"))
        [row] = self.rows(task)
        self.assertEqual(("qa_engineer", "completed"), (row["role"], row["status"]))
        self.assertIn(row["id"], {a["id"] for a in self.app.delegated_activities()})
        member = next(m for m in self.app.team.snapshot(self.app.team_tasks())["members"] if m["id"] == "qa_engineer")
        self.assertEqual(["delegated"], [a["source"] for a in member["activities"]])

    def test_stop_before_start_or_unknown_makes_nothing(self):
        task = self.live_task()
        self.feed(task, stopped("agent-z"), json.dumps({"type": "system", "subtype": "task_notification",
                                                        "task_id": "agent-z", "status": "completed"}))
        self.assertEqual([], self.rows(task))

    def test_failed_and_killed_stops_map_to_failed_and_interrupted(self):
        task = self.live_task()
        self.feed(task, started("agent-f"), started("agent-k"), stopped("agent-f", "failed"), stopped("agent-k", "killed"))
        self.assertEqual({"agent-f": "failed", "agent-k": "interrupted"},
                         {r["thread_id"]: r["status"] for r in self.rows(task)})


class SubagentHookStillDenied(Harness):
    def test_subagent_tool_call_still_denied_with_claude_hook_subagent_session(self):
        task_id = self.live()
        other = "00000000-0000-4000-8000-0000000007e5"
        out = self.post(payload(session_id=other, agent_id="agent-synthetic-1", agent_type="synthetic-worker"))
        self.assertEqual((200, DENY), self.reply(out))
        self.assertTrue(wait_for(lambda: any(d["code"] == "claude_hook_subagent_session"
                                             for d in self.app.tasks[task_id].get("diagnostics") or [])))
        self.assertEqual([], [a for a in self.app.approvals.values() if a["task_id"] == task_id])
        self.assertEqual([], [r for r in self.app.observed_tasks.values() if r["parent_task_id"] == task_id])
        self.stop_live(task_id)

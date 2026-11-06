"""Plan 5 Task 3: Claude subagent lineage is recorded as delegated activity (no subagent text, ever).

Evidence kind: fake-binary evidence plus parsed fixture lines (tests/fixtures/claude/subagent.jsonl is sanitized from a
real CLI capture with synthetic ids). The stream gives an explicit start (system/task_started, task_type local_agent)
and stop (task_updated patch.status or task_notification status); a child with no stop is finished with the parent run.
"""
from copy import deepcopy
import json

from dashboard.backends.claude_stream import MAX_AGENTS, StreamState, translate_stream_line
from dashboard.server import CHILD_REGISTRATION_LIMIT, MAX_CLAUDE_CHILDREN
from tests import test_claude_slice2b_baseline as baseline
from tests.test_claude_approvals import DENY, Harness, TERMINAL, payload, wait_for

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
        kinds = [e.kind for i in range(80) for e in translate_stream_line(started(f"b{i}"), state)
                 if e.data["phase"] == "started"]
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


    def other_live_task(self, base, index):
        """Another running Claude task with its own session, registered like a real one."""
        sid = f"00000000-0000-4000-8000-0000000a{index:04d}"
        with self.app.lock:
            task = deepcopy(base)
            task.update(id=f"task-extra-{index}", status="running", thread_id=sid)
            task["claude"].update(session_id=sid, delegation_omitted=0)
            self.app.tasks[task["id"]] = task
            self.app._register_thread(sid, task["id"])
            self.app.owned_threads[sid].update(active=True, current_turn=task["turn_id"])
            self.app.owned_threads[sid]["turns"].add(task["turn_id"])
        return task, sid

    def feed_as(self, task, sid, *lines, state=None):
        state = state or StreamState(turn_id=task["turn_id"])
        state.session_id = sid
        run = object()
        with self.app.lock:
            self.app.runs[task["id"]] = run
        try:
            for line in lines:
                for event in translate_stream_line(line, state):
                    self.app._claude_event_locked(task["id"], run, event, sid)
        finally:
            with self.app.lock:
                self.app.runs.pop(task["id"], None)
        return state

    def test_flood_across_tasks_never_sets_tracking_lost_or_blocks_a_parent(self):
        base = self.live_task()
        tasks = [(base, SID)] + [self.other_live_task(base, i) for i in range(1, 5)]
        for task, sid in tasks:
            for index in range(MAX_CLAUDE_CHILDREN + 8):
                self.feed_as(task, sid, started(f"{sid[-4:]}-agent-{index}"))
        self.assertFalse(self.app.runtime_tracking_lost)
        self.assertLessEqual(len(self.app.owned_threads), CHILD_REGISTRATION_LIMIT)
        for task, _ in tasks:
            self.assertLessEqual(len(self.rows(task)), MAX_CLAUDE_CHILDREN)
        total_omitted = sum(t["claude"]["delegation_omitted"] for t, _ in tasks)
        self.assertGreater(total_omitted, 0)
        self.assertEqual(total_omitted, self.app.omitted_count)
        with self.app.lock:  # a new parent session still registers
            self.app.tasks["task-new"] = deepcopy(base) | {"id": "task-new"}
            self.app._register_thread("00000000-0000-4000-8000-00000000ffff", "task-new")
        self.assertFalse(self.app.runtime_tracking_lost)

    def test_parent_session_registers_when_owned_threads_holds_192_entries(self):
        task = self.live_task()
        with self.app.lock:
            for index in range(CHILD_REGISTRATION_LIMIT - len(self.app.owned_threads)):
                self.app.owned_threads[f"filler-{index}"] = {"task_id": task["id"], "parent": SID, "turns": set(),
                                                             "current_turn": None, "active": True}
            self.assertEqual(CHILD_REGISTRATION_LIMIT, len(self.app.owned_threads))
        self.feed(task, started("agent-late"))
        self.assertEqual(0, len([r for r in self.rows(task) if r["thread_id"] == "agent-late"]))
        self.assertEqual(1, task["claude"]["delegation_omitted"])
        self.assertFalse(self.app.runtime_tracking_lost)
        with self.app.lock:
            self.app.tasks["task-new"] = deepcopy(task) | {"id": "task-new"}
            self.app._register_thread("00000000-0000-4000-8000-00000000fffe", "task-new")
        self.assertFalse(self.app.runtime_tracking_lost)

    def test_parser_overflow_is_signalled_once_per_agent_and_counted_on_the_task(self):
        task = self.live_task()
        state = StreamState(turn_id="t")
        state.session_id = SID
        kinds = [e.data["phase"] for i in range(MAX_AGENTS + 3) for e in translate_stream_line(started(f"p{i}"), state)]
        self.assertEqual(["started"] * MAX_AGENTS + ["omitted"] * 3, kinds)
        self.assertEqual([], translate_stream_line(started(f"p{MAX_AGENTS}"), state))  # same id again: not recounted
        self.assertEqual(0, task["claude"].get("delegation_omitted", 0))
        self.feed(task, *[started(f"q{i}") for i in range(MAX_AGENTS + 3)])
        self.assertEqual(3, self.app.tasks[task["id"]]["claude"]["delegation_omitted"])
        self.assertEqual(MAX_AGENTS, len(self.rows(task)))

    def test_new_task_starts_with_delegation_omitted_zero(self):
        self.assertEqual(0, self.app.tasks[self.finished_task()["id"]]["claude"]["delegation_omitted"])

    def test_reused_agent_id_on_followup_turn_revives_the_same_single_row(self):
        task = self.live_task()
        self.feed(task, started("agent-r"), stopped("agent-r"))
        [row] = self.rows(task)
        self.assertEqual("completed", row["status"])
        self.assertNotIn("agent-r", self.app.owned_threads)  # finished children hold no capacity
        self.feed(task, started("agent-r"))  # a new parser state, as on a follow-up process
        [row] = self.rows(task)
        self.assertEqual("running", row["status"])
        self.feed(task, RESULT)
        self.assertEqual(["completed"], [r["status"] for r in self.rows(task)])

    def test_odd_shapes_are_bounded_or_ignored(self):
        task = self.live_task()
        state = StreamState(turn_id="t")
        state.session_id = SID
        [event] = translate_stream_line(started("agent-o", "bad\x00type\n"), state)
        self.assertIsNone(event.data["agent_type"])
        [event] = translate_stream_line(started("agent-o2", "x" * 100), state)
        self.assertIsNone(event.data["agent_type"])
        for status in ("weird", 5, None, ["completed"], {"a": 1}):
            self.assertEqual([], translate_stream_line(stopped("agent-o", status), state), repr(status))
        self.feed(task, started("agent-o", "bad\x00type"))
        self.assertIsNone(self.rows(task)[0]["role"])
        with self.app.lock:  # an unknown phase or a stop with a junk status changes nothing harmful
            self.app._claude_subagent(task, SID, {"agent_id": "agent-o", "phase": "bogus"})
            self.app._claude_subagent(task, SID, {"agent_id": "agent-o", "phase": "stopped", "status": "zzz"})
        self.assertEqual("unknown", self.rows(task)[0]["status"])

    def test_stop_observed_is_recorded_only_for_an_explicit_stop(self):
        task = self.live_task()
        self.feed(task, started("agent-seen"), stopped("agent-seen"), started("agent-unseen"), RESULT)
        rows = {r["thread_id"]: r for r in self.rows(task)}
        self.assertEqual(("completed", True), (rows["agent-seen"]["status"], rows["agent-seen"]["stop_observed"]))
        # Finished with the parent run: status completed (deletion is not blocked), but the stop was not observed.
        self.assertEqual(("completed", False), (rows["agent-unseen"]["status"], rows["agent-unseen"]["stop_observed"]))

    def test_subagent_line_with_parent_tool_use_id_but_no_agent_id_makes_nothing(self):
        task = self.live_task()
        line = json.dumps({"type": "assistant", "parent_tool_use_id": "toolu_parent", "session_id": SID,
                           "message": {"content": [{"type": "text", "text": "SENSITIVE_SUBAGENT_TEXT_MARKER"}]}})
        state = StreamState(turn_id=task["turn_id"])
        state.session_id = SID
        self.assertEqual([], translate_stream_line(line, state))
        self.feed(task, line)
        self.assertEqual([], self.rows(task))

    def test_subagent_of_a_session_the_dashboard_does_not_own_makes_nothing(self):
        task = self.live_task()
        with self.app.lock:
            self.app._claude_subagent(task, "00000000-0000-4000-8000-00000000dead",
                                      {"agent_id": "agent-x", "agent_type": "Explore", "phase": "started"})
        self.assertEqual([], self.rows(task))
        self.assertNotIn("agent-x", self.app.owned_threads)

    def test_agent_id_owned_by_another_task_is_never_reattributed(self):
        task = self.live_task()
        self.feed(task, started("agent-shared"))
        [before] = deepcopy(self.rows(task))
        other, sid = self.other_live_task(task, 1)
        self.feed_as(other, sid, started("agent-shared", "qa_engineer"))
        self.assertEqual([before], self.rows(task))
        self.assertEqual([], self.rows(other))
        self.assertEqual((task["id"], SID), (self.app.owned_threads["agent-shared"]["task_id"],
                                            self.app.owned_threads["agent-shared"]["parent"]))

    def test_omitted_events_stop_after_the_id_bound(self):
        from dashboard.backends.claude_stream import MAX_OMITTED_IDS
        state = StreamState(turn_id="t")
        state.session_id = SID
        for index in range(MAX_AGENTS):
            translate_stream_line(started(f"agent-{index}"), state)
        omitted = sum(len(translate_stream_line(started(f"extra-{index}"), state)) for index in range(MAX_OMITTED_IDS))
        self.assertEqual(MAX_OMITTED_IDS, omitted)
        self.assertEqual([], translate_stream_line(started("extra-0"), state))  # a repeat is never counted again
        self.assertEqual([], translate_stream_line(started("one-more"), state))  # past the bound: silent, counted once
        self.assertEqual([], translate_stream_line(started("one-more"), state))

    def test_unnamed_delegate_shows_in_team_snapshot_under_parent_role(self):
        """Plan 5 Task 4: an unnamed delegate is listed as delegated activity under the PARENT task's role."""
        task = self.live_task()
        self.feed(task, started("agent-n", "mystery"))
        tasks = self.app.team_tasks()
        [row] = self.rows(task)
        self.assertIn(row["id"], tasks)
        self.assertIsNone(tasks[row["id"]]["role"])
        self.assertEqual(task["id"], tasks[row["id"]]["parent_task_id"])
        snapshot = self.app.team.snapshot(tasks)
        listed = [(m["id"], a) for m in snapshot["members"] for a in m["activities"] if a["id"] == row["id"]]
        self.assertEqual(["backend_developer"], [role for role, _ in listed])
        self.assertEqual(("delegated", True), (listed[0][1]["source"], listed[0][1]["unnamed_delegate"]))

    def test_deleting_a_claude_task_removes_its_child_rows_and_owned_entries(self):
        task = self.live_task()
        self.feed(task, started("agent-d1"), started("agent-d2"), stopped("agent-d2"))
        self.feed(task, RESULT)
        with self.app.lock:
            real = self.app.tasks[task["id"]]
            real["status"] = "completed"
            self.app.owned_threads[SID]["active"] = False
            state = self.app.task_deletion_state(real)
        self.assertTrue(state["can_delete"], state.get("deletion_blocker"))
        self.app.delete_task(task["id"], {"expected_version": state["deletion_version"], "confirmed": True})
        self.assertEqual([], [r for r in self.app.observed_tasks.values() if r["parent_task_id"] == task["id"]])
        self.assertEqual([], [r for r in self.app.store.load("team_activity") if r["parent_task_id"] == task["id"]])
        self.assertFalse([t for t, o in self.app.owned_threads.items() if o["task_id"] == task["id"]])


class SubagentRunEnds(Harness):
    def live_sub(self, **extra):
        task = self.start("subagent_live", **extra)
        task_id = task["id"]
        self.assertTrue(wait_for(lambda: any(r["parent_task_id"] == task_id and r["status"] == "running"
                                             for r in self.app.observed_tasks.values())), "no running child")
        return task_id

    def statuses(self, task_id):
        return [r["status"] for r in self.app.observed_tasks.values() if r["parent_task_id"] == task_id]

    def test_stop_leaves_no_child_running(self):
        task_id = self.live_sub(FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.stop_live(task_id)
        self.assertEqual(["interrupted"], self.statuses(task_id))
        self.assertEqual([], self.app.active_children(task_id))

    def test_run_that_ends_without_a_result_leaves_no_child_running(self):
        task_id = self.live_sub()  # the fake exits after the replay with no result line: a crashed run
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL and task_id not in self.app.runs))
        self.assertEqual(["unknown"], self.statuses(task_id))
        self.assertEqual([], self.app.active_children(task_id))

    def test_close_leaves_no_child_running(self):
        task_id = self.live_sub(FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.app.close()
        self.assertEqual(1, len(self.statuses(task_id)))
        self.assertNotIn("running", self.statuses(task_id))
        self.assertEqual([], self.app.active_children(task_id))


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

"""Lifecycle of Claude tool-call approvals: stop, exit, close, restart, expiry, invalid requests (Plan 4, Task 6).

Evidence kind: fake-binary evidence, not a live run. Every run executes tests/fake_claude.py through the real argv
builder, the real ClaudeRun and the real loopback hook receiver (the harness from tests/test_claude_approvals.py);
the run factory refuses any other executable. Nothing here establishes how the real CLI behaves.
"""
import json
import os
from pathlib import Path
import signal
import time
import unittest

from dashboard.approval_review import ReviewError
from dashboard.hook_receiver import HookReceiver, MAX_PENDING_PER_RUN
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard
from tests.test_claude_approvals import (DENY, SESSION, TERMINAL, Harness, payload, stray_fakes, wait_for)

STALE = "run-" + "ab" * 12 + ".json"
STALE_TMP = ".tmp-run-" + "cd" * 12 + ".json"


def codes(task):
    return [d["code"] for d in task.get("diagnostics") or []]


class Lifecycle(Harness):
    def settings_path(self, index=-1):
        return self.settings_seen[index][0]

    def assert_released(self, app, task_id, path):
        """The run's token is unregistered, its settings file gone and nothing of it is pending."""
        self.assertTrue(wait_for(lambda: not path.exists(), 5), "the settings file outlived its run")
        self.assertTrue(wait_for(lambda: not any(e["task_id"] == task_id for e in app.hook_runs.values()), 5))
        with app.lock:
            self.assertEqual([], [r for r in app.pending.values() if r.get("task_id") == task_id])
        for receiver in self.receivers:
            self.assertEqual({}, receiver._pending)

    def test_stop_with_pending_releases_deny_and_marks_unavailable(self):
        task_id = self.live()
        path = self.settings_path()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        held = self.held(approval)
        self.stop_live(task_id)
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("deny", held.decision)
        self.assertEqual(("unavailable", []), (approval["status"], approval["available_decisions"]))
        self.assertEqual("run_ended", approval.get("unavailable_reason"))
        self.assertEqual("interrupted", self.app.tasks[task_id]["status"])
        self.assert_released(self.app, task_id, path)
        stored = {a["id"]: a for a in self.app.store.load("approval")}
        self.assertEqual("unavailable", stored[approval["id"]]["status"])
        # the finished run's token answers nothing any more
        self.assertEqual((200, DENY), self.reply(self.post(payload())))
        self.assertEqual(1, len([a for a in self.app.approvals.values() if a["task_id"] == task_id]))

    def test_run_exit_with_pending_cleans_up(self):
        task_id = self.live()
        path = self.settings_path()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        pid = self.app.tasks[task_id]["claude"]["pid"]
        os.kill(pid, signal.SIGKILL)  # the process ends on its own, not by the dashboard's stop
        self.assertTrue(wait_for(lambda: task_id not in self.app.runs
                                 and self.app.tasks[task_id]["status"] in TERMINAL))
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("unavailable", approval["status"])
        self.assertEqual("unknown", self.app.tasks[task_id]["status"])
        self.assert_released(self.app, task_id, path)
        self.assertEqual((200, DENY), self.reply(self.post(payload())))

    def test_close_with_pending_leaves_no_process_thread_or_settings_file(self):
        task_id = self.live()
        path = self.settings_path()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        receiver = self.receivers[-1]
        self.app.close()
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual([], stray_fakes())
        self.assertFalse(receiver._thread.is_alive())
        self.assertEqual({}, receiver._runs)
        self.assertFalse(path.exists())
        self.assertEqual({}, self.app.hook_runs)
        self.assertEqual("unavailable", approval["status"])
        self.assertEqual("interrupted", self.app.tasks[task_id]["status"])
        names = [t.name for t in __import__("threading").enumerate()]
        self.assertNotIn("hook-receiver", names)

    def test_restart_sweep_removes_stale_settings_files_and_tokens_do_not_survive(self):
        task_id = self.live()
        url = self.url()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        old = self.app
        # A crash: nothing after this point is recorded by the old dashboard.
        old.stop.set()
        self.stop_live_raw(old, task_id)
        self.assertEqual((200, DENY), self.reply(out))
        stored = {a["id"]: a for a in old.store.load("approval")}
        self.assertEqual("pending", stored[approval["id"]]["status"])  # left as a crash would leave it
        runs = old.state_dir / "claude-runs"
        stale, stale_tmp = runs / STALE, runs / STALE_TMP
        stale.write_text('{"hooks":{}}\n')
        stale_tmp.write_text("{}")
        outside = self.root / "outside.json"
        outside.write_text("keep")
        link = runs / ("run-" + "ef" * 12 + ".json")
        link.symlink_to(outside)
        folder = runs / ("run-" + "01" * 12 + ".json")
        folder.mkdir()
        other = runs / "notes.txt"
        other.write_text("keep")
        new = Dashboard(old.state_dir, **self.app_kwargs())
        self.apps.append(new)
        self.assertFalse(stale.exists())
        self.assertFalse(stale_tmp.exists())
        self.assertTrue(link.is_symlink(), "a symlink is never followed or removed by the sweep")
        self.assertEqual("keep", outside.read_text())
        self.assertTrue(folder.is_dir())
        self.assertTrue(other.exists())
        restored = new.approvals[approval["id"]]
        self.assertEqual(("unavailable", []), (restored["status"], restored["available_decisions"]))
        self.assertEqual("dashboard_restarted", restored.get("unavailable_reason"))
        self.assertNotIn("pending", [a["status"] for a in new.store.load("approval")])
        self.assertEqual("unknown", new.tasks[task_id]["status"])
        self.assertEqual(SESSION, new.tasks[task_id]["claude"]["session_id"])
        self.assertEqual({}, new.hook_runs)
        self.assertIsNone(new.hook_receiver)
        self.assertEqual({}, new.pending)
        self.assertNotIn(url.rsplit("/", 1)[1], json.dumps(new.snapshot()))
        link.unlink()
        folder.rmdir()
        other.unlink()

    def stop_live_raw(self, app, task_id):
        with app.lock:
            run = app.runs[task_id]
        run.stop("shutdown")
        self.assertTrue(run.cleanup_complete.wait(10))

    def app_kwargs(self):
        from dashboard.backends.claude import ClaudeBackend
        from tests.test_claude_approvals import FAKE, RaisingPolicy, probe_runner
        return dict(policy_provider=RaisingPolicy(), backend=ClaudeBackend(claude_path=str(FAKE), runner=probe_runner),
                    claude_run_factory=self.factory, hook_receiver_factory=self.receiver_factory)

    def test_expiry_after_approval_wait_denies_and_marks_expired(self):
        def short(*args, **kwargs):
            limit = kwargs["wait_limit"]
            kwargs["wait_limit"] = lambda key: min(limit(key), 0.5)
            receiver = HookReceiver(*args, poll_interval=0.05, **kwargs)
            self.receivers.append(receiver)
            return receiver
        self.app.hook_receiver_factory = short
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        review = self.app.review_approval(approval["id"])
        held = self.held(approval)
        started = time.monotonic()
        self.assertEqual((200, DENY), self.reply(out, 5))
        self.assertLess(time.monotonic() - started, 4)
        self.assertTrue(wait_for(lambda: approval["status"] != "pending", 5))
        self.assertEqual(("unavailable", []), (approval["status"], approval["available_decisions"]))
        self.assertEqual("expired", approval.get("unavailable_reason"))
        self.assertTrue(held.expired)
        self.assertFalse(held.closed)
        with self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_unavailable", caught.exception.code)
        self.assertEqual("deny", held.decision)
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        stored = {a["id"]: a for a in self.app.store.load("approval")}
        self.assertEqual(("unavailable", "expired"), (stored[approval["id"]]["status"],
                                                      stored[approval["id"]]["unavailable_reason"]))
        self.stop_live(task_id)

    def assert_refused_run(self, task_id, code, path, app=None):
        app = app or self.app
        task = app.tasks[task_id]
        self.assertTrue(wait_for(lambda: task_id not in app.runs, 15), "the refused run was not stopped")
        self.assertEqual("failed", task["status"])
        self.assertEqual(1, codes(task).count(code))
        self.assert_released(app, task_id, path)
        self.assertEqual([], self._pending(app, task_id))

    def test_non_default_permission_mode_request_denied_and_run_failed(self):
        # one dashboard per mode: the fake reuses one session id, which a second run of one dashboard refuses
        for mode, app in (("acceptEdits", self.app), (None, self.make_app())):
            with self.subTest(mode=mode):
                task_id = self.live(app)
                path = self.settings_path()
                first = self.post(payload())
                [approval] = self.pending(task_id, app=app)
                held = self.held(approval, app)
                self.assertEqual((200, DENY), self.reply(self.post(payload(permission_mode=mode))))
                self.assertEqual("failed", app.tasks[task_id]["status"])
                # the run's earlier request is released too, and a later one changes nothing
                self.assertEqual((200, DENY), self.reply(first))
                self.assertEqual("deny", held.decision)
                self.assertEqual("unavailable", approval["status"])
                self.assertEqual((200, DENY), self.reply(self.post(payload(permission_mode="plan"))))
                self.assertEqual((200, DENY), self.reply(self.post(payload())))
                self.assert_refused_run(task_id, "claude_permission_mode", path, app)
                self.assertEqual(1, len([a for a in app.approvals.values() if a["task_id"] == task_id]))
                self.assertEqual("failed", app.tasks[task_id]["status"])

    def test_session_id_mismatch_denied_without_approval(self):
        task_id = self.live()
        path = self.settings_path()
        body = payload(session_id="00000000-0000-4000-8000-0000000007e5")
        self.assertEqual((200, DENY), self.reply(self.post(body)))
        self.assertEqual((200, DENY), self.reply(self.post(payload())))
        self.assertEqual([], [a for a in self.app.approvals.values() if a["task_id"] == task_id])
        self.assert_refused_run(task_id, "claude_session_rejected", path)
        self.assertNotIn("claude_permission_mode", codes(self.app.tasks[task_id]))
        self.assertNotIn("0000000007e5", json.dumps(self.app.tasks[task_id]))

    def test_deleting_task_with_pending_approval(self):
        task_id = self.live()
        path = self.settings_path()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        held = self.held(approval)
        with self.app.lock:
            state = self.app.task_deletion_state(self.app.tasks[task_id])
        self.assertFalse(state["can_delete"])
        with self.assertRaises(FileAccessError) as caught:
            self.app.delete_task(task_id, {"expected_version": state["deletion_version"], "confirmed": True})
        self.assertEqual(409, caught.exception.status)
        self.assertIsNone(held.decision)  # a refused delete changes nothing
        self.assertEqual("pending", approval["status"])
        self.stop_live(task_id)
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("unavailable", approval["status"])
        with self.app.lock:
            state = self.app.task_deletion_state(self.app.tasks[task_id])
        self.assertTrue(state["can_delete"], state["deletion_blocker"])
        self.app.delete_task(task_id, {"expected_version": state["deletion_version"], "confirmed": True})
        self.assertNotIn(task_id, self.app.tasks)
        self.assertNotIn(approval["id"], self.app.approvals)
        self.assertEqual([], [a for a in self.app.store.load("approval") if a["task_id"] == task_id])
        self.assert_released(self.app, task_id, path)

    def test_delete_releases_a_left_over_held_request(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        held = self.held(approval)
        with self.app.lock:
            self.app.approvals[approval["id"]]["status"] = "unavailable"  # an entry whose record already ended
            entry = self.app.pending[approval["id"]]
        self.stop_live(task_id)
        with self.app.lock:
            self.app.pending[approval["id"]] = entry  # left behind: deletion must still deny it
        held._decision = None
        held._event.clear()
        with self.app.lock:
            state = self.app.task_deletion_state(self.app.tasks[task_id])
        self.app.delete_task(task_id, {"expected_version": state["deletion_version"], "confirmed": True})
        self.assertEqual("deny", held.decision)
        self.assertEqual({}, self.app.pending)
        self.reply(out)

    def test_cap_16_per_run_then_deny(self):
        task_id = self.live()
        outs = [self.post(payload(tool_input={"command": "echo %d" % i})) for i in range(MAX_PENDING_PER_RUN)]
        self.pending(task_id, MAX_PENDING_PER_RUN)
        started = time.monotonic()
        self.assertEqual((200, DENY), self.reply(self.post(payload()), 5))
        self.assertLess(time.monotonic() - started, 3, "the request over the cap was held")
        self.assertEqual(MAX_PENDING_PER_RUN, len(self._pending(self.app, task_id)))
        self.assertEqual(MAX_PENDING_PER_RUN, len([a for a in self.app.approvals.values() if a["task_id"] == task_id]))
        task = self.app.tasks[task_id]
        self.assertFalse([c for c in codes(task) if c.startswith("claude_hook")], "a receiver-level deny was recorded")
        self.assertEqual("waiting_approval", task["status"])
        self.stop_live(task_id)
        for out in outs:
            self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual([], self._pending(self.app, task_id))

    def test_request_before_session_known_is_recorded_once_per_run_without_request_text(self):
        task = self.start("success", FAKE_CLAUDE_HOOK="ask_two")  # no gate: both requests come before init
        task_id = task["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL and task_id not in self.app.runs))
        self.assertEqual([{"scenario": "ask_two", "calls": 2, "told": ["deny", "deny"]}], self.hook_record())
        record = self.app.tasks[task_id]
        self.assertEqual(1, codes(record).count("claude_hook_session_unknown"))
        self.assertNotIn("claude_permission_mode", codes(record))
        self.assertNotEqual("failed", record["status"])  # the run was not stopped for it
        denials = record["claude"]["hook_denials"]
        self.assertEqual({"claude_hook_session_unknown"}, {d["code"] for d in denials})
        self.assertEqual({"Bash", "Write"}, {d["tool_name"] for d in denials})
        self.assertTrue(all(set(d) == {"code", "tool_name"} for d in denials))
        fixture = Path(__file__).resolve().parent / "fixtures" / "claude" / "permission_request_bash.json"
        command = json.loads(fixture.read_text())["tool_input"]["command"]
        self.assertNotIn(command, json.dumps(record))
        self.assertNotIn(command, json.dumps(self.app.snapshot()))
        self.assertEqual([], [a for a in self.app.approvals.values() if a["task_id"] == task_id])

    def test_request_after_the_turn_ended_is_denied_and_recorded_without_stopping(self):
        task = self.start("success", FAKE_CLAUDE_IGNORE_SIGINT="1")  # result applied, process stays
        task_id = task["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "completed"))
        self.assertIn(task_id, self.app.runs)
        for _ in range(3):
            self.assertEqual((200, DENY), self.reply(self.post(payload())))
        record = self.app.tasks[task_id]
        self.assertEqual(1, codes(record).count("claude_hook_turn_inactive"))
        self.assertEqual("completed", record["status"])
        self.assertIn(task_id, self.app.runs)
        self.assertEqual([{"code": "claude_hook_turn_inactive", "tool_name": "Bash"}], record["claude"]["hook_denials"])
        self.assertEqual([], [a for a in self.app.approvals.values() if a["task_id"] == task_id])


if __name__ == "__main__":
    unittest.main()

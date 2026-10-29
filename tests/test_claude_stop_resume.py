"""Claude stop, shutdown, restart and follow-up (Task 9).

Evidence kind: fake binary only. Every run executes tests/fake_claude.py through the real argv builder and
ClaudeRun; the factory below refuses any other executable, so the real ``claude`` can never run here.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from dashboard.backends.base import NeutralEvent
from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_runner import ClaudeRun, RunExit
from dashboard.backends.claude_stream import NEUTRAL_KEYS, usage_from_model_usage
from dashboard.ponytail_policy import PolicyError
from dashboard.server import Dashboard

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude"
SESSION = "00000000-0000-4000-8000-000000005e55"
OTHER_SESSION = "00000000-0000-4000-8000-0000000007e5"
INSTRUCTION = "Implement the synthetic feature"
FOLLOWUP = "Continue with the synthetic feature"
TERMINAL = {"completed", "failed", "interrupted", "unknown"}
STEER = "Guidance cannot be sent into a running Claude turn; send a follow-up after it finishes."
WAIT = 20.0


def probe_runner(argv, timeout):
    return 0, "2.1.312 (Claude Code)\n"


def synthetic_probe(pid):
    return f"synthetic-start-{pid}"


class RaisingPolicy:
    def load(self):
        raise PolicyError("Approved Ponytail policy configuration is invalid.")


def wait_for(predicate, seconds=WAIT):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def result_line(name):
    return [json.loads(line) for line in (FIXTURES / (name + ".jsonl")).read_text().splitlines()
            if line.strip() and json.loads(line).get("type") == "result"][0]


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stray_fakes():
    """fake_claude processes whose parent is this test process."""
    out = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True,
                         timeout=10).stdout
    found = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] == str(os.getpid()) and "fake_claude.py" in parts[2]:
            found.append(int(parts[0]))
    return found


class ClaudeStopResumeTest(unittest.TestCase):
    sigint_wait = 2.0
    term_wait = 1.0

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.record = self.root / "record.jsonl"
        self.created = []
        self.apps = []
        self.lock_violations = []
        self.gate = None
        self.rewrite_session = None
        self.app = self.make_app()

    def tearDown(self):
        for run in self.created:
            run.close()
        for app in self.apps:
            app.close()
        for run in self.created:
            if run.pid is not None:
                self.assertFalse(alive(run.pid), "a fake_claude process was left running")
        self.assertEqual([], stray_fakes())
        self.assertEqual([], self.lock_violations, "run.stop was called while holding the dashboard lock")
        self.temp.cleanup()

    def factory(self, argv, **kwargs):
        # The only executable a test may start is the fake.
        if argv[0] != str(FAKE):
            raise AssertionError("refusing to start anything but the fake claude")
        if self.gate is not None:
            self.assertTrue(self.gate.wait(WAIT))
        if self.rewrite_session is not None:
            forward, other = kwargs["on_event"], self.rewrite_session
            kwargs["on_event"] = lambda event: forward(NeutralEvent(event.kind, other, event.turn_id, event.data))
        run = ClaudeRun(argv, sigint_wait=self.sigint_wait, term_wait=self.term_wait, **kwargs)
        original, app = run.stop, self.current_app

        def guarded(reason):
            if app.lock._is_owned():
                self.lock_violations.append(reason)
            return original(reason)
        run.stop = guarded
        self.created.append(run)
        return run

    def make_app(self, fixture="success", probe=synthetic_probe, **extra):
        backend = ClaudeBackend(claude_path=str(FAKE), runner=probe_runner)
        app = Dashboard(self.root / "state", policy_provider=RaisingPolicy(), backend=backend,
                        claude_run_factory=self.factory, process_probe=probe,
                        claude_env_extra=dict(FAKE_CLAUDE_FIXTURE=fixture, FAKE_CLAUDE_RECORD=str(self.record),
                                              **extra))
        self.current_app = app
        self.apps.append(app)
        app.start()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "connected", 5))
        return app

    def close_app(self, app):
        app.close()
        self.apps.remove(app)

    def project(self, name="project"):
        path = self.root / name
        path.mkdir(exist_ok=True)
        return self.app.add_project({"name": name, "path": str(path)})

    def use(self, fixture, **extra):
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, FAKE_CLAUDE_RECORD=str(self.record), **extra)

    def start(self, fixture="success", project=None, instruction=INSTRUCTION, **extra):
        self.use(fixture, **extra)
        project = project or self.project()
        return self.app.start_task({"project_id": project["id"], "title": "Synthetic run",
                                    "instruction": instruction, "role": "backend_developer"})

    def followup(self, task_id, fixture, text=FOLLOWUP, **extra):
        self.use(fixture, **extra)
        with self.app.lock:
            turn = self.app.tasks[task_id]["turn_id"]
        return self.app.send_message(task_id, {"text": text, "expected_turn_id": turn})

    def finish(self, task_id):
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL
                                 and task_id not in self.app.runs and task_id not in self.app.launching_tasks))
        with self.app.lock:
            return deepcopy(self.app.tasks[task_id])

    def running(self, task_id):
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "running"
                                 and task_id in self.app.runs))

    def rows(self, app=None):
        return (app or self.app).store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()

    def invocations(self):
        if not self.record.exists():
            return []
        return [json.loads(x) for x in self.record.read_text().splitlines() if x.strip()]

    def codes(self, task):
        return [entry["code"] for entry in task["diagnostics"]]

    def run_of(self, task_id):
        with self.app.lock:
            return self.app.runs.get(task_id)

    # ---- stop ------------------------------------------------------------------------------------
    def test_stop_during_streaming_records_interrupted_whatever_the_exit_code(self):
        task = self.start("success", FAKE_CLAUDE_DELAY_MS="300")
        self.running(task["id"])
        run = self.run_of(task["id"])
        answer = self.app.interrupt(task["id"], {})
        self.assertEqual("interrupt_requested", answer["status"])
        final = self.finish(task["id"])
        self.assertEqual("interrupted", final["status"])
        self.assertEqual(0, run.exit_code)  # the fake prints the aborted result and exits 0
        self.assertTrue(run.stopped_by_us)
        self.assertNotIn("claude_aborted", self.codes(final))
        self.assertFalse(final.get("recovery_hold"))
        stored = {row[1]: json.loads(row[2]) for row in self.rows() if row[0] == "task"}
        self.assertEqual("interrupted", stored[task["id"]]["status"])
        self.assertFalse(self.app.owned_threads[SESSION]["active"])

    def test_stop_before_first_event_never_spawns_or_is_interrupted(self):
        self.gate = threading.Event()
        task = self.start("success")
        self.assertTrue(wait_for(lambda: task["id"] in self.app.launching_tasks))
        self.assertIsNone(self.run_of(task["id"]))
        answer = self.app.interrupt(task["id"], {})
        self.assertEqual("interrupt_requested", answer["status"])
        self.assertIn(task["id"], self.app.stop_requests)
        self.gate.set()
        final = self.finish(task["id"])
        self.assertEqual("interrupted", final["status"])
        self.assertEqual(1, len(self.created))
        self.assertIsNone(self.created[0].pid)
        self.assertEqual([], self.invocations())
        self.assertNotIn(task["id"], self.app.stop_requests)

    def test_stop_escalates_when_the_child_ignores_sigint(self):
        self.sigint_wait, self.term_wait = 1.0, 1.0
        task = self.start("no_result", FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.running(task["id"])
        run = self.run_of(task["id"])
        began = time.monotonic()
        self.app.interrupt(task["id"], {})
        self.assertLess(time.monotonic() - began, 0.9, "interrupt waited for the whole stop ladder")
        final = self.finish(task["id"])
        self.assertEqual("interrupted", final["status"])
        self.assertEqual(-signal.SIGTERM, run.exit_code)
        self.assertTrue(run.cleanup_complete.is_set())
        self.assertFalse(alive(run.pid))

    def test_interrupt_requires_an_active_task_with_a_run(self):
        with self.assertRaises(ValueError):
            self.app.interrupt("f" * 32, {})
        task = self.start("success")
        self.finish(task["id"])
        with self.assertRaisesRegex(ValueError, "no active Claude process"):
            self.app.interrupt(task["id"], {})
        with self.app.lock:  # an active status without a run or a launch worker
            self.app.tasks[task["id"]]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "no active Claude process"):
            self.app.interrupt(task["id"], {})
        self.assertEqual(set(), self.app.stop_requests)
        with self.app.lock:
            self.app.tasks[task["id"]]["status"] = "completed"

    # ---- shutdown --------------------------------------------------------------------------------
    def test_close_with_a_live_run_leaves_no_process_and_does_not_mark_recovery_hold(self):
        self.sigint_wait, self.term_wait = 1.0, 1.0
        task = self.start("no_result", FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.running(task["id"])
        run = self.run_of(task["id"])
        self.close_app(self.app)
        self.assertTrue(run.cleanup_complete.is_set())
        self.assertFalse(alive(run.pid))
        self.assertEqual([], stray_fakes())
        reopened = self.make_app()
        stored = reopened.tasks[task["id"]]
        self.assertEqual("interrupted", stored["status"])
        self.assertFalse(stored.get("recovery_hold"))
        self.assertNotIn("transport_lost", self.codes(stored))
        self.assertEqual(SESSION, stored["claude"]["session_id"])

    def test_close_stops_a_run_whose_launch_is_still_in_progress(self):
        self.gate = threading.Event()
        task = self.start("success")
        self.assertTrue(wait_for(lambda: task["id"] in self.app.launching_tasks))
        threading.Timer(0.3, self.gate.set).start()
        self.close_app(self.app)
        self.assertTrue(all(run.pid is None for run in self.created))
        self.assertEqual([], self.invocations())

    def test_disconnected_does_not_touch_claude_tasks(self):
        done = self.start("success", project=self.project("one"))
        self.finish(done["id"])
        self.rewrite_session = OTHER_SESSION  # every fixture shares one session id
        live = self.start("success", project=self.project("two"), FAKE_CLAUDE_DELAY_MS="300")
        self.running(live["id"])
        codex_id = "c" * 32
        with self.app.lock:
            codex = deepcopy(self.app.tasks[live["id"]])
            codex.update(id=codex_id, provider="codex", thread_id="codex-thread", status="running")
            del codex["claude"]
            self.app.tasks[codex_id] = codex
            self.app.owned_threads["codex-thread"] = {"task_id": codex_id, "parent": None, "turns": set(),
                                                      "current_turn": "turn-1", "active": True}
            before = deepcopy(self.app.tasks[live["id"]])
        self.app.disconnected()
        with self.app.lock:
            after = deepcopy(self.app.tasks[live["id"]])
            self.assertEqual(before["status"], after["status"])
            self.assertFalse(after.get("recovery_hold"))
            self.assertNotIn("transport_lost", self.codes(after))
            self.assertIn(SESSION, self.app.owned_threads)
            self.assertTrue(self.app.owned_threads[OTHER_SESSION]["active"])
            self.assertNotIn("codex-thread", self.app.owned_threads)
            # The Codex record is handled exactly as before.
            self.assertEqual("unknown", self.app.tasks[codex_id]["status"])
            self.assertTrue(self.app.tasks[codex_id]["recovery_hold"])
            self.assertEqual("transport_lost", self.app.tasks[codex_id]["diagnostics"][-1]["code"])
            self.app.tasks[codex_id]["status"] = "failed"
        self.app.interrupt(live["id"], {})
        self.assertEqual("interrupted", self.finish(live["id"])["status"])

    def test_close_never_calls_stop_while_holding_the_lock(self):
        self.sigint_wait, self.term_wait = 1.0, 1.0
        task = self.start("no_result", FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.running(task["id"])
        calls = []
        run = self.run_of(task["id"])
        guarded = run.stop

        def spy(reason):
            calls.append((reason, self.app.lock._is_owned()))
            return guarded(reason)
        run.stop = spy
        self.close_app(self.app)
        self.assertTrue(calls)
        self.assertEqual([], [c for c in calls if c[1]])
        self.assertFalse(alive(run.pid))

    def test_stop_all_runs_is_idempotent_and_never_raises(self):
        task = self.start("success", FAKE_CLAUDE_DELAY_MS="300")
        self.running(task["id"])
        self.app.stop_all_runs(timeout=10)
        self.app.stop_all_runs(timeout=10)
        self.assertEqual("interrupted", self.finish(task["id"])["status"])
        self.app.stop_all_runs(timeout=0)

    def test_late_callbacks_after_close_are_ignored(self):
        task = self.start("success")
        self.finish(task["id"])
        run = self.created[-1]
        app = self.app
        self.close_app(app)
        app.runs[task["id"]] = run  # a run that outlived the shutdown deadline
        event = NeutralEvent("turn_completed", SESSION, "turn-1", {"status": "failed", "error": None})
        app._claude_event(task["id"], run, event)
        app._claude_exit(task["id"], run, RunExit(0, False, None, True, False))
        self.assertEqual("completed", app.tasks[task["id"]]["status"])

    # ---- restart ---------------------------------------------------------------------------------
    def stored_active_task(self, pid=4242, marker="synthetic-start-4242", name="project"):
        task = self.start("success", project=self.project(name))
        self.finish(task["id"])
        with self.app.lock:
            record = self.app.tasks[task["id"]]
            record["status"] = "running"
            record["claude"].update(pid=pid, pid_started=marker)
            self.app.store.put("task", record)
        self.close_app(self.app)
        return task["id"]

    def test_restart_marks_unknown_keeps_session_without_recovery_hold(self):
        task_id = self.stored_active_task()
        self.app = self.make_app(probe=lambda pid: None)
        task = self.app.tasks[task_id]
        self.assertEqual("unknown", task["status"])
        self.assertEqual(SESSION, task["claude"]["session_id"])
        self.assertEqual(SESSION, task["thread_id"])
        self.assertFalse(task.get("recovery_hold"))
        self.assertEqual("claude_no_result", task["diagnostics"][-1]["code"])
        self.assertNotIn("transport_lost", self.codes(task))
        stored = {row[1]: json.loads(row[2]) for row in self.rows() if row[0] == "task"}
        self.assertEqual("unknown", stored[task_id]["status"])
        self.assertTrue(self.app.conversation(task_id)["can_send"])

    def test_restart_warns_about_a_live_pid_with_same_start_time(self):
        task_id = self.stored_active_task(pid=4242, marker="Thu Oct 29 10:00:00 2026")
        seen = []

        def probe(pid):
            seen.append(pid)
            return "Thu Oct 29 10:00:00 2026" if pid == 4242 else None
        with mock.patch("os.kill") as kill, mock.patch("os.killpg") as killpg:
            self.app = self.make_app(probe=probe)
        kill.assert_not_called()
        killpg.assert_not_called()
        self.assertIn(4242, seen)
        task = self.app.tasks[task_id]
        self.assertEqual("unknown", task["status"])
        self.assertEqual("claude_possibly_running", task["diagnostics"][-1]["code"])
        self.assertFalse(task.get("recovery_hold"))
        self.assertEqual(4242, task["claude"]["pid"])
        # While that process may still be running, no follow-up resumes the same session.
        with self.assertRaisesRegex(ValueError, "may still be running"):
            self.followup(task_id, "resumed")
        self.assertEqual([], [x for x in self.invocations() if "--resume" in x["argv"]])

    def test_restart_no_warning_when_pid_gone_or_start_differs(self):
        for index, answer in enumerate((None, "Fri Oct 30 11:00:00 2026")):
            with self.subTest(answer=answer):
                task_id = self.stored_active_task(pid=4242, marker="Thu Oct 29 10:00:00 2026",
                                                  name=f"p{index}")
                self.app = self.make_app(probe=lambda pid, value=answer: value)
                task = self.app.tasks[task_id]
                self.assertEqual("unknown", task["status"])
                self.assertEqual("claude_no_result", task["diagnostics"][-1]["code"])
                self.assertNotIn("claude_possibly_running", self.codes(task))

    def test_spawn_records_the_process_start_marker(self):
        task = self.start("success")
        final = self.finish(task["id"])
        run = self.created[-1]
        self.assertEqual(f"synthetic-start-{run.pid}", final["claude"]["pid_started"])

    # ---- follow-up -------------------------------------------------------------------------------
    def test_followup_resumes_the_same_session_and_adds_usage_and_cost(self):
        task = self.start("success")
        first = self.finish(task["id"])
        self.assertEqual("completed", first["status"])
        answer = self.followup(task["id"], "resumed")
        self.assertEqual({"status": "sent", "mode": "followup"}, answer)
        final = self.finish(task["id"])
        self.assertEqual("completed", final["status"])
        self.assertEqual(2, final["claude"]["invocations"])
        self.assertEqual("turn-2", final["turn_id"])
        self.assertEqual(SESSION, final["claude"]["session_id"])
        added = usage_from_model_usage(result_line("resumed")["modelUsage"])
        self.assertEqual({k: first["usage"][k] + added[k] for k in NEUTRAL_KEYS}, final["usage"])
        self.assertAlmostEqual(first["cost"]["usd"] + result_line("resumed")["total_cost_usd"], final["cost"]["usd"])
        self.assertEqual({k: first["usage"][k] for k in NEUTRAL_KEYS}, final["claude"]["usage_baseline"])
        self.assertAlmostEqual(first["cost"]["usd"], final["claude"]["cost_baseline"])
        argv = self.invocations()[-1]["argv"]
        at = argv.index("--resume")
        self.assertEqual(SESSION, argv[at + 1])
        self.assertEqual(["-p", FOLLOWUP], argv[0:2])
        for flag, value in (("--output-format", "stream-json"), ("--setting-sources", "user"), ("--model", "opus"),
                            ("--agent", "backend_developer"), ("--effort", "high")):
            self.assertEqual(value, argv[argv.index(flag) + 1], flag)
        for flag in ("--verbose", "--agents", "--append-system-prompt"):
            self.assertIn(flag, argv)
        self.assertEqual(self.invocations()[0]["argv"][2:], [x for x in argv[2:] if x not in ("--resume", SESSION)])
        self.assertEqual({"turn-1", "turn-2"}, self.app.owned_threads[SESSION]["turns"])
        sent = [(m["text"], m["turn_id"]) for m in self.app.conversation(task["id"])["messages"] if m["kind"] == "user"]
        self.assertEqual([(INSTRUCTION, "turn-1"), (FOLLOWUP, "turn-2")], sent)

    def test_followup_does_not_lower_totals_when_model_usage_is_empty(self):
        task = self.start("success")
        first = self.finish(task["id"])
        self.followup(task["id"], "bad_model")
        final = self.finish(task["id"])
        self.assertEqual("failed", final["status"])
        self.assertEqual(first["usage"], final["usage"])
        self.assertAlmostEqual(first["cost"]["usd"], final["cost"]["usd"])

    def test_followup_refused_while_running_for_steer_and_for_permission_mode_refused_tasks(self):
        live = self.start("success", project=self.project("one"), FAKE_CLAUDE_DELAY_MS="300")
        self.running(live["id"])
        before = len(self.invocations())
        with self.assertRaises(ValueError) as caught:
            self.followup(live["id"], "resumed")
        self.assertEqual(STEER, str(caught.exception))
        view = self.app.conversation(live["id"])
        self.assertFalse(view["can_send"])
        self.assertEqual(STEER, view["blocked_reason"])
        self.app.interrupt(live["id"], {})
        self.finish(live["id"])
        self.rewrite_session = OTHER_SESSION  # every fixture shares one session id
        refused = self.start("permission_mode_auto", project=self.project("two"))
        final = self.finish(refused["id"])
        self.assertIn("claude_permission_mode", self.codes(final))
        with self.assertRaisesRegex(ValueError, "permission mode"):
            self.followup(refused["id"], "resumed")
        with self.app.lock:
            self.assertEqual(final, self.app.tasks[refused["id"]])
        self.assertEqual(before + 1, len(self.invocations()))

    def test_unknown_run_without_session_id_cannot_resume(self):
        task = self.start("success")
        self.finish(task["id"])
        with self.app.lock:
            record = self.app.tasks[task["id"]]
            record.update(status="unknown", thread_id=None)
            record["claude"]["session_id"] = None
            before = deepcopy(record)
        with self.assertRaisesRegex(ValueError, "no Claude session"):
            self.followup(task["id"], "resumed")
        with self.app.lock:
            self.assertEqual(before, self.app.tasks[task["id"]])
        self.assertEqual(1, len(self.invocations()))

    def test_followup_after_unknown_with_session_id_works(self):
        task = self.start("no_result")
        first = self.finish(task["id"])
        self.assertEqual("unknown", first["status"])
        self.assertFalse(first.get("recovery_hold"))
        self.followup(task["id"], "resumed")
        final = self.finish(task["id"])
        self.assertEqual("completed", final["status"])
        self.assertEqual(2, final["claude"]["invocations"])
        self.assertIn("--resume", self.invocations()[-1]["argv"])

    def test_followup_session_mismatch_fails(self):
        task = self.start("success")
        first = self.finish(task["id"])
        self.rewrite_session = OTHER_SESSION
        self.followup(task["id"], "resumed")
        final = self.finish(task["id"])
        self.assertEqual("failed", final["status"])
        self.assertEqual("claude_session_rejected", final["diagnostics"][-1]["code"])
        self.assertEqual(SESSION, final["claude"]["session_id"])
        self.assertEqual(SESSION, final["thread_id"])
        self.assertEqual(first["usage"], final["usage"])
        self.assertNotIn(OTHER_SESSION, self.app.owned_threads)
        self.assertTrue(self.created[-1].stopped_by_us)

    def test_followup_invocation_and_turn_caps(self):
        task = self.start("success")
        self.finish(task["id"])
        with self.app.lock:
            self.app.tasks[task["id"]]["claude"]["invocations"] = 50
        with self.assertRaisesRegex(ValueError, "follow-up limit"):
            self.followup(task["id"], "resumed")
        with self.app.lock:
            self.app.tasks[task["id"]]["claude"]["invocations"] = 1
            self.app.owned_threads[SESSION]["turns"] = {f"turn-x{n}" for n in range(200)}
        with self.assertRaisesRegex(ValueError, "follow-up limit"):
            self.followup(task["id"], "resumed")
        self.assertEqual(1, len(self.invocations()))
        with self.app.lock:
            self.app.owned_threads[SESSION]["turns"] = {"turn-1"}
            self.app.tasks[task["id"]]["claude"]["invocations"] = 49
        self.followup(task["id"], "resumed")
        final = self.finish(task["id"])
        self.assertEqual("turn-50", final["turn_id"])
        self.assertEqual(50, final["claude"]["invocations"])

    def test_instruction_edge_cases_are_refused_before_state_change(self):
        project = self.project("edge")
        done = self.start("success", project=self.project("done"))
        self.finish(done["id"])
        cases = ("-rf /", "  --help", "--resume x", "", "   \n ", "x" * 16001, "a\0b")
        rows = self.rows()
        with self.app.lock:
            tasks = deepcopy(self.app.tasks)
        for text in cases:
            with self.subTest(text=text[:12]):
                with self.assertRaises(ValueError):
                    self.app.start_task({"project_id": project["id"], "title": "Edge", "instruction": text,
                                         "role": "backend_developer"})
                with self.assertRaises(ValueError):
                    self.app.send_message(done["id"], {"text": text, "expected_turn_id": "turn-1"})
                with self.app.lock:
                    self.assertEqual(tasks, self.app.tasks)
                    self.assertEqual(set(), self.app.launching_tasks)
                    self.assertEqual({}, self.app.runs)
                self.assertEqual(rows, self.rows())
        self.assertEqual(1, len(self.invocations()))


if __name__ == "__main__":
    unittest.main()

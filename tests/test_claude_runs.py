"""Claude managed run lifecycle: start path, stream events and exit handling (Task 8).

Evidence kind: fake binary only. Every run executes tests/fake_claude.py through the real argv builder and
ClaudeRun; the factory below refuses any other executable, so the real ``claude`` can never run here.
"""
from copy import deepcopy
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from dashboard.backends.base import NeutralEvent, ProviderUnavailable
from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_runner import ClaudeRun, RunExit
from dashboard.backends.claude_stream import NEUTRAL_KEYS, usage_from_model_usage
from dashboard.ponytail_policy import PolicyError
from dashboard.server import Dashboard

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude"
SESSION = "00000000-0000-4000-8000-000000005e55"
MARKERS = ("SENSITIVE_TOOL_INPUT_MARKER", "SENSITIVE_HOOK_OUTPUT_MARKER", "SENSITIVE_ASSISTANT_TEXT_MARKER",
           "SENSITIVE_SUBAGENT_TEXT_MARKER", "SENSITIVE")
INSTRUCTION = "Implement the synthetic feature"
TERMINAL = {"completed", "failed", "interrupted", "unknown"}


def probe_runner(argv, timeout):
    return 0, "2.1.312 (Claude Code)\n"


class RaisingPolicy:
    def load(self):
        raise PolicyError("Approved Ponytail policy configuration is invalid.")


def wait_for(predicate, seconds=20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def results(name):
    return [json.loads(line) for line in (FIXTURES / (name + ".jsonl")).read_text().splitlines()
            if line.strip() and json.loads(line).get("type") == "result"]


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def refuse_spawn(*_args, **_kwargs):
    raise OSError("synthetic spawn failure")


class ClaudeRunsTest(unittest.TestCase):
    max_line = 16 * 1024 * 1024
    spawn_fails = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.created = []
        self.envs = []
        self.apps = []
        self.app = self.make_app()

    def tearDown(self):
        for run in self.created:
            run.close()
        for app in self.apps:
            app.close()
        for run in self.created:
            if run.pid is not None:
                self.assertFalse(alive(run.pid), "a fake_claude process was left running")
        self.temp.cleanup()

    def factory(self, argv, **kwargs):
        # The only executable a test may start is the fake.
        if argv[0] != str(FAKE):
            raise AssertionError("refusing to start anything but the fake claude")
        if self.spawn_fails:
            kwargs["process_factory"] = refuse_spawn
        self.envs.append(dict(kwargs.get("env") or {}))
        run = ClaudeRun(argv, sigint_wait=2.0, term_wait=1.0, max_line_bytes=self.max_line, **kwargs)
        self.created.append(run)
        return run

    def make_app(self, fixture="success", **extra):
        backend = ClaudeBackend(claude_path=str(FAKE), runner=probe_runner)
        app = Dashboard(self.root / "state", policy_provider=RaisingPolicy(), backend=backend,
                        claude_run_factory=self.factory,
                        claude_env_extra=dict(FAKE_CLAUDE_FIXTURE=fixture, **extra))
        self.apps.append(app)
        app.start()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "connected", 5))
        return app

    def project(self, name="project"):
        path = self.root / name
        path.mkdir(exist_ok=True)
        return self.app.add_project({"name": name, "path": str(path)})

    def start(self, fixture="success", project=None, **extra):
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, **extra)
        project = project or self.project()
        return self.app.start_task({"project_id": project["id"], "title": "Synthetic run",
                                    "instruction": INSTRUCTION, "role": "backend_developer"})

    def finish(self, task_id):
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL and task_id not in self.app.runs))
        with self.app.lock:
            return deepcopy(self.app.tasks[task_id])

    def rows(self):
        return self.app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()

    def codes(self, task):
        return [entry["code"] for entry in task["diagnostics"]]

    # ---- lifecycle -------------------------------------------------------------------------------
    def test_run_goes_queued_running_completed_with_usage_and_cost(self):
        created = self.start("success", FAKE_CLAUDE_DELAY_MS="150")
        self.assertEqual("queued", created["status"])
        self.assertEqual("claude", created["provider"])
        self.assertEqual(("opus", "high"), (created["model"], created["reasoning"]))
        self.assertIsNone(created["compliance_policy"])
        self.assertEqual({"invocations": 1, "session_id": None, "version": None, "model_id": None, "pid": None,
                          "started_at": None, "denied_count": 0, "denied_tools": [],
                          "usage_baseline": dict.fromkeys(NEUTRAL_KEYS, 0), "cost_baseline": 0.0,
                          "permission_mode": None}, created["claude"])
        task_id = created["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "running"))
        task = self.finish(task_id)
        self.assertEqual("completed", task["status"])
        self.assertEqual(SESSION, task["thread_id"])
        self.assertEqual("turn-1", task["turn_id"])
        self.assertEqual(SESSION, task["claude"]["session_id"])
        self.assertEqual("default", task["claude"]["permission_mode"])
        self.assertIsInstance(task["claude"]["pid"], int)
        self.assertIsInstance(task["claude"]["started_at"], str)
        self.assertEqual(set(NEUTRAL_KEYS), set(task["usage"]))
        self.assertEqual(usage_from_model_usage(results("success")[0]["modelUsage"]), task["usage"])
        self.assertEqual({"basis": "estimated", "unit": "usd-estimate", "usd": 0.0047, "credits": None,
                          "source": "Claude Code result.total_cost_usd (list price)", "pricing_date": None}, task["cost"])
        self.assertEqual([], task["diagnostics"])
        owned = self.app.owned_threads[SESSION]
        self.assertEqual((task_id, None, {"turn-1"}, "turn-1", False, "completed"),
                         (owned["task_id"], owned["parent"], owned["turns"], owned["current_turn"],
                          owned["active"], owned["last_status"]))
        self.assertNotIn(task_id, self.app.launching_tasks)
        sent = [m for m in self.app.messages if m["task_id"] == task_id]
        # Plan 5 Task 2: the user's instruction, then the assistant reply (sender is the session id).
        self.assertEqual([("user", INSTRUCTION, "turn-1", "You", "sent"),
                          ("agent", "SENSITIVE_ASSISTANT_TEXT_MARKER", "turn-1", SESSION, "complete")],
                         [(m["kind"], m["text"], m["turn_id"], m["sender"], m["status"]) for m in sent])
        shown = next(t for t in self.app.snapshot()["tasks"] if t["id"] == task_id)
        self.assertEqual("completed", shown["status"])
        self.assertEqual("claude", shown["provider"])
        self.assertTrue(shown["can_delete"])

    def test_failed_result_is_failed_with_claude_diagnostic(self):
        task = self.finish(self.start("bad_model")["id"])
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_model_unavailable"], self.codes(task))
        self.assertIn("Claude", task["error"])
        self.assertFalse(self.app.owned_threads[SESSION]["active"])

    def test_exit_without_result_is_unknown_not_recovery_hold(self):
        task = self.finish(self.start("no_result")["id"])
        self.assertEqual("unknown", task["status"])
        self.assertEqual(["claude_no_result"], self.codes(task))
        self.assertNotIn("recovery_hold", task)
        self.assertEqual(SESSION, task["thread_id"])  # resumable later: the session id is kept
        self.assertFalse(self.app.owned_threads[SESSION]["active"])

    def test_late_second_result_changes_nothing(self):
        task = self.finish(self.start("multi_result")["id"])
        first = results("multi_result")[0]
        self.assertEqual("completed", task["status"])
        self.assertEqual(usage_from_model_usage(first["modelUsage"]), task["usage"])
        self.assertEqual(first["total_cost_usd"], task["cost"]["usd"])
        self.assertEqual([], task["diagnostics"])

    def test_interrupted_fixture_without_our_signal_is_unknown(self):
        task = self.finish(self.start("interrupted")["id"])
        self.assertEqual("unknown", task["status"])
        self.assertEqual(["claude_aborted"], self.codes(task))
        self.assertNotIn("recovery_hold", task)

    def test_permission_mode_not_default_stops_and_fails(self):
        """Review Focus 3: the run is stopped at init and nothing it sends later changes the task."""
        created = self.start("permission_mode_auto", FAKE_CLAUDE_DELAY_MS="400")
        task = self.finish(created["id"])
        run = self.created[-1]
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_permission_mode"], self.codes(task))
        self.assertEqual("auto", task["claude"]["permission_mode"])
        self.assertTrue(run.stopped_by_us)
        self.assertEqual("permission_mode", run.stop_reason)
        self.assertFalse(alive(run.pid))
        # The fixture's later result (and the interrupt tail) were never applied.
        self.assertIsNone(task["usage"])
        self.assertIsNone(task["cost"])
        self.assertFalse(self.app.owned_threads[SESSION]["active"])
        before = deepcopy(self.app.tasks[created["id"]])
        self.app._claude_event(created["id"], run, NeutralEvent("turn_completed", SESSION, "turn-1",
                                                                {"status": "completed", "error": None}))
        self.assertEqual(before, self.app.tasks[created["id"]])
        self.assertEqual(set(), self.app.refused_runs)  # refused runs are dropped at exit, never leaked

    def test_permission_mode_refusal_applies_even_when_the_run_already_ended(self):
        task = self.finish(self.start("permission_mode_auto")["id"])
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_permission_mode"], self.codes(task))
        self.assertIsNone(task["usage"])

    def test_denied_calls_are_counted_by_name_only_and_noticed(self):
        task = self.finish(self.start("denied")["id"])
        self.assertEqual("completed", task["status"])
        self.assertEqual((1, ["Bash"]), (task["claude"]["denied_count"], task["claude"]["denied_tools"]))
        self.assertEqual(["claude_calls_denied"], self.codes(task))
        self.assertEqual("Some tool calls were denied because they were not approved: by you, by the approval wait running out, or because the run was stopped.",
                         task["diagnostics"][0]["message"])
        self.assertEqual({"at", "stage", "code", "message", "action"}, set(task["diagnostics"][0]))
        self.assertIsNone(task["error"])
        blob = json.dumps([task, self.rows(), self.app.snapshot()], default=str)
        self.assertNotIn("SENSITIVE_TOOL_INPUT_MARKER", blob)

    def test_child_environment_is_the_allow_list_at_the_dashboard_launch(self):
        """Review Focus 2 at the launch line: the parent's provider switches and credentials never reach the child."""
        from dashboard.backends.claude_launch import ENV_NAMES
        parent = {"ANTHROPIC_API_KEY": "k", "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "p",
                  "GOOGLE_CLOUD_PROJECT": "p", "VERTEX_REGION": "p", "HARMLESS_VAR": "x",
                  "LC_ALL": "C", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        record = self.root / "env-record.jsonl"
        with mock.patch.dict(os.environ, parent):
            task = self.start("success", FAKE_CLAUDE_RECORD=str(record))
            self.finish(task["id"])
        extra = {"FAKE_CLAUDE_FIXTURE", "FAKE_CLAUDE_RECORD"}
        launched = set(self.envs[0]) - extra
        self.assertTrue(all(name in ENV_NAMES or name.startswith("LC_") for name in launched), sorted(launched))
        for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "AWS_PROFILE", "GOOGLE_CLOUD_PROJECT",
                     "VERTEX_REGION", "HARMLESS_VAR"):
            self.assertNotIn(name, self.envs[0])
        self.assertIn("PATH", launched)
        # What the fake process really received (names only; the interpreter may add a few of its own).
        names = set(json.loads(record.read_text().splitlines()[-1])["env_names"])
        for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "AWS_PROFILE", "GOOGLE_CLOUD_PROJECT",
                     "VERTEX_REGION", "HARMLESS_VAR"):
            self.assertNotIn(name, names)

    def test_no_sensitive_text_reaches_task_store_or_snapshot(self):
        """Review Focus 7."""
        for index, fixture in enumerate(("success", "denied", "subagent")):
            with self.subTest(fixture=fixture):
                task = self.finish(self.start(fixture, project=self.project(f"p{index}"))["id"])
                self.assertEqual("completed", task["status"])
                # The main agent's reply is the one text that reaches the conversation log (Plan 5 Task 2); it must
                # not reach the task, the snapshot or any other row.
                rows = [row for row in self.rows() if row[0] != "conversation"]
                blob = json.dumps([task, rows, self.app.snapshot()], default=str)
                for marker in MARKERS:
                    self.assertNotIn(marker, blob)
                chat = json.dumps([row for row in self.rows() if row[0] == "conversation"], default=str)
                for marker in MARKERS[:2] + ("SENSITIVE_SUBAGENT_TEXT_MARKER",):
                    self.assertNotIn(marker, chat)
                # The instruction lives only in the conversation log, never in the task or other rows.
                self.assertNotIn(INSTRUCTION, json.dumps(task))
                self.assertTrue(any(INSTRUCTION in body for kind, _, body in self.rows() if kind == "conversation"))
                for kind, _, body in self.rows():
                    if kind != "conversation":
                        self.assertNotIn(INSTRUCTION, body, kind)
                self.assertNotIn(str(FAKE), blob)
                self.assertNotIn("/Users/", blob.replace(str(self.root), ""))
                # Each fixture shares one session id: delete the run so the next can register it.
                with self.app.lock:
                    version = self.app.task_deletion_state(self.app.tasks[task["id"]])["deletion_version"]
                self.app.delete_task(task["id"], {"expected_version": version, "confirmed": True})

    # ---- caps and registration -------------------------------------------------------------------
    def test_three_run_cap_applies_to_claude_runs(self):
        for index in range(3):
            self.start("success", project=self.project(f"p{index}"), FAKE_CLAUDE_DELAY_MS="60000")
        fourth = self.project("p3")
        ids = set(self.app.tasks)
        def states():
            with self.app.lock:
                return [(t["status"], self.codes(t)) for t in self.app.tasks.values()]
        # start() replaces the shared fake environment, and a run reads it when it spawns: let all three spawn first
        self.assertTrue(wait_for(lambda: len(self.created) == 3, seconds=60.0), states())
        before = states()
        try:
            self.start("success", project=fourth)
        except ValueError as error:
            caught = error
        else:
            self.fail(f"the fourth run was accepted; states before: {before}, after: {states()}")
        self.assertEqual("The dashboard supports at most three active runs", str(caught))
        self.assertEqual(ids, set(self.app.tasks))
        self.assertEqual(3, len(self.created))
        self.assertEqual(ids, {row[1] for row in self.rows() if row[0] == "task"})

    def test_session_registration_uses_owned_threads_and_deletion_releases_it(self):
        """Review Focus 9."""
        task = self.finish(self.start("success")["id"])
        self.assertEqual(task["id"], self.app.owned_threads[SESSION]["task_id"])
        with self.app.lock:
            version = self.app.task_deletion_state(self.app.tasks[task["id"]])["deletion_version"]
        self.app.delete_task(task["id"], {"expected_version": version, "confirmed": True})
        self.assertNotIn(SESSION, self.app.owned_threads)
        self.assertEqual({}, self.app.tasks)

    def test_session_cap_marks_tracking_lost_and_stops_the_run(self):
        """Review Focus 9: the 256-session cap applies to Claude sessions."""
        with self.app.lock:
            for index in range(256):
                self.app.owned_threads[f"synthetic-{index}"] = {"task_id": "x", "parent": None, "turns": set(),
                                                               "current_turn": None, "active": False}
        task = self.finish(self.start("success", FAKE_CLAUDE_DELAY_MS="300")["id"])
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_session_rejected"], self.codes(task))
        self.assertEqual("The Claude session could not be registered, so the run was stopped.", task["error"])
        self.assertTrue(self.app.runtime_tracking_lost)
        self.assertNotIn(SESSION, self.app.owned_threads)
        self.assertIsNone(task["usage"])
        self.assertTrue(self.created[-1].stopped_by_us)

    def test_provider_unavailable_before_state_change_does_not_record_unknown(self):
        project = self.project()
        before = (self.rows(), deepcopy(self.app.tasks))
        with self.assertRaises(ProviderUnavailable):
            self.app._start_task({"project_id": project["id"], "title": "T", "instruction": INSTRUCTION,
                                  "role": "backend_developer"}, delivery_operation={"id": "x"})
        with self.app.lock:
            self.app.connection["status"] = "disabled"
        with self.assertRaises(ValueError) as caught:
            self.start("success", project=project)
        self.assertNotIsInstance(caught.exception, ProviderUnavailable)
        self.assertEqual("Claude Code is not ready.", str(caught.exception))
        self.assertEqual(before, (self.rows(), self.app.tasks))
        self.assertEqual([], self.created)

    def test_stale_run_events_are_ignored(self):
        created = self.start("success", FAKE_CLAUDE_DELAY_MS="300")
        task_id = created["id"]
        self.assertTrue(wait_for(lambda: task_id in self.app.runs))
        stale = object()
        before = deepcopy(self.app.tasks[task_id])
        self.app._claude_event(task_id, stale, NeutralEvent("turn_completed", SESSION, "turn-1",
                                                            {"status": "failed", "error": None}))
        self.app._claude_exit(task_id, stale, RunExit(1, False, None, False, True))
        self.assertEqual(before["status"], self.app.tasks[task_id]["status"])
        self.assertEqual([], self.app.tasks[task_id]["diagnostics"])
        self.assertIn(task_id, self.app.runs)
        task = self.finish(task_id)
        self.assertEqual("completed", task["status"])

    def test_launch_validation_error_marks_failed_without_a_process(self):
        role = dict(self.app.roles["backend_developer"], model="not-a-claude-alias")
        self.app.roles["backend_developer"] = role
        task = self.finish(self.start("success")["id"])
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_launch_invalid"], self.codes(task))
        self.assertEqual([], self.created)
        self.assertEqual({}, self.app.runs)

    def test_missing_binary_path_never_looks_up_claude(self):
        self.app.backend.claude_path = None
        task = self.finish(self.start("success")["id"])
        self.assertEqual(["claude_launch_invalid"], self.codes(task))
        self.assertEqual([], self.created)

    def test_spawn_failure_is_failed_launch_invalid(self):
        self.spawn_fails = True
        task = self.finish(self.start("success")["id"])
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_launch_invalid"], self.codes(task))
        self.assertIsNone(self.created[-1].pid)
        self.assertEqual({}, self.app.runs)

    def test_storage_error_after_registration_fails_the_task_and_frees_the_slot(self):
        with mock.patch.object(self.app, "_append_message", side_effect=sqlite3.OperationalError("synthetic")):
            failed = self.finish(self.start("success")["id"])
        self.assertEqual("failed", failed["status"])
        self.assertEqual(["claude_launch_invalid"], self.codes(failed))
        self.assertEqual({}, self.app.runs)
        self.assertNotIn(failed["id"], self.app.launching_tasks)
        self.assertIsNone(self.created[-1].pid)  # the run was never started
        stored = json.loads(next(body for kind, ident, body in self.rows() if ident == failed["id"]))
        self.assertEqual("failed", stored["status"])
        # The slot is free: three more starts pass the three-run cap (it counts active runs only).
        for index in range(3):
            self.start("no_result", project=self.project(f"p{index}"), FAKE_CLAUDE_DELAY_MS="2000")
        self.assertEqual(4, len(self.app.tasks))
        self.assertTrue(wait_for(lambda: len(self.created) == 4))

    def test_storage_error_during_launch_failure_keeps_failed_in_memory(self):
        self.app.roles["backend_developer"] = dict(self.app.roles["backend_developer"], model="not-a-claude-alias")
        created = self.start("success")
        # Not raised out of the worker even when the store cannot record the failure.
        task = self.app.tasks[created["id"]]
        with self.app.lock:
            task["status"] = "queued"
            task["diagnostics"] = []
            with mock.patch.object(self.app.store, "put", side_effect=sqlite3.OperationalError("synthetic")):
                self.app._claude_launch_failed(task)
        self.assertEqual("failed", task["status"])
        self.assertEqual(["claude_launch_invalid"], self.codes(task))

    def test_overflow_after_a_result_keeps_the_status_as_a_notice(self):
        created = self.start("multi_result", FAKE_CLAUDE_DELAY_MS="1000")
        task_id = created["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "completed"))
        run = self.app.runs[task_id]  # still running: the late lines are seconds away
        self.app._claude_exit(task_id, run, RunExit(None, False, None, True, True))
        task = self.app.tasks[task_id]
        self.assertEqual("completed", task["status"])
        self.assertEqual(["claude_output_too_large"], self.codes(task))
        self.assertIsNone(task["error"])
        self.assertNotIn(task_id, self.app.runs)

    def test_stopped_and_overflowing_run_is_unknown(self):
        """Task 6 carry-over: overflow is checked before stopped_by_us."""
        created = self.start("success", FAKE_CLAUDE_DELAY_MS="1000")
        task_id = created["id"]
        self.assertTrue(wait_for(lambda: task_id in self.app.runs))
        self.app._claude_exit(task_id, self.app.runs[task_id], RunExit(None, True, "owner", False, True))
        task = self.app.tasks[task_id]
        self.assertEqual("unknown", task["status"])
        self.assertEqual(["claude_output_too_large"], self.codes(task))
        self.assertNotIn("recovery_hold", task)

    def test_overflow_exit_is_unknown_with_diagnostic(self):
        self.max_line = 500
        task = self.finish(self.start("success")["id"])
        self.assertTrue(self.created[-1].overflow)
        self.assertEqual("unknown", task["status"])
        self.assertIn("claude_output_too_large", self.codes(task))
        self.assertNotIn("recovery_hold", task)


if __name__ == "__main__":
    unittest.main()

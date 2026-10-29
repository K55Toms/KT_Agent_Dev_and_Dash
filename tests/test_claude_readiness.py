"""Claude readiness (`claude --version` probe) and the provider-aware start gate (Review Focus 1).

Evidence kind: fake runner and fake binary only; nothing here runs the real ``claude``.
"""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from dashboard import backends
from dashboard.backends import claude as claude_module
from dashboard.backends.base import ProviderUnavailable
from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_launch import load_claude_roles
from dashboard.backends.claude_stream import ClaudeCapabilities
from dashboard.ponytail_policy import PolicyError
from dashboard.server import Dashboard, ROOT, dashboard_for_provider, load_roles
from tests.policy_fixtures import SyntheticPolicy

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
SCRIPT = ROOT / "scripts" / "run_dashboard.sh"
TASK = {"title": "Implement feature", "instruction": "SYNTHETIC_PRIVATE_TASK_INSTRUCTION",
        "role": "backend_developer"}
NOT_FOUND = "Claude Code was not found on PATH."
NO_VERSION = "Claude Code did not report a version."
NOT_YET = "Claude runs are not available yet."
PROTOCOL = "This operation is not available for the Claude backend."


class FakeRunner:
    """Answers the probe without a process; records each (argv, timeout)."""
    def __init__(self, returncode=0, output="2.1.312 (Claude Code)\n", error=None):
        self.returncode, self.output, self.error = returncode, output, error
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if self.error is not None:
            raise self.error
        return self.returncode, self.output


class RaisingPolicy:
    """A machine with no Codex plugin cache: every load fails, and each call is counted."""
    def __init__(self):
        self.calls = 0

    def load(self):
        self.calls += 1
        raise PolicyError("Approved Ponytail policy configuration is invalid.")


def wait_for(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class ProbeTests(unittest.TestCase):
    def probe(self, **kwargs):
        runner = FakeRunner(**kwargs)
        result = ClaudeBackend(claude_path="/synthetic/bin/claude", runner=runner).probe()
        return result, runner

    def test_probe_accepts_a_version_line_only(self):
        good, runner = self.probe()
        self.assertEqual({"ok": True, "version": "2.1.312", "detail": "Claude Code 2.1.312"}, good)
        self.assertEqual([(["/synthetic/bin/claude", "--version"], 5)], runner.calls)
        bare, _ = self.probe(output="2.1.312\n")
        self.assertEqual("2.1.312", bare["version"])
        self.assertTrue(bare["ok"])
        # Only the first line is read; nothing after it is kept.
        multi, _ = self.probe(output="2.1.312 (Claude Code)\nSYNTHETIC_SECOND_LINE /Users/someone\n")
        self.assertEqual({"ok": True, "version": "2.1.312", "detail": "Claude Code 2.1.312"}, multi)
        refused = {
            "long line": "2." + "1" * 60 + " (Claude Code)\n",
            "control characters": "2.1.312\x1b[31m (Claude Code)\n",
            "carriage return": "2.1.312\r\n",
            "nul": "2.1.312\x00\n",
            "tab": "2.1.312\t(Claude Code)\n",
            "multi-line junk first": "Welcome to Claude\n2.1.312 (Claude Code)\n",
            "leading blank line": "\n2.1.312 (Claude Code)\n",
            "not a digit first": "v2.1.312\n",
            "empty": "",
            "path": "2.1.312 /Users/someone\n".replace(" ", "/"),
        }
        for name, output in refused.items():
            with self.subTest(case=name):
                result, _ = self.probe(output=output)
                self.assertEqual({"ok": False, "version": None, "detail": NO_VERSION}, result)
        for name, kwargs in {"nonzero exit": {"returncode": 1},
                             "timeout": {"error": subprocess.TimeoutExpired(["claude"], 5)},
                             "os error": {"error": OSError("synthetic")}}.items():
            with self.subTest(case=name):
                result, _ = self.probe(**kwargs)
                self.assertEqual({"ok": False, "version": None, "detail": NO_VERSION}, result)

    def test_missing_binary_is_not_run(self):
        runner = FakeRunner()
        backend = ClaudeBackend(runner=runner)
        with mock.patch.object(claude_module.shutil, "which", return_value=None) as which:
            result = backend.probe()
        which.assert_called_once_with("claude")
        self.assertEqual({"ok": False, "version": None, "detail": NOT_FOUND}, result)
        self.assertEqual([], runner.calls)

    def test_binary_is_looked_up_on_path(self):
        runner = FakeRunner()
        backend = ClaudeBackend(runner=runner)
        with mock.patch.object(claude_module.shutil, "which", return_value="/synthetic/path/claude"):
            self.assertTrue(backend.probe()["ok"])
        self.assertEqual("/synthetic/path/claude", backend.claude_path)
        self.assertEqual([(["/synthetic/path/claude", "--version"], 5)], runner.calls)

    def test_default_runner_reads_the_fake_binary_and_fails_closed(self):
        code, output = claude_module.run_version([sys.executable, str(FAKE), "--version"], 5)
        self.assertEqual(0, code)
        self.assertEqual("2.1.312 (Claude Code)", output.split("\n")[0])
        self.assertEqual((1, ""), claude_module.run_version(
            [sys.executable, "-c", "import time; time.sleep(5)"], 0.2))
        self.assertEqual((1, ""), claude_module.run_version(["/nonexistent/synthetic/claude", "--version"], 1))

    def test_default_runner_scrubs_the_environment(self):
        script = "import os, json; print(json.dumps(sorted(os.environ)))"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k",
                                          "CLAUDE_CODE_USE_BEDROCK": "1"}):
            code, output = claude_module.run_version([sys.executable, "-c", script], 5)
        self.assertEqual(0, code)
        self.assertNotIn("ANTHROPIC_API_KEY", output)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", output)

    def test_protocol_methods_still_raise_provider_unavailable(self):
        backend = ClaudeBackend(claude_path="/synthetic/bin/claude", runner=FakeRunner())
        self.assertIs(ClaudeCapabilities, backend.capabilities)
        self.assertIs(ClaudeCapabilities, ClaudeBackend.capabilities)
        for name, call in {"translate": lambda: backend.translate({}), "list_models": lambda: backend.list_models(),
                           "start_thread": lambda: backend.start_thread({}),
                           "start_turn": lambda: backend.start_turn({}), "steer": lambda: backend.steer({}),
                           "interrupt": lambda: backend.interrupt("t", "u"),
                           "answer_approval": lambda: backend.answer_approval(None, "accept")}.items():
            with self.subTest(method=name):
                with self.assertRaises(ProviderUnavailable) as caught:
                    call()
                self.assertEqual(PROTOCOL, str(caught.exception))

    def test_resolver_returns_the_claude_backend(self):
        backend = backends.resolve("claude", object)
        self.assertIsInstance(backend, ClaudeBackend)
        self.assertIsNone(backend.claude_path)


class DashboardReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "project").mkdir()

    def claude_dashboard(self, runner=None, policy=None, claude_path="/synthetic/bin/claude"):
        backend = ClaudeBackend(claude_path=claude_path, runner=runner or FakeRunner())
        app = Dashboard(self.root / "state", policy_provider=policy or RaisingPolicy(), backend=backend)
        self.addCleanup(app.close)
        return app

    def rows(self, app):
        return app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()

    def test_claude_dashboard_connects_after_probe_and_enables_start(self):
        runner = FakeRunner()
        app = self.claude_dashboard(runner)
        self.assertEqual("disconnected", app.connection["status"])
        app.start()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "connected"))
        connection = app.snapshot()["connection"]
        self.assertEqual({"status", "detail", "last_event_at", "server_version"}, set(connection))
        self.assertEqual("Claude Code 2.1.312 (login not verified)", connection["detail"])
        self.assertEqual("2.1.312", connection["server_version"])
        self.assertIsInstance(connection["last_event_at"], str)
        self.assertEqual(1, len(runner.calls))
        self.assertIsNone(app.client)
        self.assertIsNone(app._provider_refusal())

    def test_claude_dashboard_reports_connecting_until_the_probe_answers(self):
        import threading
        gate = threading.Event()

        def slow(argv, timeout):
            gate.wait(5)
            return 0, "2.1.312 (Claude Code)\n"
        app = self.claude_dashboard(slow)
        app.start()
        self.assertEqual("connecting", app.snapshot()["connection"]["status"])
        gate.set()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "connected"))

    def test_missing_claude_disables_with_fixed_text(self):
        runner = FakeRunner()
        app = self.claude_dashboard(runner, claude_path=None)
        with mock.patch.object(claude_module.shutil, "which", return_value=None):
            app.start()
            self.assertTrue(wait_for(lambda: app.connection["status"] == "disabled"))
        self.assertEqual(NOT_FOUND, app.snapshot()["connection"]["detail"])
        self.assertIsNone(app.connection["server_version"])
        self.assertEqual([], runner.calls)
        project = app.add_project({"name": "Project One", "path": str(self.root / "project")})
        before = self.rows(app)
        with self.assertRaises(ValueError) as caught:
            app.start_task(dict(TASK, project_id=project["id"]))
        self.assertNotIsInstance(caught.exception, ProviderUnavailable)
        self.assertEqual("Claude Code is not ready.", str(caught.exception))
        self.assertEqual(before, self.rows(app))
        self.assertEqual({}, app.tasks)

    def test_bad_version_output_disables_with_fixed_text(self):
        app = self.claude_dashboard(FakeRunner(output="SYNTHETIC banner /Users/someone\n"))
        app.start()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "disabled"))
        self.assertEqual(NO_VERSION, app.connection["detail"])

    def test_claude_start_works_without_codex_plugin_cache_or_gpt_roles(self):
        """Review Focus 1: the Claude start path never touches Ponytail or the GPT-only role check."""
        policy = RaisingPolicy()
        app = self.claude_dashboard(FakeRunner(), policy=policy)
        app.start()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "connected"))
        project = app.add_project({"name": "Project One", "path": str(self.root / "project")})
        before = (self.rows(app), deepcopy(app.tasks), list(app.workers))
        with mock.patch.object(app.native_roles, "config", side_effect=AssertionError("GPT-only role check")) as config:
            with self.assertRaises(ProviderUnavailable) as caught:
                app.start_task(dict(TASK, project_id=project["id"]))
        self.assertEqual(NOT_YET, str(caught.exception))
        self.assertEqual(0, policy.calls)
        config.assert_not_called()
        self.assertEqual(before, (self.rows(app), app.tasks, app.workers))
        self.assertEqual({}, app.tasks)
        # The gates still run first: an unknown role is a validation error, not the not-yet refusal.
        with self.assertRaises(ValueError) as caught:
            app.start_task(dict(TASK, project_id=project["id"], role="no_such_role"))
        self.assertNotIsInstance(caught.exception, ProviderUnavailable)
        # A Claude task's policy check returns without Ponytail or the Codex role snapshots.
        with mock.patch.object(app.native_roles, "config", side_effect=AssertionError("GPT-only role check")):
            self.assertIsNone(app._verify_task_policy({"id": "x", "provider": "claude", "compliance_policy": None}))
        self.assertEqual(0, policy.calls)
        # A Claude task with no compliance policy shows in the snapshot with delivery off.
        task = {"id": "a" * 32, "project_id": project["id"], "title": "T", "role": "backend_developer",
                "model": "opus", "profile_model": "opus", "reasoning": "high", "status": "completed",
                "thread_id": None, "turn_id": None, "plan": [], "compliance_policy": None, "provider": "claude",
                "task_purpose": "development", "revision": 1, "recovery_schema": 1, "created_at": "2026-10-29T00:00:00+00:00",
                "updated_at": "2026-10-29T00:00:00+00:00", "error": None, "diagnostics": [], "usage": None, "cost": {}}
        with app.lock:
            app.tasks[task["id"]] = task
        shown = next(t for t in app.snapshot()["tasks"] if t["id"] == task["id"])
        self.assertFalse(shown["delivery_available"])
        self.assertEqual("claude", shown["provider"])

    def test_roles_for_claude_come_from_claude_agent_files(self):
        app = self.claude_dashboard()
        expected = load_claude_roles(ROOT)
        self.assertEqual(14, len(app.roles))
        self.assertEqual(expected, app.roles)
        self.assertEqual(("opus", "high"), (app.roles["backend_developer"]["model"],
                                            app.roles["backend_developer"]["reasoning"]))
        for role in app.roles.values():
            self.assertIn(role["model"], {"opus", "sonnet", "haiku", "fable"})
        self.assertEqual(set(expected), set(app.team.roles))
        snapshot_roles = {r["id"]: (r["model"], r["reasoning"]) for r in app.snapshot()["roles"]}
        self.assertEqual({k: (v["model"], v["reasoning"]) for k, v in expected.items()}, snapshot_roles)
        wired = dashboard_for_provider("claude", directory=self.root / "wired", policy_provider=RaisingPolicy())
        self.addCleanup(wired.close)
        self.assertIsInstance(wired.backend, ClaudeBackend)
        self.assertEqual(expected, wired.roles)

    def test_codex_deployment_gates_are_unchanged(self):
        codex = dashboard_for_provider("codex", directory=self.root / "codex", policy_provider=RaisingPolicy())
        self.addCleanup(codex.close)
        self.assertEqual(load_roles(), codex.roles)
        self.assertTrue(all(role["model"].startswith("gpt-") for role in codex.roles.values()))
        project = codex.add_project({"name": "Project One", "path": str(self.root / "project")})
        # The Codex path still loads the approved policy first and fails closed without it.
        with self.assertRaises(PolicyError):
            codex.start_task(dict(TASK, project_id=project["id"]))
        self.assertEqual(1, codex.policy_provider.calls)
        codex.policy_provider = SyntheticPolicy()
        with self.assertRaises(ValueError) as caught:
            codex.start_task(dict(TASK, project_id=project["id"]))
        self.assertEqual("Codex is disconnected; no run was started", str(caught.exception))
        self.assertEqual({}, codex.tasks)
        # A Codex task still verifies the policy and the role snapshot.
        with self.assertRaises(ValueError):
            codex._verify_task_policy({"id": "x", "provider": "codex", "compliance_policy": None})
        # And a Codex deployment never probes Claude.
        self.assertFalse(hasattr(codex.backend, "probe"))


class ScriptTests(unittest.TestCase):
    def test_script_requires_claude_on_path_for_claude_only(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as scratch:
            bin_dir = Path(scratch) / "bin"
            bin_dir.mkdir()
            # A PATH with a usable python3 and dirname but neither claude nor codex: no server can start.
            os.symlink(sys.executable, bin_dir / "python3")
            os.symlink("/usr/bin/dirname", bin_dir / "dirname")
            env = {"PATH": str(bin_dir), "HOME": scratch}
            result = subprocess.run(["/bin/sh", str(SCRIPT), "claude"], cwd=scratch, env=env,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            self.assertEqual(1, result.returncode)
            self.assertEqual("", result.stdout)
            self.assertEqual("Claude Code CLI is required on PATH.\n", result.stderr)
            # The codex argument is not checked for claude: it stops on its own missing CLI instead.
            result = subprocess.run(["/bin/sh", str(SCRIPT), "codex"], cwd=scratch, env=env,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            self.assertEqual(1, result.returncode)
            self.assertNotIn("Claude", result.stderr)
            self.assertIn("Codex CLI is required on PATH.", result.stderr)
        text = SCRIPT.read_text()
        self.assertIn('if [ "$1" = claude ] && ! command -v claude >/dev/null 2>&1; then', text)
        # The usage check stays first.
        self.assertLess(text.index("Usage: sh scripts/run_dashboard.sh"), text.index("command -v claude"))


if __name__ == "__main__":
    unittest.main()

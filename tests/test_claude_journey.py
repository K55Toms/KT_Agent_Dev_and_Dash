"""Claude deployment journey over HTTP (Plan 3, Task 11).

Evidence kind: fake-binary evidence, not a live run. Every run executes tests/fake_claude.py (replaying
sanitized fixtures) through the real argv builder, the real ClaudeRun process runner and the real HTTP
handler on an ephemeral port. The run factory refuses any executable but the fake, so the real ``claude``
can never start here. Nothing in this file establishes how the real CLI behaves.

All fixtures share one session id. A Dashboard registers each Claude session once, so a second fresh run
on the SAME Dashboard is refused as ``claude_session_rejected`` (pinned in
``test_a_second_fresh_run_on_one_dashboard_is_refused_as_session_rejected``). The journeys below therefore
use a new Dashboard per scenario, or (restart test) rewrite the session id in the run factory.
"""
from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from dashboard.backends.base import NeutralEvent
from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_runner import ClaudeRun
from dashboard.backends.claude_stream import NEUTRAL_KEYS, usage_from_model_usage
from dashboard.ponytail_policy import PolicyError
from dashboard.server import Dashboard, make_server
from tests.dashboard_key_harness import make_test_server

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude"
SESSION = "00000000-0000-4000-8000-000000005e55"
OTHER_SESSION = "00000000-0000-4000-8000-0000000007e5"
INSTRUCTION = "Implement the synthetic feature"
FOLLOWUP = "Continue with the synthetic feature"
TERMINAL = {"completed", "failed", "interrupted", "unknown"}
DENIED_NOTICE = "Some tool calls were denied because they were not approved: by you, by the approval wait running out, or because the run was stopped."
NOT_AVAILABLE = {"error": "not available for this provider"}
WAIT = 20.0


def probe_runner(argv, timeout):
    return 0, "2.1.312 (Claude Code)\n"



def without_summary(value):
    """Plan 5 Task 4: the main agent's final reply is, by design, the task's last_summary (model-reported). Everything else
    must stay free of reply text, so checks run over the data with that one field removed."""
    if isinstance(value, dict):
        return {k: without_summary(v) for k, v in value.items() if k != "last_summary"}
    if isinstance(value, list):
        return [without_summary(v) for v in value]
    return value


class RaisingPolicy:
    """A Claude deployment must never need the Codex policy; touching it fails the test."""

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


class ClaudeJourney(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.record = self.root / "record.jsonl"
        self.created = []
        self.apps = []
        self.servers = []
        self.session_rewrite = None
        self.app, self.port = self.make_app()

    def tearDown(self):
        for run in self.created:
            run.close()
        for server, thread in self.servers:
            server.shutdown()
            thread.join(3)
            server.server_close()
        for app in self.apps:
            app.close()
        self.assertTrue(wait_for(lambda: not stray_fakes(), 5), "a fake_claude process was left running")
        self.temp.cleanup()

    # ---- harness ---------------------------------------------------------------------------------
    def factory(self, argv, **kwargs):
        if argv[0] != str(FAKE):
            raise AssertionError("refusing to start anything but the fake claude")
        if self.session_rewrite is not None:
            forward, other = kwargs["on_event"], self.session_rewrite
            kwargs["on_event"] = lambda event: forward(NeutralEvent(event.kind, other, event.turn_id, event.data))
        run = ClaudeRun(argv, sigint_wait=2.0, term_wait=1.0, **kwargs)
        self.created.append(run)
        return run

    def make_app(self, **extra):
        """A Claude Dashboard on the shared state directory, served on an ephemeral port."""
        backend = ClaudeBackend(claude_path=str(FAKE), runner=probe_runner)
        app = Dashboard(self.root / "state", policy_provider=RaisingPolicy(), backend=backend,
                        claude_run_factory=self.factory,
                        claude_env_extra=dict(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_RECORD=str(self.record)),
                        **extra)
        self.apps.append(app)
        server = make_test_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        app.start()
        port = server.server_port
        self.assertTrue(wait_for(lambda: self.state(port)["connection"]["status"] == "connected", 5))
        return app, port

    def use(self, fixture, **extra):
        """Choose the fixture the NEXT fake process replays (test seam on the Dashboard)."""
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, FAKE_CLAUDE_RECORD=str(self.record), **extra)

    def http(self, method, path, body=None, port=None):
        port = port or self.port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Origin": f"http://127.0.0.1:{port}"}
        payload = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            payload = json.dumps({} if body is None else body)
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw)

    def state(self, port=None):
        status, body = self.http("GET", "/api/state", port=port)
        self.assertEqual(200, status)
        return body

    def task_state(self, task_id, port=None):
        return next(task for task in self.state(port)["tasks"] if task["id"] == task_id)

    def project(self, name="project"):
        path = self.root / name
        path.mkdir(exist_ok=True)
        status, project = self.http("POST", "/api/projects", {"name": name, "path": str(path)})
        self.assertEqual(200, status, project)
        return project

    def start(self, fixture="success", project=None, **extra):
        self.use(fixture, **extra)
        project = project or self.project()
        status, task = self.http("POST", "/api/tasks", {"project_id": project["id"], "title": "Synthetic run",
                                                        "instruction": INSTRUCTION, "role": "backend_developer"})
        self.assertEqual(200, status, task)
        return task

    def finish(self, task_id, port=None):
        """Poll /api/state (bounded) until the task is terminal and its process has been reaped."""
        app = self.apps[-1] if port else self.app
        self.assertTrue(wait_for(lambda: self.task_state(task_id, port)["status"] in TERMINAL
                                 and task_id not in app.runs and task_id not in app.launching_tasks),
                        "the run did not finish within the bound")
        return self.task_state(task_id, port)

    def codes(self, task):
        return [entry["code"] for entry in task["diagnostics"]]

    def invocations(self):
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines() if line.strip()]

    # ---- a) provider and connection --------------------------------------------------------------
    def test_a_provider_endpoint_and_connection_report_claude(self):
        status, info = self.http("GET", "/api/provider")
        self.assertEqual(200, status)
        self.assertEqual("claude", info["provider"])
        self.assertTrue(info["configured"])
        self.assertEqual("claude", info["capabilities"]["provider"])
        state = self.state()
        self.assertEqual("connected", state["connection"]["status"])
        self.assertIn("login not verified", state["connection"]["detail"])
        self.assertEqual("usd-estimate", state["pricing"]["unit"])

    # ---- b) a run to completion ------------------------------------------------------------------
    def test_b_success_run_completes_with_usage_cost_and_no_sensitive_text(self):
        created = self.start("success")
        self.assertEqual("claude", created["provider"])
        task = self.finish(created["id"])
        self.assertEqual("completed", task["status"])
        self.assertEqual("claude", task["provider"])  # the data the provider chip is drawn from
        self.assertEqual(set(NEUTRAL_KEYS), set(task["usage"]))
        self.assertEqual(5, len(task["usage"]))
        expected = usage_from_model_usage(result_line("success")["modelUsage"])
        self.assertEqual({key: expected[key] for key in NEUTRAL_KEYS}, task["usage"])
        self.assertEqual("usd-estimate", task["cost"]["unit"])
        self.assertAlmostEqual(result_line("success")["total_cost_usd"], task["cost"]["usd"])
        self.assertEqual({"denied_count": 0, "denied_tools": []}, task["claude"])
        self.assertFalse(task.get("recovery_hold"))
        state = self.state()
        self.assertEqual("claude", next(p for p in state["projects"] if p["id"] == task["project_id"])["provider"])
        raw = json.dumps(without_summary(state))
        self.assertNotIn("SENSITIVE", raw)  # hook output, assistant text, tool input, sub-agent text markers
        self.assertNotIn("<PATH>", raw)
        self.assertNotIn(INSTRUCTION, raw)

    # ---- c) denied calls -------------------------------------------------------------------------
    def test_c_denied_run_shows_count_and_the_fixed_notice(self):
        # A new Dashboard (this test's own): the shared session id would be refused on a second run.
        created = self.start("denied")
        task = self.finish(created["id"])
        self.assertEqual("completed", task["status"])
        self.assertEqual({"denied_count": 1, "denied_tools": ["Bash"]}, task["claude"])
        notices = [entry for entry in task["diagnostics"] if entry["code"] == "claude_calls_denied"]
        self.assertEqual(1, len(notices))
        self.assertEqual(DENIED_NOTICE, notices[0]["message"])
        self.assertNotIn("SENSITIVE", json.dumps(without_summary(self.state())))

    def test_a_second_fresh_run_on_one_dashboard_is_refused_as_session_rejected(self):
        first = self.start("success", project=self.project("one"))
        self.assertEqual("completed", self.finish(first["id"])["status"])
        second = self.start("denied", project=self.project("two"))
        task = self.finish(second["id"])
        self.assertEqual("failed", task["status"])
        self.assertIn("claude_session_rejected", self.codes(task))

    # ---- d) follow-up ----------------------------------------------------------------------------
    def test_d_followup_resumes_the_session_and_totals_add(self):
        created = self.start("success")
        first = self.finish(created["id"])
        self.use("resumed")
        status, answer = self.http("POST", f"/api/tasks/{created['id']}/message",
                                   {"text": FOLLOWUP, "expected_turn_id": first["turn_id"]})
        self.assertEqual((200, {"status": "sent", "mode": "followup"}), (status, answer))
        final = self.finish(created["id"])
        self.assertEqual("completed", final["status"])
        argv = self.invocations()[-1]["argv"]
        self.assertEqual(SESSION, argv[argv.index("--resume") + 1])
        self.assertNotIn("--resume", self.invocations()[0]["argv"])
        added = usage_from_model_usage(result_line("resumed")["modelUsage"])
        self.assertEqual({key: first["usage"][key] + added[key] for key in NEUTRAL_KEYS}, final["usage"])
        self.assertAlmostEqual(first["cost"]["usd"] + result_line("resumed")["total_cost_usd"], final["cost"]["usd"])
        self.assertEqual("usd-estimate", final["cost"]["unit"])
        self.assertEqual({"denied_count": 0, "denied_tools": []}, final["claude"])

    # ---- e) stop ---------------------------------------------------------------------------------
    def test_e_stop_interrupts_the_run_and_leaves_no_process(self):
        created = self.start("success", FAKE_CLAUDE_DELAY_MS="400")
        self.assertTrue(wait_for(lambda: self.task_state(created["id"])["status"] == "running"
                                 and created["id"] in self.app.runs))
        status, answer = self.http("POST", f"/api/tasks/{created['id']}/interrupt", {})
        self.assertEqual(200, status, answer)
        self.assertEqual("interrupt_requested", answer["status"])
        task = self.finish(created["id"])
        self.assertEqual("interrupted", task["status"])
        self.assertFalse(task.get("recovery_hold"))
        self.assertNotIn("claude_aborted", self.codes(task))
        self.assertTrue(wait_for(lambda: not stray_fakes(), 5))
        self.assertEqual({}, self.app.runs)
        # Stopping a run that is no longer active is a plain refusal, not a state change.
        status, answer = self.http("POST", f"/api/tasks/{created['id']}/interrupt", {})
        self.assertEqual(400, status)  # the HTTP layer maps the ValueError to its generic 400 text
        self.assertEqual("interrupted", self.task_state(created["id"])["status"])

    # ---- f) Codex-only routes --------------------------------------------------------------------
    def test_f_codex_only_routes_answer_409(self):
        task = "/api/tasks/" + "a" * 32
        before = self.state()
        for method, path, body in (("POST", task + "/recovery/check", {"expected_revision": 1}),
                                   ("POST", task + "/recovery/assess", {}),
                                   ("POST", "/api/approvals/" + "b" * 32 + "/alternative",
                                    {"text": "smaller", "mode": "decline"})):
            with self.subTest(path=path):
                self.assertEqual((409, NOT_AVAILABLE), self.http(method, path, body))
        self.assertEqual(before["tasks"], self.state()["tasks"])

    # ---- g) restart sweep ------------------------------------------------------------------------
    def test_g_restart_sweep_keeps_sessions_without_recovery_hold(self):
        done = self.start("success", project=self.project("done"))
        self.assertEqual("completed", self.finish(done["id"])["status"])
        self.session_rewrite = OTHER_SESSION  # a second session id; the fixtures all share one
        active = self.start("success", project=self.project("active"), FAKE_CLAUDE_DELAY_MS="400")
        self.assertTrue(wait_for(lambda: self.task_state(active["id"])["status"] == "running"
                                 and active["id"] in self.app.runs))
        # Phase 1: a clean close stops the live run, which is therefore recorded as interrupted.
        self.app.close()
        self.apps.remove(self.app)
        self.session_rewrite = None
        self.app, self.port = self.make_app(process_probe=lambda pid: None)
        self.assertEqual("completed", self.task_state(done["id"])["status"])
        stopped = self.task_state(active["id"])
        self.assertEqual("interrupted", stopped["status"])
        self.assertFalse(stopped.get("recovery_hold"))
        self.assertTrue(wait_for(lambda: not stray_fakes(), 5))
        # Phase 2: a dashboard that died while the run was active leaves it stored as running. Simulate
        # that by writing the status back, then restart: the sweep must say unknown and keep the session.
        with self.app.lock:
            record = self.app.tasks[active["id"]]
            record["status"] = "running"
            self.app.store.put("task", record)
        self.app.close()
        self.apps.remove(self.app)
        self.app, self.port = self.make_app(process_probe=lambda pid: None)
        state = self.state()
        tasks = {task["id"]: task for task in state["tasks"]}
        self.assertEqual("completed", tasks[done["id"]]["status"])
        swept = tasks[active["id"]]
        self.assertEqual("unknown", swept["status"])
        self.assertFalse(swept.get("recovery_hold"))
        self.assertEqual(OTHER_SESSION, swept["thread_id"])  # the session is kept for a follow-up
        self.assertEqual("claude_restart_unknown", swept["diagnostics"][-1]["code"])
        self.assertEqual({"denied_count": 0, "denied_tools": []}, swept["claude"])
        self.assertFalse(any(task.get("recovery_hold") for task in tasks.values()))
        self.assertNotIn("SENSITIVE", json.dumps(without_summary(state)))


if __name__ == "__main__":
    unittest.main()

"""Plan 5 Task 1: what a finished fake Claude task does today for the slice 2b features.

Evidence kind: fake-binary evidence, not a live run. Every run executes tests/fake_claude.py (replaying a
sanitized fixture) through the real argv builder, the real ClaudeRun process runner and the real HTTP handler on
an ephemeral port; the run factory refuses any executable but the fake. Nothing here shows how the real CLI behaves.

These are characterization tests. Passing tests pin today's behaviour. A test marked ``expectedFailure`` names
a gap that a later task of Plan 5 closes; that task removes the marker.

The server comes from tests/dashboard_key_harness.py (make_test_server); the HTTP helper below follows
tests/test_claude_journey.py (same-origin http.client). ``Slice2bHarness`` holds that setup so later Plan 5 test
modules can reuse it without re-running these tests.
"""
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_runner import ClaudeRun
from dashboard.ponytail_policy import PolicyError
from dashboard.project_files import FileAccessError
from dashboard.server import Dashboard
from tests.dashboard_key_harness import make_test_server

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
SESSION = "00000000-0000-4000-8000-000000005e55"
INSTRUCTION = "Implement the synthetic feature"
FOLLOWUP = "Continue with the synthetic feature"
TERMINAL = {"completed", "failed", "interrupted", "unknown"}
WAIT = 20.0
REPORT = "report.md"


def probe_runner(argv, timeout):
    return 0, "2.1.312 (Claude Code)\n"


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


def stray_fakes():
    out = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True,
                         timeout=10).stdout
    found = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] == str(os.getpid()) and "fake_claude.py" in parts[2]:
            found.append(int(parts[0]))
    return found


class Slice2bHarness(unittest.TestCase):
    """A keyed test server over the fake Claude binary; every resource is released by addCleanup, so a failing
    setUp leaks nothing."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.created = []
        self.env = dict(FAKE_CLAUDE_FIXTURE="success")
        backend = ClaudeBackend(claude_path=str(FAKE), runner=probe_runner)
        self.app = Dashboard(self.root / "state", policy_provider=RaisingPolicy(), backend=backend,
                             claude_run_factory=self.factory, claude_env_extra=self.env)
        self.addCleanup(lambda: self.assertTrue(wait_for(lambda: not stray_fakes(), 5),
                                                "a fake_claude process was left running"))
        self.addCleanup(self.app.close)
        self.server = make_test_server(self.app, 0)
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 3)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.close_runs)
        self.app.start()
        self.port = self.server.server_port
        self.assertTrue(wait_for(lambda: self.state()["connection"]["status"] == "connected", 5))
        self.project_dir = self.root / "project"
        self.project_dir.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project_dir)], check=True, timeout=20)

    def close_runs(self):
        for run in self.created:
            run.close()

    # ---- harness (same shape as tests/test_claude_journey.py) ------------------------------------
    def factory(self, argv, **kwargs):
        if argv[0] != str(FAKE):
            raise AssertionError("refusing to start anything but the fake claude")
        run = ClaudeRun(argv, sigint_wait=2.0, term_wait=1.0, **kwargs)
        self.created.append(run)
        return run

    def use(self, fixture):
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture)

    def http(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Origin": f"http://127.0.0.1:{self.port}"}
        payload = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            payload = json.dumps({} if body is None else body)
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw)

    def state(self):
        status, body = self.http("GET", "/api/state")
        self.assertEqual(200, status)
        return body

    def task_state(self, task_id):
        return next(task for task in self.state()["tasks"] if task["id"] == task_id)

    def finished_task(self, fixture="success"):
        """Register the project, start one fake Claude run and wait until it is completed and reaped."""
        self.use(fixture)
        status, project = self.http("POST", "/api/projects", {"name": "project", "path": str(self.project_dir)})
        self.assertEqual(200, status, project)
        status, task = self.http("POST", "/api/tasks", {"project_id": project["id"], "title": "Synthetic run",
                                                       "instruction": INSTRUCTION, "role": "backend_developer"})
        self.assertEqual(200, status, task)
        self.wait_finished(task["id"])
        return self.task_state(task["id"])

    def wait_finished(self, task_id):
        self.assertTrue(wait_for(lambda: self.task_state(task_id)["status"] in TERMINAL
                                 and task_id not in self.app.runs and task_id not in self.app.launching_tasks),
                        "the run did not finish within the bound")

    def followup(self, task, fixture="resumed"):
        self.use(fixture)
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/message",
                                   {"text": FOLLOWUP, "expected_turn_id": task["turn_id"]})
        self.assertEqual((200, {"status": "sent", "mode": "followup"}), (status, answer))
        self.wait_finished(task["id"])
        return self.task_state(task["id"])

    def write_report(self):
        (self.project_dir / REPORT).write_text("# Synthetic report\n\nNothing sensitive here.\n")

    def attach(self, task, path=REPORT):
        return self.http("POST", f"/api/tasks/{task['id']}/outputs",
                         {"path": path, "expected_turn_id": task["turn_id"], "confirmed": True})


class Slice2bBaseline(Slice2bHarness):
    # ---- conversation ----------------------------------------------------------------------------
    def test_conversation_view_for_claude_task(self):
        task = self.finished_task()
        self.assertEqual("completed", task["status"])
        status, view = self.http("GET", f"/api/tasks/{task['id']}/conversation")
        self.assertEqual(200, status)
        self.assertEqual(task["id"], view["task_id"])
        self.assertEqual(task["turn_id"], view["turn_id"])
        # The user's instruction comes first, appended when the run is started; the reply follows (Plan 5 Task 2).
        self.assertEqual(["user", "agent"], [m["kind"] for m in view["messages"]])
        self.assertEqual(INSTRUCTION, view["messages"][0]["text"])
        self.assertEqual("sent", view["messages"][0]["status"])
        self.assertEqual("SENSITIVE_ASSISTANT_TEXT_MARKER", view["messages"][1]["text"])
        self.assertEqual([], view["questions"])
        # The task's own role is listed as its agent; there are no delegated agents.
        self.assertEqual({SESSION: {"role_id": "backend_developer", "name": "Kira Voss"}}, view["agents"])
        # A finished Claude turn can take a follow-up, so the send state is open.
        self.assertTrue(view["can_send"])
        self.assertEqual("followup", view["send_mode"])
        self.assertIsNone(view["blocked_reason"])

    def test_conversation_shows_claude_assistant_text(self):
        """Closed by Plan 5 Task 2: Claude assistant text is appended to the conversation."""
        task = self.finished_task()
        _, view = self.http("GET", f"/api/tasks/{task['id']}/conversation")
        self.assertIn("agent", [m["kind"] for m in view["messages"]])

    # ---- team view -------------------------------------------------------------------------------
    def team_member(self, role="backend_developer"):
        status, team = self.http("GET", "/api/team")
        self.assertEqual(200, status)
        return next(member for member in team["members"] if member["id"] == role)

    def test_team_snapshot_lists_claude_task_as_direct_activity(self):
        task = self.finished_task()
        member = self.team_member()
        self.assertEqual([task["id"]], [a["id"] for a in member["activities"]])
        activity = member["activities"][0]
        self.assertEqual("direct", activity["source"])
        self.assertEqual("completed", activity["status"])
        self.assertEqual("backend_developer", activity["role"])
        self.assertIsNone(activity["parent_task_id"])
        self.assertEqual(task["id"], member["last_task"]["id"])

    def test_team_last_summary_is_set_for_claude(self):
        """Closed by Plan 5 Task 4: the final reply of the latest turn is the model-reported summary."""
        self.finished_task()
        self.assertIsNotNone(self.team_member()["last_task"]["last_summary"])

    # ---- outputs ---------------------------------------------------------------------------------
    def test_attach_output_on_completed_claude_task(self):
        task = self.finished_task()
        self.write_report()
        status, answer = self.attach(task)
        self.assertEqual(200, status, answer)
        self.assertEqual(REPORT, answer["output"]["path"])
        self.assertEqual("human", answer["output"]["source"])
        self.assertEqual(task["turn_id"], answer["output"]["turn_id"])
        listed = self.task_state(task["id"])["outputs"]
        self.assertEqual([REPORT], [o["path"] for o in listed])
        status, preview = self.http("GET", f"/api/tasks/{task['id']}/outputs/{listed[0]['id']}")
        self.assertEqual(200, status, preview)
        self.assertIn("Synthetic report", json.dumps(preview))

    def test_output_hidden_after_followup_turn(self):
        task = self.finished_task()
        self.write_report()
        self.assertEqual(200, self.attach(task)[0])
        self.assertEqual(1, len(self.task_state(task["id"])["outputs"]))
        after = self.followup(task)
        self.assertNotEqual(task["turn_id"], after["turn_id"])
        # The output stays stored on the old turn but is not listed for the new one.
        self.assertEqual([], after["outputs"])
        self.assertEqual(1, len(self.app.tasks[task["id"]]["outputs"]))

    # ---- deletion --------------------------------------------------------------------------------
    def test_delete_completed_claude_task_releases_session_and_hold(self):
        task = self.finished_task()
        self.assertIn(SESSION, self.app.owned_threads)
        self.assertTrue(task["can_delete"])
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delete",
                                   {"expected_version": task["deletion_version"], "confirmed": True})
        self.assertEqual((200, {"task_id": task["id"], "deleted": True}), (status, answer))
        self.assertNotIn(task["id"], [t["id"] for t in self.state()["tasks"]])
        self.assertNotIn(task["id"], self.app.tasks)
        self.assertNotIn(SESSION, self.app.owned_threads)  # the session id is free again
        self.assertEqual({}, self.app.runs)
        self.assertEqual({}, {k: v for k, v in self.app.pending.items() if v.get("task_id") == task["id"]})
        self.assertEqual([], [m for m in self.app.messages if m.get("task_id") == task["id"]])

    # ---- delivery --------------------------------------------------------------------------------
    def test_delivery_enforced_for_claude_without_ponytail(self):
        """Plan 5 Task 7 closed this gap (was test_delivery_refused_for_claude_today): a new Claude task is stamped
        with the not-applicable policy, so delivery is enforced and the first action (run checks) is offered once a
        check plan exists. A malformed request still starts nothing (route-level 409)."""
        task = self.finished_task()
        status, summary = self.http("GET", f"/api/tasks/{task['id']}/delivery")
        self.assertEqual(200, status)
        self.assertEqual(("awaiting_checks", "not_applicable"), (summary["status"], summary["ponytail"]))
        self.assertEqual(["check_plan_required"], summary["reason_codes"])
        self.assertFalse(any(summary["actions"].values()))  # no approved check plan yet
        body = {"expected_snapshot": "0" * 64, "operation_id": "1" * 32, "confirmed": True}
        for action, extra in (("checks", {"expected_plan_version": summary["plan_version"]}),
                              ("reviews", {"check_operation_id": "2" * 32})):
            with self.subTest(action=action):
                status, answer = self.http("POST", f"/api/tasks/{task['id']}/delivery/{action}", {**body, **extra})
                self.assertEqual(409, status)
                self.assertEqual("delivery_not_started", answer["code"])
                self.assertTrue(answer["not_started"])
        self.assertEqual({}, self.app.delivery_operations)
        # The provider refusal in _start_task is gone: an unprepared operation now fails delivery validation instead.
        data = {"project_id": task["project_id"], "title": "Delivery", "instruction": INSTRUCTION,
                "role": "qa_engineer"}
        with self.assertRaises(FileAccessError) as caught:
            self.app._start_task(data, delivery_operation={"id": "3" * 32})
        self.assertEqual(409, caught.exception.status)
        self.assertEqual({}, self.app.delivery_operations)

    def test_delivery_actions_available_for_claude(self):
        task = self.finished_task()
        _, summary = self.http("GET", f"/api/tasks/{task['id']}/delivery")
        self.assertNotEqual("not_enforced", summary["status"])

if __name__ == "__main__":
    unittest.main()

"""Pending approvals for Claude runs: create, review, answer and the automatic option (Plan 4, Task 5).

Evidence kind: fake-binary evidence, not a live run. Every run executes tests/fake_claude.py through the real argv
builder, the real ClaudeRun and the real loopback hook receiver; the run factory refuses any other executable, so
the real ``claude`` can never start here. Hook requests come either from the fake's hook scenarios (FAKE_CLAUDE_HOOK
with FAKE_CLAUDE_HOOK_GATE) or are posted by the test itself to the URL in the run's own settings file while a
fake run is live. Nothing here establishes how the real CLI behaves.

The sensitive-content scanner is replaced by a stand-in that reports a finding exactly when a runtime sentinel is
in the scanned bytes, so the tests do not depend on the local scanner installation.
"""
from copy import deepcopy
import http.client
import io
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import redirect_stderr
from unittest.mock import patch

from dashboard.approval_review import ApprovalReviews, ReviewError
from dashboard.backends import claude_hook
from dashboard.backends.base import ApprovalRequest, ProviderUnavailable
from dashboard.backends.claude import ClaudeBackend, RequestGone
from dashboard.backends.claude_runner import ClaudeRun
from dashboard.hook_receiver import HeldRequest, HookReceiver
from dashboard.ponytail_policy import PolicyError
from dashboard.project_files import SensitiveContentError
from dashboard.server import Dashboard, ProviderRefusal, make_server, now, unknown_cost
from tests.dashboard_key_harness import make_test_server
from dashboard.team import PROFILES
from dashboard.settings import SettingsStore
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
SESSION = "00000000-0000-4000-8000-000000005e55"
INSTRUCTION = "Implement the synthetic feature"
TERMINAL = {"completed", "failed", "interrupted", "unknown"}
ALLOW = claude_hook.allow_reply()
DENY = claude_hook.deny_reply()


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
        time.sleep(0.02)
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


def payload(tool_name="Bash", tool_input=None, **extra):
    body = {"hook_event_name": "PermissionRequest", "session_id": SESSION, "permission_mode": "default",
            "tool_name": tool_name, "tool_input": {"command": "echo synthetic"} if tool_input is None else tool_input}
    body.update(extra)
    return body


class Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.record = self.root / "record.jsonl"
        self.created, self.apps, self.receivers, self.servers, self.posts = [], [], [], [], []
        self.settings_seen = []
        self.secret = "SENTINEL_SECRET_" + uuid.uuid4().hex  # built at run time, never stored in the repo
        scanner = patch("dashboard.server.scan_preview", side_effect=self.scan)
        scanner.start()
        self.addCleanup(scanner.stop)
        self.app = self.make_app()

    def tearDown(self):
        for app in self.apps:
            app.close()
        for run in self.created:
            run.close()
        for thread in self.posts:
            thread.join(5)
            self.assertFalse(thread.is_alive(), "a hook post was left waiting")
        for server, thread in self.servers:
            server.shutdown()
            thread.join(3)
            server.server_close()
        self.assertTrue(wait_for(lambda: not stray_fakes(), 5), "a fake_claude process was left running")
        for receiver in self.receivers:
            self.assertTrue(receiver._thread is None or not receiver._thread.is_alive(), "receiver thread left")
        for app in self.apps:
            runs = app.state_dir / "claude-runs"
            self.assertEqual([], sorted(runs.iterdir()) if runs.is_dir() else [], "a settings file was left")
            self.assertEqual({}, app.hook_runs)
        self.temp.cleanup()

    # ---- harness ---------------------------------------------------------------------------------
    def scan(self, data):
        if self.secret.encode() in bytes(data):
            raise SensitiveContentError()

    def factory(self, argv, **kwargs):
        if argv[0] != str(FAKE):
            raise AssertionError("refusing to start anything but the fake claude")
        path = Path(argv[argv.index("--settings") + 1])
        self.settings_seen.append((path, json.loads(path.read_text()), os.stat(path).st_mode & 0o777))
        run = ClaudeRun(argv, sigint_wait=2.0, term_wait=1.0, **kwargs)
        self.created.append(run)
        return run

    def receiver_factory(self, *args, **kwargs):
        receiver = HookReceiver(*args, poll_interval=0.05, **kwargs)
        self.receivers.append(receiver)
        return receiver

    def make_app(self, wait=None, **extra):
        backend = ClaudeBackend(claude_path=str(FAKE), runner=probe_runner)
        kwargs = dict(policy_provider=RaisingPolicy(), backend=backend, claude_run_factory=self.factory,
                      claude_env_extra=dict(FAKE_CLAUDE_FIXTURE="success"),
                      hook_receiver_factory=self.receiver_factory)
        kwargs.update(extra)
        app = Dashboard(self.root / ("state" if not self.apps else "state%d" % len(self.apps)), **kwargs)
        self.apps.append(app)
        app.settings = SettingsStore(self.root, config_path=self.root / "settings.toml")
        if wait is not None:
            self.set_wait(app, wait)
        app.start()
        self.assertTrue(wait_for(lambda: app.connection["status"] == "connected"))
        return app

    def set_wait(self, app, wait):
        config = app.settings.load()
        config["claude_approval_wait_seconds"] = wait
        app.save_settings(config)

    def mode(self, value, app=None):
        app = app or self.app
        config = app.settings.load()
        config["project_approval_modes"] = {self.project_id: value}
        app.save_settings(config)

    def project(self, app=None):
        app = app or self.app
        path = self.root / "project"
        path.mkdir(exist_ok=True)
        project = app.add_project({"name": "project", "path": str(path)})
        self.project_id = project["id"]
        return project

    def start(self, fixture="success", app=None, **extra):
        app = app or self.app
        app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, FAKE_CLAUDE_RECORD=str(self.record), **extra)
        project = self.project(app) if not app.projects else next(iter(app.projects.values()))
        self.project_id = project["id"]
        return app.start_task({"project_id": project["id"], "title": "Synthetic run", "instruction": INSTRUCTION,
                               "role": "backend_developer"})

    def live(self, app=None):
        """A run that stays live (running, session and turn known) until it is stopped."""
        app = app or self.app
        task = self.start("no_result", app=app, FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.assertTrue(wait_for(lambda: app.tasks[task["id"]]["status"] == "running"
                                 and app.tasks[task["id"]]["claude"]["session_id"] == SESSION))
        return task["id"]

    def url(self, index=-1):
        return self.settings_seen[index][1]["hooks"]["PermissionRequest"][0]["hooks"][0]["url"]

    def post(self, body, index=-1, raw=False):
        """POST a hook request on a thread; returns the dict that receives {"status", "body"}."""
        out = {}
        url = self.url(index)
        port, path = int(url.split(":")[2].split("/")[0]), "/" + url.split("/", 3)[3]
        data = body if raw else json.dumps(body).encode()

        def run():
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
                reply = conn.getresponse()
                out.update(status=reply.status, body=reply.read())
                conn.close()
            except Exception as error:  # noqa: BLE001
                out["error"] = type(error).__name__
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.posts.append(thread)
        out["thread"] = thread
        return out

    def reply(self, out, seconds=10):
        out["thread"].join(seconds)
        self.assertFalse(out["thread"].is_alive(), "the hook request is still held")
        return out.get("status"), out.get("body")

    def pending(self, task_id, count=1, app=None):
        app = app or self.app
        self.assertTrue(wait_for(lambda: len(self._pending(app, task_id)) >= count), "no pending approval")
        return self._pending(app, task_id)

    @staticmethod
    def _pending(app, task_id):
        with app.lock:
            return [a for a in app.approvals.values()
                    if a["task_id"] == task_id and a["status"] == "pending" and a["kind"] == "tool_call"]

    def held(self, approval, app=None):
        app = app or self.app
        with app.lock:
            return app.pending[approval["id"]]["held"]

    def review_accept(self, approval, app=None):
        app = app or self.app
        review = app.review_approval(approval["id"])
        return review, app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})

    def decline(self, approval, app=None):
        return (app or self.app).respond_approval(approval["id"], {"decision": "decline"})

    def stop_live(self, task_id, app=None):
        app = app or self.app
        app.interrupt(task_id, {})
        self.assertTrue(wait_for(lambda: app.tasks[task_id]["status"] in TERMINAL and task_id not in app.runs))

    def hook_record(self):
        lines = [json.loads(x) for x in self.record.read_text().splitlines() if x.strip()]
        return [x["hook"] for x in lines if "hook" in x]

    def invocations(self):
        lines = [json.loads(x) for x in self.record.read_text().splitlines() if x.strip()]
        return [x for x in lines if "hook" not in x]


class CreateReviewAnswer(Harness):
    def test_request_creates_pending_tool_call_approval_and_waiting_status(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        self.assertEqual(("tool_call", "PermissionRequest", "Kira Voss (Backend Developer) via Claude Code",
                          "A tool call requires approval", ["decline"], "pending"),
                         (approval["kind"], approval["native_method"], approval["requester"], approval["summary"],
                          approval["available_decisions"], approval["status"]))
        self.assertNotIn("Codex", json.dumps(approval))
        self.assertEqual("waiting_approval", self.app.tasks[task_id]["status"])
        with self.app.lock:
            binding = self.app.pending[approval["id"]]["binding"]
        self.assertEqual((SESSION, "turn-1"), binding[:2])
        self.assertRegex(binding[2], r"\A[0-9a-f]{32}\Z")
        shown = next(a for a in self.app.snapshot()["approvals"] if a["id"] == approval["id"])
        self.assertFalse(shown["can_request_alternative"])
        self.assertEqual("Kira Voss (Backend Developer) via Claude Code", shown["requester"])
        self.assertNotIn("status", out)  # still held
        # a subagent's request names its agent_type
        sub = self.post(payload(agent_type="synthetic-worker", agent_id="agent-synthetic-1"))
        second = next(a for a in self.pending(task_id, 2) if a["id"] != approval["id"])
        self.assertEqual("a subagent via Claude Code", second["requester"])  # unknown agent_type: never echoed
        self.decline(approval)
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("waiting_approval", self.app.tasks[task_id]["status"])  # the second still waits
        self.decline(second)
        self.assertEqual((200, DENY), self.reply(sub))
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        self.stop_live(task_id)

    def test_review_then_accept_resumes_same_run_and_tool_runs_once(self):
        gate = self.root / "gate"
        task = self.start("success", FAKE_CLAUDE_HOOK="ask_allowed", FAKE_CLAUDE_HOOK_GATE=str(gate))
        task_id = task["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["claude"]["session_id"] == SESSION))
        pid = self.app.tasks[task_id]["claude"]["pid"] or self.created[-1].pid
        gate.write_text("go")
        [approval] = self.pending(task_id)
        review, resolved = self.review_accept(approval)
        self.assertEqual({"tool_name": "Bash", "tool_input": {"command": "echo SENTINEL_HOOK_INPUT"}}, review["context"])
        self.assertEqual(("resolved", "accept", "human"),
                         (resolved["status"], resolved["decision"]["value"], resolved["decision"]["source"]))
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL and task_id not in self.app.runs))
        self.assertEqual("completed", self.app.tasks[task_id]["status"])
        self.assertEqual([{"scenario": "ask_allowed", "calls": 1, "told": ["allow"]}], self.hook_record())
        self.assertEqual(1, len(self.invocations()))  # the same process continued; nothing was relaunched
        self.assertEqual(pid, self.created[-1].pid)
        with self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_unavailable", caught.exception.code)

    def test_decline_denies_and_run_continues(self):
        gate = self.root / "gate"
        task_id = self.start("success", FAKE_CLAUDE_HOOK="ask_declined", FAKE_CLAUDE_HOOK_GATE=str(gate))["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["claude"]["session_id"] == SESSION))
        gate.write_text("go")
        [approval] = self.pending(task_id)
        resolved = self.decline(approval)
        self.assertEqual(("resolved", "decline", "human"),
                         (resolved["status"], resolved["decision"]["value"], resolved["decision"]["source"]))
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] in TERMINAL and task_id not in self.app.runs))
        task = self.app.tasks[task_id]
        self.assertNotIn(task["status"], {"interrupted", "failed"})  # the run went on to its own end
        self.assertEqual([{"scenario": "ask_declined", "calls": 1, "told": ["deny"]}], self.hook_record())
        self.assertGreaterEqual(task["claude"]["denied_count"], 1)

    def test_accept_without_review_receipt_refused(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        for data in ({"decision": "accept", "review_id": uuid.uuid4().hex}, {"decision": "accept", "review_id": None}):
            with self.assertRaises(ReviewError) as caught:
                self.app.respond_approval(approval["id"], data)
            self.assertEqual("receipt_required", caught.exception.code)
        with self.assertRaises(ValueError):
            self.app.respond_approval(approval["id"], {"decision": "accept"})
        with self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "cancel"})
        self.assertEqual("cancel_not_offered", caught.exception.code)
        for decision in ("acceptForSession", "allow", None):
            with self.assertRaises(ValueError):
                self.app.respond_approval(approval["id"], {"decision": decision})
        with self.assertRaises(ReviewError) as caught:
            self.app.request_approval_alternative(approval["id"], {"text": "try something else"})
        self.assertEqual("alternative_unavailable", caught.exception.code)
        review = self.app.review_approval(approval["id"])
        self.assertEqual(["decline", "accept"], approval["available_decisions"])
        with self.assertRaises(ReviewError):
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"],
                                                      "sensitive_confirmed": True})
        with self.assertRaises(ReviewError):  # the automatic route never accepts a request that is not eligible
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]},
                                      _source="project_policy")
        self.assertIsNone(self.held(approval).decision)
        self.assertNotIn("status", out)
        self.decline(approval)
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_accept_after_context_changed_refused(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        review = self.app.review_approval(approval["id"])
        with self.app.lock:
            self.app.pending[approval["id"]]["params"]["tool_input"]["command"] = "echo something else"
        with self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_changed", caught.exception.code)
        self.assertIsNone(self.held(approval).decision)
        self.assertEqual("pending", approval["status"])
        self.decline(approval)
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_two_concurrent_requests_two_approvals_accept_one_denies_other_untouched(self):
        task_id = self.live()
        first_out, second_out = self.post(payload()), self.post(payload())  # identical requests, two approvals
        first, second = self.pending(task_id, 2)
        with self.app.lock:
            bindings = {self.app.pending[a["id"]]["binding"] for a in (first, second)}
        self.assertEqual(2, len(bindings))
        review_second = self.app.review_approval(second["id"])
        with self.assertRaises(ReviewError):  # one approval's receipt never answers the other
            self.app.respond_approval(first["id"], {"decision": "accept", "review_id": review_second["review_id"]})
        _, resolved = self.review_accept(first)
        self.assertEqual("resolved", resolved["status"])
        held_first = first_out if self.held_reply_is(first_out, ALLOW) else second_out
        other_out = second_out if held_first is first_out else first_out
        self.assertEqual((200, ALLOW), self.reply(held_first))
        self.assertEqual("pending", second["status"])
        self.assertIsNone(self.held(second).decision)
        self.assertNotIn("status", other_out)
        self.assertEqual("waiting_approval", self.app.tasks[task_id]["status"])
        self.decline(second)
        self.assertEqual((200, DENY), self.reply(other_out))
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        self.stop_live(task_id)

    def held_reply_is(self, out, body, seconds=5):
        out["thread"].join(seconds)
        return out.get("body") == body

    def test_accept_after_connection_closed_is_request_unavailable(self):
        task_id = self.live()
        url = self.url()
        port, path = int(url.split(":")[2].split("/")[0]), "/" + url.split("/", 3)[3]
        body = json.dumps(payload()).encode()
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(("POST %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                      "Content-Length: %d\r\n\r\n" % (path, port, len(body))).encode() + body)
        [approval] = self.pending(task_id)
        review = self.app.review_approval(approval["id"])
        held = self.held(approval)
        sock.close()  # hook timeout or killed CLI: the held connection is gone
        self.assertTrue(wait_for(lambda: approval["status"] != "pending", 5))
        self.assertEqual(("unavailable", []), (approval["status"], approval["available_decisions"]))
        self.assertEqual("deny", held.decision)
        self.assertTrue(held.closed)
        with self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_unavailable", caught.exception.code)
        with self.assertRaises(ReviewError):
            self.app.review_approval(approval["id"])
        self.assertEqual("deny", held.decision)
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        shown = next(a for a in self.app.snapshot()["approvals"] if a["id"] == approval["id"])
        self.assertEqual(("unavailable", []), (shown["status"], shown["available_decisions"]))
        # the run ending with a request pending: the held request is answered deny, the approval unavailable
        out = self.post(payload())
        [late] = self.pending(task_id)
        self.stop_live(task_id)
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("unavailable", late["status"])

    def test_requester_names_only_known_roles_never_the_hook_agent_type(self):
        task_id = self.live()
        token_shaped = "tok_" + uuid.uuid4().hex + uuid.uuid4().hex[:24]
        known = "security_reviewer"
        self.assertIn(known, self.app.roles)
        cases = (("security_reviewer_APPROVED", "a subagent via Claude Code"),
                 (token_shaped, "a subagent via Claude Code"),
                 ("Kira_Voss", "a subagent via Claude Code"),
                 (known, PROFILES[known][0] + " (" + self.app.roles[known]["label"] + ") via Claude Code"),
                 ("backend_developer", "Kira Voss (Backend Developer) via Claude Code"))
        outs = []
        for index, (agent_type, _) in enumerate(cases):
            outs.append(self.post(payload(agent_type=agent_type, agent_id="agent-synthetic-%d" % index)))
            self.pending(task_id, index + 1)
        with self.app.lock:
            shown = sorted((a["created_at"], a["id"], a["requester"]) for a in self.app.approvals.values()
                           if a["task_id"] == task_id)
        requesters = [self.app.approvals[x[1]]["requester"] for x in shown]
        self.assertEqual(sorted(expected for _, expected in cases), sorted(requesters))
        dumped = json.dumps(self.app.snapshot())
        for spoof in ("security_reviewer_APPROVED", token_shaped, "Kira_Voss"):
            self.assertNotIn(spoof, dumped)
        for approval in self._pending(self.app, task_id):
            self.decline(approval)
        for out in outs:
            self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_closed_hook_connection_cannot_be_accepted(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        review = self.app.review_approval(approval["id"])
        held = self.held(approval)
        with held._lock:
            held._closed = True  # the connection is seen closed before the deny is recorded
        self.assertIsNone(held.decision)
        with self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_unavailable", caught.exception.code)
        self.assertNotEqual("allow", held.decision)
        held.resolve("deny")
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_finish_approvals_releases_the_held_request_with_deny(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        held = self.held(approval)
        with self.app.lock:
            self.app._finish_approvals(self.app.tasks[task_id])  # what run exit and turn completion call
            self.assertEqual("deny", held.decision)  # at once, before the token is unregistered
        self.assertEqual(("unavailable", []), (approval["status"], approval["available_decisions"]))
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_answer_racing_the_end_of_the_hold_is_unavailable_and_allows_nothing(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        review = self.app.review_approval(approval["id"])
        held = self.held(approval)
        real = self.app.backend.answer_approval

        def late(request, decision):
            held.resolve("deny")  # the hold ends between the last liveness check and the answer
            return real(request, decision)
        with patch.object(self.app.backend, "answer_approval", side_effect=late):
            with self.assertRaises(ReviewError) as caught:
                self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_unavailable", caught.exception.code)
        self.assertEqual("unavailable", approval["status"])
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        self.stop_live(task_id)

    def test_secret_in_tool_input_needs_sensitive_confirmation_and_is_absent_from_logs_snapshot_store(self):
        server = make_test_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(lambda: (root.removeHandler(handler), root.setLevel(previous)))
        errors = io.StringIO()
        with redirect_stderr(errors):
            task_id = self.live()
            out = self.post(payload(tool_input={"command": "deploy --token " + self.secret}))
            [approval] = self.pending(task_id)
            with self.assertRaises(ReviewError) as caught:
                self.app.review_approval(approval["id"])
            self.assertEqual("scanner_blocked", caught.exception.code)
            public = self.app.record_review_failure(approval["id"], caught.exception)
            self.assertTrue(public["can_sensitive_review"])
            with self.assertRaises(ReviewError):
                self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": uuid.uuid4().hex})
            review = self.app.sensitive_review_approval(approval["id"], {"confirmed": True})
            self.assertIn(self.secret, review["context"]["tool_input"]["command"])  # only the review path shows it
            with self.assertRaises(ReviewError) as caught:
                self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
            self.assertEqual("sensitive_confirmation_required", caught.exception.code)
            self.assertIsNone(self.held(approval).decision)
            resolved = self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"],
                                                                  "sensitive_confirmed": True})
            self.assertEqual("human_sensitive_review", resolved["decision"]["source"])
            self.assertEqual((200, ALLOW), self.reply(out))
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/state")
            state = connection.getresponse().read().decode()
            connection.close()
            snapshot = json.dumps(self.app.snapshot())
            self.stop_live(task_id)
        self.assertIn(approval["id"], state)
        stored = b"".join(p.read_bytes() for p in self.app.state_dir.rglob("*") if p.is_file())
        for where, text in (("state", state), ("snapshot", snapshot), ("logs", captured.getvalue()),
                            ("stderr", errors.getvalue()), ("diagnostics", json.dumps(self.app.tasks[task_id]))):
            self.assertNotIn(self.secret, text, where)
            self.assertNotIn("SENTINEL_SECRET_", text, where)
        self.assertNotIn(self.secret.encode(), stored)
        self.assertNotIn(b"deploy --token", stored)


    def test_accept_losing_the_race_with_expiry_is_recorded_as_expired(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        review = self.app.review_approval(approval["id"])
        held = self.held(approval)
        original = self.app.backend.answer_approval

        def expire_first(request, decision):  # the wait runs out after the last liveness check, before the answer
            with held._lock:
                held._expired = True
            held.resolve("deny")
            return original(request, decision)
        with patch.object(self.app.backend, "answer_approval", side_effect=expire_first), \
                self.assertRaises(ReviewError) as caught:
            self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual("request_unavailable", caught.exception.code)
        self.assertEqual(("unavailable", "expired"), (approval["status"], approval["unavailable_reason"]))
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

class Automatic(Harness):
    def wait_settled(self, approval, seconds=10):
        self.assertTrue(wait_for(lambda: approval["status"] != "pending" or approval.get("review_failure"), seconds),
                        "automatic review did not settle")

    def test_manual_project_never_auto_accepts_tool_call(self):
        task_id = self.live()
        self.mode("manual")
        outs = [self.post(payload(name, tool_input)) for name, tool_input in
                (("Bash", {"command": "echo synthetic"}), ("Write", {"file_path": "/synthetic/a.txt", "content": "x"}))]
        approvals = self.pending(task_id, 2)
        time.sleep(0.5)
        for approval in approvals:
            self.assertEqual("pending", approval["status"])
            self.assertNotIn("review_failure", approval)
            self.assertIsNone(self.held(approval).decision)
            with self.app.lock:
                self.assertNotIn("automatic_eligible", self.app.pending[approval["id"]])
        for approval in approvals:
            self.decline(approval)
        for out in outs:
            self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_automatic_project_accepts_plain_bash_write_edit_once_as_project_policy(self):
        task_id = self.live()
        self.mode("automatic")
        root = self.app.projects[self.project_id]["path"]
        cases = (("Bash", {"command": "echo synthetic"}),
                 ("Write", {"file_path": root + "/a.txt", "content": "synthetic"}),
                 ("Edit", {"file_path": "sub/a.txt", "old_string": "a", "new_string": "b"}),
                 ("NotebookEdit", {"notebook_path": root + "/n.ipynb", "new_source": "print(1)"}))
        for name, tool_input in cases:
            with self.subTest(name):
                out = self.post(payload(name, tool_input))
                self.assertEqual((200, ALLOW), self.reply(out))
        with self.app.lock:
            done = [a for a in self.app.approvals.values() if a["task_id"] == task_id]
        self.assertEqual(4, len(done))
        for approval in done:
            self.assertEqual(("resolved", "accept", "project_policy"),
                             (approval["status"], approval["decision"]["value"], approval["decision"]["source"]))
            with self.assertRaises(ReviewError):
                self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": uuid.uuid4().hex},
                                          _source="project_policy")
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        self.stop_live(task_id)

    def test_automatic_mode_leaves_unconfined_file_paths_for_the_owner(self):
        task_id = self.live()
        self.mode("automatic")
        root = Path(self.app.projects[self.project_id]["path"])
        outside = self.root / "outside"
        outside.mkdir()
        (root / "link").symlink_to(outside)
        (root / ".git").mkdir(exist_ok=True)
        (root / "gitlink").symlink_to(root / ".git")
        cases = [("Write", {"file_path": str(outside / "a.txt"), "content": "x"}),
                 ("Write", {"file_path": "../outside/a.txt", "content": "x"}),
                 ("Write", {"file_path": "link/a.txt", "content": "x"}),
                 ("Write", {"file_path": str(root / ".git" / "hooks" / "pre-commit"), "content": "x"}),
                 ("Edit", {"file_path": ".claude/settings.json", "old_string": "a", "new_string": "b"}),
                 ("Edit", {"file_path": "x/.LOCAL/state", "old_string": "a", "new_string": "b"}),
                 ("Write", {"file_path": "gitlink/config", "content": "x"}),
                 ("NotebookEdit", {"notebook_path": str(outside / "n.ipynb"), "new_source": "1"}),
                 ("NotebookEdit", {"new_source": "1"}),
                 ("Write", {"file_path": 7, "content": "x"}),
                 ("Write", {"file_path": "", "content": "x"}),
                 ("Write", {"file_path": str(root), "content": "x"})]
        outs = [self.post(payload(name, tool_input)) for name, tool_input in cases]
        approvals = self.pending(task_id, len(cases))
        time.sleep(0.5)
        for approval in approvals:
            self.assertEqual("pending", approval["status"])
            self.assertIsNone(self.held(approval).decision)
            with self.app.lock:
                self.assertNotIn("automatic_eligible", self.app.pending[approval["id"]])
        # manual review still works for such a call
        for approval in approvals:
            self.decline(approval)
        for out in outs:
            self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_automatic_mode_never_answers_a_claude_delivery_run(self):
        """Plan 5 Task 7: a Claude checks or review run is never answered by project policy; the owner decides."""
        task_id = self.live()
        with self.app.lock:  # the live run stands in for a delivery runner (only the marker matters here)
            self.app.tasks[task_id]["delivery_context"] = {"operation_id": "0" * 32, "subject_id": "1" * 32,
                                                           "kind": "checks"}
        self.mode("automatic")
        out = self.post(payload("Bash", {"command": "echo synthetic"}))
        [approval] = self.pending(task_id)
        time.sleep(0.5)
        self.assertEqual("pending", approval["status"])
        self.assertIsNone(self.held(approval).decision)
        with self.app.lock:
            self.assertNotIn("automatic_eligible", self.app.pending[approval["id"]])
        self.decline(approval)
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_manual_mode_unchanged_by_path_confinement(self):
        task_id = self.live()
        self.mode("manual")
        out = self.post(payload("Write", {"file_path": "/synthetic/a.txt", "content": "x"}))
        [approval] = self.pending(task_id)
        self.assertEqual("pending", approval["status"])
        self.decline(approval)
        self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def test_automatic_accept_refused_when_task_becomes_recovery_manual_before_respond(self):
        task_id = self.live()
        entered, release = threading.Event(), threading.Event()

        def blocking(data):
            entered.set()
            self.assertTrue(release.wait(10))
            return self.scan(data)
        self.mode("automatic")
        with patch("dashboard.server.scan_preview", side_effect=blocking):
            out = self.post(payload())
            [approval] = self.pending(task_id)
            self.assertTrue(entered.wait(10))
            with self.app.lock:
                self.app.tasks[task_id]["recovery_manual"] = True
            release.set()
            self.wait_settled(approval)
        time.sleep(0.3)
        self.assertEqual("pending", approval["status"])
        self.assertEqual("project_policy_changed", approval["review_failure"]["code"])
        self.assertIsNone(self.held(approval).decision)
        with self.app.lock:
            self.app.tasks[task_id].pop("recovery_manual")
        self.stop_live(task_id)
        self.assertEqual((200, DENY), self.reply(out))

    def test_automatic_project_leaves_sensitive_mcp_web_and_unknown_tools_for_owner(self):
        task_id = self.live()
        self.mode("automatic")
        cases = [("Bash", {"command": "echo " + self.secret}),
                 ("Write", {"file_path": "a.txt", "content": self.secret})]
        cases += [(name, {"value": "synthetic"}) for name in
                  ("mcp__synthetic__tool", "WebFetch", "WebSearch", "Agent", "Task", "Read", "SyntheticUnknown",
                   "bash", "BASH", "Bash.", "Bash:", "Bash_", "NotebookEditX", "Edits")]
        outs = [self.post(payload(name, tool_input)) for name, tool_input in cases]
        approvals = self.pending(task_id, len(cases))
        for approval in approvals:
            with self.app.lock:
                name = self.app.pending[approval["id"]]["params"]["tool_name"]
            if name in {"Bash", "Write"}:  # the secret-shaped input: the automatic review stops at the scanner
                self.wait_settled(approval)
                self.assertEqual("scanner_blocked", approval["review_failure"]["code"])
        time.sleep(0.5)
        for approval in approvals:
            self.assertEqual("pending", approval["status"])
            self.assertIsNone(self.held(approval).decision)
        for out in outs:
            self.assertNotIn("status", out)
        for approval in approvals:
            self.decline(approval)
        for out in outs:
            self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)

    def blocked_automatic(self, change):
        """Start an automatic review whose scan blocks, apply change() while it is in flight, then release it."""
        entered, release = threading.Event(), threading.Event()

        def blocking(data):
            entered.set()
            self.assertTrue(release.wait(10))
            return self.scan(data)
        task_id = self.live()
        self.mode("automatic")
        with patch("dashboard.server.scan_preview", side_effect=blocking):
            out = self.post(payload())
            [approval] = self.pending(task_id)
            held = self.held(approval)
            self.assertTrue(entered.wait(10), "the automatic review did not start")
            change()
            release.set()
            self.wait_settled(approval)
        time.sleep(0.3)
        self.assertEqual("pending", approval["status"], approval.get("decision"))
        self.assertEqual("project_policy_changed", approval["review_failure"]["code"])
        self.assertIsNone(held.decision)
        self.assertNotIn("status", out)
        self.stop_live(task_id)  # the run ends: the held request is answered deny, never allow
        self.assertEqual((200, DENY), self.reply(out))
        self.assertEqual("deny", held.decision)
        self.assertEqual("unavailable", approval["status"])

    def test_switch_to_manual_revokes_an_in_flight_automatic_accept(self):
        self.blocked_automatic(lambda: self.mode("manual"))

    def test_revoke_and_re_enable_during_review_still_revokes(self):
        # mode is automatic again at answer time; only the policy version shows the revocation
        self.blocked_automatic(lambda: (self.mode("manual"), self.mode("automatic")))

    def test_manual_mode_written_without_a_version_bump_still_revokes(self):
        # the settings file says manual but no in-dashboard change bumped the policy version: the answer-time
        # mode check alone must refuse
        def change():
            config = self.app.settings.load()
            config["project_approval_modes"] = {self.project_id: "manual"}
            self.app.settings.save(config)
        self.blocked_automatic(change)

    def test_automatic_mode_change_applies_only_to_later_requests(self):
        task_id = self.live()
        before_out = self.post(payload())
        [before] = self.pending(task_id)
        self.mode("automatic")
        during = self.post(payload())
        self.assertEqual((200, ALLOW), self.reply(during))
        time.sleep(0.3)
        self.assertEqual("pending", before["status"])
        self.assertIsNone(self.held(before).decision)
        with self.app.lock:
            self.assertNotIn("automatic_eligible", self.app.pending[before["id"]])
        self.mode("manual")
        after_out = self.post(payload())
        after = next(a for a in self.pending(task_id, 2) if a["id"] != before["id"])
        time.sleep(0.5)
        self.assertEqual("pending", after["status"])
        self.assertIsNone(self.held(after).decision)
        for approval, out in ((before, before_out), (after, after_out)):
            self.decline(approval)
            self.assertEqual((200, DENY), self.reply(out))
        self.stop_live(task_id)


class LaunchWiring(Harness):
    def test_hook_timeout_in_file_is_wait_plus_margin_at_launch(self):
        self.set_wait(self.app, 120)
        task_id = self.live()
        path, data, mode = self.settings_seen[-1]
        hook = data["hooks"]["PermissionRequest"][0]["hooks"][0]
        self.assertEqual({"hooks"}, set(data))
        self.assertEqual(("http", 180), (hook["type"], hook["timeout"]))
        self.assertEqual(0o600, mode)
        self.assertEqual(Path(os.path.realpath(self.app.state_dir)) / "claude-runs", Path(os.path.realpath(path.parent)))
        self.assertTrue(path.exists())
        self.stop_live(task_id)
        self.assertTrue(wait_for(lambda: not path.exists(), 5), "the settings file outlived its run")
        other = self.make_app(wait=3600)
        task = self.start("success", app=other)
        self.assertTrue(wait_for(lambda: other.tasks[task["id"]]["status"] in TERMINAL and task["id"] not in other.runs))
        self.assertEqual(3660, self.settings_seen[-1][1]["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"])

    def test_changed_setting_does_not_lengthen_a_live_runs_wait(self):
        self.set_wait(self.app, 120)
        task_id = self.live()
        timeout_before = self.settings_seen[-1][1]["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"]
        with self.app.lock:
            [key] = [k for k, e in self.app.hook_runs.items() if e["task_id"] == task_id]
        self.set_wait(self.app, 3600)
        self.assertEqual(120, self.app._claude_hook_wait(key))  # never beyond the launch-time wait
        self.assertEqual(120, self.receivers[-1]._runs[key][1])
        self.set_wait(self.app, 60)
        self.assertEqual(60, self.app._claude_hook_wait(key))  # a lower current setting applies
        self.assertEqual(timeout_before, json.loads(self.settings_seen[-1][0].read_text())
                         ["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"])
        self.stop_live(task_id)
        # The hook registration is released just after the exit is applied (outside the lock): wait for it.
        self.assertTrue(wait_for(lambda: key not in self.app.hook_runs), "the run's hook registration was not released")
        with self.assertRaises(LookupError):
            self.app._claude_hook_wait(key)

    def assert_launch_failed_closed(self, app, task_id):
        self.assertTrue(wait_for(lambda: app.tasks[task_id]["status"] == "failed" and task_id not in app.launching_tasks))
        self.assertIn("claude_launch_invalid", [d["code"] for d in app.tasks[task_id]["diagnostics"]])
        self.assertEqual([], self.created)
        self.assertEqual({}, app.hook_runs)
        runs = app.state_dir / "claude-runs"
        self.assertEqual([], [p for p in runs.iterdir() if p.is_file()] if runs.is_dir() else [])
        for receiver in self.receivers:
            self.assertEqual({}, receiver._runs)

    def test_unreadable_or_invalid_wait_setting_fails_the_launch_closed(self):
        (self.root / "settings.toml").write_text("claude_approval_wait_seconds = 5\n")
        self.assert_launch_failed_closed(self.app, self.start("success")["id"])
        self.assertEqual([], self.receivers)  # nothing was even started

    def test_receiver_start_failure_fails_the_launch_closed(self):
        def broken(*_args, **_kwargs):
            raise OSError("synthetic bind failure")
        self.app.hook_receiver_factory = broken
        self.assert_launch_failed_closed(self.app, self.start("success")["id"])

    def test_settings_file_write_failure_fails_the_launch_closed(self):
        self.app.state_dir.mkdir(parents=True, exist_ok=True)
        (self.app.state_dir / "claude-runs").write_text("not a folder")
        self.assert_launch_failed_closed(self.app, self.start("success")["id"])
        (self.app.state_dir / "claude-runs").unlink()

    def test_symlinked_runs_folder_is_refused(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.app.state_dir.mkdir(parents=True, exist_ok=True)
        (self.app.state_dir / "claude-runs").symlink_to(elsewhere)
        self.assert_launch_failed_closed(self.app, self.start("success")["id"])
        self.assertEqual([], list(elsewhere.iterdir()))
        (self.app.state_dir / "claude-runs").unlink()
        self.assertFalse(self.app._settings_path_ok(elsewhere / "run-0123456789abcdef01234567.json"))

    def test_invalid_requests_are_denied_and_never_queued(self):
        task_id = self.live()
        # Malformed requests are refused by the parser and leave the run alone.
        for body in (payload(tool_name="Bash\n"), payload(tool_name="Bash "), payload(permission_mode="default\n")):
            with self.subTest(body=body):
                self.assertEqual((200, DENY), self.reply(self.post(body)))
        self.assertEqual("running", self.app.tasks[task_id]["status"])
        # A contradicting request is denied; the first one also stops the run and fails it (Task 6).
        for body in (payload(permission_mode="acceptEdits"), payload(permission_mode="bypassPermissions"),
                     payload(permission_mode=None), {k: v for k, v in payload().items() if k != "permission_mode"},
                     payload(session_id="00000000-0000-4000-8000-0000000007e5")):
            with self.subTest(body=body):
                self.assertEqual((200, DENY), self.reply(self.post(body)))
        self.assertEqual([], [a for a in self.app.approvals.values() if a["task_id"] == task_id])
        self.assertEqual("failed", self.app.tasks[task_id]["status"])
        self.assertEqual(["claude_permission_mode"], [d["code"] for d in self.app.tasks[task_id]["diagnostics"]])
        self.assertTrue(wait_for(lambda: task_id not in self.app.runs, 15))

    def test_request_before_the_session_is_known_is_denied(self):
        gate = self.root / "never"
        task = self.start("success", FAKE_CLAUDE_HOOK="ask_allowed")  # no gate: posts before its init line
        self.assertTrue(wait_for(lambda: self.app.tasks[task["id"]]["status"] in TERMINAL
                                 and task["id"] not in self.app.runs))
        self.assertEqual([{"scenario": "ask_allowed", "calls": 1, "told": ["deny"]}], self.hook_record())
        self.assertEqual([], [a for a in self.app.approvals.values() if a["task_id"] == task["id"]])
        self.assertFalse(gate.exists())

    def test_close_with_a_pending_request_denies_and_stops_the_receiver(self):
        task_id = self.live()
        out = self.post(payload())
        [approval] = self.pending(task_id)
        receiver = self.receivers[-1]
        self.app.close()
        self.assertEqual((200, DENY), self.reply(out))
        self.assertFalse(receiver._thread.is_alive())
        self.assertIsNone(self.app.hook_receiver)
        with self.assertRaises(RuntimeError):
            self.app._hook_receiver()


class ProviderGuardAndCodex(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_claude_approval_refused_under_codex_deployment_and_vice_versa(self):
        claude = Dashboard(self.root / "state", policy_provider=RaisingPolicy(),
                           backend=ClaudeBackend(claude_path=str(FAKE), runner=probe_runner))
        project = claude.add_project({"name": "p", "path": str(self.root)})
        task = {"id": "c" * 32, "project_id": project["id"], "title": "t", "role": "backend_developer",
                "model": "opus", "reasoning": "high", "status": "completed", "thread_id": SESSION,
                "turn_id": "turn-1", "plan": [], "usage": None, "cost": None, "error": None, "provider": "claude",
                "created_at": now(), "updated_at": now()}
        approval = {"id": "d" * 32, "task_id": task["id"], "kind": "tool_call", "native_method": "PermissionRequest",
                    "requester": "Kira Voss (Backend Developer) via Claude Code", "summary": "A tool call requires approval",
                    "status": "pending", "created_at": now(), "available_decisions": ["decline"]}
        claude.store.put("task", task)
        claude.store.put("approval", approval)
        codex_task = dict(task, id="e" * 32, provider="codex")
        codex_approval = dict(approval, id="f" * 32, task_id=codex_task["id"], kind="command")
        claude.store.put("task", codex_task)
        claude.store.put("approval", codex_approval)
        claude.close()
        codex = Dashboard(self.root / "state", policy_provider=SyntheticPolicy())
        try:
            for call in (lambda: codex.respond_approval(approval["id"], {"decision": "decline"}),
                         lambda: codex.review_approval(approval["id"]),
                         lambda: codex.sensitive_review_approval(approval["id"], {"confirmed": True})):
                with self.assertRaises(ProviderRefusal):
                    call()
            self.assertIsNone(codex.hook_receiver)  # a Codex deployment never starts the receiver
        finally:
            codex.close()
        claude = Dashboard(self.root / "state", policy_provider=RaisingPolicy(),
                           backend=ClaudeBackend(claude_path=str(FAKE), runner=probe_runner))
        try:
            for call in (lambda: claude.respond_approval(codex_approval["id"], {"decision": "decline"}),
                         lambda: claude.review_approval(codex_approval["id"])):
                with self.assertRaises(ProviderRefusal):
                    call()
        finally:
            claude.close()

    def test_backend_answer_approval_resolves_the_held_request_only(self):
        backend = ClaudeBackend(claude_path=str(FAKE), runner=probe_runner)
        for decision, expected in (("accept", "allow"), ("decline", "deny")):
            held = HeldRequest()
            backend.answer_approval(ApprovalRequest("tool_call", "PermissionRequest", ("s", "turn-1", "r"), {},
                                                    ("accept", "decline"), held), decision)
            self.assertEqual(expected, held.decision)
        held = HeldRequest()
        held.resolve("deny")
        with self.assertRaises(RequestGone):
            backend.answer_approval(ApprovalRequest("tool_call", "PermissionRequest", (), {}, (), held), "accept")
        self.assertEqual("deny", held.decision)
        for kind, decision, responder in (("tool_call", "cancel", HeldRequest()), ("command", "accept", HeldRequest()),
                                          ("tool_call", "accept", None), ("tool_call", "accept", (object(), 1))):
            with self.assertRaises(ProviderUnavailable):
                backend.answer_approval(ApprovalRequest(kind, "PermissionRequest", (), {}, (), responder), decision)
            if isinstance(responder, HeldRequest):
                self.assertIsNone(responder.decision)

    def test_codex_kinds_unchanged(self):
        """The Codex kinds keep their contexts and their automatic eligibility; tool_call is its own shape."""
        reviews = ApprovalReviews()
        tool = {"tool_name": "Bash", "tool_input": {"command": "echo synthetic"}}
        self.assertEqual(tool, reviews.context(deepcopy(tool), "tool_call"))
        for kind in ("command", "file_change", "permissions", "approval_question", "elicitation"):
            with self.assertRaises(ReviewError):
                reviews.context(deepcopy(tool), kind)
        for bad in ({"tool_name": "Bash"}, {"tool_name": "", "tool_input": {}}, {"tool_name": "Bash", "tool_input": []},
                    dict(tool, extra=1), dict(tool, agent_type=7), {"tool_name": 3, "tool_input": {}}):
            with self.assertRaises(ReviewError):
                reviews.context(bad, "tool_call")
        app = Dashboard(self.root / "codex", policy_provider=SyntheticPolicy())
        try:
            fake = FakeClient()
            app.client = fake
            app.connection["status"] = "connected"
            project = app.add_project({"name": "p", "path": str(self.root)})
            task = {"id": "a" * 32, "project_id": project["id"], "title": "t", "role": "backend_developer",
                    "model": "gpt-6.1-sol", "reasoning": "high", "status": "running", "thread_id": "native-root",
                    "turn_id": "native-turn", "plan": [], "usage": None, "cost": unknown_cost(), "error": None,
                    "created_at": now(), "updated_at": now()}
            app.tasks[task["id"]] = task
            app._register_thread("native-root", task["id"])
            app.owned_threads["native-root"].update(current_turn="native-turn", turns={"native-turn"})
            app.on_message({"id": 1, "method": "item/commandExecution/requestApproval", "params": {
                "threadId": "native-root", "turnId": "native-turn", "itemId": "item-1", "startedAtMs": 1,
                "reason": "synthetic", "command": "/usr/bin/true", "cwd": str(self.root),
                "availableDecisions": ["accept", "acceptForSession", "decline", "cancel"]}})
            [approval] = list(app.approvals.values())
            self.assertEqual(("command", "Kira Voss (Backend Developer) via Codex App Server"),
                             (approval["kind"], approval["requester"]))
            self.assertNotIn("provider", app.pending[approval["id"]])
            self.assertEqual(["decline", "cancel"], approval["available_decisions"])
            with patch("dashboard.server.scan_preview"):
                review = app.review_approval(approval["id"])
                app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
            self.assertEqual([(1, {"decision": "accept"})], fake.responses)
            self.assertIsNone(app.hook_receiver)
        finally:
            app.close()


class AutomaticPathOk(unittest.TestCase):
    """Direct unit tests of Dashboard._automatic_path_ok (no run, no receiver)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(os.path.realpath(self.tmp.name))
        self.root = base / "project"
        self.outside = base / "outside"
        for folder in (self.root / "src", self.root / ".git", self.outside):
            folder.mkdir(parents=True)
        (self.outside / "secret.txt").write_text("x")
        os.symlink(self.outside, self.root / "link-out")
        os.symlink(self.root / ".git", self.root / "link-git")
        self.project = {"path": str(self.root)}

    def ok(self, tool, tool_input, **kwargs):
        request = {"params": {"tool_name": tool, "tool_input": tool_input}}
        return Dashboard._automatic_path_ok(request, kwargs.get("project", self.project))

    def test_inside_paths_are_allowed(self):
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                self.assertTrue(self.ok(tool, {key: str(self.root / "src" / "a.py")}))
                self.assertTrue(self.ok(tool, {key: "src/new.py"}))
                self.assertTrue(self.ok(tool, {key: "not-yet/created.py"}))

    def test_outside_dotdot_and_symlink_escape_fall_to_manual(self):
        for target in (str(self.outside / "secret.txt"), "../outside/secret.txt", "src/../../outside/x",
                       "link-out/secret.txt", "link-out/new.txt", "/etc/hosts"):
            with self.subTest(target=target):
                self.assertFalse(self.ok("Write", {"file_path": target}))

    def test_protected_components_fall_to_manual(self):
        for target in (".git/config", ".GIT/config", ".claude/settings.json", ".Claude/x", ".local/x", ".LOCAL/x",
                       "src/.git/hooks/pre-commit", "link-git/config", str(self.root / ".git" / "HEAD")):
            with self.subTest(target=target):
                self.assertFalse(self.ok("Edit", {"file_path": target}))

    def test_project_root_itself_is_refused(self):
        for target in (str(self.root), ".", "src/.."):
            with self.subTest(target=target):
                self.assertFalse(self.ok("Write", {"file_path": target}))

    def test_missing_or_malformed_path_falls_to_manual(self):
        for tool_input in ({}, {"file_path": ""}, {"file_path": 7}, {"file_path": None}, {"file_path": ["a"]},
                           {"file_path": "a\0b"}, {"file_path": b"a"}, {"notebook_path": "x.ipynb"}, "text", None):
            with self.subTest(tool_input=tool_input):
                self.assertFalse(self.ok("Write", tool_input))
        self.assertFalse(self.ok("NotebookEdit", {"file_path": "x.ipynb"}))

    def test_notebook_path_key(self):
        self.assertTrue(self.ok("NotebookEdit", {"notebook_path": "src/n.ipynb"}))
        self.assertFalse(self.ok("NotebookEdit", {"notebook_path": "../outside/n.ipynb"}))
        self.assertFalse(self.ok("NotebookEdit", {"notebook_path": ".git/n.ipynb"}))

    def test_bash_is_name_only(self):
        self.assertTrue(self.ok("Bash", {"command": "cat /etc/hosts"}))
        self.assertTrue(self.ok("Bash", {}))

    def test_bad_request_or_project_falls_to_manual(self):
        good = {"file_path": "src/a.py"}
        for project in (None, {}, "path", {"path": None}):
            with self.subTest(project=project):
                self.assertFalse(self.ok("Write", good, project=project))
        for request in (None, {}, {"params": None}, {"params": {}}, {"params": {"tool_name": "Write"}}):
            with self.subTest(request=request):
                self.assertFalse(Dashboard._automatic_path_ok(request, self.project))


if __name__ == "__main__":
    unittest.main()

"""Claude approval journeys over HTTP (Plan 4, Task 8).

Evidence kind: fake-binary evidence, not a live run. The owner's request is exercised end to end: start a run, it
asks for permission, the owner approves once, work resumes. Everything goes through the real HTTP handler on an
ephemeral port, the real Dashboard, the real loopback hook receiver, the real argv builder and ClaudeRun, and a real
settings file (a SettingsStore on a temporary path). Only the ``claude`` binary is faked (tests/fake_claude.py,
replaying sanitized fixtures); the run factory refuses any other executable, so the real ``claude`` can never start
here. Nothing in this file establishes how the real CLI behaves.

Two stand-ins, both used by the shared harness (tests/test_claude_approvals.py): the sensitive-content scanner
reports a finding exactly when a run-time sentinel is in the scanned bytes, and the approval wait of the expiry
journey is shortened through the receiver factory (the setting itself is saved at its legal minimum, 60 s).
A Dashboard registers each Claude session id once, and every fixture shares one, so each journey that starts a
fresh run uses its own Dashboard.
"""
import http.client
import json
import os
from pathlib import Path
import subprocess
import threading
import unittest
import uuid

from dashboard.backends.claude import ClaudeBackend
from dashboard.backends.claude_runner import ClaudeRun
from dashboard.hook_receiver import HookReceiver
from dashboard.server import Dashboard, make_server
from dashboard.settings import SettingsStore
from tests.policy_fixtures import SyntheticPolicy
from tests.test_claude_approvals import (ALLOW, DENY, FAKE, INSTRUCTION, SESSION, TERMINAL, Harness, RaisingPolicy,
                                         payload, probe_runner, stray_fakes, wait_for)
from tests.test_dashboard_backend import FakeClient

SENTINEL_RESULT = "SENTINEL_TOOL_RESULT"


class TeeStdout:
    """Reads the fake's stdout exactly as the runner does and counts the tool-result lines it printed."""

    def __init__(self, stream, counter):
        self._stream, self._counter = stream, counter

    def readline(self, size=-1):
        line = self._stream.readline(size)
        if SENTINEL_RESULT.encode() in line:
            self._counter.append(1)
        return line

    def close(self):
        self._stream.close()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class FakeBinaryApprovalJourney(Harness):
    """The Task 5 harness plus an HTTP server in front of every Dashboard it creates (fake claude only)."""

    def factory(self, argv, **kwargs):
        if argv[0] != str(FAKE):
            raise AssertionError("refusing to start anything but the fake claude")
        path = Path(argv[argv.index("--settings") + 1])
        self.settings_seen.append((path, json.loads(path.read_text()), os.stat(path).st_mode & 0o777))

        def spawn(*args, **popen_kwargs):
            process = subprocess.Popen(*args, **popen_kwargs)
            process.stdout = TeeStdout(process.stdout, self.tool_results)
            return process
        run = ClaudeRun(argv, sigint_wait=2.0, term_wait=1.0, process_factory=spawn, **kwargs)
        self.created.append(run)
        return run

    def make_app(self, wait=None, **extra):
        self.tool_results = getattr(self, "tool_results", [])
        app = super().make_app(wait, **extra)
        self.serve(app)
        return app

    def serve(self, app):
        server = make_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        app.test_port = server.server_port

    def tearDown(self):
        super().tearDown()
        self.assertEqual([], [t.name for t in threading.enumerate() if t.name == "hook-receiver"],
                         "a hook receiver thread outlived the test")

    # ---- HTTP helpers ----------------------------------------------------------------------------
    def http(self, method, path, body=None, app=None, port=None):
        port = port or (app or self.app).test_port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Origin": "http://127.0.0.1:%d" % port}
        data = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps({} if body is None else body)
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw)

    def state(self, app=None):
        status, body = self.http("GET", "/api/state", app=app)
        self.assertEqual(200, status)
        return body

    def task_state(self, task_id, app=None):
        return next(t for t in self.state(app)["tasks"] if t["id"] == task_id)

    def approvals_of(self, task_id, app=None):
        return [a for a in self.state(app)["approvals"] if a["task_id"] == task_id]

    def add_project(self, app=None):
        path = self.root / "project"
        path.mkdir(exist_ok=True)
        status, project = self.http("POST", "/api/projects", {"name": "project", "path": str(path)}, app=app)
        self.assertEqual(200, status, project)
        return project

    def start_run(self, fixture="success", app=None, project=None, **env):
        """POST /api/tasks with the fake configured through the Dashboard's env seam."""
        app = app or self.app
        app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, FAKE_CLAUDE_RECORD=str(self.record), **env)
        project = project or self.add_project(app)
        status, task = self.http("POST", "/api/tasks", {"project_id": project["id"], "title": "Synthetic run",
                                                        "instruction": INSTRUCTION, "role": "backend_developer"}, app=app)
        self.assertEqual(200, status, task)
        self.project_id = project["id"]
        return task

    def gated_run(self, scenario, app=None, **env):
        """A run whose fake asks for permission once the dashboard knows its session."""
        app = app or self.app
        gate = self.root / ("gate-%d" % len(self.apps))
        task = self.start_run("success", app=app, FAKE_CLAUDE_HOOK=scenario, FAKE_CLAUDE_HOOK_GATE=str(gate), **env)
        self.assertTrue(wait_for(lambda: app.tasks[task["id"]]["claude"]["session_id"] == SESSION), "no session")
        gate.write_text("go")
        return task

    def pending_over_http(self, task_id, count=1, app=None):
        self.assertTrue(wait_for(lambda: len([a for a in self.approvals_of(task_id, app)
                                              if a["status"] == "pending"]) >= count), "no pending approval in /api/state")
        return [a for a in self.approvals_of(task_id, app) if a["status"] == "pending"]

    def review(self, approval_id, app=None):
        status, body = self.http("GET", "/api/approvals/%s/review" % approval_id, app=app)
        self.assertEqual(200, status, body)
        return body

    def respond(self, approval_id, body, app=None):
        return self.http("POST", "/api/approvals/%s/respond" % approval_id, body, app=app)

    def accept(self, approval_id, app=None):
        review = self.review(approval_id, app)
        return review, self.respond(approval_id, {"decision": "accept", "review_id": review["review_id"]}, app)

    def finish(self, task_id, app=None):
        app = app or self.app
        self.assertTrue(wait_for(lambda: self.task_state(task_id, app)["status"] in TERMINAL and task_id not in app.runs),
                        "the run did not finish")
        return self.task_state(task_id, app)

    def config(self, app=None):
        status, body = self.http("GET", "/api/config", app=app)
        self.assertEqual(200, status)
        return body

    def save_config(self, changes, app=None):
        config = self.config(app)
        config.update(changes)
        status, body = self.http("POST", "/api/config", config, app=app)
        self.assertEqual(200, status, body)
        return body

    def set_modes(self, modes, app=None):
        return self.save_config({"project_approval_modes": modes}, app)

    def codes(self, task):
        return [d["code"] for d in task.get("diagnostics") or []]

    def settings_files(self):
        return sorted(p.name for app in self.apps for p in (app.state_dir / "claude-runs").glob("*")
                      if (app.state_dir / "claude-runs").is_dir())

    def assert_clean(self, task_id, app=None):
        app = app or self.app
        self.assertTrue(wait_for(lambda: not self.settings_files(), 5), "a settings file was left")
        self.assertTrue(wait_for(lambda: not any(e["task_id"] == task_id for e in app.hook_runs.values()), 5))

    # ---- journeys --------------------------------------------------------------------------------
    def test_journey_start_ask_review_approve_work_resumes_and_completes(self):
        task = self.start_run("success", FAKE_CLAUDE_HOOK="ask_allowed",
                              FAKE_CLAUDE_HOOK_GATE=str(self.root / "gate-journey"))
        task_id = task["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["claude"]["session_id"] == SESSION))
        (self.root / "gate-journey").write_text("go")
        [approval] = self.pending_over_http(task_id)
        # /api/state: the task waits, the approval is a pending tool call with only the accept-free decisions listed
        shown = self.task_state(task_id)
        self.assertEqual("waiting_approval", shown["status"])
        self.assertEqual(("tool_call", "pending", "A tool call requires approval"),
                         (approval["kind"], approval["status"], approval["summary"]))
        self.assertIn("Claude Code", approval["requester"])
        self.assertNotIn("SENTINEL_HOOK_INPUT", json.dumps(self.state()))  # the input is shown only through review
        pid = self.created[-1].pid
        # review shows the checked input; accept with the receipt
        review, (status, resolved) = self.accept(approval["id"])
        self.assertEqual({"tool_name": "Bash", "tool_input": {"command": "echo SENTINEL_HOOK_INPUT"}}, review["context"])
        self.assertEqual(200, status, resolved)
        self.assertEqual(("resolved", "accept", "human"),
                         (resolved["status"], resolved["decision"]["value"], resolved["decision"]["source"]))
        # the same process carries on: one invocation, one allow, the tool result once, the task completes
        final = self.finish(task_id)
        self.assertEqual("completed", final["status"])
        self.assertEqual(1, len(self.invocations()))
        self.assertEqual(pid, self.created[-1].pid)
        self.assertEqual([{"scenario": "ask_allowed", "calls": 1, "told": ["allow"]}], self.hook_record())
        self.assertEqual(1, len(self.tool_results))  # the tool result the run printed after the allow: once
        self.assertEqual("resolved", self.approvals_of(task_id)[0]["status"])
        self.assertEqual("usd-estimate", final["cost"]["unit"])
        self.assertGreater(final["cost"]["usd"], 0)
        self.assertGreater(sum(final["usage"].values()), 0)
        self.assertEqual(0, final["claude"]["denied_count"])
        # the receipt is single use and the run is over: a second accept is refused
        status, refused = self.respond(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual(409, status)
        self.assertEqual("request_unavailable", refused["code"])
        self.assert_clean(task_id)

    def test_journey_decline_run_finishes_with_denial_recorded(self):
        task = self.gated_run("ask_declined")
        [approval] = self.pending_over_http(task["id"])
        status, resolved = self.respond(approval["id"], {"decision": "decline"})
        self.assertEqual(200, status, resolved)
        self.assertEqual(("resolved", "decline"), (resolved["status"], resolved["decision"]["value"]))
        final = self.finish(task["id"])
        self.assertEqual("completed", final["status"])
        self.assertEqual([{"scenario": "ask_declined", "calls": 1, "told": ["deny"]}], self.hook_record())
        self.assertEqual(1, final["claude"]["denied_count"])
        self.assertIn("claude_calls_denied", self.codes(final))
        self.assertEqual(0, len(self.tool_results))  # the denied call never ran
        self.assertEqual("resolved", self.approvals_of(task["id"])[0]["status"])
        self.assert_clean(task["id"])

    def test_journey_ignore_until_expiry_denied_and_expired_state(self):
        def short(*args, **kwargs):
            limit = kwargs["wait_limit"]
            kwargs["wait_limit"] = lambda key: min(limit(key), 3.0)  # the configured 60 s, cut for the test
            receiver = HookReceiver(*args, poll_interval=0.05, **kwargs)
            self.receivers.append(receiver)
            return receiver
        self.app.hook_receiver_factory = short
        self.save_config({"claude_approval_wait_seconds": 60})  # the legal minimum, through the real route
        task = self.gated_run("ask_allowed")
        [approval] = self.pending_over_http(task["id"])
        review = self.review(approval["id"])  # the owner has looked but not answered
        self.assertTrue(wait_for(lambda: self.approvals_of(task["id"])[0]["status"] != "pending", 10), "no expiry")
        expired = self.approvals_of(task["id"])[0]
        self.assertEqual(("unavailable", []), (expired["status"], expired["available_decisions"]))
        self.assertEqual("expired", expired.get("unavailable_reason"))
        # a late accept is refused and sends nothing
        status, refused = self.respond(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual((409, "request_unavailable"), (status, refused["code"]))
        final = self.finish(task["id"])
        self.assertEqual("completed", final["status"])
        self.assertEqual([{"scenario": "ask_allowed", "calls": 1, "told": ["deny"]}], self.hook_record())
        self.assertEqual(1, final["claude"]["denied_count"])
        self.assertIn("claude_calls_denied", self.codes(final))
        self.assertEqual("expired", self.approvals_of(task["id"])[0].get("unavailable_reason"))
        self.assertEqual(0, len(self.tool_results))
        self.assert_clean(task["id"])

    def test_journey_stop_while_waiting(self):
        # Covers the receiver plus the Dashboard's stop, not the fake's ask scenario. A run that ignores SIGINT and
        # asks for permission (posted to its own hook URL while it is live; the
        # fake's own ask scenarios end with a result line the moment they are denied, which would complete the
        # task before the stop ladder could mark it interrupted).
        task = self.start_run("no_result", FAKE_CLAUDE_IGNORE_SIGINT="1")
        task_id = task["id"]
        self.assertTrue(wait_for(lambda: self.app.tasks[task_id]["status"] == "running"
                                 and self.app.tasks[task_id]["claude"]["session_id"] == SESSION))
        held = self.post(payload())
        [approval] = self.pending_over_http(task_id)
        review = self.review(approval["id"])
        status, answer = self.http("POST", "/api/tasks/%s/interrupt" % task_id, {})
        self.assertEqual((200, "interrupt_requested"), (status, answer["status"]))
        # The run ignores SIGINT, so it is still alive here (the ladder escalates after 2 s). Only the withdraw
        # that precedes the signal explains what follows: the approval is already unavailable with its reason,
        # and the held call is already told deny.
        self.assertIn(task_id, self.app.runs)
        shown = self.approvals_of(task_id)[0]
        self.assertEqual(("unavailable", "run_ended"), (shown["status"], shown.get("unavailable_reason")))
        self.assertEqual((200, DENY), self.reply(held, 1))
        self.assertIn(task_id, self.app.runs)
        status, refused = self.respond(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual((409, "request_unavailable"), (status, refused["code"]))
        final = self.finish(task_id)
        self.assertEqual("interrupted", final["status"])
        shown = self.approvals_of(task_id)[0]
        self.assertEqual(("unavailable", "run_ended"), (shown["status"], shown.get("unavailable_reason")))
        self.assertTrue(wait_for(lambda: not stray_fakes(), 5))
        self.assert_clean(task_id)

    def test_journey_restart_while_waiting(self):
        task = self.gated_run("ask_allowed", FAKE_CLAUDE_IGNORE_SIGINT="1")
        task_id = task["id"]
        [approval] = self.pending_over_http(task_id)
        token = self.url().rsplit("/", 1)[1]
        old = self.app
        # A crash: the old dashboard records nothing more, its run is killed and the approval stays stored pending.
        old.stop.set()
        with old.lock:
            run = old.runs[task_id]
        run.stop("shutdown")
        self.assertTrue(run.cleanup_complete.wait(10))
        stored = {a["id"]: a for a in old.store.load("approval")}
        self.assertEqual("pending", stored[approval["id"]]["status"])
        new = Dashboard(old.state_dir, policy_provider=RaisingPolicy(),
                        backend=ClaudeBackend(claude_path=str(FAKE), runner=probe_runner),
                        claude_run_factory=self.factory, hook_receiver_factory=self.receiver_factory)
        self.apps.append(new)
        new.settings = old.settings
        self.serve(new)
        new.start()
        self.assertTrue(wait_for(lambda: new.connection["status"] == "connected", 5))
        shown = self.task_state(task_id, new)
        self.assertEqual("unknown", shown["status"])
        self.assertFalse(shown.get("recovery_hold"))
        self.assertEqual(SESSION, new.tasks[task_id]["claude"]["session_id"])  # kept, so a follow-up can resume it
        [restored] = self.approvals_of(task_id, new)
        self.assertEqual(("unavailable", "dashboard_restarted", []),
                         (restored["status"], restored.get("unavailable_reason"), restored["available_decisions"]))
        self.assertEqual([], [a for a in self.state(new)["approvals"] if a["status"] == "pending"])
        review_status, _ = self.http("GET", "/api/approvals/%s/review" % approval["id"], app=new)
        self.assertEqual(409, review_status)
        status, refused = self.respond(approval["id"], {"decision": "accept", "review_id": uuid.uuid4().hex}, app=new)
        self.assertEqual(409, status)
        self.assertEqual({}, new.hook_runs)
        self.assertIsNone(new.hook_receiver)
        self.assertEqual([], self.settings_files())
        self.assertNotIn(token, json.dumps(self.state(new)))
        raw = b"".join(p.read_bytes() for p in old.state_dir.rglob("*") if p.is_file())
        self.assertNotIn(token.encode(), raw)
        self.assertTrue(wait_for(lambda: not stray_fakes(), 5))

    def test_journey_codex_deployment_has_no_receiver_and_claude_routes_gated(self):
        # a Codex deployment: no hook receiver, thread, port or settings folder, even after a task starts
        codex = Dashboard(self.root / "codex-state", policy_provider=SyntheticPolicy())
        self.apps.append(codex)
        codex.settings = SettingsStore(self.root, config_path=self.root / "codex-settings.toml")
        codex.client = FakeClient()
        codex.connection["status"] = "connected"
        self.serve(codex)
        project = self.add_project(codex)
        status, started = self.http("POST", "/api/tasks", {"project_id": project["id"], "title": "Synthetic run",
                                                           "instruction": INSTRUCTION, "role": "backend_developer"},
                                    app=codex)
        self.assertEqual(200, status, started)
        self.assertEqual("codex", started["provider"])
        self.assertIsNone(codex.hook_receiver)
        self.assertEqual({}, codex.hook_runs)
        self.assertFalse((codex.state_dir / "claude-runs").exists())
        self.assertEqual([], [t.name for t in threading.enumerate() if t.name == "hook-receiver"])
        self.assertEqual("codex", self.http("GET", "/api/provider", app=codex)[1]["provider"])
        # the Codex-only routes answer on a Codex deployment (not the gate's 409 "not available for this provider")
        status, body = self.http("POST", "/api/approvals/%s/alternative" % ("b" * 32),
                                 {"text": "smaller", "mode": "decline"}, app=codex)
        self.assertEqual(409, status)  # not the provider gate: the Codex route itself answers (unknown approval)
        self.assertNotEqual({"error": "not available for this provider"}, body)
        # a Claude deployment: the Codex-only routes are gated before anything is read, and a Claude approval's
        # own routes are not gated
        task = self.gated_run("ask_allowed")
        [approval] = self.pending_over_http(task["id"])
        before = json.dumps(self.state(), sort_keys=True)
        for method, path, body in (("POST", "/api/approvals/%s/alternative" % approval["id"],
                                    {"text": "smaller", "mode": "decline"}),
                                   ("POST", "/api/tasks/%s/recovery/check" % task["id"], {"expected_revision": 1}),
                                   ("GET", "/api/recovery-auth", None)):
            with self.subTest(path=path):
                self.assertEqual((409, {"error": "not available for this provider"}),
                                 self.http(method, path, body))
        self.assertEqual(before, json.dumps(self.state(), sort_keys=True))
        self.assertEqual(200, self.http("GET", "/api/approvals/%s/review" % approval["id"])[0])
        # the receiver serves only its hook path: no dashboard route, wrong token, wrong method
        port = int(self.url().split(":")[2].split("/")[0])
        self.assertIn(self.raw_status("GET", "/api/state", port), {404, 405})
        self.assertEqual((200, json.loads(DENY)), self.raw_reply("POST", "/hook/managed/" + "x" * 43, port, b"{}"))  # unknown token: deny
        self.assertEqual(1, len(self.pending_over_http(task["id"])))  # none of that touched the approval
        self.decline_and_finish(task["id"], approval["id"])

    def raw_status(self, method, path, port, body=None):
        return self.raw_reply(method, path, port, body)[0]

    def raw_reply(self, method, path, port, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, None

    def decline_and_finish(self, task_id, approval_id):
        self.assertEqual(200, self.respond(approval_id, {"decision": "decline"})[0])
        self.assertEqual("completed", self.finish(task_id)["status"])

    def test_journey_automatic_project_accepts_plain_bash_once_but_not_sensitive_input(self):
        # "Sensitive" here is decided by the harness's scanner stand-in (a runtime sentinel), so this proves the
        # routing (a finding keeps the call for the owner), not the real scan_preview patterns.
        # Run 1, through the fake: a plain Bash request in an automatic project is accepted once, without the owner.
        project = self.add_project()
        self.set_modes({project["id"]: "automatic"})
        task = self.start_run("success", project=project, FAKE_CLAUDE_HOOK="ask_allowed",
                              FAKE_CLAUDE_HOOK_GATE=str(self.root / "gate-auto"))
        self.assertTrue(wait_for(lambda: self.app.tasks[task["id"]]["claude"]["session_id"] == SESSION))
        (self.root / "gate-auto").write_text("go")
        final = self.finish(task["id"])
        self.assertEqual("completed", final["status"])
        [approval] = self.approvals_of(task["id"])
        self.assertEqual(("resolved", "accept", "project_policy"),
                         (approval["status"], approval["decision"]["value"], approval["decision"]["source"]))
        self.assertEqual([{"scenario": "ask_allowed", "calls": 1, "told": ["allow"]}], self.hook_record())
        # one call only: the receipt-less project-policy accept is not reusable
        status, refused = self.respond(approval["id"], {"decision": "accept", "review_id": uuid.uuid4().hex})
        self.assertEqual((409, "request_unavailable"), (status, refused["code"]))
        # Run 2, a second Dashboard on the same settings file: a secret-shaped Bash input still waits for the owner.
        other = self.make_app()
        other.settings = self.app.settings
        project2 = self.add_project(other)
        self.set_modes({project["id"]: "automatic", project2["id"]: "automatic"}, app=other)
        task2 = self.start_run("no_result", app=other, project=project2, FAKE_CLAUDE_IGNORE_SIGINT="1")
        self.assertTrue(wait_for(lambda: other.tasks[task2["id"]]["status"] == "running"
                                 and other.tasks[task2["id"]]["claude"]["session_id"] == SESSION))
        out_plain = self.post(payload("Bash", {"command": "echo plain"}), index=-1)
        self.assertEqual((200, ALLOW), self.reply(out_plain))
        out_secret = self.post(payload("Bash", {"command": "echo " + self.secret}), index=-1)
        [waiting] = self.pending_over_http(task2["id"], app=other)
        self.assertEqual("waiting_approval", self.task_state(task2["id"], other)["status"])
        self.assertIsNone(out_secret.get("status"))  # still held: the owner has not decided
        self.assertNotIn(self.secret, json.dumps(self.state(other)))
        review_status, review = self.http("GET", "/api/approvals/%s/review" % waiting["id"], app=other)
        self.assertEqual(409, review_status)  # the sensitive-review path, not a plain review
        self.assertIn(review["code"], {"scanner_blocked", "sensitive_confirmation_required"})
        self.assertEqual(200, self.http("POST", "/api/tasks/%s/interrupt" % task2["id"], {}, app=other)[0])
        self.assertEqual((200, DENY), self.reply(out_secret))
        self.assertEqual("interrupted", self.finish(task2["id"], other)["status"])
        self.assertTrue(wait_for(lambda: not self.settings_files(), 5))

    def test_journey_approving_one_call_does_not_approve_a_differently_worded_second(self):
        task = self.gated_run("ask_two")
        task_id = task["id"]
        approvals = self.pending_over_http(task_id, 2)
        reviews = {a["id"]: self.review(a["id"]) for a in approvals}
        tools = {aid: r["context"]["tool_name"] for aid, r in reviews.items()}
        self.assertEqual({"Bash", "Write"}, set(tools.values()))
        bash = next(aid for aid, name in tools.items() if name == "Bash")
        write = next(aid for aid, name in tools.items() if name == "Write")
        # the Bash receipt cannot answer for the Write call
        status, refused = self.respond(write, {"decision": "accept", "review_id": reviews[bash]["review_id"]})
        self.assertEqual(409, status)
        self.assertEqual("pending", next(a for a in self.approvals_of(task_id) if a["id"] == write)["status"])
        # a refused answer withdraws the receipts: look at both calls again, then approve ONE call
        reviews = {a["id"]: self.review(a["id"]) for a in approvals}
        # approve ONE call: the second still prompts and the run keeps waiting
        status, resolved = self.respond(bash, {"decision": "accept", "review_id": reviews[bash]["review_id"]})
        self.assertEqual(200, status, resolved)
        self.assertEqual("resolved", resolved["status"])
        second = next(a for a in self.approvals_of(task_id) if a["id"] == write)
        self.assertEqual("pending", second["status"])
        self.assertEqual("waiting_approval", self.task_state(task_id)["status"])
        self.assertEqual([], [x for x in self.hook_record()])  # the fake has not finished: the second is unanswered
        # it needs its own approval
        status, resolved = self.respond(write, {"decision": "accept", "review_id": reviews[write]["review_id"]})
        self.assertEqual(200, status, resolved)
        self.assertEqual("resolved", resolved["status"])
        final = self.finish(task_id)
        self.assertEqual("completed", final["status"])
        self.assertEqual([{"scenario": "ask_two", "calls": 2, "told": ["allow", "allow"]}], self.hook_record())
        self.assertEqual(2, len(self.tool_results))
        self.assertEqual(2, len([a for a in self.approvals_of(task_id) if a["status"] == "resolved"]))
        self.assert_clean(task_id)


if __name__ == "__main__":
    unittest.main()

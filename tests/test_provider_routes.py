"""Codex-only routes answer 409 when the active provider lacks the capability (Review Focus 7)."""
from copy import deepcopy
import http.client
import inspect
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest

from dashboard import server
from dashboard.backends.base import NoBackend
from dashboard.backends.claude import ClaudeBackendStub
from dashboard.server import Dashboard, Handler, make_server
from dashboard.store import Store
from tests.characterization import ScriptedDashboard
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient
from tests.test_provider_records import ID_A, ID_B, legacy_rows

NOT_AVAILABLE = {"error": "not available for this provider"}
MISMATCH = {"error": "recorded under a different provider"}
HANDOFF = "c" * 32
PLAN = "d" * 32
OPERATION = "e" * 32
APPROVAL = "f" * 32
TASK = "/api/tasks/" + ID_B

# (method, path, sample body, capability that gates it). Derived from Handler.do_GET / do_POST; the
# coverage test below fails if a route containing "recovery" or "alternative" is missing here.
GATED = [
    ("GET", "/api/recovery-auth", None, "assessment"),
    ("POST", "/api/recovery-auth/start", {}, "assessment"),
    ("POST", "/api/recovery-auth/cancel", {}, "assessment"),
    ("POST", "/api/recovery-auth/sign-out", {}, "assessment"),
    ("GET", TASK + "/recovery", None, "recovery"),
    ("GET", TASK + "/recovery/handoffs/" + HANDOFF, None, "recovery"),
    ("POST", TASK + "/recovery/check", {"expected_revision": 1}, "recovery"),
    ("POST", TASK + "/recovery/assess", {"receipt_id": "r", "operation_id": OPERATION, "selected_message_ids": [],
                                          "text": "x", "confirmed": True}, "assessment"),
    ("POST", TASK + "/recovery/plans", {"expected_revision": 1, "instruction": "x", "target_strategy": "continue",
                                         "role": "backend_developer", "assessment_task_id": ID_A}, "recovery"),
    ("POST", TASK + "/recovery/plans/" + PLAN, {"expected_revision": 1, "instruction": "x", "target_strategy": "continue",
                                                 "role": "backend_developer", "expected_plan_version": 1}, "recovery"),
    ("POST", TASK + "/recovery/continue", {"receipt_id": "r", "operation_id": OPERATION, "assessment_task_id": ID_A,
                                            "plan_id": PLAN, "plan_digest": "d", "confirmed": True}, "recovery"),
    ("POST", TASK + "/recovery/disposition", {"expected_revision": 1, "disposition": "reviewed", "note": "n",
                                               "confirmed": True}, "recovery"),
    ("POST", TASK + "/recovery/restart-plan", {"expected_revision": 1, "confirmed": True}, "recovery"),
    ("POST", TASK + "/recovery/handoffs", {"expected_revision": 1, "operation_id": OPERATION,
                                            "selected_message_ids": [], "text": "x", "confirmed": True}, "assessment"),
    ("POST", TASK + "/recovery/handoffs/" + HANDOFF + "/responses",
     {"expected_revision": 1, "operation_id": OPERATION, "packet_digest": "d", "expected_handoff_version": 1,
      "text": "x", "confirmed": True}, "assessment"),
    ("POST", TASK + "/recovery/handoffs/" + HANDOFF + "/accept",
     {"expected_revision": 1, "operation_id": OPERATION, "packet_digest": "d", "expected_handoff_version": 1,
      "response_id": "r", "response_digest": "d", "response_version": 1, "review_id": "v", "confirmed": True},
     "assessment"),
    ("POST", TASK + "/recovery/operations/" + OPERATION + "/cancel", {"expected_revision": 1, "confirmed": True},
     "recovery"),
    ("POST", "/api/approvals/" + APPROVAL + "/alternative", {"text": "smaller", "mode": "decline"},
     "approval_alternative"),
]


class RouteFixture(unittest.TestCase):
    backend = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        legacy_rows(self.root / "state")
        kwargs = {} if self.backend is None else {"backend": self.backend}
        self.app = Dashboard(self.root / "state", policy_provider=SyntheticPolicy(), **kwargs)
        self.addCleanup(self.app.close)
        self.fake = FakeClient()
        self.app.client = self.fake
        self.app.connection["status"] = "connected"
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.port = self.server.server_port

    def stop(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Origin": "http://127.0.0.1:" + str(self.port)}
        payload = None
        if body is not None or method == "POST":
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body if body is not None else {})
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    def everything(self):
        rows = self.app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()
        return {"rows": rows, "tasks": deepcopy(self.app.tasks), "projects": deepcopy(self.app.projects),
                "approvals": deepcopy(self.app.approvals), "operations": deepcopy(self.app.recovery_operations),
                "handoffs": deepcopy(self.app.recovery_handoffs), "requests": list(self.fake.requests)}


class ClaudeStubRouteTests(RouteFixture):
    backend = ClaudeBackendStub()

    def test_codex_only_routes_409_under_claude_stub(self):
        before = self.everything()
        for method, path, body, _capability in GATED:
            with self.subTest(method=method, path=path):
                status, result = self.request(method, path, body)
                self.assertEqual(409, status)
                self.assertEqual(NOT_AVAILABLE, result)
        self.assertEqual(before, self.everything())
        self.assertEqual([], self.fake.requests)
        self.assertEqual([], self.fake.responses)

    def test_gate_answers_before_the_body_is_checked(self):
        for method, path, _body, _capability in GATED:
            if method == "POST":
                with self.subTest(path=path):
                    self.assertEqual((409, NOT_AVAILABLE), self.request("POST", path, {"unexpected": 1}))

    @staticmethod
    def expansions(pattern):
        """Every concrete path a handler pattern accepts: ids become samples, each (a|b|c) group is expanded."""
        pattern = re.sub(r"\\(.)", r"\1", pattern).replace("([0-9a-f]{32})", ID_A)
        paths = [pattern]
        while any("(" in path for path in paths):
            paths = [path[:m.start()] + alternative + path[m.end():]
                     for path in paths for m in [re.search(r"\(([^()]*)\)", path)] if m
                     for alternative in m.group(1).split("|")]
        return paths

    def handler_patterns(self, method):
        function = Handler.do_GET if method == "GET" else Handler.do_POST
        source = inspect.getsource(function)
        # Dispatch branches only (`match := re.fullmatch(...)`), not helper matches such as approval_route.
        patterns = re.findall(r':= re\.fullmatch\(r"([^"]+)", self\.path\)', source)
        patterns += [re.escape(value) for value in re.findall(r'self\.path == "([^"]+)"', source)]
        return [p for p in patterns if "recovery" in p or "alternative" in p]

    def test_every_recovery_or_alternative_route_in_the_handler_is_gated(self):
        relevant = {method: self.handler_patterns(method) for method in ("GET", "POST")}
        self.assertGreaterEqual(len(relevant["GET"]) + len(relevant["POST"]), 10)
        for method, patterns in relevant.items():
            for pattern in patterns:
                with self.subTest(method=method, pattern=pattern):
                    self.assertTrue(any(re.fullmatch(pattern, path) for m, path, _b, _c in GATED if m == method),
                                    "no sample route in GATED matches " + pattern)
                    # Every alternative inside the pattern's groups, not just the sampled one.
                    expanded = self.expansions(pattern)
                    self.assertTrue(expanded)
                    for path in expanded:
                        self.assertIn(server.gated_capability(method, path),
                                      {"recovery", "assessment", "approval_alternative"},
                                      method + " " + path + " is a handler route but is not gated")

    def test_table_capability_names_match_the_gating_table(self):
        for method, path, _body, capability in GATED:
            with self.subTest(method=method, path=path):
                self.assertEqual(capability, server.gated_capability(method, path))

    def test_routes_outside_the_table_are_not_gated(self):
        for method, path in (("GET", "/api/state"), ("GET", "/api/provider"), ("GET", TASK + "/conversation"),
                             ("POST", "/api/tasks"), ("POST", TASK + "/message"), ("POST", TASK + "/interrupt"),
                             ("GET", "/api/config")):
            with self.subTest(method=method, path=path):
                self.assertIsNone(server.gated_capability(method, path))
                status, result = self.request(method, path, {} if method == "POST" else None)
                self.assertNotEqual(NOT_AVAILABLE, result)

    def test_unconfirmed_capability_is_not_gated(self):
        original = self.app.backend.capabilities
        try:
            from dataclasses import replace
            self.app.backend = type("Unconfirmed", (), {"capabilities": replace(original, recovery="unconfirmed")})()
            status, result = self.request("GET", TASK + "/recovery")
            self.assertNotEqual(NOT_AVAILABLE, result)
        finally:
            self.app.backend = ClaudeBackendStub()


class NoProviderRouteTests(RouteFixture):
    backend = NoBackend()

    def test_codex_only_routes_409_with_no_provider(self):
        before = self.everything()
        for method, path, body, _capability in GATED:
            with self.subTest(method=method, path=path):
                self.assertEqual((409, NOT_AVAILABLE), self.request(method, path, body))
        self.assertEqual(before, self.everything())


class CodexRouteTests(RouteFixture):
    def test_codex_routes_unchanged_under_codex(self):
        for method, path, body, _capability in GATED:
            with self.subTest(method=method, path=path):
                status, result = self.request(method, path, body)
                self.assertNotEqual(NOT_AVAILABLE, result)
                self.assertNotEqual(MISMATCH, result)
        self.app.tasks[ID_B].update(status="unknown", error="Dashboard restarted; run was not replayed")
        status, result = self.request("GET", TASK + "/recovery")
        self.assertEqual(200, status)
        self.assertEqual(ID_B, result["task_id"])
        self.assertEqual(404, self.request("GET", "/api/tasks/" + "9" * 32 + "/recovery")[0])

    def test_mismatch_refusal_is_409_with_exact_text_under_codex(self):
        record = self.app.tasks[ID_B]
        record["provider"] = "claude"
        self.app.store.put("task", record)
        before = self.everything()
        routes = [(TASK + "/message", {"text": "hello", "expected_turn_id": "turn-one"}), (TASK + "/interrupt", {})]
        routes += [(path, body) for method, path, body, _c in GATED
                   if method == "POST" and "/recovery/" in path]
        self.assertGreaterEqual(len(routes), 12)
        for path, body in routes:
            with self.subTest(path=path):
                self.assertEqual((409, MISMATCH), self.request("POST", path, body))
        self.assertEqual(before, self.everything())


class MismatchRouteTests(RouteFixture):
    backend = ClaudeBackendStub()

    def test_mismatch_refusal_is_409_with_exact_text(self):
        before = self.everything()
        for path, body in ((TASK + "/message", {"text": "hello", "expected_turn_id": "turn-one"}),
                           (TASK + "/interrupt", {})):
            with self.subTest(path=path):
                self.assertEqual((409, MISMATCH), self.request("POST", path, body))
        self.assertEqual(before, self.everything())
        self.assertEqual([], self.fake.requests)

    def test_mismatch_error_is_still_a_value_error(self):
        with self.assertRaises(ValueError) as caught:
            self.app._require_active_provider(self.app.tasks[ID_B])
        self.assertIsInstance(caught.exception, server.ProviderRefusal)
        self.assertEqual("recorded under a different provider", str(caught.exception))

    def test_start_run_refusal_is_409_with_exact_text(self):
        status, result = self.request("POST", "/api/tasks", {
            "project_id": ID_A, "title": "T", "instruction": "do it", "role": "backend_developer"})
        self.assertEqual((409, {"error": "Claude backend is not implemented yet."}), (status, result))
        self.assertEqual({ID_B}, set(self.app.tasks))
        self.assertEqual([], self.fake.requests)


class NoProviderStartTests(RouteFixture):
    backend = NoBackend()

    def test_start_run_refusal_is_409_with_exact_text(self):
        status, result = self.request("POST", "/api/tasks", {
            "project_id": ID_A, "title": "T", "instruction": "do it", "role": "backend_developer"})
        self.assertEqual((409, {"error": "No provider configured."}), (status, result))

    def test_provider_unavailable_from_a_handler_is_409_with_its_message(self):
        from dashboard.backends.base import ProviderUnavailable

        def boom(*_args, **_kwargs):
            raise ProviderUnavailable("No provider configured")
        self.app.add_project = boom
        self.assertEqual((409, {"error": "No provider configured"}),
                         self.request("POST", "/api/projects", {"name": "x", "path": "/private/tmp"}))


class RecoveryTaskProviderTests(RouteFixture):
    def test_recovery_task_records_provider(self):
        role = {"id": "backend_developer", "model": "m", "reasoning": "high"}
        origin = {"id": ID_B, "project_id": ID_A, "cost": {"basis": "none"}}
        legacy = self.app._new_recovery_task(origin, role, "recovery_development", "x", OPERATION)
        self.assertEqual("codex", legacy["provider"])
        other = self.app._new_recovery_task(dict(origin, provider="claude"), role, "recovery_development", "x", OPERATION)
        self.assertEqual("claude", other["provider"])


class RecoveryMutatorGuardTests(RouteFixture):
    """Each recovery mutator refuses a run recorded under another provider, before any state change."""
    backend = ClaudeBackendStub()

    def refused(self, call, *args):
        before = self.everything()
        with self.assertRaises(ValueError) as caught:
            call(*args)
        self.assertIsInstance(caught.exception, server.ProviderRefusal)
        self.assertEqual("recorded under a different provider", str(caught.exception))
        self.assertEqual(before, self.everything())
        self.assertEqual([], self.fake.requests)

    def test_recovery_plan_refuses_other_provider_run(self):
        app = self.app
        self.refused(app.recovery_plan, ID_B, {"expected_revision": 1, "instruction": "x", "target_strategy": "continue",
                                               "role": "backend_developer", "assessment_task_id": ID_A})
        self.refused(app.recovery_plan, ID_B, {"expected_revision": 1, "instruction": "x", "target_strategy": "continue",
                                               "role": "backend_developer", "expected_plan_version": 1}, PLAN)

    def test_recovery_disposition_refuses_other_provider_run(self):
        self.refused(self.app.recovery_disposition, ID_B, {"expected_revision": 1, "disposition": "reviewed",
                                                           "note": "n", "confirmed": True})

    def test_recovery_restart_plan_refuses_other_provider_run(self):
        self.refused(self.app.recovery_restart_plan, ID_B, {"expected_revision": 1, "confirmed": True})

    def test_handoff_create_refuses_other_provider_run(self):
        self.refused(self.app.recovery_handoff_create, ID_B, {
            "expected_revision": 1, "operation_id": OPERATION, "selected_message_ids": [], "text": "x", "confirmed": True})

    def test_handoff_response_refuses_other_provider_run(self):
        self.refused(self.app.recovery_handoff_response, ID_B, HANDOFF, {
            "expected_revision": 1, "operation_id": OPERATION, "packet_digest": "d", "expected_handoff_version": 1,
            "text": "x", "confirmed": True})

    def test_handoff_accept_refuses_other_provider_run(self):
        self.refused(self.app.recovery_handoff_accept, ID_B, HANDOFF, {
            "expected_revision": 1, "operation_id": OPERATION, "packet_digest": "d", "expected_handoff_version": 1,
            "response_id": "r", "response_digest": "d", "response_version": 1, "review_id": "v", "confirmed": True})


class OtherProviderRunHttpTests(ScriptedDashboard):
    """A claude-recorded run with a live approval and question answers 409 over HTTP for every action."""

    def setUp(self):
        super().setUp()
        task = self.task()
        self.task_id = task["id"]
        self.app.on_message({"id": 17, "method": "item/commandExecution/requestApproval", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "itemId": "item-one", "startedAtMs": 1,
            "command": "SYNTHETIC_PRIVATE_COMMAND", "cwd": str(self.root), "reason": "SYNTHETIC_PRIVATE_REASON",
            "availableDecisions": ["accept", "decline", "cancel"]}})
        self.approval_id = list(self.app.approvals)[-1]
        self.app.on_message({"id": 71, "method": "item/tool/requestUserInput", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "itemId": "question-item",
            "questions": [{"id": "layout", "header": "Layout", "question": "Which layout should we use?",
                           "options": [{"label": "Compact", "description": "Use less space"},
                                       {"label": "Roomy", "description": "Use more space"}]}]}})
        self.app.wait_conversations()
        self.question_id = list(self.app.questions)[-1]
        self.app.tasks[self.task_id]["provider"] = "claude"
        self.app.store.put("task", self.app.tasks[self.task_id])
        self.fake.requests.clear()
        self.fake.responses.clear()
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()
        super().tearDown()

    def post(self, path, body):
        port = self.server.server_port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", path, body=json.dumps(body), headers={
            "Content-Type": "application/json", "Origin": "http://127.0.0.1:" + str(port)})
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    def test_actions_on_other_provider_run_are_409_over_http(self):
        task, delivery = "/api/tasks/" + self.task_id, {"expected_snapshot": "d" * 64, "operation_id": "e" * 32,
                                                      "confirmed": True}
        routes = [
            ("/api/approvals/" + self.approval_id + "/respond", {"decision": "decline"}),
            ("/api/questions/" + self.question_id + "/respond", {"answers": {"layout": ["Compact"]}}),
            ("/api/approvals/" + self.approval_id + "/alternative", {"text": "smaller"}),
            (task + "/delivery/checks", dict(delivery, expected_plan_version=1)),
            (task + "/delivery/reviews", dict(delivery, check_operation_id="c" * 32)),
        ]
        before = {"approvals": deepcopy(self.app.approvals), "questions": deepcopy(self.app.questions),
                  "tasks": deepcopy(self.app.tasks), "stored": self.app.store.db.execute(
                      "SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()}
        for path, body in routes:
            with self.subTest(path=path):
                self.assertEqual((409, MISMATCH), self.post(path, body))
        self.assertEqual([], self.fake.requests)
        self.assertEqual([], self.fake.responses)
        self.assertEqual(before["approvals"], self.app.approvals)
        self.assertEqual(before["questions"], self.app.questions)
        self.assertEqual(before["tasks"], self.app.tasks)
        self.assertEqual(before["stored"], self.app.store.db.execute(
            "SELECT kind, id, body FROM records ORDER BY kind, id").fetchall())


class OtherValidationStays400(RouteFixture):
    def test_plain_validation_errors_stay_400(self):
        status, result = self.request("POST", "/api/tasks", {"project_id": 1})
        self.assertEqual(400, status)


if __name__ == "__main__":
    unittest.main()

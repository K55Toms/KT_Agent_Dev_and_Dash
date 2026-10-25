import http.client
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest

from dashboard.server import Dashboard, make_server
from dashboard.store import Store
from dashboard.codex_client import ProtocolError, RequestRejected


class FakeClient:
    def __init__(self, on_message=None, on_disconnect=None):
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.closed = False
        self.requests = []
        self.responses = []
        self.rejections = []
        self.started = threading.Event()
        self.thread_count = 0

    def request(self, method, params):
        self.requests.append((method, params))
        if method == "model/list":
            return {"data": [{"model": m, "supportedReasoningEfforts": [{"reasoningEffort": effort} for effort in ("low", "medium", "high", "xhigh")]} for m in ("gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra")], "nextCursor": None}
        if method == "thread/start":
            self.thread_count += 1
            thread = "thread-one" if self.thread_count == 1 else "thread-" + str(self.thread_count)
            return {"thread": {"id": thread, "ephemeral": False}, "model": "gpt-6.1-sol", "serviceTier": None,
                    "approvalPolicy": "on-request", "approvalsReviewer": "user", "cwd": params["cwd"],
                    "runtimeWorkspaceRoots": params["runtimeWorkspaceRoots"],
                    "activePermissionProfile": {"id": params["permissions"], "extends": None},
                    "sandbox": {"type": "workspaceWrite", "networkAccess": False, "writableRoots": [],
                                "excludeSlashTmp": True, "excludeTmpdirEnvVar": True}}
        if method == "turn/start":
            self.started.set()
            return {"turn": {"id": "turn-one", "status": "inProgress"}}
        return {}

    def request_readonly(self, method, params, *, timeout=30):
        return self.request(method, params)

    def respond(self, request_id, result):
        self.responses.append((request_id, result))

    def request_guarded(self, method, params, guard, timeout=30):
        # This protocol double has no wire. Real IPC atomicity is exercised by
        # CodexClient tests with a synthetic process, not this reply simulator.
        with guard() as validate:
            validate()
        return self.request(method, params)

    def reject(self, request_id):
        self.rejections.append(request_id)

    def close(self):
        self.closed = True


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / "state")
        self.fake = FakeClient()
        self.app.client = self.fake
        self.app.connection["status"] = "connected"
        self.project = self.app.add_project({"name": "Project One", "path": str(self.root)})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def task(self):
        task = self.app.start_task({"project_id": self.project["id"], "title": "Implement feature",
                                   "instruction": "SYNTHETIC_PRIVATE_TASK_INSTRUCTION", "role": "backend_developer"})
        self.assertTrue(self.fake.started.wait(2))
        self.app.workers[-1].join(2)
        for _ in range(100):
            if self.app.tasks[task["id"]]["turn_id"]:
                return self.app.tasks[task["id"]]
            time.sleep(.005)
        self.fail("Task did not start")

    def event(self, method, **kwargs):
        self.app.on_message({"method": method, "params": {"threadId": "thread-one", "turnId": "turn-one", **kwargs}})

    def approval(self, task, rpc_id=17, method="item/commandExecution/requestApproval"):
        self.app.on_message({"id": rpc_id, "method": method, "params": {
            "threadId": task["thread_id"], "turnId": task["turn_id"],
            "command": "SYNTHETIC_PRIVATE_COMMAND", "reason": "SYNTHETIC_PRIVATE_REASON"}})
        return list(self.app.approvals.values())[-1]

    def test_empty_state_explicit_launch_scanned_conversation_persistence(self):
        self.assertEqual([], self.app.snapshot()["tasks"])
        self.assertEqual([], self.fake.requests)
        task = self.task()
        self.assertEqual("running", task["status"])
        self.assertEqual(["model/list", "thread/start", "turn/start"], [x[0] for x in self.fake.requests])
        self.assertEqual("on-request", self.fake.requests[1][1]["approvalPolicy"])
        self.assertEqual("user", self.fake.requests[1][1]["approvalsReviewer"])
        self.assertIs(False, self.fake.requests[1][1]["ephemeral"])
        self.assertTrue(self.fake.requests[1][1]["config"]["agents"]["enabled"])
        self.assertEqual(3, self.fake.requests[1][1]["config"]["agents"]["max_concurrent_threads_per_session"])
        self.assertEqual(set(self.app.roles), set(self.fake.requests[1][1]["config"]["agents"]) -
                         {"enabled", "max_concurrent_threads_per_session"})
        profile = self.fake.requests[1][1]["permissions"]
        self.assertFalse(self.fake.requests[1][1]["config"]["permissions"][profile]["network"]["enabled"])
        self.assertEqual({"/": "read", ":workspace_roots": {".": "write"}}, self.fake.requests[1][1]["config"]["permissions"][profile]["filesystem"])
        self.assertNotIn("permissions", self.fake.requests[2][1])
        self.assertNotIn("runtimeWorkspaceRoots", self.fake.requests[2][1])
        self.assertEqual("gpt-6.1-sol", self.fake.requests[2][1]["model"])
        self.assertNotIn("sandboxPolicy", self.fake.requests[2][1])
        self.assertNotIn("SYNTHETIC_PRIVATE_TASK_INSTRUCTION", json.dumps(self.app.snapshot()))
        self.assertEqual("SYNTHETIC_PRIVATE_TASK_INSTRUCTION", self.app.conversation(task["id"])["messages"][0]["text"])
        self.assertIn(b"SYNTHETIC_PRIVATE_TASK_INSTRUCTION", (self.root / "state/dashboard.sqlite3").read_bytes())
        self.assertEqual("unknown", task["cost"]["basis"])

    def test_cumulative_usage_duplicate_reroute_and_unknown_tier(self):
        task = self.task()
        self.assertIsNone(task["cost"]["credits"])
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})
        total = {"inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
                 "reasoningOutputTokens": 40, "totalTokens": 1100}
        for _ in range(2):
            self.event("thread/tokenUsage/updated", tokenUsage={"total": total})
        self.assertEqual(1000, task["usage"]["input_tokens"])
        self.assertAlmostEqual(.0655, task["cost"]["credits"])
        self.event("model/rerouted", toModel="gpt-6-astra", fromModel="gpt-6.1-sol")
        self.assertEqual("unknown", task["cost"]["basis"])
        total["cachedInputTokens"] = 2000
        self.event("thread/tokenUsage/updated", tokenUsage={"total": total})
        self.assertEqual(200, task["usage"]["cached_input_tokens"])

    def test_mixed_service_tiers_never_reprice_cumulative_tokens_as_standard(self):
        task = self.task()
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})
        total = {"inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
                 "reasoningOutputTokens": 40, "totalTokens": 1100}
        self.event("thread/tokenUsage/updated", tokenUsage={"total": total})
        self.assertEqual("estimated", task["cost"]["basis"])
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "priority"})
        self.assertIsNone(task["cost"]["credits"])
        doubled = {key: value * 2 for key, value in total.items()}
        self.event("thread/tokenUsage/updated", tokenUsage={"total": doubled})
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})
        self.event("thread/tokenUsage/updated", tokenUsage={"total": doubled})
        self.assertEqual(2200, task["usage"]["total_tokens"])
        self.assertEqual("unknown", task["cost"]["basis"])
        self.assertIsNone(task["cost"]["credits"])

    def test_unknown_consumed_tier_stays_unknown_after_default_is_observed(self):
        task = self.task()
        total = {"inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
                 "reasoningOutputTokens": 40, "totalTokens": 1100}
        self.event("thread/tokenUsage/updated", tokenUsage={"total": total})
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})
        self.event("thread/tokenUsage/updated", tokenUsage={"total": total})
        self.assertEqual("unknown", task["cost"]["basis"])
        self.assertIsNone(task["cost"]["credits"])

    def test_approval_scoped_decline_and_sensitive_details_withheld(self):
        task = self.task()
        approval = self.approval(task)
        self.assertEqual("waiting_approval", task["status"])
        snapshot = self.app.snapshot()
        self.assertEqual("Awaiting a human response", snapshot["tasks"][0]["blocker"])
        self.assertEqual("Kira Voss (Backend Developer) via Codex App Server", snapshot["approvals"][0]["requester"])
        self.assertEqual(["decline"], approval["available_decisions"])
        self.assertNotIn("SYNTHETIC_PRIVATE", json.dumps(self.app.snapshot()))
        for decision in ["accept", "acceptForSession", "cancel", {"acceptWithExecpolicyAmendment": {}}]:
            with self.assertRaises(ValueError):
                self.app.respond_approval(approval["id"], {"decision": decision})
        self.app.respond_approval(approval["id"], {"decision": "decline"})
        self.assertEqual([(17, {"decision": "decline"})], self.fake.responses)
        self.assertEqual("running", task["status"])
        with self.assertRaises(ValueError):
            self.app.respond_approval(approval["id"], {"decision": "decline"})

    def test_multiple_requests_resolution_completion_and_unsupported(self):
        task = self.task()
        first = self.approval(task, 1)
        second = self.approval(task, 2, "unknown/request")
        self.assertEqual([], second["available_decisions"])
        self.event("serverRequest/resolved", requestId=1)
        self.assertEqual("resolved", first["status"])
        self.assertEqual("waiting_approval", task["status"])
        self.event("turn/completed", turn={"id": "turn-one", "status": "completed"})
        self.assertEqual("unavailable", second["status"])
        self.assertEqual("completed", task["status"])
        self.assertFalse(self.app.pending)

    def test_disconnect_and_restart_do_not_replay_or_preserve_approvals(self):
        task = self.task()
        approval = self.approval(task)
        self.app.disconnected()
        self.assertEqual("unknown", task["status"])
        self.assertEqual("unavailable", approval["status"])
        self.assertFalse(self.app.pending)
        self.app.close()
        self.app = Dashboard(self.root / "state")
        self.assertEqual("unknown", self.app.tasks[task["id"]]["status"])
        self.assertIsNone(self.app.client)

    def test_turn_mismatch_unknown_request_and_hidden_plan(self):
        task = self.task()
        self.event("turn/plan/updated", plan=[{"step": "SYNTHETIC_PRIVATE_PLAN", "status": "inProgress"}])
        self.assertEqual([{"step": "Step 1", "status": "inProgress"}], task["plan"])
        self.event("turn/completed", turnId="wrong", turn={"id": "wrong", "status": "completed"})
        self.assertEqual("running", task["status"])
        self.app.on_message({"id": 12, "method": "unknown/request", "params": {"threadId": "unknown"}})
        self.assertEqual([12], self.fake.rejections)

    def test_active_project_conflict_and_invalid_role(self):
        self.task()
        for role in ["backend_developer", "arbitrary"]:
            with self.assertRaises(ValueError):
                self.app.start_task({"project_id": self.project["id"], "title": "More", "instruction": "Continue", "role": role})

    def test_safety_override_prevents_first_turn(self):
        original = self.fake.request
        def unsafe(method, params):
            response = original(method, params)
            if method == "thread/start":
                response["approvalsReviewer"] = "auto_review"
            return response
        self.fake.request = unsafe
        task = self.app.start_task({"project_id": self.project["id"], "title": "Guard", "instruction": "Do work", "role": "backend_developer"})
        for _ in range(100):
            if self.app.tasks[task["id"]]["status"] == "failed":
                break
            time.sleep(.005)
        self.assertEqual("failed", self.app.tasks[task["id"]]["status"])
        self.assertNotIn("turn/start", [x[0] for x in self.fake.requests])
        self.assertEqual("safety_mismatch", self.app.tasks[task["id"]]["diagnostics"][-1]["code"])

    def test_native_rejection_has_phase_specific_safe_persisted_diagnostics(self):
        original = self.fake.request
        def rejected(method, params):
            if method == "model/list":
                return original(method, params)
            raise RequestRejected(code="config_invalid")
        self.fake.request = rejected
        task = self.app.start_task({"project_id": self.project["id"], "title": "Failure details",
                                   "instruction": "Synthetic diagnostic request", "role": "chief_of_staff"})
        self.app.workers[-1].join(2)
        saved = self.app.tasks[task["id"]]
        self.assertEqual("failed", saved["status"])
        self.assertIsNone(saved["thread_id"])
        self.assertEqual("thread_start", saved["diagnostics"][0]["stage"])
        self.assertEqual("config_invalid", saved["diagnostics"][0]["code"])
        self.assertIn("configuration", saved["error"])
        self.assertEqual(saved["diagnostics"], self.app.store.load("task")[0]["diagnostics"])

    def test_parent_history_must_be_acknowledged_before_inference(self):
        original = self.fake.request
        for acknowledgement in (None, True, 0, "false"):
            with self.subTest(acknowledgement=acknowledgement):
                def malformed(method, params):
                    result = original(method, params)
                    if method == "thread/start":
                        if acknowledgement is None:
                            result["thread"].pop("ephemeral")
                        else:
                            result["thread"]["ephemeral"] = acknowledgement
                    return result
                self.fake.request = malformed
                task = self.app.start_task({"project_id": self.project["id"], "title": "History probe",
                                           "instruction": "Synthetic history probe", "role": "chief_of_staff"})
                self.app.workers[-1].join(2)
                saved = self.app.tasks[task["id"]]
                self.assertEqual("failed", saved["status"])
                self.assertIsNone(saved["thread_id"])
                self.assertEqual("safety_mismatch", saved["diagnostics"][-1]["code"])
                self.assertEqual("safety_check", saved["diagnostics"][-1]["stage"])
        self.assertNotIn("turn/start", [method for method, _ in self.fake.requests])
        self.assertFalse(self.app.owned_threads)

    def test_malformed_or_weaker_thread_response_never_starts_inference(self):
        variants = [None, {"networkAccess": False},
                    {"type": "workspaceWrite", "networkAccess": True, "writableRoots": [], "excludeSlashTmp": True, "excludeTmpdirEnvVar": True},
                    {"type": "workspaceWrite", "writableRoots": [], "excludeSlashTmp": True, "excludeTmpdirEnvVar": True},
                    {"type": "workspaceWrite", "networkAccess": False, "writableRoots": ["/"], "excludeSlashTmp": True, "excludeTmpdirEnvVar": True}]
        original = self.fake.request
        for sandbox in variants:
            def malformed(method, params):
                result = original(method, params)
                if method == "thread/start":
                    result["sandbox"] = sandbox
                return result
            self.fake.request = malformed
            task = self.app.start_task({"project_id": self.project["id"], "title": "Safety probe",
                                       "instruction": "Synthetic safety probe", "role": "backend_developer"})
            self.app.workers[-1].join(2)
            self.assertEqual("failed", self.app.tasks[task["id"]]["status"])
            self.assertEqual("safety_mismatch", self.app.tasks[task["id"]]["diagnostics"][-1]["code"])
        self.assertNotIn("turn/start", [x[0] for x in self.fake.requests])

    def test_unsupported_model_is_diagnosed_without_creating_thread(self):
        self.app.roles["backend_developer"]["model"] = "unavailable-synthetic-model"
        task = self.app.start_task({"project_id": self.project["id"], "title": "Unsupported model",
                                   "instruction": "Synthetic model check", "role": "backend_developer"})
        self.app.workers[-1].join(2)
        record = self.app.tasks[task["id"]]
        self.assertEqual("failed", record["status"])
        self.assertEqual("model_check", record["diagnostics"][-1]["stage"])
        self.assertEqual("model_unavailable", record["diagnostics"][-1]["code"])
        self.assertEqual(["model/list"], [method for method, _ in self.fake.requests])

    def test_followup_retains_native_model_and_sticky_validated_permission_profile(self):
        task = self.task()
        options = self.app._turn_options(task)
        self.assertEqual("gpt-6.1-sol", options["model"])
        self.assertTrue(task["permission_profile"].startswith("dashboard-local-"))
        self.assertNotIn("permissions", options)
        self.assertNotIn("runtimeWorkspaceRoots", options)
        self.assertNotIn("sandboxPolicy", options)
        self.assertEqual("gpt-6-luna", self.app.roles["technical_writer"]["model"])
        self.assertEqual("gpt-6-luna", self.app.roles["technical_writer"]["profile_model"])

    def test_native_execution_error_has_safe_category_without_raw_payload(self):
        task = self.task()
        self.event("error", willRetry=False, error={"message": "SYNTHETIC_PRIVATE_UPSTREAM", "codexErrorInfo": "unauthorized"})
        self.assertEqual("authentication_required", task["diagnostics"][-1]["code"])
        self.assertNotIn("SYNTHETIC_PRIVATE_UPSTREAM", json.dumps(self.app.snapshot()))

    def test_started_turn_lost_response_unknown_in_both_disconnect_orders(self):
        for callback_first in (False, True):
            with self.subTest(callback_first=callback_first):
                app = Dashboard(self.root / ("callback-first" if callback_first else "exception-first"))
                client = FakeClient()
                app.client = client
                app.connection["status"] = "connected"
                project = app.add_project({"name": "Race fixture", "path": str(self.root)})
                original = client.request
                def lost_response(method, params):
                    response = original(method, params)
                    if method == "turn/start":
                        app.on_message({"method": "turn/started", "params": {
                            "threadId": "thread-one", "turn": {"id": "turn-one", "status": "inProgress"}}})
                        app.on_message({"id": 19, "method": "item/commandExecution/requestApproval", "params": {
                            "threadId": "thread-one", "turnId": "turn-one"}})
                        client.closed = True
                        if callback_first:
                            app.disconnected()
                        raise ProtocolError("Codex response was lost")
                    return response
                client.request = lost_response
                try:
                    task = app.start_task({"project_id": project["id"], "title": "Lost response",
                                           "instruction": "Synthetic objective", "role": "backend_developer"})
                    app.workers[-1].join(2)
                    self.assertFalse(app.workers[-1].is_alive())
                    self.assertEqual("unknown", app.tasks[task["id"]]["status"])
                    if not callback_first:
                        app.disconnected()
                    self.assertEqual("unknown", app.tasks[task["id"]]["status"])
                    self.assertFalse(app.pending)
                    self.assertTrue(all(a["status"] == "unavailable" for a in app.approvals.values()))
                    self.assertEqual(1, [x[0] for x in client.requests].count("turn/start"))
                finally:
                    app.close()

    def test_explicit_launch_rejection_distinct_from_ambiguous_transport_error(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                app = Dashboard(self.root / ("rejected" if explicit else "ambiguous"))
                client = FakeClient()
                app.client = client
                app.connection["status"] = "connected"
                project = app.add_project({"name": "Error fixture", "path": str(self.root)})
                original = client.request
                def reject_turn(method, params):
                    response = original(method, params)
                    if method == "turn/start":
                        if explicit:
                            raise RequestRejected("Codex explicitly rejected the request")
                        raise ProtocolError("Response missing; connection may still look open")
                    return response
                client.request = reject_turn
                try:
                    task = app.start_task({"project_id": project["id"], "title": "Launch error",
                                           "instruction": "Synthetic objective", "role": "backend_developer"})
                    app.workers[-1].join(2)
                    self.assertEqual("failed" if explicit else "unknown", app.tasks[task["id"]]["status"])
                finally:
                    app.close()

    def test_overlapping_project_roots_block_both_orders_but_allow_siblings(self):
        for child_first in (False, True):
            with self.subTest(child_first=child_first):
                suffix = "child-first" if child_first else "parent-first"
                parent = self.root / suffix
                child = parent / "child"
                sibling = self.root / (suffix + "-sibling")
                child.mkdir(parents=True)
                sibling.mkdir()
                outer = self.app.add_project({"name": "Parent", "path": str(parent)})
                inner = self.app.add_project({"name": "Child", "path": str(child)})
                other = self.app.add_project({"name": "Sibling", "path": str(sibling)})
                first, second = (inner, outer) if child_first else (outer, inner)
                def start(project):
                    return self.app.start_task({"project_id": project["id"], "title": "Scoped work",
                                                "instruction": "Synthetic objective", "role": "backend_developer"})
                task = start(first)
                with self.assertRaises(ValueError):
                    start(second)
                sibling_task = start(other)
                for worker in self.app.workers:
                    worker.join(2)
                self.assertEqual("running", self.app.tasks[sibling_task["id"]]["status"])
                # End these fixtures before testing the opposite ordering and active cap.
                self.app.tasks[task["id"]]["status"] = "completed"
                self.app.tasks[sibling_task["id"]]["status"] = "completed"

    def test_http_origin_host_json_and_routing_boundaries(self):
        server = make_server(self.app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        def request(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            result = response.status, response.read(), dict(response.getheaders())
            conn.close()
            return result
        try:
            status, body, headers = request("GET", "/api/state")
            self.assertEqual(200, status)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(403, request("GET", "/api/state", headers={"Host": "attacker.example"})[0])
            self.assertEqual(403, request("GET", "/api/state", headers={"Origin": "https://attacker.example"})[0])
            self.assertEqual(403, request("POST", "/api/projects", "{}", {"Content-Type": "application/json"})[0])
            same = {"Origin": "http://127.0.0.1:" + str(port), "Content-Type": "application/json"}
            self.assertEqual(400, request("POST", "/api/projects", '{"name":"a","name":"b"}', same)[0])
            self.assertEqual(400, request("POST", "/api/projects", '[]', same)[0])
            self.assertEqual(404, request("POST", "/api/rpc", '{}', same)[0])
            self.assertEqual(413, request("POST", "/api/projects", ' ' * 65537, same)[0])
            self.assertEqual(404, request("GET", "/../SECURITY.md")[0])
            self.assertEqual(404, request("GET", "/.local/dashboard.sqlite3")[0])
            self.assertFalse(self.fake.requests)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


class StoreSecurityTests(unittest.TestCase):
    def test_private_permissions_and_symlink_or_hardlink_rejection(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            root = Path(tmp).resolve()
            store = Store(root / "state")
            self.assertEqual(0o700, stat.S_IMODE((root / "state").stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE((root / "state/dashboard.sqlite3").stat().st_mode))
            store.close()
            (root / "alias").symlink_to(root / "state", target_is_directory=True)
            with self.assertRaises(ValueError):
                Store(root / "alias/nested")
            (root / "linked").mkdir()
            original = root / "unrelated"
            original.write_text("not a database")
            original.chmod(0o640)
            os.link(original, root / "linked/dashboard.sqlite3")
            with self.assertRaises(ValueError):
                Store(root / "linked")
            self.assertEqual(0o640, stat.S_IMODE(original.stat().st_mode))


if __name__ == "__main__":
    unittest.main()

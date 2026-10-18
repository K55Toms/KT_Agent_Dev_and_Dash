"""Independent HTTP acceptance scenarios; never invoke a real Codex process."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from dashboard.server import Dashboard, make_server


class ManagedRunFixture:
    def __init__(self, message, disconnect):
        self.message = message
        self.disconnect = disconnect
        self.closed = False
        self.calls = []
        self.answers = []
        self.sequence = 0

    def connect(self):
        self.calls.append(("initialize", {}))
        return {}

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "model/list":
            return {"data": [{"model": m, "supportedReasoningEfforts": [{"reasoningEffort": effort} for effort in ("low", "medium", "high", "xhigh")]} for m in ("gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra")], "nextCursor": None}
        if method == "thread/start":
            self.sequence += 1
            return {"thread": {"id": f"fixture-thread-{self.sequence}"},
                    "model": params["model"], "serviceTier": "default",
                    "cwd": params["cwd"], "approvalPolicy": "on-request",
                    "approvalsReviewer": "user",
                    "runtimeWorkspaceRoots": params["runtimeWorkspaceRoots"],
                    "activePermissionProfile": {"id": params["permissions"], "extends": None},
                    "sandbox": {"type": "workspaceWrite", "networkAccess": False, "writableRoots": [],
                                "excludeSlashTmp": True, "excludeTmpdirEnvVar": True}}
        if method == "turn/start":
            return {"turn": {"id": params["threadId"] + "-turn", "status": "inProgress"}}
        return {}

    def respond(self, request_id, result):
        self.answers.append((request_id, result))

    def reject(self, request_id):
        self.answers.append((request_id, "rejected"))

    def close(self):
        self.closed = True


class HTTPAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.clients = []

        def factory(message, disconnect):
            client = ManagedRunFixture(message, disconnect)
            self.clients.append(client)
            return client

        self.factory = factory
        self.app = Dashboard(self.root / "state", client_factory=factory)
        self.server = make_server(self.app, 0)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.app.start()
        self.wait_for(lambda: self.state()["connection"]["status"] == "connected")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(2)
        self.app.close()
        self.temp.cleanup()

    def http(self, method, path, data=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, None if data is None else json.dumps(data), headers)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def state(self):
        status, body = self.http("GET", "/api/state")
        self.assertEqual(200, status)
        return json.loads(body)

    def post(self, path, data, status=200):
        actual, body = self.http("POST", path, data)
        self.assertEqual(status, actual, body)
        return json.loads(body)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        self.fail("Expected observable state did not arrive within three seconds")

    def project(self, name):
        directory = self.root / name
        directory.mkdir()
        return self.post("/api/projects", {"name": name, "path": str(directory)})

    def launch(self, project):
        task = self.post("/api/tasks", {"project_id": project["id"], "title": "Synthetic task",
                        "role": "backend_developer", "instruction": "Synthetic nonfunctional objective"})
        self.wait_for(lambda: any(t["id"] == task["id"] and t["turn_id"] for t in self.state()["tasks"]))
        return next(t for t in self.state()["tasks"] if t["id"] == task["id"])

    def emit(self, task, method, **params):
        self.clients[-1].message({"method": method, "params": {
            "threadId": task["thread_id"], "turnId": task["turn_id"], **params}})

    def test_opening_and_registering_multiple_projects_starts_no_inference(self):
        self.assertEqual([], self.state()["tasks"])
        self.assertEqual(200, self.http("GET", "/")[0])
        one, two = self.project("one"), self.project("two")
        state = self.state()
        self.assertEqual({one["id"], two["id"]}, {p["id"] for p in state["projects"]})
        self.assertEqual(["initialize"], [method for method, _ in self.clients[0].calls])
        self.post("/api/tasks", {"project_id": "unregistered", "title": "Synthetic task",
                  "role": "backend_developer", "instruction": "Synthetic objective"}, status=400)
        self.assertEqual([], self.state()["tasks"])
        self.assertEqual(["initialize"], [method for method, _ in self.clients[0].calls])

    def test_two_project_usage_coverage_and_authoritative_completion(self):
        one, two = self.project("one"), self.project("two")
        first, second = self.launch(one), self.launch(two)
        for task in (first, second):
            self.assertIsNone(task["usage"])
            self.assertEqual("unknown", task["cost"]["basis"])
            self.assertIsNone(task["cost"]["credits"])
        usage = {"inputTokens": 100, "cachedInputTokens": 20, "outputTokens": 40,
                 "reasoningOutputTokens": 10, "totalTokens": 140}
        for _ in range(2):
            self.emit(first, "thread/tokenUsage/updated", tokenUsage={"total": usage})
        self.post(f"/api/tasks/{first['id']}/interrupt", {})
        tasks = {t["id"]: t for t in self.state()["tasks"]}
        self.assertEqual("running", tasks[first["id"]]["status"], "An interrupt request is not completion evidence")
        self.assertEqual(140, tasks[first["id"]]["usage"]["total_tokens"])
        self.assertEqual("estimated", tasks[first["id"]]["cost"]["basis"])
        self.assertAlmostEqual(.01405, tasks[first["id"]]["cost"]["credits"])
        self.assertIsNone(tasks[second["id"]]["cost"]["credits"])
        self.assertEqual({one["id"], two["id"]}, {t["project_id"] for t in tasks.values()})
        self.emit(first, "turn/completed", turn={"id": first["turn_id"], "status": "interrupted"})
        self.assertEqual("interrupted", next(t for t in self.state()["tasks"] if t["id"] == first["id"])["status"])

    def test_native_request_decline_permissions_disconnect_and_recovery(self):
        task = self.launch(self.project("one"))
        self.clients[0].message({"id": 29, "method": "item/fileChange/requestApproval", "params": {
            "threadId": task["thread_id"], "turnId": task["turn_id"],
            "reason": "Synthetic confidential details", "changes": "Synthetic confidential patch"}})
        approval = self.state()["approvals"][0]
        self.assertEqual(["decline"], approval["available_decisions"])
        self.assertNotIn("Synthetic confidential", json.dumps(self.state()))
        path = f"/api/approvals/{approval['id']}/respond"
        self.post(path, {"decision": "accept"}, status=400)
        self.assertEqual([], self.clients[0].answers)
        self.post(path, {"decision": "decline"})
        self.assertEqual([(29, {"decision": "decline"})], self.clients[0].answers)
        self.post(path, {"decision": "decline"}, status=400)
        self.clients[0].message({"id": 30, "method": "item/tool/requestUserInput", "params": {
            "threadId": task["thread_id"], "turnId": task["turn_id"]}})
        self.app.wait_conversations()
        pending = self.app.conversation(task["id"])["questions"][0]
        self.assertEqual("unavailable", pending["status"])
        self.assertEqual([], pending["questions"])
        self.post(f"/api/questions/{pending['id']}/respond", {"answers": {}}, status=400)
        self.clients[0].disconnect()
        state = self.state()
        self.assertEqual("disconnected", state["connection"]["status"])
        self.assertEqual("unknown", state["tasks"][0]["status"])
        self.assertEqual([], state["questions"])
        self.assertEqual("unavailable", self.app.conversation(task["id"])["questions"][0]["status"])
        self.post(f"/api/questions/{pending['id']}/respond", {"answers": {}}, status=400)
        self.post(f"/api/tasks/{task['id']}/interrupt", {}, status=400)
        self.app.close()
        self.app = Dashboard(self.root / "state", client_factory=self.factory)
        self.server.dashboard = self.app
        self.app.start()
        self.wait_for(lambda: self.state()["connection"]["status"] == "connected")
        recovered = self.state()
        self.assertEqual("unknown", recovered["tasks"][0]["status"])
        self.assertEqual(1, len(recovered["projects"]))
        self.assertEqual(["initialize"], [method for method, _ in self.clients[-1].calls])
        self.assertEqual([], self.clients[-1].answers)


if __name__ == "__main__":
    unittest.main()

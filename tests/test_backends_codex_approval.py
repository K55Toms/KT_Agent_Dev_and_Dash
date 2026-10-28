from pathlib import Path
import tempfile
import threading
import time
import unittest

from dashboard.backends.base import ApprovalRequest
from dashboard.backends.codex import CodexBackend, codex_approval_result
from dashboard.codex_client import ProtocolError
from dashboard.server import Dashboard, now, unknown_cost
from dashboard.settings import SettingsStore
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient


class Recorder:
    def __init__(self, error=None):
        self.responses = []
        self.error = error

    def respond(self, rpc_id, result):
        if self.error:
            raise self.error
        self.responses.append((rpc_id, result))


def request(kind="command", params=None, responder=None):
    return ApprovalRequest(kind, "native/method", ("thread", "turn", "item"), params or {},
                           ("accept", "decline", "cancel"), responder)


class ResultShapeTests(unittest.TestCase):
    def test_result_shapes_for_each_kind_and_decision(self):
        permissions = {"network": {"enabled": True}}
        form = {"name": "synthetic"}
        answers = {"choice": ["Accept"]}
        accept_params = {"context": {"permissions": permissions, "mode": "form"},
                         "content": form, "answers": answers}
        cases = [
            ("command", {"accept": {"decision": "accept"}, "decline": {"decision": "decline"},
                             "cancel": {"decision": "cancel"}}),
            ("file_change", {"accept": {"decision": "accept"}, "decline": {"decision": "decline"},
                                 "cancel": {"decision": "cancel"}}),
            ("permissions", {"accept": {"permissions": permissions, "scope": "turn"},
                                 "decline": {"permissions": {}, "scope": "turn"},
                                 "cancel": {"permissions": {}, "scope": "turn"}}),
            ("elicitation", {"accept": {"action": "accept", "content": form},
                                 "decline": {"action": "decline", "content": None},
                                 "cancel": {"action": "cancel", "content": None}}),
            ("approval_question", {"accept": {"answers": {"choice": {"answers": ["Accept"]}}}}),
        ]
        for kind, expected in cases:
            for decision, result in expected.items():
                # Only an accept carries reviewed context; a decline or cancel carries none.
                params = accept_params if decision == "accept" else {}
                with self.subTest(kind=kind, decision=decision):
                    self.assertEqual(result, codex_approval_result(kind, decision, params))

    def test_question_decline_or_cancel_has_no_native_shape(self):
        for decision in ("decline", "cancel"):
            with self.subTest(decision=decision):
                with self.assertRaises(ValueError):
                    codex_approval_result("approval_question", decision, {})

    def test_url_elicitation_accepts_with_empty_content(self):
        params = {"context": {"mode": "url"}, "content": {"ignored": 1}}
        self.assertEqual({"action": "accept", "content": {}}, codex_approval_result("elicitation", "accept", params))

    def test_result_does_not_alias_reviewed_inputs(self):
        permissions = {"network": {"enabled": True}}
        form = {"name": "synthetic"}
        answers = {"choice": ["Accept"]}
        granted = codex_approval_result("permissions", "accept", {"context": {"permissions": permissions}})
        filled = codex_approval_result("elicitation", "accept", {"context": {"mode": "form"}, "content": form})
        answered = codex_approval_result("approval_question", "accept", {"answers": answers})
        permissions["network"]["enabled"] = False
        form["name"] = "changed"
        answers["choice"].append("extra")
        self.assertEqual({"network": {"enabled": True}}, granted["permissions"])
        self.assertEqual({"name": "synthetic"}, filled["content"])
        self.assertEqual(["Accept"], answered["answers"]["choice"]["answers"])

    def test_str_subclass_decision_is_refused(self):
        class Accept(str):
            pass
        for kind in ("command", "permissions", "elicitation", "approval_question"):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    codex_approval_result(kind, Accept("accept"), {})
        client = Recorder()
        with self.assertRaises(ValueError):
            CodexBackend(lambda: client).answer_approval(request(responder=(client, 1)), Accept("accept"))
        self.assertEqual([], client.responses)

    def test_unrecognised_or_missing_decision_has_no_result(self):
        for kind in ("command", "permissions", "elicitation", "approval_question"):
            for decision in (None, "", "Accept", "accept ", "acceptForSession", "approve", 1, ["accept"]):
                with self.subTest(kind=kind, decision=decision):
                    with self.assertRaises(ValueError):
                        codex_approval_result(kind, decision, {})


class AnswerApprovalTests(unittest.TestCase):
    def test_answer_approval_writes_through_responder(self):
        client = Recorder()
        backend = CodexBackend(lambda: None)
        self.assertIsNone(backend.answer_approval(request(responder=(client, 7)), "decline"))
        self.assertEqual([(7, {"decision": "decline"})], client.responses)

    def test_answer_approval_shapes_by_kind_and_params(self):
        client = Recorder()
        backend = CodexBackend(lambda: None)
        backend.answer_approval(request("permissions", {"context": {"permissions": {"fs": {}}}}, (client, 3)), "accept")
        backend.answer_approval(request("elicitation", {}, (client, 4)), "cancel")
        self.assertEqual([(3, {"permissions": {"fs": {}}, "scope": "turn"}),
                          (4, {"action": "cancel", "content": None})], client.responses)

    def test_answer_approval_uses_the_client_in_the_responder_not_get_client(self):
        validated, current = Recorder(), Recorder()
        backend = CodexBackend(lambda: current)
        backend.answer_approval(request(responder=(validated, 9)), "accept")
        self.assertEqual([(9, {"decision": "accept"})], validated.responses)
        self.assertEqual([], current.responses)

    def test_answer_approval_never_asks_get_client(self):
        def boom():
            raise AssertionError("get_client must not be called")
        client = Recorder()
        CodexBackend(boom).answer_approval(request(responder=(client, 1)), "cancel")
        self.assertEqual([(1, {"decision": "cancel"})], client.responses)

    def test_unknown_decision_never_responds(self):
        client = Recorder()
        backend = CodexBackend(lambda: client)
        for decision in (None, "", "Accept", "acceptForSession", "approve", 0):
            for kind in ("command", "permissions", "elicitation", "approval_question"):
                with self.subTest(kind=kind, decision=decision):
                    with self.assertRaises(ValueError):
                        backend.answer_approval(request(kind, {}, (client, 5)), decision)
        self.assertEqual([], client.responses)

    def test_malformed_responder_never_responds(self):
        client = Recorder()
        backend = CodexBackend(lambda: client)
        for responder in (None, client, (client,), (client, 1, 2), []):
            with self.subTest(responder=responder):
                with self.assertRaises(ValueError):
                    backend.answer_approval(request(responder=responder), "accept")
        self.assertEqual([], client.responses)

    def test_guidance_kind_writes_the_plain_decision_shape(self):
        client = Recorder()
        backend = CodexBackend(lambda: None)
        for mode in ("decline", "cancel"):
            backend.answer_approval(request("guidance", {}, (client, 6)), mode)
        self.assertEqual([(6, {"decision": "decline"}), (6, {"decision": "cancel"})], client.responses)
        self.assertEqual({"decision": "decline"}, codex_approval_result("guidance", "decline", {}))

    def test_answer_failure_propagates(self):
        for error in (ProtocolError("write failed"), BrokenPipeError("closed"), OSError("down")):
            with self.subTest(error=type(error).__name__):
                client = Recorder(error)
                with self.assertRaises(type(error)) as caught:
                    CodexBackend(lambda: client).answer_approval(request(responder=(client, 2)), "accept")
                self.assertIs(error, caught.exception)


class ConsumeBeforeRespondTests(unittest.TestCase):
    """Review Focus 8: authority is consumed and persisted BEFORE the native write.

    The client's respond() records what the dashboard looks like at the instant of the
    write, so a writer that responds first and consumes afterwards fails these tests.
    """
    CONSUMED = {"pending": False, "status": "unavailable", "decisions": [],
                "stored_status": "unavailable", "stored_decisions": []}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.app = Dashboard(self.root / "state", policy_provider=SyntheticPolicy())
        self.app.settings = SettingsStore(self.root, config_path=self.root / "settings.toml")
        self.fake = FakeClient()
        self.app.client = self.fake
        self.app.connection["status"] = "connected"
        project = self.app.add_project({"name": "Ordering fixture", "path": str(self.root)})
        self.task = {"id": "b" * 32, "project_id": project["id"], "title": "Ordering test",
                     "role": "backend_developer", "model": "gpt-6.1-sol", "reasoning": "high",
                     "status": "running", "thread_id": "native-root", "turn_id": "native-turn",
                     "plan": [], "usage": None, "cost": unknown_cost(), "error": None,
                     "created_at": now(), "updated_at": now()}
        self.app.tasks[self.task["id"]] = self.task
        self.app.store.put("task", self.task)
        self.app._register_thread("native-root", self.task["id"])
        self.app.owned_threads["native-root"].update(current_turn="native-turn", turns={"native-turn"})
        self.rpc = 0
        self.observations = []

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def native(self, method, **params):
        self.rpc += 1
        base = {"threadId": "native-root", "turnId": "native-turn", "itemId": "item-" + str(self.rpc),
                "startedAtMs": 1, "reason": "Run the checked synthetic request"}
        self.app.on_message({"id": self.rpc, "method": method, "params": {**base, **params}})
        approval = list(self.app.approvals.values())[-1]
        self.observe(approval)
        return approval

    def command(self):
        return self.native("item/commandExecution/requestApproval", command="/usr/bin/true", cwd=str(self.root),
                           availableDecisions=["accept", "decline", "cancel"])

    def permission(self):
        return self.native("item/permissions/requestApproval", cwd=str(self.root),
                           permissions={"network": {"enabled": True}})

    def observe(self, approval):
        approval_id = approval["id"]
        original = FakeClient.respond.__get__(self.fake)

        def respond(request_id, result):
            stored = [row for row in self.app.store.load("approval") if row["id"] == approval_id][-1]
            self.observations.append({
                "pending": approval_id in self.app.pending,
                "status": self.app.approvals[approval_id]["status"],
                "decisions": list(self.app.approvals[approval_id]["available_decisions"]),
                "stored_status": stored["status"], "stored_decisions": list(stored["available_decisions"])})
            original(request_id, result)
        self.fake.respond = respond

    def assert_consumed_at_write(self, writes=1):
        self.assertEqual(writes, len(self.fake.responses))
        self.assertEqual([self.CONSUMED] * writes, self.observations)

    def test_accept_consumes_before_the_native_write(self):
        approval = self.command()
        review = self.app.review_approval(approval["id"])
        self.app.respond_approval(approval["id"], {"decision": "accept", "review_id": review["review_id"]})
        self.assertEqual([(1, {"decision": "accept"})], self.fake.responses)
        self.assert_consumed_at_write()
        self.assertEqual("resolved", self.app.store.load("approval")[-1]["status"])

    def test_decline_consumes_before_the_native_write(self):
        approval = self.command()
        self.app.respond_approval(approval["id"], {"decision": "decline"})
        self.assertEqual([(1, {"decision": "decline"})], self.fake.responses)
        self.assert_consumed_at_write()

    def test_project_policy_accept_consumes_before_the_native_write(self):
        config = self.app.settings.load()
        config["project_approval_modes"] = {self.task["project_id"]: "automatic"}
        self.app.save_settings(config)
        approval = self.command()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and approval["status"] != "resolved":
            time.sleep(.01)
        self.assertEqual("project_policy", approval["decision"]["source"])
        self.assertEqual([(1, {"decision": "accept"})], self.fake.responses)
        self.assert_consumed_at_write()

    def test_guidance_consumes_before_the_native_write(self):
        for mode in ("decline", "cancel"):
            with self.subTest(mode=mode):
                self.fake.responses.clear()
                self.observations.clear()
                self.fake.request = lambda *_: {"turnId": "native-turn"}
                approval = self.command()
                result = self.app.request_approval_alternative(approval["id"], {"text": "Smaller please.", "mode": mode})
                self.assertTrue(result["guidance_sent"])
                self.assertEqual([(self.rpc, {"decision": mode})], self.fake.responses)
                self.assert_consumed_at_write()

    def test_guidance_on_a_permissions_request_answers_the_plain_decision_shape(self):
        # Old behaviour kept on purpose: guidance never used the permissions shape.
        approval = self.permission()
        self.fake.request = lambda *_: {"turnId": "native-turn"}
        self.app.request_approval_alternative(approval["id"], {"text": "Narrower grant please."})
        self.assertEqual([(self.rpc, {"decision": "decline"})], self.fake.responses)
        self.assert_consumed_at_write()


if __name__ == "__main__":
    unittest.main()

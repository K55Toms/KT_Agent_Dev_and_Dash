import unittest

from dashboard.backends.base import ApprovalRequest
from dashboard.backends.codex import CodexBackend, codex_approval_result
from dashboard.codex_client import ProtocolError


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
            ("command", {}, {"accept": {"decision": "accept"}, "decline": {"decision": "decline"},
                             "cancel": {"decision": "cancel"}}),
            ("file_change", {}, {"accept": {"decision": "accept"}, "decline": {"decision": "decline"},
                                 "cancel": {"decision": "cancel"}}),
            ("permissions", {}, {"accept": {"permissions": permissions, "scope": "turn"},
                                 "decline": {"permissions": {}, "scope": "turn"},
                                 "cancel": {"permissions": {}, "scope": "turn"}}),
            ("elicitation", {}, {"accept": {"action": "accept", "content": form},
                                 "decline": {"action": "decline", "content": None},
                                 "cancel": {"action": "cancel", "content": None}}),
            ("approval_question", {}, {"accept": {"answers": {"choice": {"answers": ["Accept"]}}}}),
        ]
        for kind, _, expected in cases:
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

    def test_answer_failure_propagates(self):
        for error in (ProtocolError("write failed"), BrokenPipeError("closed"), OSError("down")):
            with self.subTest(error=type(error).__name__):
                client = Recorder(error)
                with self.assertRaises(type(error)) as caught:
                    CodexBackend(lambda: client).answer_approval(request(responder=(client, 2)), "accept")
                self.assertIs(error, caught.exception)


if __name__ == "__main__":
    unittest.main()

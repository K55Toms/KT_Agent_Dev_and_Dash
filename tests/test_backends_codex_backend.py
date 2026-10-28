from contextlib import contextmanager
import unittest

from dashboard.backends.base import NeutralEvent
from dashboard.backends.codex import CODEX_CAPABILITIES, CodexBackend
from dashboard.codex_client import ProtocolError
from tests.test_dashboard_backend import FakeClient


class PagedClient(FakeClient):
    """Offers a model/list page for every cursor, forever."""

    def request(self, method, params):
        if method == "model/list":
            self.requests.append((method, params))
            page = len(self.requests)
            return {"data": [{"model": "m" + str(page)}], "nextCursor": "c" + str(page)}
        return super().request(method, params)


class GuardedRecorder(FakeClient):
    def __init__(self):
        super().__init__()
        self.guarded = []

    def request_guarded(self, method, params, guard, timeout=30):
        self.guarded.append((method, params, guard))
        return {"turn": {"id": "turn-guarded"}}


class CodexBackendTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.backend = CodexBackend(lambda: self.client)

    def test_capabilities_and_translate(self):
        self.assertIs(self.backend.capabilities, CODEX_CAPABILITIES)
        event = self.backend.translate({"method": "turn/started", "params": {"threadId": "t", "turn": {"id": "u"}}})
        self.assertIsInstance(event, NeutralEvent)
        self.assertEqual(event.kind, "turn_started")

    def test_start_thread_sends_thread_start_with_same_params(self):
        params = {"cwd": "/p", "runtimeWorkspaceRoots": ["/p"], "permissions": "profile-one", "ephemeral": False}
        response = self.backend.start_thread(params)
        self.assertEqual(self.client.requests, [("thread/start", params)])
        self.assertIs(self.client.requests[0][1], params)
        self.assertEqual(response["thread"]["id"], "thread-one")

    def test_start_turn_with_guard_uses_request_guarded(self):
        client = self.client = GuardedRecorder()

        @contextmanager
        def guard():
            yield lambda: None

        params = {"threadId": "thread-one", "input": []}
        response = self.backend.start_turn(params, guard)
        self.assertEqual(client.requests, [])
        self.assertEqual(len(client.guarded), 1)
        method, sent, passed_guard = client.guarded[0]
        self.assertEqual((method, sent), ("turn/start", params))
        self.assertIs(passed_guard, guard)
        self.assertEqual(response["turn"]["id"], "turn-guarded")

    def test_start_thread_with_guard_uses_request_guarded(self):
        client = self.client = GuardedRecorder()
        guard = object()
        self.backend.start_thread({"cwd": "/p"}, guard)
        self.assertEqual([(m, p) for m, p, _ in client.guarded], [("thread/start", {"cwd": "/p"})])
        self.assertEqual(client.requests, [])

    def test_guard_without_request_guarded_refuses_and_sends_nothing(self):
        class Plain:
            requests = []

            def request(self, method, params):
                self.requests.append(method)

        self.client = Plain()
        with self.assertRaisesRegex(ValueError, "Recovery requires guarded native dispatch"):
            self.backend.start_turn({"threadId": "t"}, lambda: None)
        self.assertEqual(Plain.requests, [])

    def test_start_turn_without_guard_uses_request(self):
        params = {"threadId": "thread-one", "input": []}
        response = self.backend.start_turn(params)
        self.assertEqual(self.client.requests, [("turn/start", params)])
        self.assertEqual(response["turn"]["id"], "turn-one")

    def test_steer_and_interrupt_send_native_methods(self):
        steer = {"threadId": "t", "expectedTurnId": "u", "input": [{"type": "text", "text": "x"}]}
        self.backend.steer(steer)
        self.assertIsNone(self.backend.interrupt("t", "u"))
        self.assertEqual(self.client.requests, [("turn/steer", steer),
                                                ("turn/interrupt", {"threadId": "t", "turnId": "u"})])

    def test_list_models_collects_a_single_page(self):
        models = self.backend.list_models()
        self.assertEqual([m["model"] for m in models], ["gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra"])
        self.assertEqual(self.client.requests, [("model/list", {"includeHidden": True, "limit": 100, "cursor": None})])

    def test_list_models_collects_pages_up_to_ten(self):
        self.client = PagedClient()
        models = self.backend.list_models()
        self.assertEqual(len(self.client.requests), 10)
        self.assertEqual([m["model"] for m in models], ["m" + str(i) for i in range(1, 11)])
        self.assertEqual([p["cursor"] for _, p in self.client.requests], [None] + ["c" + str(i) for i in range(1, 10)])

    def test_list_models_stops_when_the_predicate_is_satisfied(self):
        self.client = PagedClient()
        models = self.backend.list_models(lambda collected: any(m["model"] == "m3" for m in collected))
        self.assertEqual(len(self.client.requests), 3)
        self.assertEqual(len(models), 3)

    def test_list_models_rejects_invalid_catalog_and_cursor(self):
        self.client.request = lambda method, params: ["not", "a", "dict"]
        with self.assertRaisesRegex(ValueError, "Invalid model catalog"):
            self.backend.list_models()
        self.client.request = lambda method, params: {"data": [], "nextCursor": 7}
        with self.assertRaisesRegex(ValueError, "Invalid model cursor"):
            self.backend.list_models()
        self.client.request = lambda method, params: {"data": [], "nextCursor": "x" * 4097}
        with self.assertRaisesRegex(ValueError, "Invalid model cursor"):
            self.backend.list_models()

    def test_backend_follows_client_reassignment(self):
        second = FakeClient()
        self.client = second
        self.backend.steer({"threadId": "t", "expectedTurnId": "u", "input": []})
        self.assertEqual(len(second.requests), 1)

    def test_missing_client_raises_protocol_error(self):
        self.client = None
        with self.assertRaises(ProtocolError):
            self.backend.interrupt("t", "u")

    def test_backend_does_not_close_client(self):
        self.backend.start_thread({"cwd": "/p", "runtimeWorkspaceRoots": [], "permissions": "p"})
        self.backend.start_turn({"threadId": "t"})
        self.backend.steer({"threadId": "t"})
        self.backend.interrupt("t", "u")
        self.backend.list_models()
        self.assertFalse(self.client.closed)


if __name__ == "__main__":
    unittest.main()

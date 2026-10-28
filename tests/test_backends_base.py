"""Neutral backend types and the no-provider placeholder."""
import dataclasses
import unittest

from dashboard.backends.base import (
    ApprovalRequest, Backend, Capabilities, EVENT_KINDS, NeutralEvent, NO, NoBackend,
    ProviderUnavailable, UNCONFIRMED, YES)

FIELDS = ("provider", "guidance_while_running", "subagent_questions", "plan", "recovery",
          "assessment", "approval_alternative")


class BackendsBaseTests(unittest.TestCase):
    def test_capabilities_public_is_plain_dict(self):
        caps = Capabilities("x", YES, NO, UNCONFIRMED, YES, NO, UNCONFIRMED)
        public = caps.public()
        self.assertIs(type(public), dict)
        self.assertEqual(tuple(public), FIELDS)
        self.assertEqual(public, {"provider": "x", "guidance_while_running": "yes", "subagent_questions": "no",
                                  "plan": "unconfirmed", "recovery": "yes", "assessment": "no",
                                  "approval_alternative": "unconfirmed"})

    def test_capabilities_reject_unknown_value(self):
        for field in FIELDS[1:]:
            values = {name: NO for name in FIELDS[1:]}
            values[field] = "maybe"
            with self.assertRaises(ValueError):
                Capabilities("x", **values)

    def test_event_kinds_are_the_eight_named(self):
        self.assertEqual(set(EVENT_KINDS), {"turn_started", "turn_completed", "plan_updated", "usage_updated",
                                            "run_error", "model_changed", "request_resolved", "unrecognized"})
        self.assertEqual(len(EVENT_KINDS), 8)

    def test_neutral_event_is_frozen(self):
        event = NeutralEvent("turn_started", "t1", "u1", {})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.kind = "unrecognized"
        request = ApprovalRequest("command", "m", ("a",), {}, ("accept",), None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.kind = "x"

    def test_no_backend_reports_provider_none_and_all_no(self):
        public = NoBackend().capabilities.public()
        self.assertEqual(public["provider"], "none")
        self.assertEqual({k: v for k, v in public.items() if k != "provider"}, {k: NO for k in FIELDS[1:]})

    def test_no_backend_methods_raise_provider_unavailable(self):
        backend = NoBackend()
        request = ApprovalRequest("command", "m", ("a",), {}, ("accept",), None)
        calls = {
            "translate": lambda: backend.translate({}),
            "list_models": lambda: backend.list_models(),
            "start_thread": lambda: backend.start_thread({}),
            "start_turn": lambda: backend.start_turn({}),
            "steer": lambda: backend.steer({}),
            "interrupt": lambda: backend.interrupt("t", "u"),
            "answer_approval": lambda: backend.answer_approval(request, "accept"),
        }
        for name, call in calls.items():
            with self.subTest(method=name):
                with self.assertRaisesRegex(ProviderUnavailable, "No provider configured"):
                    call()
        self.assertTrue(issubclass(ProviderUnavailable, Exception))
        self.assertTrue(hasattr(Backend, "translate"))


if __name__ == "__main__":
    unittest.main()

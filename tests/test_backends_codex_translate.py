"""Codex notification translator: pure mapping from native messages to NeutralEvent."""
import unittest

from dashboard import server
from dashboard.backends.base import EVENT_KINDS, NeutralEvent, YES
from dashboard.backends.codex import CODEX_CAPABILITIES, translate_notification

TOTAL = {"inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
         "reasoningOutputTokens": 40, "totalTokens": 1100}
USAGE = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100,
         "reasoning_output_tokens": 40, "total_tokens": 1100}
ERROR = {"message": "SYNTHETIC_PRIVATE_UPSTREAM", "codexErrorInfo": "unauthorized"}


def note(method, **params):
    return {"method": method, "params": {"threadId": "thread-one", "turnId": "turn-one", **params}}


# One row per translator output: (native message, expected kind, expected data).
ROWS = (
    (note("turn/started", turn={"id": "turn-one", "status": "inProgress"}),
     "turn_started", {}),
    (note("turn/completed", turn={"id": "turn-one", "status": "completed"}),
     "turn_completed", {"status": "completed", "error": None}),
    (note("turn/plan/updated", plan=[{"step": "SYNTHETIC_PRIVATE_PLAN", "status": "inProgress"}]),
     "plan_updated", {"steps": [{"step": "Step 1", "status": "inProgress"}]}),
    (note("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)}),
     "usage_updated", {"usage": USAGE}),
    (note("model/rerouted", toModel="model-b", fromModel="model-a"),
     "model_changed", {"model": "model-b", "service_tier": None, "rerouted": True}),
    (note("thread/settings/updated", threadSettings={"model": "model-a", "serviceTier": "priority"}),
     "model_changed", {"model": "model-a", "service_tier": "priority", "rerouted": False}),
    (note("error", willRetry=False, error=dict(ERROR)),
     "run_error", {"error": ERROR, "will_retry": False}),
    (note("serverRequest/resolved", requestId=7),
     "request_resolved", {"request_id": 7}),
    (note("item/started", item={"id": "item-one"}),
     "unrecognized", {"method": "item/started"}),
)


class TranslateRowTests(unittest.TestCase):
    def test_each_row_maps_to_its_kind_and_data(self):
        for message, kind, data in ROWS:
            with self.subTest(method=message["method"]):
                event = translate_notification(message)
                self.assertIsInstance(event, NeutralEvent)
                self.assertEqual(kind, event.kind)
                self.assertEqual(data, dict(event.data))

    def test_ids_come_from_thread_id_and_turn(self):
        event = translate_notification(note("turn/started", turnId="other", turn={"id": "turn-two"}))
        self.assertEqual(("thread-one", "turn-two"), (event.thread_id, event.turn_id))
        event = translate_notification(note("error", willRetry=True, error=None))
        self.assertEqual(("thread-one", "turn-one"), (event.thread_id, event.turn_id))
        event = translate_notification({"method": "error", "params": {}})
        self.assertEqual((None, None), (event.thread_id, event.turn_id))

    def test_every_emitted_kind_is_a_declared_event_kind(self):
        emitted = {translate_notification(message).kind for message, _, _ in ROWS}
        self.assertTrue(emitted <= set(EVENT_KINDS), emitted - set(EVENT_KINDS))
        self.assertEqual(set(EVENT_KINDS), emitted)
        self.assertEqual({kind for _, kind, _ in ROWS}, emitted)


class TurnCompletedTests(unittest.TestCase):
    def test_native_statuses_and_error(self):
        for native in ("completed", "failed", "interrupted"):
            event = translate_notification(note("turn/completed", turn={"id": "turn-one", "status": native}))
            self.assertEqual(native, event.data["status"])
        failure = {"message": "SYNTHETIC_PRIVATE_FAILURE"}
        event = translate_notification(note("turn/completed", turn={"id": "turn-one", "status": "failed", "error": failure}))
        self.assertEqual(failure, event.data["error"])
        event = translate_notification(note("turn/completed", turn={"id": "turn-one", "status": "failed", "error": {}}))
        self.assertIsNone(event.data["error"])

    def test_unknown_terminal_status_maps_to_unknown(self):
        for native in ("mystery", None, "", 5, ["completed"], {"x": 1}, "Completed"):
            with self.subTest(status=native):
                event = translate_notification(note("turn/completed", turn={"id": "turn-one", "status": native}))
                self.assertEqual("turn_completed", event.kind)
                self.assertEqual("unknown", event.data["status"])
        event = translate_notification(note("turn/completed", turn={"id": "turn-one"}))
        self.assertEqual("unknown", event.data["status"])


class PlanTests(unittest.TestCase):
    def test_plan_keeps_ordinal_labels_and_statuses_only(self):
        plan = [{"step": "SYNTHETIC_PRIVATE_A", "status": "pending"},
                {"step": "SYNTHETIC_PRIVATE_B", "status": "inProgress", "extra": "SYNTHETIC_PRIVATE_X"},
                {"step": "SYNTHETIC_PRIVATE_C", "status": "completed"},
                {"step": "SYNTHETIC_PRIVATE_D", "status": "weird"},
                {"step": "SYNTHETIC_PRIVATE_E"},
                {"step": "SYNTHETIC_PRIVATE_F", "status": ["unhashable"]}]
        event = translate_notification(note("turn/plan/updated", plan=plan))
        self.assertEqual(
            [{"step": "Step 1", "status": "pending"}, {"step": "Step 2", "status": "inProgress"},
             {"step": "Step 3", "status": "completed"}, {"step": "Step 4", "status": "pending"},
             {"step": "Step 5", "status": "pending"}, {"step": "Step 6", "status": "pending"}],
            list(event.data["steps"]))
        self.assertNotIn("SYNTHETIC_PRIVATE", repr(event))

    def test_plan_ordinals_count_skipped_entries_and_cap_at_100(self):
        event = translate_notification(note("turn/plan/updated", plan=["junk", {"status": "completed"}]))
        self.assertEqual([{"step": "Step 2", "status": "completed"}], list(event.data["steps"]))
        event = translate_notification(note("turn/plan/updated", plan=[{"status": "pending"}] * 150))
        self.assertEqual(100, len(event.data["steps"]))
        self.assertEqual("Step 100", event.data["steps"][-1]["step"])

    def test_missing_plan_is_empty_and_non_list_plan_is_none(self):
        self.assertEqual([], list(translate_notification(note("turn/plan/updated")).data["steps"]))
        self.assertIsNone(translate_notification(note("turn/plan/updated", plan="x")).data["steps"])
        self.assertIsNone(translate_notification(note("turn/plan/updated", plan={"a": 1})).data["steps"])


class UsageTests(unittest.TestCase):
    def test_usage_keys_match_the_server_table(self):
        total = dict(TOTAL)
        event = translate_notification(note("thread/tokenUsage/updated", tokenUsage={"total": total}))
        self.assertEqual({v: total[k] for k, v in server.USAGE_KEYS.items()}, dict(event.data["usage"]))

    def test_invalid_usage_is_kept_as_none(self):
        bad = (
            {**TOTAL, "inputTokens": True}, {**TOTAL, "inputTokens": -1}, {**TOTAL, "totalTokens": 10 ** 15 + 1},
            {**TOTAL, "outputTokens": 1.5}, {**TOTAL, "cachedInputTokens": 2000},
            {k: v for k, v in TOTAL.items() if k != "totalTokens"}, {}, "x", None)
        for total in bad:
            with self.subTest(total=total):
                event = translate_notification(note("thread/tokenUsage/updated", tokenUsage={"total": total}))
                self.assertEqual("usage_updated", event.kind)
                self.assertIsNone(event.data["usage"])
        for token_usage in ("x", None, [], {}):
            event = translate_notification(note("thread/tokenUsage/updated", tokenUsage=token_usage))
            self.assertIsNone(event.data["usage"])
        self.assertIsNone(translate_notification(note("thread/tokenUsage/updated")).data["usage"])

    def test_boundary_values_are_accepted(self):
        total = {**TOTAL, "inputTokens": 10 ** 15, "cachedInputTokens": 10 ** 15, "totalTokens": 0}
        event = translate_notification(note("thread/tokenUsage/updated", tokenUsage={"total": total}))
        self.assertEqual(10 ** 15, event.data["usage"]["input_tokens"])


class ModelAndErrorTests(unittest.TestCase):
    def test_settings_missing_fields_are_none(self):
        event = translate_notification(note("thread/settings/updated"))
        self.assertEqual({"model": None, "service_tier": None, "rerouted": False}, dict(event.data))
        event = translate_notification(note("thread/settings/updated", threadSettings="x"))
        self.assertEqual({"model": None, "service_tier": None, "rerouted": False}, dict(event.data))

    def test_error_will_retry_follows_truthiness(self):
        self.assertIs(False, translate_notification(note("error", error=ERROR)).data["will_retry"])
        self.assertIs(True, translate_notification(note("error", error=ERROR, willRetry=True)).data["will_retry"])
        self.assertIs(False, translate_notification(note("error", error=ERROR, willRetry=0)).data["will_retry"])
        self.assertIs(True, translate_notification(note("error", error=ERROR, willRetry="yes")).data["will_retry"])
        self.assertIsNone(translate_notification(note("error", willRetry=False)).data["error"])

    def test_request_resolved_keeps_the_raw_request_id(self):
        self.assertEqual("req-1", translate_notification(note("serverRequest/resolved", requestId="req-1")).data["request_id"])
        self.assertIsNone(translate_notification(note("serverRequest/resolved")).data["request_id"])


class UnrecognizedTests(unittest.TestCase):
    def test_translate_never_raises_on_junk(self):
        junk = (None, 42, "turn/started", [], {}, {"method": 7}, {"method": None},
                {"method": "turn/completed"}, {"method": "turn/completed", "params": "x"},
                {"method": "turn/started", "params": {"turn": "x"}},
                {"method": "turn/started", "params": {}},
                {"method": "turn/completed", "params": {"turn": None}},
                {"method": "turn/plan/updated", "params": []},
                {"method": "thread/tokenUsage/updated", "params": None},
                {"method": ["x"], "params": {"turn": []}})
        for message in junk:
            with self.subTest(message=message):
                event = translate_notification(message)
                self.assertIsInstance(event, NeutralEvent)
                self.assertIn(event.kind, EVENT_KINDS)

    def test_junk_yields_unrecognized_with_method_or_none(self):
        for message, method in ((None, None), (42, None), ({}, None), ({"method": 7}, None),
                                ({"method": "turn/completed"}, "turn/completed"),
                                ({"method": "turn/completed", "params": "x"}, "turn/completed"),
                                ({"method": "turn/started", "params": {"turn": "x"}}, "turn/started")):
            with self.subTest(message=message):
                event = translate_notification(message)
                self.assertEqual(NeutralEvent("unrecognized", None, None, {"method": method}), event)

    def test_unrecognized_carries_method_only(self):
        message = note("item/agentMessage/delta", delta="SYNTHETIC_PRIVATE_TEXT", item={"id": "item-one"})
        event = translate_notification(message)
        self.assertEqual(NeutralEvent("unrecognized", None, None, {"method": "item/agentMessage/delta"}), event)
        self.assertNotIn("SYNTHETIC_PRIVATE", repr(event))

    def test_known_method_with_non_dict_turn_is_unrecognized_like_the_handler_drop(self):
        # on_message returns early when params["turn"] is not a dict, for every method.
        event = translate_notification(note("error", error=ERROR, turn="x"))
        self.assertEqual("unrecognized", event.kind)

    def test_translation_does_not_mutate_the_message(self):
        message = note("turn/plan/updated", plan=[{"step": "SYNTHETIC_PRIVATE_PLAN", "status": "inProgress"}])
        before = repr(message)
        translate_notification(message)
        self.assertEqual(before, repr(message))


class CapabilitiesTests(unittest.TestCase):
    def test_codex_capabilities(self):
        self.assertEqual({"provider": "codex", "guidance_while_running": YES, "subagent_questions": YES,
                          "plan": YES, "recovery": YES, "assessment": YES, "approval_alternative": YES},
                         CODEX_CAPABILITIES.public())


if __name__ == "__main__":
    unittest.main()

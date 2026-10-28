"""Parity of the Codex run lifecycle handled by Dashboard.on_message.

Each test drives a ScriptedDashboard through one lifecycle family and asserts the state the dashboard
holds today. They were written and run green before on_message consumed NeutralEvent (Task 6 of the
provider-seam plan), so they prove the refactor kept each family's behaviour. The characterization
goldens cover whole snapshots; these pin each family on its own, including the shared tail
(updated_at stamp and store write) and the cases where nothing may change.
"""
import unittest
from unittest.mock import patch

from dashboard.diagnostics import classify_error
from dashboard.server import ACTIVE
from tests.characterization import ScriptedDashboard
from tests.test_dashboard_backend import FakeClient

TURN = {"id": "turn-one"}
SENTINEL = "SENTINEL_UPDATED_AT"
TOTAL = {"inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
         "reasoningOutputTokens": 40, "totalTokens": 1100}
USAGE = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100,
         "reasoning_output_tokens": 40, "total_tokens": 1100}


class LifecycleParityTests(ScriptedDashboard):
    def running(self):
        task = self.task()
        self.event("turn/started", turn={**TURN, "status": "inProgress"})
        self.assertEqual("running", task["status"])
        return task

    def fresh(self):
        """Replace the dashboard with a new one (one terminal status per dashboard)."""
        self.tearDown()
        self.setUp()

    def stamp(self, task):
        task["updated_at"] = SENTINEL

    def puts(self):
        return patch.object(self.app.store, "put", wraps=self.app.store.put)

    def task_puts(self, put, task):
        return [call for call in put.call_args_list if call.args[0] == "task" and call.args[1] is task]

    def settle_default_tier(self):
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})

    # turn/started, turn/completed

    def test_turn_started_sets_turn_and_running(self):
        task = self.task()
        self.stamp(task)
        with self.puts() as put:
            self.event("turn/started", turn={"id": "turn-one", "status": "inProgress"})
        self.assertEqual(("running", "turn-one"), (task["status"], task["turn_id"]))
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    def test_turn_completed_statuses(self):
        for native, expected in (("completed", "completed"), ("failed", "failed"),
                                 ("interrupted", "interrupted"), ("weird", "unknown")):
            with self.subTest(status=native):
                self.fresh()
                task = self.running()
                self.stamp(task)
                with self.puts() as put:
                    self.event("turn/completed", turn={**TURN, "status": native})
                self.assertEqual(expected, task["status"])
                self.assertEqual("turn-one", task["turn_id"])
                self.assertNotEqual(SENTINEL, task["updated_at"])
                self.assertEqual(1, len(self.task_puts(put, task)))
                if expected == "failed":
                    self.assertEqual(classify_error(None), task["diagnostics"][-1]["code"])
                else:
                    self.assertEqual([], task["diagnostics"])

    def test_turn_started_keeps_waiting_approval(self):
        # A turn/started for the current turn never overwrites waiting_approval with running.
        task = self.running()
        approval = self.approval(task)
        self.assertEqual("waiting_approval", task["status"])
        self.stamp(task)
        self.event("turn/started", turn={"id": "turn-one", "status": "inProgress"})
        self.assertEqual(("waiting_approval", "turn-one"), (task["status"], task["turn_id"]))
        self.assertEqual("pending", approval["status"])
        self.assertNotEqual(SENTINEL, task["updated_at"])

    def test_turn_completed_runs_recovery_terminal_before_stale_filter(self):
        # Carry-over (f): _recovery_terminal sees turn/completed before the stale-turn filter. The
        # top-level turnId is stale, so the lifecycle branches drop the message; only the recovery
        # bookkeeping may act on it (synthetic operation and record in stop_requested).
        task = self.running()
        origin_id, op_id = "0" * 31 + "1", "0" * 31 + "2"
        record = {"id": origin_id, "revision": 0, "state": "stopping"}
        operation = {"id": op_id, "kind": "continuation", "status": "stop_requested",
                     "origin_task_id": origin_id, "reason_codes": ["SYNTHETIC_REASON"]}
        self.app.recoveries[origin_id] = record
        self.app.recovery_operations[op_id] = operation
        task["recovery_operation_id"] = op_id
        task["recovery_stop_pending"] = {"thread_id": "thread-one", "turn_id": "turn-one"}
        self.event("turn/completed", turnId="turn-stale", turn={"id": "turn-one", "status": "interrupted"})
        self.assertEqual(("terminal_observed", []), (operation["status"], operation["reason_codes"]))
        self.assertEqual(("connected", 1), (record["state"], record["revision"]))
        self.assertEqual("interrupted", task["status"])
        self.assertNotIn("recovery_stop_pending", task)
        stored = {row["id"]: row for row in self.app.store.load("recovery_operation")}
        self.assertEqual("terminal_observed", stored[op_id]["status"])

    def test_turn_completed_closes_approvals_and_questions(self):
        task = self.running()
        approval = self.approval(task)
        self.assertEqual("waiting_approval", task["status"])
        self.event("turn/completed", turn={**TURN, "status": "completed"})
        self.assertEqual("completed", task["status"])
        self.assertEqual("unavailable", approval["status"])
        self.assertEqual([], approval["available_decisions"])
        self.assertEqual({}, self.app.pending)

    def test_turn_events_for_inactive_task_change_nothing(self):
        task = self.running()
        self.event("turn/completed", turn={**TURN, "status": "completed"})
        self.stamp(task)
        with self.puts() as put:
            self.event("turn/completed", turn={**TURN, "status": "failed"})
            self.event("turn/started", turn={"id": "turn-one", "status": "inProgress"})
            self.event("error", error={"message": "SYNTHETIC_PRIVATE_ERROR"}, willRetry=False)
        self.assertEqual(("completed", SENTINEL), (task["status"], task["updated_at"]))
        self.assertEqual([], task["diagnostics"])
        self.assertEqual([], self.task_puts(put, task))

    def test_turn_completed_error_uses_the_raw_error(self):
        # Carry-over (e): `if failure or not diagnostics` with the raw turn error.
        task = self.running()
        self.event("turn/completed", turn={**TURN, "status": "failed", "error": {}})
        self.assertEqual(classify_error({}), task["diagnostics"][-1]["code"])
        self.assertNotEqual(classify_error({}), classify_error(None))

        self.fresh()
        task = self.running()
        task["diagnostics"] = [{"at": "x", "stage": "earlier", "code": "SYNTHETIC_CODE", "message": "m", "action": "a"}]
        task["error"] = "SYNTHETIC_EARLIER_ERROR"
        self.event("turn/completed", turn={**TURN, "status": "failed", "error": {}})
        self.assertEqual("failed", task["status"])
        self.assertEqual(1, len(task["diagnostics"]))
        self.assertEqual("SYNTHETIC_EARLIER_ERROR", task["error"])

        self.fresh()
        task = self.running()
        task["diagnostics"] = [{"at": "x", "stage": "earlier", "code": "SYNTHETIC_CODE", "message": "m", "action": "a"}]
        self.event("turn/completed", turn={**TURN, "status": "failed",
                                           "error": {"codexErrorInfo": "usageLimitExceeded"}})
        self.assertEqual(2, len(task["diagnostics"]))
        self.assertEqual("usage_limit", task["diagnostics"][-1]["code"])

    def without_turn_id(self):
        """turn/started and turn/completed whose turn has no id, with and without a top-level turnId."""
        for method in ("turn/completed", "turn/started"):
            for params in ({"threadId": "thread-one", "turn": {"status": "completed"}},
                           {"threadId": "thread-one", "turnId": "turn-one", "turn": {"status": "completed"}},
                           {"threadId": "thread-one", "turnId": "turn-one"}):
                yield {"method": method, "params": params}

    def test_turn_completed_without_turn_id_changes_no_state(self):
        # Carry-over (c), state part: the old handler read params["turn"]["id"] and raised KeyError
        # before setting any status, so nothing may change (a top-level turnId does not stand in for it).
        for message in self.without_turn_id():
            with self.subTest(message=message):
                self.fresh()
                task = self.running()
                self.stamp(task)
                with self.puts() as put:
                    try:
                        self.app.on_message(message)
                    except KeyError:
                        pass  # the pre-Task-6 handler; the no-raise half is pinned separately
                self.assertEqual(("running", "turn-one", SENTINEL),
                                 (task["status"], task["turn_id"], task["updated_at"]))
                self.assertEqual([], self.task_puts(put, task))

    def test_turn_events_without_turn_id_do_not_raise(self):
        # Carry-over (c) and Review Focus 5: added after the baseline run; the old handler raised
        # KeyError here, which ended the Codex reader thread.
        for message in self.without_turn_id():
            with self.subTest(message=message):
                self.fresh()
                task = self.running()
                self.app.on_message(message)
                self.assertEqual(("running", "turn-one"), (task["status"], task["turn_id"]))

    # turn/plan/updated

    def test_plan_update_keeps_labels_and_statuses_only(self):
        task = self.running()
        self.stamp(task)
        with self.puts() as put:
            self.event("turn/plan/updated", plan=[
                {"step": "SYNTHETIC_PRIVATE_A", "status": "completed"},
                "not-a-dict",
                {"step": "SYNTHETIC_PRIVATE_B", "status": "inProgress", "extra": "SYNTHETIC_PRIVATE_X"},
                {"step": "SYNTHETIC_PRIVATE_C", "status": "bogus"},
                {"step": "SYNTHETIC_PRIVATE_D"}])
        self.assertEqual([{"step": "Step 1", "status": "completed"}, {"step": "Step 3", "status": "inProgress"},
                          {"step": "Step 4", "status": "pending"}, {"step": "Step 5", "status": "pending"}],
                         task["plan"])
        self.assertNotIn("SYNTHETIC_PRIVATE", repr(task))
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    def test_plan_update_caps_at_one_hundred(self):
        task = self.running()
        self.event("turn/plan/updated", plan=[{"status": "completed"}] * 150)
        self.assertEqual(100, len(task["plan"]))
        self.assertEqual({"step": "Step 100", "status": "completed"}, task["plan"][-1])

    def test_non_list_plan_keeps_plan_but_runs_tail(self):
        # Carry-over (b): steps None assigns nothing but still stamps and stores.
        task = self.running()
        self.event("turn/plan/updated", plan=[{"status": "completed"}])
        before = list(task["plan"])
        self.stamp(task)
        with self.puts() as put:
            self.event("turn/plan/updated", plan="SYNTHETIC_PRIVATE_NOT_A_LIST")
        self.assertEqual(before, task["plan"])
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    # thread/tokenUsage/updated

    def test_usage_update_sets_usage_and_cost(self):
        task = self.running()
        self.settle_default_tier()
        self.stamp(task)
        with self.puts() as put:
            self.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
        self.assertEqual(USAGE, task["usage"])
        self.assertEqual("estimated", task["cost"]["basis"])
        self.assertEqual(round((800 * 50 + 200 * 2.5 + 100 * 250) / 1_000_000, 8), task["cost"]["credits"])
        actual = self.app.actual[task["id"]]
        self.assertEqual(("gpt-6.1-sol", "default"), actual["usage_basis"])
        self.assertFalse(actual["mixed"])
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    def test_usage_without_default_tier_has_unknown_cost(self):
        task = self.running()
        self.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
        self.assertEqual(USAGE, task["usage"])
        self.assertEqual("unknown", task["cost"]["basis"])
        self.assertIsNone(task["cost"]["credits"])

    def test_usage_never_decreases_and_invalid_usage_runs_tail(self):
        # Carry-over (b): an ignored usage update assigns nothing but still stamps and stores.
        task = self.running()
        self.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
        for total in ({**TOTAL, "totalTokens": 5}, {**TOTAL, "cachedInputTokens": 2000},
                      {**TOTAL, "inputTokens": True}, {**TOTAL, "outputTokens": -1}, {}):
            with self.subTest(total=total):
                self.stamp(task)
                with self.puts() as put:
                    self.event("thread/tokenUsage/updated", tokenUsage={"total": total})
                self.assertEqual(USAGE, task["usage"])
                self.assertNotEqual(SENTINEL, task["updated_at"])
                self.assertEqual(1, len(self.task_puts(put, task)))
        self.stamp(task)
        self.event("thread/tokenUsage/updated")
        self.assertNotEqual(SENTINEL, task["updated_at"])

    def test_usage_basis_change_marks_mixed(self):
        task = self.running()
        self.settle_default_tier()
        self.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
        self.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "priority"})
        actual = self.app.actual[task["id"]]
        self.assertTrue(actual["mixed"])
        self.assertEqual(("gpt-6.1-sol", "priority"), (actual["model"], actual["tier"]))
        self.assertEqual("unknown", task["cost"]["basis"])

    # model/rerouted, thread/settings/updated

    def test_model_reroute_marks_mixed(self):
        # Carry-over (d): a reroute only marks mixed; its model is never applied to `actual`.
        task = self.running()
        self.settle_default_tier()
        self.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
        self.assertEqual("estimated", task["cost"]["basis"])
        self.stamp(task)
        with self.puts() as put:
            self.event("model/rerouted", fromModel="gpt-6.1-sol", toModel="gpt-6-luna", reason="SYNTHETIC")
        actual = self.app.actual[task["id"]]
        self.assertTrue(actual["mixed"])
        self.assertEqual(("gpt-6.1-sol", "default"), (actual["model"], actual["tier"]))
        self.assertEqual("unknown", task["cost"]["basis"])
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    def test_settings_update_applies_model_and_tier(self):
        task = self.running()
        self.stamp(task)
        with self.puts() as put:
            self.event("thread/settings/updated", threadSettings={"model": "gpt-6-luna", "serviceTier": "default"})
        actual = self.app.actual[task["id"]]
        self.assertEqual(("gpt-6-luna", "default"), (actual["model"], actual["tier"]))
        self.assertTrue(actual["mixed"])  # gpt-6.1-sol from thread/start differs from gpt-6-luna
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    def test_settings_update_same_model_does_not_mark_mixed(self):
        task = self.running()
        self.settle_default_tier()
        self.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
        actual = self.app.actual[task["id"]]
        self.assertFalse(actual["mixed"])
        self.assertEqual("estimated", task["cost"]["basis"])

    # error

    def test_error_without_retry_fails_task_and_closes_approvals(self):
        task = self.running()
        approval = self.approval(task)
        self.stamp(task)
        with self.puts() as put:
            self.event("error", error={"message": "SYNTHETIC_PRIVATE_ERROR", "codexErrorInfo": "unauthorized"},
                       willRetry=False)
        self.assertEqual("failed", task["status"])
        self.assertEqual("authentication_required", task["diagnostics"][-1]["code"])
        self.assertNotIn("SYNTHETIC_PRIVATE", repr(task))
        self.assertEqual("unavailable", approval["status"])
        self.assertEqual({}, self.app.pending)
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    def test_error_with_retry_runs_tail_only(self):
        # Carry-over (b): will_retry assigns nothing but still stamps and stores.
        task = self.running()
        approval = self.approval(task)
        self.stamp(task)
        with self.puts() as put:
            self.event("error", error={"message": "SYNTHETIC_PRIVATE_ERROR"}, willRetry=True)
        self.assertEqual("waiting_approval", task["status"])
        self.assertEqual([], task["diagnostics"])
        self.assertEqual("pending", approval["status"])
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertEqual(1, len(self.task_puts(put, task)))

    # serverRequest/resolved

    def test_server_request_resolved_removes_pending(self):
        task = self.running()
        approval = self.approval(task, rpc_id=21)
        self.assertEqual("waiting_approval", task["status"])
        self.stamp(task)
        with self.puts() as put:
            self.event("serverRequest/resolved", requestId=21)
        self.assertEqual("resolved", approval["status"])
        self.assertEqual([], approval["available_decisions"])
        self.assertEqual({}, self.app.pending)
        self.assertEqual("running", task["status"])
        self.assertNotEqual(SENTINEL, task["updated_at"])
        self.assertTrue(self.task_puts(put, task))

    def test_server_request_resolved_other_id_keeps_pending_and_runs_tail(self):
        task = self.running()
        approval = self.approval(task, rpc_id=21)
        self.stamp(task)
        self.event("serverRequest/resolved", requestId=22)
        self.assertEqual("pending", approval["status"])
        self.assertEqual(1, len(self.app.pending))
        self.assertEqual("waiting_approval", task["status"])
        self.assertNotEqual(SENTINEL, task["updated_at"])

    # unrecognized, stale, native requests

    def test_unrecognized_message_does_not_raise(self):
        task = self.running()
        before = dict(task)
        self.stamp(task)
        with self.puts() as put:
            self.event("thread/unknownLifecycleThing", turn={**TURN, "status": "completed"})
            self.app.on_message({"method": "turn/completed", "params": "SYNTHETIC_NOT_A_DICT"})
            self.event("turn/completed", turn="SYNTHETIC_NOT_A_DICT")
        self.assertEqual({**before, "updated_at": SENTINEL}, task)
        self.assertEqual([], self.task_puts(put, task))

    def test_unowned_thread_changes_nothing(self):
        task = self.running()
        before = dict(task)
        self.app.on_message({"method": "turn/completed", "params": {
            "threadId": "thread-other", "turn": {**TURN, "status": "failed"}}})
        self.assertEqual(before, task)

    def test_stale_turn_event_ignored(self):
        task = self.running()
        before = dict(task)
        self.event("turn/completed", turnId="turn-stale", turn={"id": "turn-stale", "status": "failed"})
        self.event("error", turnId="turn-stale", error={"message": "x"}, willRetry=False)
        self.event("serverRequest/resolved", turnId="turn-stale", requestId=1)
        self.assertEqual(before, task)

    def test_stale_client_message_ignored(self):
        task = self.running()
        old_client = self.app.client
        self.app.client = FakeClient()
        before = dict(task)
        actual_before = dict(self.app.actual[task["id"]])
        for method, params in (("turn/completed", {"turn": {**TURN, "status": "failed"}}),
                               ("error", {"error": {"message": "x"}, "willRetry": False}),
                               ("thread/settings/updated", {"threadSettings": {"model": "gpt-6-luna"}}),
                               ("thread/tokenUsage/updated", {"tokenUsage": {"total": dict(TOTAL)}})):
            self.app._client_message(old_client, {"method": method, "params": {
                "threadId": "thread-one", "turnId": "turn-one", **params}})
        self.assertEqual(before, task)
        self.assertEqual(actual_before, self.app.actual[task["id"]])
        # The current client's message is still handled.
        self.app._client_message(self.app.client, {"method": "turn/completed", "params": {
            "threadId": "thread-one", "turn": {**TURN, "status": "completed"}}})
        self.assertEqual("completed", task["status"])

    def test_native_request_with_lifecycle_method_is_not_a_notification(self):
        # Carry-over (a): a message carrying "id" goes to approvals routing, never the lifecycle branches.
        task = self.running()
        before = dict(task)
        actual_before = dict(self.app.actual[task["id"]])
        self.app.on_message({"id": 99, "method": "turn/completed", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "turn": {**TURN, "status": "completed"}}})
        self.app.on_message({"id": 98, "method": "error", "params": {
            "threadId": "thread-one", "turnId": "turn-one", "error": {"message": "x"}, "willRetry": False}})
        self.assertEqual(before, task)
        self.assertEqual(actual_before, self.app.actual[task["id"]])
        self.assertEqual([99, 98], self.fake.rejections)
        self.assertEqual({}, self.app.approvals)
        self.assertIn(task["status"], ACTIVE)


class UsageKeyTableTests(unittest.TestCase):
    def test_server_and_translator_share_one_usage_key_table(self):
        # Carry-over (h): one definition, in the translator; server re-exports it without an import cycle.
        import inspect
        from dashboard import server
        from dashboard.backends import codex
        self.assertIs(codex.USAGE_KEYS, server.USAGE_KEYS)
        source = inspect.getsource(codex)
        self.assertNotIn("dashboard.server", source)
        self.assertNotIn("from .. import server", source)


if __name__ == "__main__":
    unittest.main()

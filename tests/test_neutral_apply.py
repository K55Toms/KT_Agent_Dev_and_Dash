"""Dashboard._apply_neutral_event and Dashboard._note_turn match the Codex path they were extracted from.

Each parity case builds the same dashboard state twice. Path A sends the Codex message through
on_message. Path B sends the same message through on_message with the translator forced to
"unrecognized" (so everything before the lifecycle branches runs, and the branches do nothing),
then calls _apply_neutral_event(task, translate_notification(message)) under the lock. The task,
`actual`, approvals, pending approvals, questions, owned threads, every store row and every store
write must be identical. Ids and the clock are made deterministic so the two worlds compare equal.
"""
from contextlib import ExitStack
import itertools
import json
import re
import unittest
from unittest.mock import patch
import uuid

from dashboard.backends.base import NeutralEvent
from dashboard.backends.codex import translate_notification
from dashboard.diagnostics import classify_error
from tests.characterization import ScriptedDashboard

FIXED_NOW = "2001-02-03T04:05:06+00:00"
SENTINEL = "SENTINEL_UPDATED_AT"
TURN = {"id": "turn-one"}
TOTAL = {"inputTokens": 1000, "cachedInputTokens": 200, "outputTokens": 100,
         "reasoningOutputTokens": 40, "totalTokens": 1100}
UNRECOGNIZED = NeutralEvent("unrecognized", None, None, {})


def message(method, **params):
    return {"method": method, "params": {"threadId": "thread-one", "turnId": "turn-one", **params}}


def encode(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return "<" + type(value).__name__ + ">"


class World:
    """One Dashboard on a FakeClient with deterministic ids and a fixed clock."""

    def __init__(self, test):
        self.stack = ExitStack()
        test.addCleanup(self.stack.close)
        counter = itertools.count(1)
        self.stack.enter_context(patch("uuid.uuid4", side_effect=lambda: uuid.UUID(int=next(counter))))
        self.stack.enter_context(patch("dashboard.server.now", return_value=FIXED_NOW))
        self.stack.enter_context(patch("dashboard.conversation.timestamp", return_value=FIXED_NOW))
        self.harness = ScriptedDashboard("setUp")
        self.harness.setUp()
        self.stack.callback(self.harness.tearDown)
        self.app = self.harness.app

    def task(self):
        return self.harness.task()

    def running(self):
        task = self.task()
        self.event("turn/started", turn={**TURN, "status": "inProgress"})
        return task

    def event(self, method, **params):
        self.app.on_message(message(method, **params))

    def approval(self, task, rpc_id=17):
        return self.harness.approval(task, rpc_id=rpc_id)

    def puts(self):
        return patch.object(self.app.store, "put", wraps=self.app.store.put)

    def state(self, task):
        app = self.app
        rows = app.store.db.execute("SELECT kind, id, body FROM records ORDER BY kind, id").fetchall()
        text = json.dumps({
            "task": task, "actual": app.actual.get(task["id"]), "approvals": app.approvals,
            "pending": app.pending, "questions": app.questions, "question_requests": app.question_requests,
            "owned_threads": app.owned_threads, "rows": [list(row) for row in rows]}, default=encode)
        for root in (str(self.harness.root), self.harness.temp.name):  # the temporary directory differs per world
            text = text.replace(root, "<root>").replace(json.dumps(root)[1:-1], "<root>")
        text = re.sub(r'(inode\\*": )\d+', r"\g<1>0", text)  # the project directory's inode differs too
        return json.loads(text)


# Each case: (name, prepare(world) -> task, the Codex message).
def prepare_started(world):
    return world.task()


def prepare_running(world):
    return world.running()


def prepare_with_approval(world):
    task = world.running()
    world.approval(task)
    return task


def prepare_failed_with_diagnostic(world):
    task = world.running()
    task["diagnostics"] = [{"at": "x", "stage": "earlier", "code": "SYNTHETIC_CODE", "message": "m", "action": "a"}]
    return task


def prepare_default_tier(world):
    task = world.running()
    world.event("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})
    return task


def prepare_with_usage(world):
    task = prepare_default_tier(world)
    world.event("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})
    return task


def prepare_resolvable(world):
    task = world.running()
    world.approval(task, rpc_id=21)
    return task


def prepare_completed(world):
    task = world.running()
    world.event("turn/completed", turn={**TURN, "status": "completed"})
    return task


CASES = (
    ("turn_started", prepare_started, message("turn/started", turn={**TURN, "status": "inProgress"})),
    ("turn_started_waiting_approval", prepare_with_approval,
     message("turn/started", turn={**TURN, "status": "inProgress"})),
    ("turn_completed", prepare_running, message("turn/completed", turn={**TURN, "status": "completed"})),
    ("turn_completed_closes_approvals", prepare_with_approval,
     message("turn/completed", turn={**TURN, "status": "interrupted"})),
    ("turn_completed_failed_no_diagnostic", prepare_running,
     message("turn/completed", turn={**TURN, "status": "failed"})),
    ("turn_completed_failed_with_diagnostic", prepare_failed_with_diagnostic,
     message("turn/completed", turn={**TURN, "status": "failed", "error": {"codexErrorInfo": "usageLimitExceeded"}})),
    ("turn_completed_failed_empty_error_keeps_diagnostic", prepare_failed_with_diagnostic,
     message("turn/completed", turn={**TURN, "status": "failed"})),
    ("plan_updated", prepare_running, message("turn/plan/updated", plan=[
        {"step": "SYNTHETIC_PRIVATE_A", "status": "completed"}, {"step": "SYNTHETIC_PRIVATE_B"}])),
    ("plan_not_a_list", prepare_running, message("turn/plan/updated", plan="SYNTHETIC_PRIVATE_NOT_A_LIST")),
    ("usage_updated", prepare_default_tier, message("thread/tokenUsage/updated", tokenUsage={"total": dict(TOTAL)})),
    ("usage_lower_total_not_applied", prepare_with_usage,
     message("thread/tokenUsage/updated", tokenUsage={"total": {**TOTAL, "totalTokens": 5}})),
    ("usage_invalid", prepare_with_usage, message("thread/tokenUsage/updated", tokenUsage={"total": {}})),
    ("model_rerouted", prepare_with_usage,
     message("model/rerouted", fromModel="gpt-6.1-sol", toModel="gpt-6-luna", reason="SYNTHETIC")),
    ("settings_model_changed", prepare_with_usage,
     message("thread/settings/updated", threadSettings={"model": "gpt-6-luna", "serviceTier": "priority"})),
    ("settings_same_model", prepare_running,
     message("thread/settings/updated", threadSettings={"model": "gpt-6.1-sol", "serviceTier": "default"})),
    ("run_error", prepare_with_approval,
     message("error", error={"message": "SYNTHETIC_PRIVATE_ERROR", "codexErrorInfo": "unauthorized"}, willRetry=False)),
    ("run_error_will_retry", prepare_with_approval,
     message("error", error={"message": "SYNTHETIC_PRIVATE_ERROR"}, willRetry=True)),
    ("request_resolved", prepare_resolvable, message("serverRequest/resolved", requestId=21)),
    ("request_resolved_other_id", prepare_resolvable, message("serverRequest/resolved", requestId=22)),
    ("inactive_turn_completed", prepare_completed, message("turn/completed", turn={**TURN, "status": "failed"})),
    ("inactive_turn_started", prepare_completed, message("turn/started", turn={**TURN, "status": "inProgress"})),
    ("inactive_run_error", prepare_completed, message("error", error={"message": "x"}, willRetry=False)),
    ("turn_started_without_id", prepare_running, message("turn/started", turn={"status": "inProgress"})),
    ("turn_completed_without_id", prepare_running, message("turn/completed", turn={"status": "completed"})),
    ("unrecognized", prepare_running, message("thread/unknownLifecycleThing", turn={**TURN, "status": "completed"})),
)


class ApplyNeutralEventParityTests(unittest.TestCase):
    def run_path(self, prepare, codex_message, direct):
        world = World(self)
        task = prepare(world)
        task["updated_at"] = SENTINEL
        with world.puts() as put:
            if direct:
                with patch.object(world.app.backend, "translate", return_value=UNRECOGNIZED):
                    world.app.on_message(codex_message)
                with world.app.lock:
                    world.app._apply_neutral_event(task, translate_notification(codex_message))
            else:
                world.app.on_message(codex_message)
        writes = [(call.args[0], call.args[1].get("id")) for call in put.call_args_list]
        return world.state(task), writes

    def test_apply_neutral_event_matches_on_message_for_each_kind(self):
        for name, prepare, codex_message in CASES:
            with self.subTest(case=name):
                expected, expected_writes = self.run_path(prepare, codex_message, direct=False)
                actual, actual_writes = self.run_path(prepare, codex_message, direct=True)
                self.assertEqual(expected, actual)
                self.assertEqual(expected_writes, actual_writes)

    def test_worlds_are_deterministic(self):
        # Harness check (no new method used): two on_message runs of one case compare equal.
        for name, prepare, codex_message in CASES:
            with self.subTest(case=name):
                self.assertEqual(self.run_path(prepare, codex_message, direct=False),
                                 self.run_path(prepare, codex_message, direct=False))

    def test_unrecognized_event_skips_the_tail(self):
        world = World(self)
        task = world.running()
        task["updated_at"] = SENTINEL
        before = world.state(task)
        with world.puts() as put, world.app.lock:
            world.app._apply_neutral_event(task, UNRECOGNIZED)
        self.assertEqual(before, world.state(task))
        self.assertEqual([], put.call_args_list)

    def test_inactive_task_skips_the_tail(self):
        world = World(self)
        task = prepare_completed(world)
        task["updated_at"] = SENTINEL
        before = world.state(task)
        with world.puts() as put, world.app.lock:
            for event in (NeutralEvent("turn_started", "thread-one", "turn-one", {}),
                          NeutralEvent("turn_completed", "thread-one", "turn-one", {"status": "failed", "error": None}),
                          NeutralEvent("run_error", "thread-one", "turn-one", {"error": None, "will_retry": False})):
                world.app._apply_neutral_event(task, event)
        self.assertEqual(before, world.state(task))
        self.assertEqual([], put.call_args_list)

    def test_turn_completed_failed_records_a_diagnostic(self):
        world = World(self)
        task = world.running()
        error = {"codexErrorInfo": "usageLimitExceeded"}
        with world.app.lock:
            world.app._apply_neutral_event(task, NeutralEvent(
                "turn_completed", "thread-one", "turn-one", {"status": "failed", "error": error}))
        self.assertEqual("failed", task["status"])
        self.assertEqual(classify_error(error), task["diagnostics"][-1]["code"])
        self.assertEqual(FIXED_NOW, task["updated_at"])

    def test_lower_usage_total_is_not_applied_but_the_tail_runs(self):
        world = World(self)
        task = prepare_with_usage(world)
        usage = dict(task["usage"])
        task["updated_at"] = SENTINEL
        lower = {**usage, "total_tokens": 5}
        with world.puts() as put, world.app.lock:
            world.app._apply_neutral_event(task, NeutralEvent("usage_updated", "thread-one", "turn-one", {"usage": lower}))
        self.assertEqual(usage, task["usage"])
        self.assertEqual(FIXED_NOW, task["updated_at"])
        self.assertEqual([("task", task["id"])], [(c.args[0], c.args[1]["id"]) for c in put.call_args_list])

    def test_reroute_marks_mixed_and_settings_apply_the_model(self):
        world = World(self)
        task = prepare_with_usage(world)
        actual = world.app.actual[task["id"]]
        self.assertFalse(actual["mixed"])
        with world.app.lock:
            world.app._apply_neutral_event(task, NeutralEvent(
                "model_changed", "thread-one", "turn-one", {"model": "gpt-6-luna", "service_tier": None, "rerouted": True}))
        self.assertTrue(actual["mixed"])
        self.assertEqual(("gpt-6.1-sol", "default"), (actual["model"], actual["tier"]))

        world = World(self)
        task = prepare_with_usage(world)
        actual = world.app.actual[task["id"]]
        with world.app.lock:
            world.app._apply_neutral_event(task, NeutralEvent(
                "model_changed", "thread-one", "turn-one",
                {"model": "gpt-6-luna", "service_tier": "default", "rerouted": False}))
        self.assertTrue(actual["mixed"])
        self.assertEqual(("gpt-6-luna", "default"), (actual["model"], actual["tier"]))


class NoteTurnTests(unittest.TestCase):
    def owned(self, world):
        owned = world.app._owned("thread-one")
        return {**owned, "turns": sorted(owned["turns"])}

    def test_note_turn_started_and_completed_update_owned_thread(self):
        world = World(self)
        world.task()
        with world.app.lock:
            world.app._note_turn("thread-one", "turn-two", "started")
        owned = self.owned(world)
        self.assertIn("turn-two", owned["turns"])
        self.assertEqual(("turn-two", True, "running"), (owned["current_turn"], owned["active"], owned["last_status"]))

        with world.app.lock:
            world.app._note_turn("thread-one", "turn-other", "completed", "completed")
        self.assertEqual(owned, self.owned(world))  # only the current turn completes

        for status, expected in (("failed", "failed"), ("interrupted", "interrupted"), ("weird", "unknown"),
                                 (None, "unknown"), ("completed", "completed")):
            with self.subTest(status=status):
                with world.app.lock:
                    world.app._note_turn("thread-one", "turn-two", "started")
                    world.app._note_turn("thread-one", "turn-two", "completed", status)
                owned = self.owned(world)
                self.assertEqual((False, expected), (owned["active"], owned["last_status"]))

    def test_note_turn_matches_conversation_metadata(self):
        cases = (("turn/started", {"id": "turn-two"}, ("started", None)),
                 ("turn/completed", {"id": "turn-one", "status": "failed"}, ("completed", "failed")),
                 ("turn/completed", {"id": "turn-one", "status": "completed"}, ("completed", "completed")),
                 ("turn/completed", {"id": "turn-one"}, ("completed", None)),
                 ("turn/completed", {"id": "turn-stale", "status": "failed"}, ("completed", "failed")))
        for method, turn, (phase, status) in cases:
            with self.subTest(method=method, turn=turn):
                native = World(self)
                native.running()
                with native.app.lock:
                    native.app._conversation_metadata(method, {"threadId": "thread-one", "turn": turn})
                direct = World(self)
                direct.running()
                with direct.app.lock:
                    direct.app._note_turn("thread-one", turn["id"], phase, status)
                self.assertEqual(self.owned(native), self.owned(direct))
                self.assertEqual(native.app.omitted_count, direct.app.omitted_count)

    def test_turn_limit_marks_thread_limited(self):
        for use_note_turn in (False, True):
            with self.subTest(use_note_turn=use_note_turn):
                world = World(self)
                world.running()
                owned = world.app._owned("thread-one")
                owned["turns"].update("turn-%d" % n for n in range(300))
                before = set(owned["turns"])
                omitted = world.app.omitted_count
                with world.app.lock:
                    if use_note_turn:
                        world.app._note_turn("thread-one", "turn-new", "started")
                    else:
                        world.app._conversation_metadata(
                            "turn/started", {"threadId": "thread-one", "turn": {"id": "turn-new"}})
                self.assertEqual(before, owned["turns"])
                self.assertEqual(("turn-new", True, True), (owned["current_turn"], owned["active"], owned["limited"]))
                self.assertEqual(omitted + 1, world.app.omitted_count)

    def test_conversation_metadata_malformed_and_unowned_change_nothing(self):
        world = World(self)
        world.running()
        before = self.owned(world)
        omitted = world.app.omitted_count
        with world.app.lock:
            for method, params in (
                    ("turn/started", {"threadId": "thread-one", "turn": "SYNTHETIC_NOT_A_DICT"}),
                    ("turn/started", {"threadId": "thread-one", "turn": {"id": "bad id with spaces"}}),
                    ("turn/started", {"threadId": "thread-one", "turn": {"id": 7}}),
                    ("turn/started", {"threadId": "thread-one"}),
                    ("turn/completed", {"threadId": "thread-one", "turn": {"id": "x" * 201, "status": "failed"}}),
                    ("turn/completed", {"threadId": "thread-other", "turn": {"id": "turn-one", "status": "failed"}}),
                    ("turn/started", {"threadId": "thread-other", "turn": {"id": "turn-two"}}),
                    ("turn/started", {"threadId": 5, "turn": {"id": "turn-two"}})):
                world.app._conversation_metadata(method, params)
        self.assertEqual(before, self.owned(world))
        self.assertEqual(omitted, world.app.omitted_count)
        self.assertNotIn("thread-other", world.app.owned_threads)

    def test_note_turn_for_unowned_thread_changes_nothing(self):
        world = World(self)
        world.running()
        before = self.owned(world)
        with world.app.lock:
            world.app._note_turn("thread-other", "turn-two", "started")
            world.app._note_turn("thread-other", "turn-one", "completed", "failed")
        self.assertEqual(before, self.owned(world))
        self.assertNotIn("thread-other", world.app.owned_threads)

    def test_conversation_metadata_unhashable_status_still_raises(self):
        # Pinned for the refactor only: today an unhashable turn status on the current turn raises
        # TypeError from the status lookup, after `active` is cleared. The extraction keeps that.
        world = World(self)
        world.running()
        with world.app.lock, self.assertRaises(TypeError):
            world.app._conversation_metadata(
                "turn/completed", {"threadId": "thread-one", "turn": {"id": "turn-one", "status": ["x"]}})
        self.assertFalse(world.app._owned("thread-one")["active"])


if __name__ == "__main__":
    unittest.main()

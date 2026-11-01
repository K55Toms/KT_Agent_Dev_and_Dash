"""Tests for the pure Claude stream parser (dashboard/backends/claude_stream.py)."""
import copy
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.backends.base import EVENT_KINDS, NO, UNCONFIRMED, NeutralEvent  # noqa: E402
from dashboard.backends.claude_stream import (ClaudeCapabilities, StreamState, cost_usd,  # noqa: E402
                                              translate_stream_line, usage_from_model_usage)
from dashboard.backends.codex import USAGE_KEYS  # noqa: E402
from fake_claude import fixture_path, huge_line  # noqa: E402

SID = "00000000-0000-4000-8000-000000005e55"
MARKERS = ("SENSITIVE_TOOL_INPUT_MARKER", "SENSITIVE_HOOK_OUTPUT_MARKER",
           "SENSITIVE_ASSISTANT_TEXT_MARKER", "SENSITIVE_SUBAGENT_TEXT_MARKER", "SENSITIVE")
NEUTRAL = tuple(USAGE_KEYS.values())


def lines(name):
    return fixture_path(name).read_text().splitlines()


def run(name, state=None):
    state = state or StreamState(turn_id="turn-1")
    events = []
    for line in lines(name):
        events.extend(translate_stream_line(line, state))
    return events, state


def result_line(model_usage=None, cost=0.0, is_error=False, terminal="completed", denials=None,
                subtype="success", api=None, **extra):
    d = {"type": "result", "subtype": subtype, "is_error": is_error, "api_error_status": api,
         "total_cost_usd": cost, "modelUsage": model_usage if model_usage is not None else {},
         "permission_denials": denials or [], "terminal_reason": terminal}
    d.update(extra)
    return json.dumps(d)


def mu(i=1, o=2, cr=3, cc=4, th=5):
    return {"inputTokens": i, "outputTokens": o, "cacheReadInputTokens": cr,
            "cacheCreationInputTokens": cc, "thinkingTokens": th}


class StreamTests(unittest.TestCase):
    def test_init_gives_turn_started_and_fills_state(self):
        events, state = run("success")
        self.assertEqual(events[0], NeutralEvent("turn_started", SID, "turn-1", events[0].data))
        self.assertEqual(state.session_id, SID)
        self.assertEqual(state.model_id, "claude-haiku-5-5")
        self.assertEqual(state.permission_mode, "default")
        self.assertEqual(state.version, "2.1.312")

    def test_first_init_only_emits_turn_started(self):
        events, _ = run("multi_result")
        self.assertEqual([e.kind for e in events].count("turn_started"), 1)

    def test_permission_mode_and_model_are_carried_in_event_data(self):
        events, _ = run("permission_mode_auto")
        self.assertEqual(dict(events[0].data), {"permission_mode": "auto", "model_id": "claude-haiku-5-5",
                                                "version": "2.1.312"})

    def test_result_success_gives_usage_then_completed(self):
        events, state = run("success")
        self.assertEqual([e.kind for e in events], ["turn_started", "usage_updated", "turn_completed"])
        usage = events[1].data
        self.assertEqual(usage["usage"], {"input_tokens": 80734, "cached_input_tokens": 61400,
                                          "output_tokens": 340, "reasoning_output_tokens": 223,
                                          "total_tokens": 81074})
        self.assertEqual(usage["cost_usd"], 0.0047)
        self.assertEqual(events[2].data["status"], "completed")
        self.assertIsNone(events[2].data["error"])
        self.assertTrue(state.seen_result)

    def test_result_error_is_failed(self):
        state = StreamState(turn_id="t")
        ev = translate_stream_line(result_line(is_error=True, terminal="api_error", api=500), state)
        self.assertEqual(ev[-1].data["status"], "failed")
        self.assertEqual(ev[-1].data["error"], {"terminal_reason": "api_error", "api_error_status": 500,
                                                "subtype": "success"})

    def test_bad_model_fixture_gives_failed_with_api_error_status_404(self):
        events, _ = run("bad_model")
        done = events[-1]
        self.assertEqual(done.kind, "turn_completed")
        self.assertEqual(done.data["status"], "failed")
        self.assertEqual(done.data["error"]["api_error_status"], 404)
        self.assertEqual(done.data["error"]["terminal_reason"], "api_error")

    def test_aborted_terminal_reason_is_unknown(self):
        state = StreamState(turn_id="t")
        ev = translate_stream_line(result_line(is_error=True, terminal="aborted_tools"), state)
        self.assertEqual(ev[-1].data["status"], "unknown")

    def test_interrupted_fixture_gives_unknown_and_usage_kept(self):
        events, _ = run("interrupted")
        self.assertEqual(events[-1].data["status"], "unknown")
        self.assertEqual(events[-1].data["error"]["subtype"], "error_during_execution")
        self.assertEqual(events[-2].data["usage"]["output_tokens"], 80)

    def test_error_during_execution_is_unknown(self):
        state = StreamState(turn_id="t")
        ev = translate_stream_line(result_line(is_error=True, terminal="other",
                                               subtype="error_during_execution"), state)
        self.assertEqual(ev[-1].data["status"], "unknown")

    def test_no_result_fixture_emits_only_turn_started(self):
        events, state = run("no_result")
        self.assertEqual([e.kind for e in events], ["turn_started"])
        self.assertFalse(state.seen_result)

    def test_second_result_is_ignored(self):
        state = StreamState(turn_id="t")
        first = translate_stream_line(result_line(mu(), 0.5), state)
        second = translate_stream_line(result_line(mu(9, 9, 9, 9, 9), 0.9, denials=[
            {"tool_name": "Late", "tool_use_id": "x"}]), state)
        self.assertEqual([e.kind for e in first], ["usage_updated", "turn_completed"])
        self.assertEqual(second, [])
        self.assertEqual(state.denied_count, 0)

    def test_multi_result_fixture_emits_one_completion(self):
        events, _ = run("multi_result")
        self.assertEqual([e.kind for e in events].count("turn_completed"), 1)

    def test_denials_keep_tool_names_and_counts_only(self):
        events, state = run("denied")
        self.assertEqual(state.denied_tools, ["Bash"])
        self.assertEqual(state.denied_count, 1)
        self.assertNotIn("tool_input", repr(events))

    def test_denied_tool_name_validation_and_dedupe(self):
        state = StreamState(turn_id="t")
        def denial(name, tid):
            return json.dumps({"type": "system", "subtype": "permission_denied", "tool_name": name,
                               "tool_use_id": tid})
        translate_stream_line(denial("Bash", "a"), state)
        translate_stream_line(denial("Bash", "a"), state)       # same id: counted once
        translate_stream_line(denial("mcp__x:y.z-1", "b"), state)
        translate_stream_line(denial("bad name/../etc", "c"), state)
        translate_stream_line(denial("x" * 65, "d"), state)
        translate_stream_line(denial(5, "e"), state)
        self.assertEqual(state.denied_tools, ["Bash", "mcp__x:y.z-1", "unknown_tool"])
        self.assertEqual(state.denied_count, 6 - 1)
        # the same denial reported again in result.permission_denials is not double counted
        translate_stream_line(result_line(denials=[{"tool_name": "Bash", "tool_use_id": "a"},
                                                   {"tool_name": "Edit", "tool_use_id": "f"}]), state)
        self.assertEqual(state.denied_count, 6)
        self.assertEqual(state.denied_tools, ["Bash", "mcp__x:y.z-1", "unknown_tool", "Edit"])
        for i in range(60):
            translate_stream_line(denial("T%d" % i, "id%d" % i), StreamState(turn_id="t"))
        big = StreamState(turn_id="t")
        for i in range(300):
            translate_stream_line(denial("T%d" % i, "id%d" % i), big)
        self.assertEqual(len(big.denied_tools), 20)
        self.assertEqual(big.denied_count, 300)
        self.assertLessEqual(len(big.denied_ids), 200)

    def test_subagent_events_are_ignored(self):
        state = StreamState(turn_id="t")
        for obj in ({"type": "system", "subtype": "init", "session_id": SID, "parent_tool_use_id": "tu"},
                    {"type": "result", "parent_tool_use_id": "tu", "modelUsage": {"m": mu()}},
                    {"type": "system", "subtype": "permission_denied", "tool_name": "Bash", "agent_id": "a"}):
            self.assertEqual(translate_stream_line(json.dumps(obj), state), [])
        self.assertIsNone(state.session_id)
        self.assertFalse(state.seen_result)
        self.assertEqual(state.denied_count, 0)

    def test_subagent_fixture_changes_nothing_and_leaks_nothing(self):
        events, state = run("subagent")
        self.assertEqual([e.kind for e in events], ["turn_started", "usage_updated", "turn_completed"])
        for m in MARKERS:
            self.assertNotIn(m, repr(events) + repr(state))

    def test_junk_lines_never_raise(self):
        state = StreamState(turn_id="t")
        junk = ["", "x", "[]", "{", "null", "5", '"s"', "{}", '{"type": 5}', '{"type": "result", "modelUsage": 3}',
                '{"type": "system", "subtype": ["a"]}', '{"type":"result","permission_denials":"x"}',
                '{"type":"result","permission_denials":[1,null,{"tool_name":{}}]}',
                '{"type":"system","subtype":"init","session_id":{}}', "\x00\xff", "A" * 1048576]
        for line in junk:
            for ev in translate_stream_line(line, state):
                self.assertIsInstance(ev, NeutralEvent)

    def test_oversized_line_is_ignored(self):
        state = StreamState(turn_id="t")
        big = result_line(mu()) + " " * (1024 * 1024 + 1)
        self.assertEqual(translate_stream_line(big, state), [])
        self.assertFalse(state.seen_result)
        self.assertEqual(translate_stream_line(huge_line(), state), [])
        marker = lines("huge_line")[0]
        self.assertEqual(translate_stream_line(marker, state), [])

    def test_malformed_fixture_is_survivable(self):
        events, state = run("malformed")
        self.assertTrue(all(isinstance(e, NeutralEvent) for e in events))
        self.assertIn("turn_completed", [e.kind for e in events])

    def test_usage_mapping_sums_models_and_counts_cache_as_input(self):
        got = usage_from_model_usage({"a": mu(1, 2, 3, 4, 5), "b": mu(10, 20, 30, 40, 50)})
        self.assertEqual(got, {"input_tokens": 1 + 3 + 4 + 10 + 30 + 40, "cached_input_tokens": 33,
                               "output_tokens": 22, "reasoning_output_tokens": 55,
                               "total_tokens": 88 + 22})
        self.assertEqual(set(got), set(USAGE_KEYS.values()))
        self.assertEqual(usage_from_model_usage({}), dict.fromkeys(NEUTRAL, 0))

    def test_bad_usage_values_are_skipped_not_raised(self):
        good = mu(1, 1, 1, 1, 1)
        bad = [dict(good, inputTokens=-1), dict(good, outputTokens="5"), dict(good, thinkingTokens=1e20),
               dict(good, cacheReadInputTokens=True), dict(good, inputTokens=10 ** 15), "x", None, [1]]
        got = usage_from_model_usage({"ok": good, **{"b%d" % i: b for i, b in enumerate(bad)}})
        self.assertEqual(got["output_tokens"], 1)
        self.assertEqual(got["input_tokens"], 3)
        self.assertEqual(usage_from_model_usage("junk"), dict.fromkeys(NEUTRAL, 0))
        self.assertEqual(usage_from_model_usage({str(i): good for i in range(5000)})["output_tokens"], 64)

    def test_absent_usage_keys_count_as_zero_present_invalid_skip(self):
        self.assertEqual(usage_from_model_usage({"a": {"inputTokens": 5, "outputTokens": 7}}),
                         {"input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 7,
                          "reasoning_output_tokens": 0, "total_tokens": 12})
        no_think = {k: v for k, v in mu().items() if k != "thinkingTokens"}
        self.assertEqual(usage_from_model_usage({"a": no_think})["reasoning_output_tokens"], 0)
        no_cache = {"inputTokens": 3, "outputTokens": 4, "thinkingTokens": 1}
        got = usage_from_model_usage({"a": no_cache})
        self.assertEqual((got["input_tokens"], got["cached_input_tokens"]), (3, 0))
        for bad in (True, 1.5, -1, 10 ** 15, "1", None):
            self.assertEqual(usage_from_model_usage({"a": dict(mu(), thinkingTokens=bad)}),
                             dict.fromkeys(NEUTRAL, 0))
        g = usage_from_model_usage({"a": mu(), "b": no_cache})
        self.assertGreaterEqual(g["input_tokens"], g["cached_input_tokens"])

    def test_model_id_validation(self):
        def model(m):
            st = StreamState(turn_id="t")
            ev = translate_stream_line(json.dumps({"type": "system", "subtype": "init", "session_id": SID,
                                                   "model": m}), st)
            self.assertEqual(st.model_id, ev[0].data["model_id"])
            return st.model_id
        self.assertEqual(model("claude-haiku-5-5"), "claude-haiku-5-5")
        self.assertIsNone(model("/Users/x/secret"))
        self.assertIsNone(model("arn:aws:bedrock:us-east-1:123456789012:inference-profile/x"))
        self.assertIsNone(model("ARN:aws:x"))
        self.assertIsNone(model("x" * 101))

    def test_oversized_multibyte_line_is_ignored(self):
        state = StreamState(turn_id="t")
        line = '{"type":"result","x":"' + "\u00e9" * 600000 + '"}'   # ~600k chars, ~1.2 MB in UTF-8
        self.assertLess(len(line), 1024 * 1024)
        self.assertEqual(translate_stream_line(line, state), [])
        self.assertFalse(state.seen_result)

    def test_aborted_reason_wins_over_is_error_false(self):
        state = StreamState(turn_id="t")
        ev = translate_stream_line(result_line(is_error=False, terminal="aborted_streaming"), state)
        self.assertEqual(ev[-1].data["status"], "unknown")

    def test_invalid_session_id_still_emits_result_with_no_thread(self):
        state = StreamState(turn_id="t")
        translate_stream_line(json.dumps({"type": "system", "subtype": "init", "session_id": "bad id"}), state)
        ev = translate_stream_line(result_line(mu(), 0.1), state)
        self.assertEqual([e.kind for e in ev], ["usage_updated", "turn_completed"])
        self.assertTrue(all(e.thread_id is None for e in ev))

    def test_cost_usd_bounds(self):
        self.assertEqual(cost_usd({"total_cost_usd": 0.5}), 0.5)
        self.assertEqual(cost_usd({"total_cost_usd": 3}), 3.0)
        for bad in (-1, 1e7, "1", None, True, float("nan"), float("inf")):
            self.assertEqual(cost_usd({"total_cost_usd": bad}), 0.0)
        self.assertEqual(cost_usd({}), 0.0)
        self.assertEqual(cost_usd("x"), 0.0)

    def test_baseline_adds_and_totals_never_decrease(self):
        baseline = dict(dict.fromkeys(NEUTRAL, 0), input_tokens=100, total_tokens=130, output_tokens=30,
                        cost_usd=1.0)
        state = StreamState(turn_id="t", baseline=baseline)
        ev = translate_stream_line(result_line({"m": mu(1, 2, 3, 4, 5)}, 0.5), state)
        self.assertEqual(ev[0].data["usage"]["input_tokens"], 108)
        self.assertEqual(ev[0].data["usage"]["output_tokens"], 32)
        self.assertEqual(ev[0].data["usage"]["total_tokens"], 140)
        self.assertEqual(ev[0].data["cost_usd"], 1.5)
        # a later (ignored for completion) result with lower usage must not lower the totals
        state.seen_result = False
        ev2 = translate_stream_line(result_line({"m": mu(0, 0, 0, 0, 0)}, 0.1), state)
        self.assertEqual(ev2[0].data["usage"], ev[0].data["usage"])
        self.assertEqual(ev2[0].data["cost_usd"], 1.5)

    def test_empty_model_usage_keeps_previous_totals(self):
        state = StreamState(turn_id="t", baseline=dict(dict.fromkeys(NEUTRAL, 7), cost_usd=2.0))
        ev = translate_stream_line(result_line({}, 0.0), state)
        self.assertEqual(ev[0].data["usage"], dict.fromkeys(NEUTRAL, 7))
        self.assertEqual(ev[0].data["cost_usd"], 2.0)
        self.assertEqual(ev[1].kind, "turn_completed")

    def test_no_sensitive_text_in_any_event(self):
        for name in ("success", "denied", "resumed", "interrupted", "bad_model", "malformed",
                     "permission_mode_auto", "subagent", "multi_result", "no_result"):
            events, state = run(name)
            blob = repr(events) + repr(state)
            for m in MARKERS:
                self.assertNotIn(m, blob, name)
            self.assertNotIn("/Users", blob)
            self.assertNotIn("toolu_synth", repr(events))

    def test_every_emitted_kind_is_in_event_kinds(self):
        for name in ("success", "denied", "resumed", "interrupted", "bad_model", "malformed",
                     "subagent", "multi_result"):
            for e in run(name)[0]:
                self.assertIn(e.kind, EVENT_KINDS)

    def test_state_is_the_only_thing_mutated(self):
        baseline = dict(dict.fromkeys(NEUTRAL, 1), cost_usd=0.1)
        before = copy.deepcopy(baseline)
        state = StreamState(turn_id="t", baseline=baseline)
        for line in lines("denied"):
            translate_stream_line(line, state)
        self.assertEqual(baseline, before)
        self.assertEqual(StreamState.baseline_zero(), dict(dict.fromkeys(NEUTRAL, 0), cost_usd=0.0))
        a, b = StreamState(turn_id="x"), StreamState(turn_id="y")
        a.denied_tools.append("Z")
        self.assertEqual(b.denied_tools, [])

    def test_init_validation(self):
        state = StreamState(turn_id="t")
        bad = json.dumps({"type": "system", "subtype": "init", "session_id": "bad id with spaces"})
        self.assertEqual(translate_stream_line(bad, state), [])
        self.assertIsNone(state.session_id)
        odd = json.dumps({"type": "system", "subtype": "init", "session_id": SID, "model": "bad model!",
                          "permissionMode": "x" * 41, "claude_code_version": "evil; rm"})
        ev = translate_stream_line(odd, state)
        self.assertEqual(dict(ev[0].data), {"permission_mode": None, "model_id": None, "version": None})

    def test_other_events_return_nothing(self):
        state = StreamState(turn_id="t")
        for t in ("assistant", "user", "stream_event", "rate_limit_event"):
            self.assertEqual(translate_stream_line(json.dumps({"type": t, "parent_tool_use_id": None}), state), [])
        for s in ("hook_started", "hook_response", "task_started", "task_summary", "thinking_tokens"):
            self.assertEqual(translate_stream_line(json.dumps({"type": "system", "subtype": s}), state), [])

    def test_property_junk_lines(self):
        rng = random.Random(1234)
        keys = ["type", "subtype", "session_id", "model", "permissionMode", "modelUsage", "total_cost_usd",
                "permission_denials", "tool_name", "tool_use_id", "is_error", "terminal_reason",
                "api_error_status", "parent_tool_use_id", "agent_id", "claude_code_version"]
        types = ["system", "result", "assistant", "user", 5, None, ["x"]]
        subs = ["init", "permission_denied", "success", "hook_started", None, 3]

        def val(depth=0):
            c = rng.randrange(9)
            if c == 0:
                return None
            if c == 1:
                return rng.choice([True, False])
            if c == 2:
                return rng.choice([0, -1, 5, 10 ** 16, 2 ** 70, 1.5, float(rng.random())])
            if c == 3:
                return rng.choice(["", "Bash", SID, "x" * 300, "a b", "aborted_x", "é"])
            if c == 4 and depth < 3:
                return [val(depth + 1) for _ in range(rng.randrange(4))]
            if c == 5 and depth < 3:
                return {rng.choice(keys + ["inputTokens", "outputTokens"]): val(depth + 1)
                        for _ in range(rng.randrange(5))}
            if c == 6:
                return {"m": {"inputTokens": rng.randrange(-5, 100), "outputTokens": val(3)}}
            return rng.choice(types)

        state = StreamState(turn_id="t")
        for _ in range(400):
            obj = {rng.choice(keys): val() for _ in range(rng.randrange(1, 8))}
            obj["type"] = rng.choice(types)
            obj["subtype"] = rng.choice(subs)
            line = json.dumps(obj)
            if rng.random() < 0.1:
                line = line[:rng.randrange(len(line))]
            if rng.random() < 0.15:
                state.seen_result = False
            for ev in translate_stream_line(line, state):
                self.assertIsInstance(ev, NeutralEvent)
                self.assertIn(ev.kind, EVENT_KINDS)
        self.assertLessEqual(len(state.denied_tools), 20)

    def test_capabilities(self):
        c = ClaudeCapabilities
        self.assertEqual((c.provider, c.guidance_while_running, c.subagent_questions, c.plan, c.recovery,
                          c.assessment, c.approval_alternative),
                         ("claude", NO, NO, UNCONFIRMED, NO, NO, NO))


if __name__ == "__main__":
    unittest.main()

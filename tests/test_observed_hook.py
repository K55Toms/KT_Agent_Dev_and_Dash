"""Tests for observed-session hook event parsing (dashboard/observed_hook.py)."""
import dataclasses
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import observed_hook  # noqa: E402
from dashboard.backends import claude_hook  # noqa: E402
from dashboard.backends.claude_hook import HookRejected, MAX_BODY  # noqa: E402

SESSION = "00000000-0000-4000-8000-000000000b5e"


def raw(obj):
    return json.dumps(obj).encode("utf-8")


def base(event, **extra):
    body = {"hook_event_name": event, "session_id": SESSION, "cwd": "/synthetic/projects/alpha",
            "prompt_id": "prompt-synthetic-1", "transcript_path": "/synthetic/transcript.jsonl",
            "scratchpad_dir": "/synthetic/scratch"}
    body.update(extra)
    return body


# Field names follow spike S7 for the events it saw. PostToolUse and Stop were not observed live (S11
# pending), so their bodies here are assumptions; the parser is lenient about their extra fields.
FIXTURES = {
    "permission_request": base("PermissionRequest", permission_mode="default", effort="low",
                               permission_suggestions=[{"type": "addRules"}], tool_name="Bash",
                               tool_input={"command": "echo SENTINEL_OBSERVED"}),
    "post_tool_use": base("PostToolUse", permission_mode="default", tool_name="Bash",
                          tool_input={"command": "echo SENTINEL_OBSERVED"},
                          tool_response={"stdout": "SENTINEL_RESPONSE"}),
    "stop": base("Stop", permission_mode="default", stop_hook_active=False,
                 last_assistant_message="SENTINEL_MESSAGE"),
    "session_start": base("SessionStart", source="startup"),
    "session_end": base("SessionEnd", reason="other"),
    "subagent_start": base("SubagentStart", agent_id="agent-synthetic-1", agent_type="synthetic-worker"),
    "subagent_stop": base("SubagentStop", agent_id="agent-synthetic-1", agent_type="synthetic-worker",
                          agent_transcript_path="/synthetic/agent.jsonl", background_tasks=[],
                          session_crons=[], stop_hook_active=False, effort="low",
                          last_assistant_message="SENTINEL_MESSAGE"),
}


class ParseObservedTests(unittest.TestCase):
    def test_parse_each_event_kind(self):
        for kind, body in FIXTURES.items():
            with self.subTest(kind):
                event = observed_hook.parse_observed(raw(body))
                self.assertIsInstance(event, observed_hook.ObservedEvent)
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.session_id, SESSION)
                self.assertEqual(event.cwd, "/synthetic/projects/alpha")
                self.assertNotIn("SENTINEL_RESPONSE", repr(event))
                self.assertNotIn("SENTINEL_MESSAGE", repr(event))
                self.assertNotIn("transcript", repr(event))
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    event.kind = "x"
        perm = observed_hook.parse_observed(raw(FIXTURES["permission_request"]))
        self.assertIsInstance(perm.request, claude_hook.HookRequest)
        self.assertEqual(perm.request.tool_name, "Bash")
        self.assertEqual(perm.request.tool_input, {"command": "echo SENTINEL_OBSERVED"})
        self.assertIsNone(perm.agent_id)
        post = observed_hook.parse_observed(raw(FIXTURES["post_tool_use"]))
        self.assertIsNone(post.request)
        self.assertEqual(post.tool_name, "Bash")
        self.assertEqual(post.tool_input, {"command": "echo SENTINEL_OBSERVED"})
        sub = observed_hook.parse_observed(raw(FIXTURES["subagent_start"]))
        self.assertEqual(sub.agent_id, "agent-synthetic-1")
        stop = observed_hook.parse_observed(raw(FIXTURES["stop"]))
        self.assertIsNone(stop.request)
        self.assertIsNone(stop.tool_name)
        self.assertIsNone(stop.tool_input)

    def test_subagent_permission_request_carries_agent_id(self):
        body = dict(FIXTURES["permission_request"], agent_id="agent-synthetic-2", agent_type="synthetic-worker")
        event = observed_hook.parse_observed(raw(body))
        self.assertEqual(event.agent_id, "agent-synthetic-2")
        self.assertEqual(event.request.agent_type, "synthetic-worker")

    def test_post_tool_use_is_lenient_but_checks_what_is_present(self):
        bare = {"hook_event_name": "PostToolUse", "session_id": SESSION}
        event = observed_hook.parse_observed(raw(bare))
        self.assertIsNone(event.tool_name)
        self.assertIsNone(event.tool_input)
        self.assertIsNone(event.cwd)
        for bad in ({"tool_name": "bad name!"}, {"tool_name": 5}, {"tool_input": "text"},
                    {"tool_input": [1]}, {"agent_id": "bad id!"}):
            with self.subTest(bad):
                with self.assertRaises(HookRejected):
                    observed_hook.parse_observed(raw(dict(bare, **bad)))

    def test_unknown_event_rejected(self):
        for name in ("Notification", "permissionrequest", "", None, 7, ["Stop"]):
            with self.subTest(name):
                with self.assertRaises(HookRejected) as ctx:
                    observed_hook.parse_observed(raw(dict(FIXTURES["stop"], hook_event_name=name)))
                self.assertEqual(ctx.exception.code, "bad_field")
        missing = dict(FIXTURES["stop"])
        del missing["hook_event_name"]
        with self.assertRaises(HookRejected) as ctx:
            observed_hook.parse_observed(raw(missing))
        self.assertEqual(ctx.exception.code, "bad_field")

    def test_session_id_required_and_patterned(self):
        for value in (None, "", "bad id!", 12, "x" * 201):
            with self.subTest(value):
                body = dict(FIXTURES["session_end"], session_id=value)
                with self.assertRaises(HookRejected) as ctx:
                    observed_hook.parse_observed(raw(body))
                self.assertEqual(ctx.exception.code, "bad_field")

    def test_cwd_must_be_bounded_string(self):
        ok = observed_hook.parse_observed(raw(dict(FIXTURES["stop"], cwd="/" + "a" * 4095)))
        self.assertEqual(len(ok.cwd), 4096)
        for kind in ("stop", "permission_request", "post_tool_use"):
            for value in ("/" + "a" * 4096, 5, ["/x"], {"p": "/x"}, True):
                with self.subTest(kind=kind, value=type(value).__name__):
                    with self.assertRaises(HookRejected) as ctx:
                        observed_hook.parse_observed(raw(dict(FIXTURES[kind], cwd=value)))
                    self.assertEqual(ctx.exception.code, "bad_field")

    def test_permission_request_reuses_managed_limits(self):
        perm = FIXTURES["permission_request"]
        oversize = raw(dict(perm, tool_input={"command": "x" * (MAX_BODY + 1)}))
        with self.assertRaises(HookRejected) as ctx:
            observed_hook.parse_observed(oversize)
        self.assertEqual(ctx.exception.code, "too_large")
        duplicate = raw(perm)[:-1] + b', "session_id": "other"}'
        with self.assertRaises(HookRejected) as ctx:
            observed_hook.parse_observed(duplicate)
        self.assertEqual(ctx.exception.code, "bad_json")
        nan = raw(perm)[:-1] + b', "x": NaN}'
        with self.assertRaises(HookRejected) as ctx:
            observed_hook.parse_observed(nan)
        self.assertEqual(ctx.exception.code, "bad_json")
        # the strict managed parser still applies: tool_input is required for a permission request
        no_input = dict(perm)
        del no_input["tool_input"]
        with self.assertRaises(HookRejected) as ctx:
            observed_hook.parse_observed(raw(no_input))
        self.assertEqual(ctx.exception.code, "bad_shape")
        # and the same limits apply to the other events
        for kind in ("post_tool_use", "stop"):
            with self.subTest(kind):
                with self.assertRaises(HookRejected) as ctx:
                    observed_hook.parse_observed(raw(FIXTURES[kind])[:-1] + b', "x": Infinity}')
                self.assertEqual(ctx.exception.code, "bad_json")

    def test_bad_bodies_rejected_without_echo(self):
        marker = "SENTINEL_" + "Q" * 20
        cases = [(b"not json " + marker.encode(), "bad_json"), (raw([marker]), "bad_shape"),
                 (raw(marker), "bad_shape"), (b"\xff\xfe", "bad_json"),
                 (raw(dict(FIXTURES["stop"], session_id=marker + "!")), "bad_field")]
        for body, code in cases:
            with self.subTest(code):
                with self.assertRaises(HookRejected) as ctx:
                    observed_hook.parse_observed(body)
                self.assertEqual(ctx.exception.code, code)
                self.assertNotIn(marker, str(ctx.exception))
                self.assertNotIn(marker, repr(ctx.exception))
        with self.assertRaises(HookRejected) as ctx:
            observed_hook.parse_observed("text")
        self.assertEqual(ctx.exception.code, "bad_shape")


if __name__ == "__main__":
    unittest.main()

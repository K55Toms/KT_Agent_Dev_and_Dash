"""Tests for the pure Claude hook protocol module (dashboard/backends/claude_hook.py)."""
import dataclasses
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.backends import claude_hook as hook  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "claude")


def load(name):
    with open(os.path.join(FIXTURES, name), "rb") as handle:
        return json.loads(handle.read())


def raw(obj):
    return json.dumps(obj).encode("utf-8")


class ParseTests(unittest.TestCase):
    def test_parse_accepts_s7_payload_fields(self):
        req = hook.parse_request(raw(load("hook_main.json")))
        self.assertEqual(req.session_id, "00000000-0000-4000-8000-000000005e55")
        self.assertEqual(req.permission_mode, "default")
        self.assertEqual(req.tool_name, "Bash")
        self.assertEqual(req.tool_input, {"command": "echo SENTINEL_HOOK_INPUT"})
        self.assertEqual(req.prompt_id, "prompt-synthetic-1")
        self.assertIsNone(req.agent_id)
        self.assertIsNone(req.agent_type)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            req.tool_name = "x"

    def test_parse_subagent_and_drops_unknown_fields(self):
        req = hook.parse_request(raw(load("hook_subagent.json")))
        self.assertEqual(req.agent_id, "agent-synthetic-1")
        self.assertEqual(req.agent_type, "synthetic-worker")
        self.assertNotIn("SENTINEL_UNKNOWN_FIELD", repr(req))
        self.assertEqual(sorted(f.name for f in dataclasses.fields(req)),
                         ["agent_id", "agent_type", "permission_mode", "prompt_id", "session_id",
                          "tool_input", "tool_name"])

    def test_tool_input_is_a_copy(self):
        source = {"command": "x", "nested": {"k": [1]}}
        body = raw(dict(load("hook_main.json"), tool_input=source))
        a = hook.parse_request(body)
        a.tool_input["command"] = "MUTATED"
        a.tool_input["nested"]["k"].append(2)
        self.assertEqual(source, {"command": "x", "nested": {"k": [1]}})
        self.assertEqual(hook.parse_request(body).tool_input, source)

    def test_non_default_permission_mode_parses(self):
        for mode in ("acceptEdits", "bypassPermissions", "plan", "dontAsk", "auto"):
            with self.subTest(mode):
                req = hook.parse_request(raw(dict(load("hook_main.json"), permission_mode=mode)))
                self.assertEqual(req.permission_mode, mode)

    def test_missing_or_null_mode_is_none_and_odd_mode_rejected(self):
        data = load("hook_main.json")
        data.pop("permission_mode")
        self.assertIsNone(hook.parse_request(raw(data)).permission_mode)
        self.assertIsNone(hook.parse_request(raw(dict(data, permission_mode=None))).permission_mode)
        with self.assertRaises(hook.HookRejected) as ctx:
            hook.parse_request(raw(dict(data, permission_mode="a b")))
        self.assertEqual(ctx.exception.code, "bad_field")

    def test_id_fields_reject_newline_nul_space(self):
        for field in ("session_id", "agent_id", "agent_type", "prompt_id"):
            for bad in ("ab\n", "a\nb", "a\u0000b", "a b", " ab", "ab "):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(hook.HookRejected) as ctx:
                        hook.parse_request(raw(dict(load("hook_main.json"), **{field: bad})))
                    self.assertEqual(ctx.exception.code, "bad_field")

    def test_tool_name_and_mode_reject_newline_nul_space(self):
        # Task 5 ruling (d): the automatic allow-list compares tool_name by exact equality, so a name such as
        # "Bash\n" must never parse.
        for field, base in (("tool_name", "Bash"), ("permission_mode", "default")):
            for bad in (base + "\n", base + "\r\n", "\n" + base, base[:2] + "\n" + base[2:], base + "\u0000",
                        base + " ", " " + base, base[:2] + " " + base[2:], base + "\t", ""):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(hook.HookRejected) as ctx:
                        hook.parse_request(raw(dict(load("hook_main.json"), **{field: bad})))
                    self.assertEqual(ctx.exception.code, "bad_field")

    def test_parse_rejects(self):
        good = load("hook_main.json")

        def mutate(**kw):
            data = dict(good)
            for key, value in kw.items():
                if value is KeyError:
                    data.pop(key)
                else:
                    data[key] = value
            return raw(data)

        deep = {}
        cur = deep
        for _ in range(40):
            cur["a"] = {}
            cur = cur["a"]
        cases = {
            "non_object_list": (b"[]", "bad_shape"),
            "non_object_str": (b'"x"', "bad_shape"),
            "wrong_event": (mutate(hook_event_name="PreToolUse"), "bad_field"),
            "missing_event": (mutate(hook_event_name=KeyError), "bad_field"),
            "missing_tool_name": (mutate(tool_name=KeyError), "bad_field"),
            "tool_name_int": (mutate(tool_name=3), "bad_field"),
            "missing_session": (mutate(session_id=KeyError), "bad_field"),
            "session_int": (mutate(session_id=3), "bad_field"),
            "tool_input_list": (mutate(tool_input=[1]), "bad_shape"),
            "tool_input_missing": (mutate(tool_input=KeyError), "bad_shape"),
            "too_deep": (mutate(tool_input=deep), "bad_shape"),
            "agent_type_int": (mutate(agent_type=5), "bad_field"),
            "oversize": (b" " * (hook.MAX_BODY + 1), "too_large"),
            "bad_utf8": (b'{"a":"\xff"}', "bad_json"),
            "not_json": (b"{", "bad_json"),
            "nan": (b'{"a":NaN}', "bad_json"),
            "duplicate_key": (b'{"session_id":"a","session_id":"b"}', "bad_json"),
            "nested_duplicate_key": (b'{"tool_input":{"x":1,"x":2}}', "bad_json"),
            "inf_float": (b'{"hook_event_name":"PermissionRequest","session_id":"a","tool_name":"B","tool_input":{"x":1e999}}', "bad_json"),
            "lone_surrogate": (b'{"hook_event_name":"PermissionRequest","session_id":"a","tool_name":"B","tool_input":{"x":"\\ud800"}}', "bad_field"),
            "not_bytes": ("text", "bad_shape"),
        }
        for name, (body, code) in cases.items():
            with self.subTest(name):
                with self.assertRaises(hook.HookRejected) as ctx:
                    hook.parse_request(body)
                self.assertEqual(ctx.exception.code, code)
                self.assertIs(type(ctx.exception), hook.HookRejected)
                self.assertEqual(str(ctx.exception), code)

    def test_exactly_max_body_is_not_too_large(self):
        body = raw(load("hook_main.json"))
        body += b" " * (hook.MAX_BODY - len(body))
        self.assertEqual(hook.parse_request(body).tool_name, "Bash")

    def test_hook_rejected_is_value_error_with_code(self):
        err = hook.HookRejected("bad_json")
        self.assertIsInstance(err, ValueError)
        self.assertEqual(err.code, "bad_json")


class ReplyTests(unittest.TestCase):
    def test_replies_are_exact(self):
        self.assertEqual(
            hook.allow_reply(),
            b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}')
        self.assertEqual(
            hook.deny_reply(),
            b'{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":'
            b'{"behavior":"deny","message":"Declined in the dashboard."}}}')

    def test_reply_never_contains_request_text(self):
        hook.parse_request(raw(load("hook_subagent.json")))
        for reply in (hook.allow_reply(), hook.deny_reply()):
            self.assertNotIn(b"SENTINEL", reply)
            self.assertNotIn(b"interrupt", reply)
            self.assertNotIn(b"updated", reply)


class WaitTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((hook.MAX_BODY, hook.DEFAULT_WAIT_SECONDS, hook.MIN_WAIT_SECONDS,
                          hook.MAX_WAIT_SECONDS, hook.HOOK_TIMEOUT_MARGIN),
                         (262144, 900, 60, 3600, 60))

    def test_hook_timeout(self):
        self.assertEqual(hook.hook_timeout(60), 120)
        self.assertEqual(hook.hook_timeout(900), 960)
        self.assertEqual(hook.hook_timeout(3600), 3660)
        for bad in (59, 3601, 0, -1, "900", None, 900.0, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    hook.hook_timeout(bad)


if __name__ == "__main__":
    unittest.main()

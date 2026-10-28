"""Tests for the synthetic Claude stream fixtures and the fake ``claude`` executable (tests/fake_claude.py)."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from dashboard.project_files import scan_preview
from tests import fake_claude
from tests.characterization import require_scanner

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude"
NAMES = ("success", "subagent", "denied", "resumed", "interrupted", "bad_model", "no_result", "multi_result", "malformed",
         "permission_mode_auto", "huge_line")
SCRIPT = Path(fake_claude.__file__).resolve()
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
SYNTHETIC_UUID = re.compile(r"00000000-0000-4000-8000-[0-9a-f]{12}")
ABSOLUTE_PATH = re.compile(r"(?<![\w<.:-])/(?:Users|home|private|tmp|var|etc|opt|usr|Library|Volumes)/")
WAIT = 20  # generous: CI machines are slow


def read_lines(name):
    return (FIXTURES / (name + ".jsonl")).read_text(encoding="utf-8").splitlines()


def spawn(environment, *arguments, cwd=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("FAKE_CLAUDE_")}
    env.update(environment)
    return subprocess.Popen([str(SCRIPT), *arguments], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(process):
    """Terminate and reap a child so a failing test never leaves a stray process behind."""
    try:
        if process.poll() is None:
            process.kill()
    finally:
        process.wait(timeout=WAIT)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


class FixtureTests(unittest.TestCase):
    def test_every_fixture_is_valid_jsonl_except_malformed(self):
        for name in NAMES:
            path = FIXTURES / (name + ".jsonl")
            self.assertTrue(path.is_file(), name)
            self.assertEqual(fake_claude.fixture_path(name), path)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"), name)
            lines = text.splitlines()
            self.assertTrue(lines, name)
            if name == "malformed":
                continue
            for number, line in enumerate(lines, 1):
                with self.subTest(fixture=name, line=number):
                    self.assertIsInstance(json.loads(line), dict)

    def test_malformed_mixes_valid_and_invalid_lines(self):
        kinds = []
        for line in read_lines("malformed"):
            try:
                kinds.append(type(json.loads(line)).__name__)
            except ValueError:
                kinds.append("invalid")
        self.assertIn("dict", kinds)
        self.assertIn("list", kinds)
        self.assertGreaterEqual(kinds.count("invalid"), 2)  # a non-JSON line and a truncated one

    def test_fixtures_have_the_documented_shape(self):
        def events(name):
            return [json.loads(line) for line in read_lines(name)]

        def kinds(name):
            return [(event["type"], event.get("subtype")) for event in events(name)]

        sid = events("success")[0]["session_id"]
        self.assertEqual({event["session_id"] for event in events("success")}, {sid})
        success = kinds("success")
        self.assertLess(success.index(("system", "init")), success.index(("result", "success")))
        self.assertEqual(success[-1], ("system", "task_summary"))  # the result is not the last line
        self.assertIn(("system", "hook_started"), success)
        self.assertIn(("system", "hook_response"), success)
        denied = kinds("denied")
        for kind in (("system", "permission_denied"), ("user", None), ("result", "success")):
            self.assertIn(kind, denied)
        denied_result = [e for e in events("denied") if e["type"] == "result"][0]
        self.assertFalse(denied_result["is_error"])
        self.assertEqual(denied_result["permission_denials"][0]["tool_input"]["command"], "SENSITIVE_TOOL_INPUT_MARKER")
        resumed = events("resumed")
        self.assertEqual({e["session_id"] for e in resumed}, {sid})
        success_result = [e for e in events("success") if e["type"] == "result"][0]
        resumed_result = [e for e in resumed if e["type"] == "result"][0]
        self.assertTrue(resumed_result["modelUsage"])
        self.assertNotEqual(resumed_result["modelUsage"], success_result["modelUsage"])
        interrupted = events("interrupted")
        self.assertEqual(interrupted[-1]["subtype"], "error_during_execution")
        self.assertEqual(interrupted[-1]["terminal_reason"], "aborted_tools")
        self.assertTrue(interrupted[-1]["is_error"])
        self.assertIn(("system", "task_started"), kinds("interrupted"))
        for absent in ("api_error_status", "result", "process_turn_index"):
            self.assertNotIn(absent, interrupted[-1])
        for present in ("safety_stops", "model_usage_since_last_result", "errors"):
            self.assertIn(present, interrupted[-1])
        subagent = events("subagent")
        agent_tool = [e for e in subagent if e["type"] == "assistant" and e["message"]["content"][0].get("name") == "Agent"]
        agent_tool_id = agent_tool[0]["message"]["content"][0]["id"]
        children = [e for e in subagent if e.get("parent_tool_use_id")]
        self.assertEqual({e["type"] for e in children}, {"assistant", "user"})
        for child in children:
            self.assertEqual(child["parent_tool_use_id"], agent_tool_id)
            self.assertEqual(child["agent_id"], "agent-synth-1")
        started = [e for e in subagent if e.get("subtype") == "task_started"][0]
        self.assertEqual((started["task_type"], started["task_id"]), ("local_agent", "agent-synth-1"))
        self.assertIn("SENSITIVE_SUBAGENT_TEXT_MARKER", "\n".join(read_lines("subagent")))
        self.assertEqual(sum(1 for e in subagent if e["type"] == "result"), 1)
        bad = events("bad_model")
        self.assertEqual([kind for kind in kinds("bad_model")],
                         [("system", "hook_started"), ("system", "hook_response"), ("system", "init"),
                          ("assistant", None), ("result", "success")])
        self.assertTrue(events("bad_model")[2]["model"])
        self.assertTrue(events("bad_model")[2]["permissionMode"])
        self.assertEqual(bad[-1]["duration_ms"], 532)
        self.assertEqual(bad[-1]["usage"]["output_tokens"], 0)
        self.assertEqual(bad[-1]["type"], "result")
        self.assertTrue(bad[-1]["is_error"])
        self.assertEqual(bad[-1]["api_error_status"], 404)
        self.assertEqual(bad[-1]["terminal_reason"], "api_error")
        self.assertEqual(bad[-2]["type"], "assistant")
        self.assertNotIn("result", {kind[0] for kind in kinds("no_result")})
        self.assertEqual([kind for kind in kinds("no_result")][-1][0], "assistant")
        self.assertEqual(sum(1 for kind in kinds("multi_result") if kind[0] == "result"), 2)
        self.assertNotEqual(events("permission_mode_auto")[0]["permissionMode"], "default")
        for name in ("success", "denied", "resumed"):
            self.assertIn("SENSITIVE_HOOK_OUTPUT_MARKER", "\n".join(read_lines(name)), name)
            self.assertIn("SENSITIVE_ASSISTANT_TEXT_MARKER", "\n".join(read_lines(name)), name)

    @require_scanner()
    def test_fixtures_pass_the_repository_secret_scan(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                scan_preview((FIXTURES / (name + ".jsonl")).read_bytes())

    def test_fixtures_contain_no_absolute_paths_or_real_ids(self):
        for name in NAMES:
            text = (FIXTURES / (name + ".jsonl")).read_text(encoding="utf-8")
            with self.subTest(fixture=name):
                for forbidden in ("/Users/", "/private/", "/home/", "kt111777", "K55Toms", "privaterelay"):
                    self.assertNotIn(forbidden, text)
                self.assertIsNone(ABSOLUTE_PATH.search(text))
                for found in UUID.findall(text):
                    self.assertRegex(found, SYNTHETIC_UUID)
                for identifier in re.findall(r"\b(?:toolu|msg|req)_\w+", text):
                    self.assertRegex(identifier, r"^(?:toolu|msg|req)_synth")


class FakeClaudeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_executable_bit_is_set(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertTrue(SCRIPT.stat().st_mode & 0o111)
        self.assertEqual(SCRIPT.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")

    def test_fake_replays_success_and_exits_0(self):
        process = spawn({"FAKE_CLAUDE_FIXTURE": "success"}, "-p", "synthetic prompt")
        try:
            output, _ = process.communicate(timeout=WAIT)
            self.assertEqual(process.returncode, 0)
        finally:
            finish(process)
        self.assertEqual(output.splitlines(), read_lines("success"))

    def test_fake_delay_spaces_the_lines(self):
        process = spawn({"FAKE_CLAUDE_FIXTURE": "no_result", "FAKE_CLAUDE_DELAY_MS": "150"})
        try:
            started = time.monotonic()
            output, _ = process.communicate(timeout=WAIT)
            elapsed = time.monotonic() - started
        finally:
            finish(process)
        self.assertEqual(output.splitlines(), read_lines("no_result"))
        self.assertGreaterEqual(elapsed, 0.15 * (len(read_lines("no_result")) - 1) * 0.8)

    def test_fake_sigint_prints_tail_and_exits_0(self):
        process = spawn({"FAKE_CLAUDE_FIXTURE": "success", "FAKE_CLAUDE_DELAY_MS": "2000"})
        try:
            # Always wait for the first output line before signalling: only then is the SIGINT handler installed.
            first = process.stdout.readline()
            self.assertEqual(first.rstrip("\n"), read_lines("success")[0])
            process.send_signal(signal.SIGINT)
            rest, _ = process.communicate(timeout=WAIT)
            self.assertEqual(process.returncode, 0)
        finally:
            finish(process)
        tail = [json.loads(line) for line in rest.splitlines()]
        self.assertEqual(tail[-1]["type"], "result")
        self.assertEqual(tail[-1]["terminal_reason"], "aborted_tools")
        self.assertEqual(tail, [json.loads(line) for line in fake_claude.interrupted_tail()])
        self.assertNotIn("success", {event.get("subtype") for event in tail if event["type"] == "result"})
        self.assertLess(len(tail), len(read_lines("interrupted")))

    def test_fake_ignoring_sigint_keeps_running_until_killed(self):
        process = spawn({"FAKE_CLAUDE_FIXTURE": "success", "FAKE_CLAUDE_IGNORE_SIGINT": "1",
                         "FAKE_CLAUDE_DELAY_MS": "200"})
        try:
            self.assertTrue(process.stdout.readline())  # wait for output first: the handler is installed by then
            process.send_signal(signal.SIGINT)
            time.sleep(1.0)
            self.assertIsNone(process.poll())
            process.send_signal(signal.SIGINT)
            time.sleep(0.5)
            self.assertIsNone(process.poll())
            process.terminate()  # plain SIGTERM still works
            self.assertEqual(process.wait(timeout=WAIT), -signal.SIGTERM)
        finally:
            finish(process)

    def test_fake_records_argv_cwd_and_env_names_only(self):
        record = self.directory / "record.jsonl"
        work = self.directory / "work"
        work.mkdir()
        secret_value = "synthetic-value-not-for-the-record"
        process = spawn({"FAKE_CLAUDE_FIXTURE": "success", "FAKE_CLAUDE_RECORD": str(record),
                         "FAKE_CLAUDE_TEST_ONLY_NAME": secret_value}, "-p", "synthetic prompt", "--model", "haiku",
                        cwd=work)
        try:
            process.communicate(timeout=WAIT)
            self.assertEqual(process.returncode, 0)
        finally:
            finish(process)
        entry = fake_claude.recorded(record)
        self.assertEqual(entry["argv"], ["-p", "synthetic prompt", "--model", "haiku"])
        self.assertEqual(Path(entry["cwd"]).resolve(), work.resolve())
        self.assertEqual(entry["env_names"], sorted(entry["env_names"]))
        self.assertIn("FAKE_CLAUDE_TEST_ONLY_NAME", entry["env_names"])
        self.assertIn("FAKE_CLAUDE_RECORD", entry["env_names"])
        self.assertNotIn(secret_value, record.read_text(encoding="utf-8"))
        self.assertEqual(set(entry), {"argv", "cwd", "env_names"})

    def test_version_flag(self):
        record = self.directory / "record.jsonl"
        process = spawn({"FAKE_CLAUDE_RECORD": str(record)}, "--version")
        try:
            output, _ = process.communicate(timeout=WAIT)
            self.assertEqual(process.returncode, 0)
        finally:
            finish(process)
        self.assertEqual(output, "2.1.312 (Claude Code)\n")
        self.assertEqual(fake_claude.recorded(record)["argv"], ["--version"])

    def test_unknown_or_missing_fixture_fails_with_exit_2(self):
        for environment in ({}, {"FAKE_CLAUDE_FIXTURE": "../success"}, {"FAKE_CLAUDE_FIXTURE": "nope"}):
            process = spawn(environment)
            try:
                output, error = process.communicate(timeout=WAIT)
                self.assertEqual(process.returncode, 2, environment)
            finally:
                finish(process)
            self.assertEqual(output, "")
            self.assertIn("fake_claude", error)

    def test_huge_line_helper_exceeds_the_16_mib_cap_and_is_one_json_line(self):
        line = fake_claude.huge_line()
        self.assertGreater(len(line), 16 * 1024 * 1024)
        self.assertNotIn("\n", line)
        self.assertEqual(json.loads(line)["type"], "system")
        self.assertEqual(len(fake_claude.huge_line(100)), 100)

    def test_fixture_path_rejects_unsafe_names(self):
        for name in ("", "../success", "a/b", "Success", "x.jsonl"):
            with self.assertRaises(ValueError):
                fake_claude.fixture_path(name)

    def test_script_runs_with_the_current_interpreter_too(self):
        completed = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=WAIT,
                                   env={**os.environ, "FAKE_CLAUDE_FIXTURE": "no_result"})
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.splitlines(), read_lines("no_result"))


if __name__ == "__main__":
    unittest.main()

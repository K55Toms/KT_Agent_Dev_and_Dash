#!/usr/bin/env python3
"""A fake ``claude`` for tests: replays a sanitized stream-json fixture instead of calling Claude.

Run as a program it stands in for ``claude``; import it for the helpers ``fixture_path`` and ``recorded``.

Environment (all optional except the fixture):
  FAKE_CLAUDE_FIXTURE       name of a file in tests/fixtures/claude (without ``.jsonl``); required unless --version.
  FAKE_CLAUDE_DELAY_MS      pause between output lines, in milliseconds.
  FAKE_CLAUDE_IGNORE_SIGINT 1: ignore SIGINT and, once the replay is done, keep running until killed. A plain
                            SIGTERM still ends the process. Without it, SIGINT prints the tail of the
                            ``interrupted`` fixture (what the real CLI printed) and exits 0.
  FAKE_CLAUDE_RECORD        path of a file that gets one appended JSON line per invocation:
                            {"argv": [...without argv[0]], "cwd": "...", "env_names": [sorted names, never values]}.
  FAKE_CLAUDE_HOOK          ask_allowed | ask_declined | ask_silent | ask_two: read the ``--settings`` file named in
                            argv, take the one PermissionRequest hook's url and timeout, and POST synthetic
                            payloads (fixtures permission_request_*.json) to it before replaying the fixture. Exactly
                            the allow reply emits a tool-result line and the replay goes on; anything else
                            (error, timeout, non-2xx, malformed, deny, a missing/bad settings file) emits a
                            ``permission_denied`` system line and a final ``result`` and ends. SIGINT while waiting
                            prints the interrupted tail and exits 0. ask_two posts two requests from two threads and
                            needs both allowed. The url and token are never printed or recorded; the record gets a
                            second line {"hook": {"scenario", "calls", "told": ["allow"|"deny", ...]}}.
Tests must read the first output line before sending SIGINT: until then Python may not have installed the
handler yet and the default SIGINT would kill the process. The SIGINT tail is always the aborted_tools one (a
simplification: the real CLI ends differently when interrupted while streaming text, ``aborted_streaming``).
The ignore-SIGINT mode exits by itself after 5 minutes so a forgotten child cannot linger.
``--version`` prints the version line and exits 0 (and is recorded too). No prompt text is ever read or echoed.
"""
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.request

VERSION_LINE = "2.1.312 (Claude Code)"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude"
NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
HANG_LIMIT_SECONDS = 300
HUGE_LINE_SIZE = 16 * 1024 * 1024 + 1024
TAIL_STARTS_AT = '"subtype":"task_notification"'


def fixture_path(name):
    """Path of the named fixture; only plain lower-case names are accepted (no separators, no extension)."""
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError("fixture name must be a plain lower-case name")
    return FIXTURES / (name + ".jsonl")


def huge_line(size=HUGE_LINE_SIZE):
    """A JSON line (no newline) of at least ``size`` characters, built at test time; never stored in the repo."""
    prefix = '{"type":"system","subtype":"synthetic_padding","pad":"'
    suffix = '"}'
    return prefix + "x" * max(0, size - len(prefix) - len(suffix)) + suffix


def recorded(path):
    """The last record written to a FAKE_CLAUDE_RECORD file, as a dict."""
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    entries = [json.loads(line) for line in lines]
    return [entry for entry in entries if "hook" not in entry][-1]


def fixture_lines(name):
    return fixture_path(name).read_text(encoding="utf-8").splitlines()


def interrupted_tail():
    """The lines the CLI printed after an interrupt: from the first task_notification of ``interrupted`` on."""
    lines = fixture_lines("interrupted")
    for index, line in enumerate(lines):
        if TAIL_STARTS_AT in line:
            return lines[index:]
    return lines[-1:]


def record(path):
    entry = {"argv": sys.argv[1:], "cwd": os.getcwd(), "env_names": sorted(os.environ)}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def emit(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def delay_seconds():
    try:
        return max(0, int(os.environ.get("FAKE_CLAUDE_DELAY_MS", "0"))) / 1000
    except ValueError:
        return 0


HOOK_SCENARIOS = {
    "ask_allowed": ["permission_request_bash"],
    "ask_declined": ["permission_request_bash"],
    "ask_silent": ["permission_request_bash"],
    "ask_two": ["permission_request_bash", "permission_request_edit"],
}
ALLOW_BODY = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
DENIED_NAME = "denied"


def hook_target(argv):
    """(url, timeout seconds) from the --settings file in argv, or None when anything is off."""
    try:
        path = argv[argv.index("--settings") + 1]
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entry = data["hooks"]["PermissionRequest"][0]["hooks"][0]
        url, timeout = entry["url"], entry["timeout"]
        if not isinstance(url, str) or type(timeout) is not int or timeout < 1:
            return None
        return url, timeout
    except (ValueError, IndexError, KeyError, TypeError, OSError):
        return None


def post_hook(target, name, result, interrupted):
    """POST one payload; result gets "allow" only for the exact allow reply, else "deny"."""
    verdict = "deny"
    try:
        url, timeout = target
        body = (FIXTURES / (name + ".json")).read_bytes()
        request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            if reply.status == 200 and json.loads(reply.read(65536).decode("utf-8")) == ALLOW_BODY:
                verdict = "allow"
    except Exception:  # every failure, including the timeout, is a denial; nothing is echoed
        pass
    result.append(verdict)


def tool_result_line(number):
    return json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_synth_h%d" % number, "content": "SENTINEL_TOOL_RESULT", "is_error": False}]},
        "session_id": "00000000-0000-4000-8000-000000005e55"}, separators=(",", ":"))


def denied_lines():
    lines = fixture_lines(DENIED_NAME)
    picked = [line for line in lines if '"subtype":"permission_denied"' in line]
    picked += [line for line in lines if line.startswith('{"type":"result"')][-1:]
    return picked


def run_hook(scenario, interrupted):
    """Ask the dashboard for each request. Returns the list of verdicts, or None when interrupted."""
    names = HOOK_SCENARIOS[scenario]
    target = hook_target(sys.argv[1:])
    verdicts = [[] for _ in names]
    if target is None:
        return [["deny"] for _ in names]
    threads = []
    for index, name in enumerate(names):
        thread = threading.Thread(target=post_hook, args=(target, name, verdicts[index], interrupted), daemon=True)
        threads.append(thread)
        thread.start()
    while any(thread.is_alive() for thread in threads):
        if interrupted:
            return None
        time.sleep(0.02)
    return [v or ["deny"] for v in verdicts]


def main():
    target = os.environ.get("FAKE_CLAUDE_RECORD")
    if target:
        record(target)
    if "--version" in sys.argv[1:]:
        emit(VERSION_LINE)
        return 0
    try:
        lines = fixture_lines(os.environ.get("FAKE_CLAUDE_FIXTURE", ""))
    except (ValueError, OSError):
        sys.stderr.write("fake_claude: set FAKE_CLAUDE_FIXTURE to the name of an existing fixture\n")
        return 2
    ignore = os.environ.get("FAKE_CLAUDE_IGNORE_SIGINT") == "1"
    interrupted = []
    # The handler only sets a flag, so a signal never cuts a line in half; the loop below acts on it.
    signal.signal(signal.SIGINT, signal.SIG_IGN if ignore else (lambda *_: interrupted.append(True)))
    scenario = os.environ.get("FAKE_CLAUDE_HOOK")
    if scenario is not None:
        if scenario not in HOOK_SCENARIOS:
            sys.stderr.write("fake_claude: unknown FAKE_CLAUDE_HOOK scenario\n")
            return 2
        verdicts = run_hook(scenario, interrupted)
        if verdicts is None:
            for line in interrupted_tail():
                emit(line)
            return 0
        told = [v[0] for v in verdicts]
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"hook": {"scenario": scenario, "calls": len(told), "told": told}}) + "\n")
        for number, verdict in enumerate(told):
            if verdict == "allow":
                emit(tool_result_line(number + 1))
        if "deny" in told:
            for line in denied_lines():
                emit(line)
            return 0
    pause = delay_seconds()
    for number, line in enumerate(lines):
        if number and pause:
            deadline = time.monotonic() + pause
            while time.monotonic() < deadline and not interrupted:
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        if interrupted:
            break
        emit(line)
    else:
        interrupted.clear()  # the replay finished before the signal was acted on
    if interrupted:
        for line in interrupted_tail():
            emit(line)
        return 0
    limit = time.monotonic() + HANG_LIMIT_SECONDS
    while ignore and time.monotonic() < limit:  # a hung CLI: stays up until the test kills it (or the watchdog)
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())

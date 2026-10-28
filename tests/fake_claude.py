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
``--version`` prints the version line and exits 0 (and is recorded too). No prompt text is ever read or echoed.
"""
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

VERSION_LINE = "2.1.312 (Claude Code)"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude"
NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
TAIL_STARTS_AT = '"subtype":"task_notification"'


def fixture_path(name):
    """Path of the named fixture; only plain lower-case names are accepted (no separators, no extension)."""
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError("fixture name must be a plain lower-case name")
    return FIXTURES / (name + ".jsonl")


def recorded(path):
    """The last record written to a FAKE_CLAUDE_RECORD file, as a dict."""
    lines = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1])


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
    while ignore:  # a hung CLI: stays up until the test kills it
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())

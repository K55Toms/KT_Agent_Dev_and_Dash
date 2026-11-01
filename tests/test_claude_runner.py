"""Tests for the Claude process runner (dashboard/backends/claude_runner.py), driven by tests/fake_claude.py.

Evidence kind: fake binary only; nothing here runs the real ``claude``.
"""
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.backends import claude_runner  # noqa: E402
from dashboard.backends.claude_runner import ClaudeRun, RunExit  # noqa: E402
from dashboard.backends.claude_stream import StreamState  # noqa: E402
from fake_claude import fixture_path, recorded  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_claude.py"
WAIT = 20.0
# macOS CoreFoundation may add this one to every process it starts; it carries no value we passed.
PLATFORM_NAMES = {"__CF_USER_TEXT_ENCODING"}


def sent(killpg):
    """Signals actually sent through a wrapped os.killpg (the group probe, signal 0, is left out)."""
    return [c.args[1] for c in killpg.call_args_list if c.args[1] != 0]


def group_members(pgid):
    """PIDs still in the process group (pgrep -g), empty when the group is gone."""
    out = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True)
    return out.stdout.split()


def wait_for_file(path, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return int(path.read_text())
        time.sleep(0.02)
    raise AssertionError("helper process did not report its pid")


def kill_quietly(pid):
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def gone(pid, timeout=5.0):
    """True when pid no longer exists (reaped, not a zombie)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    return False


class Recorder:
    def __init__(self, fail_on_first=False):
        self.events = []
        self.exits = []
        self.lock = threading.Lock()
        self.first_event = threading.Event()
        self.exited = threading.Event()
        self.fail_on_first = fail_on_first
        self.order = []

    def on_event(self, event):
        with self.lock:
            self.events.append(event)
            self.order.append("event")
        self.first_event.set()
        if self.fail_on_first and len(self.events) == 1:
            raise RuntimeError("callback failure")

    def on_exit(self, run_exit):
        with self.lock:
            self.exits.append(run_exit)
            self.order.append("exit")
        self.exited.set()


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.close()
            if run.pid:
                self.assertTrue(gone(run.pid), "runner child left behind")

    def env(self, **extra):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        env.update(extra)
        return env

    def make(self, argv, env, rec=None, **kw):
        rec = rec or Recorder()
        run = ClaudeRun(argv, cwd=str(self.dir), env=env, state=StreamState(turn_id="turn-1"),
                        on_event=rec.on_event, on_exit=rec.on_exit, **kw)
        self.runs.append(run)
        return run, rec

    def fake(self, *args):
        return [sys.executable, str(FAKE), *args]

    def script(self, name, body):
        path = self.dir / name
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return [sys.executable, str(path)]


class SpawnTests(RunnerCase):
    def test_spawn_uses_devnull_stdin_new_session_and_exact_env(self):
        record = self.dir / "record.jsonl"
        # LANG is set so the child interpreter does not add LC_CTYPE itself (PEP 538 locale coercion).
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_RECORD=str(record),
                       FAKE_CLAUDE_DELAY_MS="200", LANG="en_US.UTF-8")
        seen = {}

        def factory(argv, **kwargs):
            seen.update(kwargs)
            seen["argv"] = list(argv)
            return subprocess.Popen(argv, **kwargs)

        argv = self.fake("-p", "--output-format", "stream-json")
        run, rec = self.make(argv, env, process_factory=factory)
        run.start()
        self.assertTrue(rec.first_event.wait(WAIT))
        self.assertEqual(os.getpgid(run.pid), run.pid)  # leads its own process group
        self.assertEqual(os.getsid(run.pid), run.pid)   # and its own session
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual(seen["argv"], argv)
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        self.assertIs(seen["stdout"], subprocess.PIPE)
        self.assertIs(seen["stderr"], subprocess.PIPE)
        self.assertIs(seen["start_new_session"], True)
        self.assertIs(seen["close_fds"], True)
        self.assertEqual(seen["cwd"], str(self.dir))
        self.assertEqual(seen["env"], env)
        self.assertFalse(seen.get("text") or seen.get("universal_newlines") or seen.get("encoding"))
        entry = recorded(record)
        self.assertEqual(entry["argv"], ["-p", "--output-format", "stream-json"])
        self.assertEqual(os.path.realpath(entry["cwd"]), os.path.realpath(str(self.dir)))
        self.assertEqual(set(entry["env_names"]) - PLATFORM_NAMES, set(env))
        self.assertNotIn("ANTHROPIC_API_KEY", entry["env_names"])

    def test_spawn_failure_reports_exit_without_raising(self):
        run, rec = self.make([str(self.dir / "no-such-claude")], self.env())
        run.start()  # returns normally
        self.assertTrue(rec.exited.is_set())
        self.assertEqual(rec.exits, [RunExit(None, False, None, False, False)])
        self.assertIsNone(run.pid)
        self.assertTrue(run.cleanup_complete.is_set())
        self.assertNotIn("no-such-claude", repr(run))
        run.stop("late")
        run.close()
        self.assertEqual(len(rec.exits), 1)


class StreamTests(RunnerCase):
    def test_events_flow_in_order_and_exit_is_reported_once(self):
        run, rec = self.make(self.fake(), self.env(FAKE_CLAUDE_FIXTURE="success"))
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertTrue(run.cleanup_complete.wait(WAIT))
        self.assertEqual([e.kind for e in rec.events], ["turn_started", "usage_updated", "turn_completed"])
        self.assertEqual(rec.order[-1], "exit")
        self.assertEqual(rec.exits, [RunExit(0, False, None, True, False)])
        self.assertEqual(run.exit_code, 0)
        self.assertIsInstance(run.started_at, float)
        self.assertEqual(run.callback_errors, 0)
        self.assertTrue(gone(run.pid))
        run.close()
        self.assertEqual(len(rec.exits), 1)

    def test_line_over_the_cap_ends_the_run_and_stops_the_child(self):
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_DELAY_MS="300")
        with mock.patch.object(claude_runner.os, "killpg", wraps=os.killpg) as killpg:
            run, rec = self.make(self.fake(), env, max_line_bytes=100, term_wait=2.0)
            run.start()
            self.assertTrue(rec.exited.wait(WAIT))
        self.assertTrue(run.cleanup_complete.wait(WAIT))
        (exit_,) = rec.exits
        self.assertTrue(exit_.overflow)
        self.assertFalse(exit_.saw_result)
        self.assertFalse(exit_.stopped_by_us)
        self.assertEqual(exit_.code, -signal.SIGTERM)
        self.assertEqual(rec.events, [])
        self.assertNotIn(signal.SIGINT, sent(killpg))
        self.assertTrue(gone(run.pid))

    def test_line_exactly_at_the_cap_is_accepted(self):
        lines = fixture_path("success").read_text(encoding="utf-8").splitlines()
        longest = max(len(line.encode("utf-8")) for line in lines)
        run, rec = self.make(self.fake(), self.env(FAKE_CLAUDE_FIXTURE="success"), max_line_bytes=longest)
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual(rec.exits, [RunExit(0, False, None, True, False)])

    def test_malformed_line_is_skipped(self):
        run, rec = self.make(self.fake(), self.env(FAKE_CLAUDE_FIXTURE="malformed"))
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        kinds = [e.kind for e in rec.events]
        self.assertEqual(kinds[0], "turn_started")
        self.assertEqual(kinds[-1], "turn_completed")
        self.assertEqual(rec.exits, [RunExit(0, False, None, True, False)])
        self.assertEqual(run.callback_errors, 0)

    def test_callback_exception_does_not_kill_the_reader(self):
        rec = Recorder(fail_on_first=True)
        run, rec = self.make(self.fake(), self.env(FAKE_CLAUDE_FIXTURE="success"), rec=rec)
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual([e.kind for e in rec.events], ["turn_started", "usage_updated", "turn_completed"])
        self.assertEqual(run.callback_errors, 1)
        self.assertEqual(rec.exits, [RunExit(0, False, None, True, False)])

    def test_stderr_is_bounded_and_not_in_events(self):
        success = fixture_path("success")
        argv = self.script("noisy.py", f"""
            import sys
            sys.stderr.write("STDERR_HEAD_MARKER" + "e" * 100000 + "STDERR_TAIL_MARKER\\n")
            sys.stderr.flush()
            with open({str(success)!r}, encoding="utf-8") as handle:
                sys.stdout.write(handle.read())
            sys.stdout.flush()
        """)
        run, rec = self.make(argv, self.env())
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertTrue(run.cleanup_complete.wait(WAIT))
        self.assertLessEqual(len(run.stderr_tail), 8192)
        self.assertIn(b"STDERR_TAIL_MARKER", run.stderr_tail)
        self.assertNotIn(b"STDERR_HEAD_MARKER", run.stderr_tail)
        self.assertTrue(rec.exits[0].saw_result)
        self.assertNotIn("STDERR", repr(rec.events) + repr(rec.exits) + repr(run))


class StopTests(RunnerCase):
    def test_stop_sends_sigint_and_reports_stopped_by_us(self):
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_DELAY_MS="300")
        flags_at_signal = []
        real_killpg = os.killpg

        def spy(pgid, signum):
            if signum:
                flags_at_signal.append((run.stopped_by_us, run.stop_reason))
            return real_killpg(pgid, signum)

        with mock.patch.object(claude_runner.os, "killpg", side_effect=spy) as killpg:
            run, rec = self.make(self.fake(), env)
            run.start()
            self.assertTrue(rec.first_event.wait(WAIT))
            run.stop("user")
            self.assertTrue(rec.exited.wait(WAIT))
        self.assertTrue(run.cleanup_complete.wait(WAIT))
        self.assertEqual(sent(killpg), [signal.SIGINT])
        self.assertEqual({c.args[0] for c in killpg.call_args_list}, {run.pid})
        self.assertEqual(flags_at_signal[0], (True, "user"))  # recorded before the first signal
        (exit_,) = rec.exits
        self.assertEqual((exit_.code, exit_.stopped_by_us, exit_.reason, exit_.overflow), (0, True, "user", False))
        self.assertTrue(run.stopped_by_us)
        self.assertEqual(run.stop_reason, "user")
        self.assertEqual(rec.order[-1], "exit")
        self.assertTrue(gone(run.pid))

    def test_child_ignoring_sigint_is_terminated_then_killed_and_reaped(self):
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_IGNORE_SIGINT="1")
        with mock.patch.object(claude_runner.os, "killpg", wraps=os.killpg) as killpg:
            run, rec = self.make(self.fake(), env, sigint_wait=0.3, term_wait=0.3)
            run.start()
            self.assertTrue(rec.first_event.wait(WAIT))
            run.stop("user")
            self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual(sent(killpg), [signal.SIGINT, signal.SIGTERM])
        self.assertEqual(rec.exits[0].code, -signal.SIGTERM)
        self.assertTrue(rec.exits[0].stopped_by_us)
        self.assertTrue(gone(run.pid, timeout=0.5))  # reaped: a zombie would still answer kill(pid, 0)

    def test_child_ignoring_sigint_and_sigterm_is_killed_and_reaped(self):
        mark = self.dir / "stubborn.ready"
        argv = self.script("stubborn.py", """
            import signal, sys, time
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            open(sys.argv[1], "w").close()  # handlers are installed: the marker file is the ready signal
            sys.stdout.write("ready\\n"); sys.stdout.flush()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                time.sleep(0.05)
        """)
        started = threading.Event()
        real_factory = subprocess.Popen

        def factory(argv, **kwargs):
            process = real_factory(argv, **kwargs)
            started.set()
            return process

        with mock.patch.object(claude_runner.os, "killpg", wraps=os.killpg) as killpg:
            run, rec = self.make(argv + [str(mark)], self.env(), sigint_wait=0.3, term_wait=0.3,
                                 process_factory=factory)
            run.start()
            self.assertTrue(started.wait(WAIT))
            deadline = time.monotonic() + WAIT  # wait for the marker file, not for a fixed sleep
            while not mark.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(mark.exists())
            run.stop("user")
            self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual(sent(killpg), [signal.SIGINT, signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(rec.exits[0].code, -signal.SIGKILL)
        self.assertTrue(gone(run.pid, timeout=0.5))

    def test_stop_after_exit_is_a_noop(self):
        run, rec = self.make(self.fake(), self.env(FAKE_CLAUDE_FIXTURE="success"))
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertTrue(run.cleanup_complete.wait(WAIT))
        with mock.patch.object(claude_runner.os, "killpg") as killpg:
            run.stop("late")
            run.stop("again")
        killpg.assert_not_called()
        self.assertFalse(run.stopped_by_us)
        self.assertEqual(rec.exits, [RunExit(0, False, None, True, False)])

    def test_close_reaps_and_is_idempotent(self):
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_DELAY_MS="300")
        run, rec = self.make(self.fake(), env)
        run.start()
        self.assertTrue(rec.first_event.wait(WAIT))
        run.close()
        self.assertTrue(run.cleanup_complete.is_set())
        run.close()
        run.stop("again")
        self.assertEqual(len(rec.exits), 1)
        self.assertEqual(rec.exits[0].reason, "close")
        self.assertTrue(rec.exits[0].stopped_by_us)
        self.assertTrue(gone(run.pid, timeout=0.5))
        self.assertNotIn(str(FAKE), repr(run))

    def test_stop_from_inside_on_event_does_not_deadlock(self):
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_DELAY_MS="300")
        holder = {}
        rec = Recorder()
        original = rec.on_event

        def on_event(event):
            original(event)
            if event.kind == "turn_started":
                holder["run"].stop("policy")

        rec.on_event = on_event
        run, rec = self.make(self.fake(), env, rec=rec)
        holder["run"] = run
        run.start()
        self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual((rec.exits[0].stopped_by_us, rec.exits[0].reason), (True, "policy"))

    def test_stop_during_spawn_is_not_lost(self):
        env = self.env(FAKE_CLAUDE_FIXTURE="success", FAKE_CLAUDE_DELAY_MS="300")
        entered, release = threading.Event(), threading.Event()

        def slow_factory(argv, **kwargs):
            entered.set()
            self.assertTrue(release.wait(WAIT))
            return subprocess.Popen(argv, **kwargs)

        with mock.patch.object(claude_runner.os, "killpg", wraps=os.killpg) as killpg:
            run, rec = self.make(self.fake(), env, process_factory=slow_factory)
            starter = threading.Thread(target=run.start)
            starter.start()
            try:
                self.assertTrue(entered.wait(WAIT))
                run.stop("user")  # lands while the factory is spawning
                self.assertTrue(run.stopped_by_us)
            finally:
                release.set()
                starter.join(WAIT)
            self.assertTrue(rec.exited.wait(WAIT))
        self.assertEqual(sent(killpg)[0], signal.SIGINT)
        self.assertEqual((rec.exits[0].stopped_by_us, rec.exits[0].reason), (True, "user"))
        self.assertIn(rec.exits[0].code, (0, -signal.SIGINT))  # SIGINT may land before the fake's handler
        self.assertTrue(gone(run.pid, timeout=0.5))

    def test_group_member_ignoring_sigint_is_gone_after_stop(self):
        pid_file = self.dir / "member.pid"
        argv = self.script("leader.py", f"""
            import subprocess, sys, time
            member = subprocess.Popen([sys.executable, "-c", (
                "import os, signal, time\\n"
                "signal.signal(signal.SIGINT, signal.SIG_IGN)\\n"
                "open({str(pid_file)!r}, 'w').write(str(os.getpid()))\\n"
                "time.sleep(60)\\n")])
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                time.sleep(0.05)
        """)
        member = None
        try:
            run, rec = self.make(argv, self.env(), sigint_wait=2.0, term_wait=1.0, group_wait=1.0)
            run.start()
            member = wait_for_file(pid_file)
            self.assertEqual(os.getpgid(member), run.pid)  # same process group as the leader
            run.stop("user")
            self.assertTrue(rec.exited.wait(WAIT))
            self.assertTrue(rec.exits[0].stopped_by_us)
            self.assertTrue(gone(member))  # killed and reaped (no zombie answers kill(pid, 0))
            self.assertEqual(group_members(run.pid), [])
            self.assertTrue(gone(run.pid, timeout=0.5))
        finally:
            kill_quietly(member)

    def test_group_member_left_after_natural_exit_is_cleaned_up(self):
        pid_file = self.dir / "member.pid"
        success = fixture_path("success")
        argv = self.script("leader.py", f"""
            import subprocess, sys, time
            member = subprocess.Popen([sys.executable, "-c", (
                "import os, signal, time\\n"
                "signal.signal(signal.SIGINT, signal.SIG_IGN)\\n"
                "open({str(pid_file)!r}, 'w').write(str(os.getpid()))\\n"
                "time.sleep(60)\\n")], stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if open({str(pid_file)!r}).read().strip():
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            with open({str(success)!r}, encoding="utf-8") as handle:
                sys.stdout.write(handle.read())
            sys.stdout.flush()
        """)
        member = None
        try:
            run, rec = self.make(argv, self.env(), group_wait=1.0)
            run.start()
            self.assertTrue(rec.exited.wait(WAIT))
            member = wait_for_file(pid_file)
            self.assertEqual(rec.exits[0], RunExit(0, False, None, True, False))
            self.assertTrue(gone(member))
            self.assertEqual(group_members(run.pid), [])
        finally:
            kill_quietly(member)

    def test_descendant_that_keeps_writing_does_not_delay_exit(self):
        pid_file = self.dir / "writer.pid"
        success = fixture_path("success")
        writer_argv = self.script("writer.py", f"""
            import os, sys, time
            open({str(pid_file)!r}, "w").write(str(os.getpid()))
            end = time.monotonic() + 60
            while time.monotonic() < end:
                sys.stdout.write('{{"type":"noise"}}\\n')
                sys.stdout.flush()
                time.sleep(0.02)
        """)
        argv = self.script("parent.py", f"""
            import subprocess, sys, time
            subprocess.Popen({writer_argv!r}, start_new_session=True)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if open({str(pid_file)!r}).read().strip():
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            with open({str(success)!r}, encoding="utf-8") as handle:
                sys.stdout.write(handle.read())
            sys.stdout.flush()
        """)
        writer = None
        try:
            run, rec = self.make(argv, self.env(), reader_grace=0.5)
            began = time.monotonic()
            run.start()
            self.assertTrue(rec.exited.wait(WAIT))
            elapsed = time.monotonic() - began
            writer = wait_for_file(pid_file)
            self.assertLess(elapsed, 0.5 + 4.0)
            self.assertTrue(rec.exits[0].saw_result)
            self.assertTrue(run.cleanup_complete.is_set())
            count = len(rec.events)
            time.sleep(0.2)
            self.assertEqual(len(rec.events), count)  # nothing is emitted after on_exit
            self.assertEqual(rec.order[-1], "exit")
        finally:
            kill_quietly(writer)
            if writer:
                self.assertTrue(gone(writer))

    def test_descendant_holding_stdout_does_not_hang_exit(self):
        pid_file = self.dir / "grandchild.pid"
        success = fixture_path("success")
        argv = self.script("parent.py", f"""
            import subprocess, sys
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     start_new_session=True)
            with open({str(pid_file)!r}, "w") as handle:
                handle.write(str(child.pid))
            with open({str(success)!r}, encoding="utf-8") as handle:
                sys.stdout.write(handle.read())
            sys.stdout.flush()
        """)
        grandchild = None
        try:
            run, rec = self.make(argv, self.env())
            began = time.monotonic()
            run.start()
            self.assertTrue(rec.exited.wait(WAIT))
            self.assertLess(time.monotonic() - began, 10)
            grandchild = int(pid_file.read_text())
            self.assertEqual(rec.exits[0].code, 0)
            self.assertTrue(rec.exits[0].saw_result)
            self.assertFalse(rec.exits[0].overflow)
            self.assertTrue(run.cleanup_complete.wait(WAIT))
            self.assertTrue(gone(run.pid, timeout=0.5))
        finally:
            if grandchild is None and pid_file.exists():
                grandchild = int(pid_file.read_text())
            if grandchild:
                try:
                    os.kill(grandchild, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.assertTrue(gone(grandchild))


class ReprTests(unittest.TestCase):
    def test_repr_has_pid_and_state_only(self):
        run = ClaudeRun(["/x/claude", "-p", "SECRET_PROMPT"], cwd="/", env={"FAKE_SETTING": "SECRET_MARKER_VALUE"},
                        state=StreamState(), on_event=lambda e: None, on_exit=lambda x: None)
        text = repr(run)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("claude\"", text)
        self.assertIn("pid=None", text)


if __name__ == "__main__":
    unittest.main()

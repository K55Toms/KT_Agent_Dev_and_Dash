"""Claude process runner: spawns one ``claude -p`` invocation, streams its events and stops it safely.

The runner reports what it observed; it never decides a task status (the dashboard does).

Threads (all daemons):
- reader: reads stdout lines (bytes, hard cap ``max_line_bytes``), translates them with
  ``translate_stream_line`` and calls ``on_event`` for each NeutralEvent, in order.
- stderr drain: keeps only the last 8 KiB of stderr in ``stderr_tail``; it is never logged and never
  put in an event.
- waiter: reaps the child, cleans up the rest of its process group (SIGTERM, ``group_wait``, SIGKILL),
  waits for the reader at most ``reader_grace`` seconds in total (a descendant outside the group can hold
  stdout open, or keep writing to it, forever), then calls ``on_exit`` exactly once, after the last
  ``on_event``, and sets ``cleanup_complete``. Lines read after that are dropped, never turned into events.
  The reader thread and the stdout descriptor can outlive ``cleanup_complete`` only in that case (a
  descendant still holding stdout after ``reader_grace``); the reader closes the pipe at its EOF.
- stopper: runs the stop ladder (decision 7: SIGINT, wait, SIGTERM, wait, SIGKILL, each to the child's
  process group). ``stop()`` waits for it when called from another thread and returns at once when
  called from one of the runner's own threads (for example from inside ``on_event``), so a callback can
  stop its own run without deadlocking. A second or concurrent ``stop()`` returns at once (the first one
  owns the ladder); ``close()`` waits on ``cleanup_complete`` instead. A ``stop()`` that lands while the
  process factory is still spawning is recorded and the ladder starts as soon as the process exists.

``on_event`` and ``on_exit`` are called from the reader and waiter threads respectively (``on_exit``
from the caller's thread when the spawn fails inside ``start()``). Exceptions they raise are counted
in ``callback_errors`` and never stop the stream from being drained.

No argv text, no environment value and no stream content appears in any exception message, repr or
log line; this module logs nothing.
"""
from dataclasses import dataclass
import os
import signal
import subprocess
import threading
import time
from typing import Optional

from .claude_stream import translate_stream_line

STDERR_TAIL_BYTES = 8 * 1024
REAP_SECONDS = 5.0


@dataclass(frozen=True)
class RunExit:
    """How a run ended, as observed: the exit code (None if it never started or could not be reaped),
    whether the dashboard stopped it and why, whether a ``turn_completed`` was emitted, and whether
    a line over the cap ended it."""
    code: Optional[int]
    stopped_by_us: bool
    reason: Optional[str]
    saw_result: bool
    overflow: bool


class ClaudeRun:
    """One child process per instance; single use."""

    def __init__(self, argv, *, cwd, env, state, on_event, on_exit, process_factory=subprocess.Popen,
                 clock=time.monotonic, sigint_wait=10.0, term_wait=5.0, max_line_bytes=16 * 1024 * 1024,
                 reader_grace=3.0, group_wait=1.0):
        self._argv = list(argv)
        self._cwd = cwd
        self._env = env
        self._state = state
        self.state = state  # public, read-only use: the controller reads denied_count/denied_tools
        self._on_event = on_event
        self._on_exit = on_exit
        self._factory = process_factory
        self._clock = clock  # used only for started_at; internal waits use Popen.wait timeouts
        self._sigint_wait = sigint_wait
        self._term_wait = term_wait
        self._max = max_line_bytes
        self._reader_grace = reader_grace
        self._group_wait = group_wait
        self._pending_stop = False  # stop() arrived while the factory was spawning
        self._lock = threading.Lock()       # start/stop bookkeeping
        self._emit_lock = threading.Lock()  # orders on_event before on_exit
        self._process = None
        self._started = False
        self._finished = False  # set once on_exit is about to run; the reader emits nothing after it
        self._exit_reported = False
        self._ladder_thread = None
        self._reader = None
        self._stderr_thread = None
        self._waiter = None
        self._own_threads = set()
        self.pid = None
        self.started_at = None
        self.exit_code = None
        self.cleanup_complete = threading.Event()
        self.stopped_by_us = False
        self.stop_reason = None
        self.saw_result = False
        self.overflow = False
        self.callback_errors = 0
        self.signal_errors = 0
        self.stderr_tail = b""

    def __repr__(self):
        return f"<ClaudeRun pid={self.pid} state={self._phase()}>"

    def _phase(self):
        if self.cleanup_complete.is_set():
            return "exited"
        if self._ladder_thread is not None:
            return "stopping"
        if self._process is not None:
            return "running"
        return "new"

    # ---- start -------------------------------------------------------------------------------------
    def start(self) -> None:
        """Spawn the child. Returns normally even when the spawn fails: the caller then sees ``on_exit``
        with code None (called synchronously from this thread). A second call does nothing."""
        with self._lock:
            if self._started:
                return
            self._started = True
            cancelled = self.stopped_by_us
        if cancelled:  # stop() before start(): never spawn
            self._finish(None)
            return
        try:
            process = self._factory(self._argv, cwd=self._cwd, env=self._env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                                    close_fds=True)
        except Exception:  # its message can name argv[0]: discarded, never surfaced
            self._finish(None)
            return
        try:
            with self._lock:
                self._process = process
                self.pid = process.pid
                self.started_at = self._clock()
                self._reader = self._thread(self._read, "claude-run-reader")
                self._stderr_thread = self._thread(self._drain_stderr, "claude-run-stderr")
                self._waiter = self._thread(self._wait_for_exit, "claude-run-waiter")
                if self._pending_stop:
                    self._start_ladder_locked(skip_sigint=False)
            self._reader.start()
            self._stderr_thread.start()
            self._waiter.start()
        except Exception:
            self._abort_after_spawn(process)

    def _abort_after_spawn(self, process):
        """The child exists but the threads could not be started: kill and reap it, then report."""
        code = None
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            self.signal_errors += 1
        try:
            code = process.wait(timeout=REAP_SECONDS)
        except Exception:
            pass
        self._finish(code)

    def _thread(self, target, name):
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._own_threads.add(thread)
        return thread

    # ---- stdout / stderr ---------------------------------------------------------------------------
    def _read(self):
        stream = self._process.stdout
        try:
            while True:
                line = stream.readline(self._max + 1)
                if not line:
                    break
                if line.endswith(b"\n"):
                    line = line[:-1]
                elif len(line) > self._max:
                    self.overflow = True
                    self._begin_ladder(skip_sigint=True)
                    break
                text = line.decode("utf-8", errors="replace")
                with self._emit_lock:
                    if self._finished:
                        break
                    self._translate_and_emit(text)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _translate_and_emit(self, text):
        try:
            events = translate_stream_line(text, self._state)
        except Exception:
            self.callback_errors += 1
            return
        for event in events:
            if getattr(event, "kind", None) == "turn_completed":
                self.saw_result = True
            try:
                self._on_event(event)
            except Exception:
                self.callback_errors += 1

    def _drain_stderr(self):
        stream = self._process.stderr
        tail = bytearray()
        try:
            while True:
                chunk = stream.read1(4096)
                if not chunk:
                    break
                tail += chunk
                if len(tail) > STDERR_TAIL_BYTES:
                    del tail[:-STDERR_TAIL_BYTES]
                self.stderr_tail = bytes(tail)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    # ---- exit --------------------------------------------------------------------------------------
    def _wait_for_exit(self):
        code = None
        try:
            code = self._process.wait()
        except Exception:
            code = self._process.returncode
        if self._process.returncode is not None:
            self._clean_up_group()
        # Drain what the child left in the pipe, for at most reader_grace in total; a descendant holding
        # stdout open (or still writing to it) must not delay on_exit. Later lines are dropped (_finished).
        self._reader.join(self._reader_grace)
        self._stderr_thread.join(0.5)
        ladder = self._ladder_thread
        if ladder is not None and ladder is not threading.current_thread():
            ladder.join(self._sigint_wait + self._term_wait + REAP_SECONDS + 1)
        self._finish(code)

    def _clean_up_group(self):
        """Stop whatever is left in the child's process group after the leader was reaped by this Popen.

        Why the pgid cannot name an unrelated group: a process group ID stays allocated while any member
        is alive, and the kernel never hands out a PID that is still in use as a process group ID. So
        while the probe below finds members, they are the leader's own descendants. The only window is
        between the reap and the first probe (microseconds, this same thread): an unrelated process would
        need to receive this exact PID and make itself a group leader in it. Once the probe reports the
        group empty (ESRCH) nothing is ever sent to this pgid again. EPERM is treated the same way.
        """
        deadline_wait = self._group_wait
        for signum in (signal.SIGTERM, signal.SIGKILL):
            if not self._group_alive():
                return
            try:
                os.killpg(self.pid, signum)
            except (ProcessLookupError, PermissionError):
                self.signal_errors += 1
                return
            except OSError:
                self.signal_errors += 1
                return
            deadline = time.monotonic() + deadline_wait
            while time.monotonic() < deadline and self._group_alive():
                time.sleep(0.02)

    def _group_alive(self):
        try:
            os.killpg(self.pid, 0)
            return True
        except OSError:  # ESRCH: the group is empty; EPERM: not ours to signal
            return False

    def _finish(self, code):
        with self._emit_lock:
            if self._exit_reported:
                return
            self._finished = True
            self._exit_reported = True
        self.exit_code = code
        run_exit = RunExit(code, self.stopped_by_us, self.stop_reason, self.saw_result, self.overflow)
        try:
            self._on_exit(run_exit)
        except Exception:
            self.callback_errors += 1
        finally:
            self.cleanup_complete.set()

    # ---- stop --------------------------------------------------------------------------------------
    def stop(self, reason: str) -> None:
        """Stop the run (decision 7). Idempotent; a no-op once the child has exited; never raises.
        Sets ``stopped_by_us`` and ``stop_reason`` before the first signal."""
        try:
            with self._lock:
                if self._exit_reported or self._ladder_thread is not None:
                    return
                if not self._started:  # start() will not spawn
                    self.stopped_by_us, self.stop_reason = True, reason
                    return
                process = self._process
                if process is None:  # the factory is still spawning: start() runs the ladder
                    if not self._pending_stop:
                        self._pending_stop = True
                        self.stopped_by_us, self.stop_reason = True, reason
                    return
                # A child that exits between this check and the first signal is harmless: the ladder skips
                # signals once returncode is set, and before the reap the pgid is still the child's own.
                if process.returncode is not None or process.poll() is not None:
                    return
                self.stopped_by_us, self.stop_reason = True, reason
                ladder = self._start_ladder_locked(skip_sigint=False)
            if threading.current_thread() not in self._own_threads:
                ladder.join(self._sigint_wait + self._term_wait + REAP_SECONDS + 1)
        except Exception:
            pass

    def close(self) -> None:
        """stop('close'), then wait for cleanup up to the ladder bound plus 2 * group_wait + reader_grace. Idempotent."""
        self.stop("close")
        if self._started and threading.current_thread() not in self._own_threads:
            self.cleanup_complete.wait(
                self._sigint_wait + self._term_wait + 5 + 2 * self._group_wait + self._reader_grace)

    def _begin_ladder(self, skip_sigint):
        with self._lock:
            if self._ladder_thread is None:
                self._start_ladder_locked(skip_sigint)

    def _start_ladder_locked(self, skip_sigint):
        thread = self._thread(lambda: self._ladder(skip_sigint), "claude-run-stopper")
        self._ladder_thread = thread
        thread.start()
        return thread

    def _ladder(self, skip_sigint):
        if not skip_sigint:
            self._signal(signal.SIGINT)
            if self._reaped_within(self._sigint_wait):
                return
        self._signal(signal.SIGTERM)
        if self._reaped_within(self._term_wait):
            return
        self._signal(signal.SIGKILL)
        self._reaped_within(REAP_SECONDS)

    def _reaped_within(self, seconds):
        try:
            self._process.wait(timeout=seconds)
            return True
        except subprocess.TimeoutExpired:  # its message names argv: never surfaced
            return False
        except Exception:
            return False

    def _signal(self, signum):
        if self._process.returncode is not None:
            return
        try:
            os.killpg(self.pid, signum)  # start_new_session=True: the child leads its own group
        except (ProcessLookupError, PermissionError, OSError):
            self.signal_errors += 1

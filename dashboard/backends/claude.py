"""Claude backend: readiness through `claude --version`; runs are started by the Dashboard through ClaudeRun.

The Codex-shaped protocol methods do not apply to Claude Code and raise ProviderUnavailable with a
fixed text. Nothing from the probe output is kept except a validated version string.
"""
import os
import re
import shutil
import subprocess
from typing import Callable, Optional

from dashboard.backends.base import ProviderUnavailable
from dashboard.backends.claude_launch import child_environment
from dashboard.backends.claude_stream import ClaudeCapabilities

PROBE_TIMEOUT = 5
VERSION_RE = re.compile(r"[0-9][0-9A-Za-z.\- ]{0,40}( \(Claude Code\))?")
NOT_FOUND = "Claude Code was not found on PATH."
NO_VERSION = "Claude Code did not report a version."
PROTOCOL_UNAVAILABLE = "This operation is not available for the Claude backend."
REQUEST_GONE = "The tool call is no longer waiting for an answer."


class RequestGone(ValueError):
    """The held hook request ended before the answer arrived; nothing was allowed."""


def run_version(argv: list, timeout: float) -> tuple:
    """Run argv with no input and the allow-listed environment; (returncode, stdout) or (1, '') on any error."""
    try:
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, timeout=timeout,
                                   env=child_environment(os.environ), check=False)
        return completed.returncode, completed.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - fail closed: any failure reads as "no version".
        return 1, ""


class ClaudeBackend:
    capabilities = ClaudeCapabilities

    def __init__(self, claude_path: Optional[str] = None,
                 runner: Optional[Callable[[list, float], tuple]] = None):
        self.claude_path = claude_path
        self.runner = runner if runner is not None else run_version

    def probe(self) -> dict:
        """Readiness only: the binary exists and reports a version. Login is not checked."""
        if self.claude_path is None:
            self.claude_path = shutil.which("claude")
            if self.claude_path is None:
                return {"ok": False, "version": None, "detail": NOT_FOUND}
        try:
            code, output = self.runner([self.claude_path, "--version"], PROBE_TIMEOUT)
        except Exception:  # noqa: BLE001 - an injected runner that fails is a failed probe.
            code, output = 1, ""
        if code != 0 or not isinstance(output, str):
            return {"ok": False, "version": None, "detail": NO_VERSION}
        line = output.split("\n", 1)[0]
        match = VERSION_RE.fullmatch(line)
        if not match:
            return {"ok": False, "version": None, "detail": NO_VERSION}
        version = line[:match.start(1)] if match.group(1) else line
        return {"ok": True, "version": version, "detail": "Claude Code " + version}

    def _unavailable(self, *args, **kwargs):
        raise ProviderUnavailable(PROTOCOL_UNAVAILABLE)

    translate = list_models = start_thread = start_turn = steer = interrupt = _unavailable

    def answer_approval(self, request, decision) -> None:
        """Answer one held PermissionRequest: "accept" resolves it allow, "decline" deny; nothing else.

        The responder is the receiver's HeldRequest. Raises RequestGone when the hold had already ended (expired,
        connection closed, run ended): then nothing was allowed. Any other request shape is refused.
        """
        held = getattr(request, "responder", None)
        if (getattr(request, "kind", None) != "tool_call" or decision not in ("accept", "decline")
                or not callable(getattr(held, "resolve", None))):
            raise ProviderUnavailable(PROTOCOL_UNAVAILABLE)
        if held.resolve("allow" if decision == "accept" else "deny") is not True:
            raise RequestGone(REQUEST_GONE)


# Kept for existing tests that use it as a non-Codex backend fixture.
ClaudeBackendStub = ClaudeBackend

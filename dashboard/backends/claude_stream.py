"""Claude stream-json parser: pure mapping from one output line to NeutralEvents.

Allow-list reading only. The one text exception is the visible reply of the main agent: each ``text`` block of
a top-level ``assistant`` line becomes a ``message`` event with bounded plain text (control characters removed,
over MAX_MESSAGE_TEXT truncated with a marker). The caller must scan that text (``safe_text``) before it is stored
or shown. Nothing else is copied into an event or kept in the state: not thinking blocks, tool_use input,
tool results, user lines, hook output, ``result.result``, sub-agent lines (only their agent id, type and
start/stop become a ``subagent`` event), paths, or the plugin and MCP
inventories. Only short validated identifiers, bounded numbers and tool names survive.

Delivery checks runs only (``StreamState.check_commands`` set, None for every other run): a main-session ``Bash``
tool_use becomes a ``check_command`` event carrying its tool_use id and the id of the approved command it equals
exactly (None for any other command; the command text itself never leaves the parser), and the tool_result of such a
call becomes a ``check_result`` event with ``ok`` True only for ``is_error`` exactly False, no non-execution marker
and no "Exit code" content prefix. Nothing of the result content is copied.

Contracts for callers:
- Lines over 1 MiB (counted in UTF-8 bytes) yield []; the runner enforces its own larger line cap.
- If the init event has no valid session_id it is ignored, and a later result still emits events with
  thread_id None. The caller must treat thread_id None as "no session: ignore, the run is unknown".
- Only the first result counts. Later results are dropped entirely, so their usage and denials are lost.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, Mapping, Optional

from .base import Capabilities, NeutralEvent, NO, UNCONFIRMED
from .codex import USAGE_KEYS

MAX_LINE = 1024 * 1024
MAX_DENIED_NAMES = 20
MAX_DENIED_IDS = 200
MAX_DENIALS_PER_RESULT = 1000
MAX_MODELS = 64
MAX_AGENTS = 64
MAX_OMITTED_IDS = 1024
MAX_MESSAGE_TEXT = 32000
MAX_MESSAGE_BLOCKS = 50
MAX_LINE_MESSAGE_TEXT = 64 * 1024  # all reply text of one stream line together
TRUNCATION_MARKER = "\n[Reply truncated]"
MAX_TOKENS = 10 ** 15
MAX_COST = 1e6
UNKNOWN_TOOL = "unknown_tool"

_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_MODEL = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_MODE = re.compile(r"[A-Za-z_-]{1,40}\Z")
_VERSION = re.compile(r"[0-9][0-9A-Za-z.\- ]{0,40}( \(Claude Code\))?\Z")
_TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_LINE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\Z")
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f]")
_TOOL_USE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")

NEUTRAL_KEYS = tuple(USAGE_KEYS.values())

ClaudeCapabilities = Capabilities(provider="claude", guidance_while_running=NO, subagent_questions=NO,
                                  plan=UNCONFIRMED, recovery=NO, assessment=NO, approval_alternative=NO)


def _zero_baseline() -> dict:
    return dict(dict.fromkeys(NEUTRAL_KEYS, 0), cost_usd=0.0)


@dataclass
class StreamState:
    """What the parser remembers between lines; the only thing translate_stream_line mutates."""
    turn_id: str = "turn-1"
    session_id: Optional[str] = None
    baseline: Mapping = field(default_factory=_zero_baseline)
    seen_result: bool = False
    denied_tools: list = field(default_factory=list)
    denied_count: int = 0
    permission_mode: Optional[str] = None
    model_id: Optional[str] = None
    version: Optional[str] = None
    last_totals: Optional[dict] = None
    denied_ids: list = field(default_factory=list)
    init_seen: bool = False
    omitted: set = field(default_factory=set)  # ids refused past MAX_AGENTS (bounded; each is signalled once)
    agents: dict = field(default_factory=dict)  # agent_id -> "started" | "stopped" (lineage only, bounded)
    check_commands: Optional[Mapping] = None  # delivery checks run: exact approved command text -> check id
    check_tools: set = field(default_factory=set)  # Bash tool_use ids already reported (bounded)
    # Reply text not shown in full: main-session text blocks truncated or past a cap, and every line over MAX_LINE
    # (its type is unknown, so it is counted as a possible reply). Read by the dashboard for review runs.
    dropped_replies: int = 0

    @staticmethod
    def baseline_zero() -> dict:
        return _zero_baseline()


def _token(value: Any) -> Optional[int]:
    if type(value) is int and 0 <= value < MAX_TOKENS:
        return value
    return None


def usage_from_model_usage(model_usage: Any) -> dict:
    """Sum modelUsage over models into the five neutral keys; a model with a bad value is skipped."""
    out = dict.fromkeys(NEUTRAL_KEYS, 0)
    if not isinstance(model_usage, Mapping):
        return out
    inp = cached = outp = reasoning = 0
    for index, entry in enumerate(model_usage.values()):
        if index >= MAX_MODELS:
            break
        if not isinstance(entry, Mapping):
            continue
        # An absent key counts as 0 (other CLI versions omit some); a present but invalid one skips the model.
        vals = [0 if k not in entry else _token(entry[k])
                for k in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
                          "outputTokens", "thinkingTokens")]
        if any(v is None for v in vals):
            continue
        i, cr, cc, o, th = vals
        inp += i + cr + cc
        cached += cr
        outp += o
        reasoning += th
    inp, cached, outp, reasoning = (min(v, MAX_TOKENS) for v in (inp, cached, outp, reasoning))
    out.update(input_tokens=inp, cached_input_tokens=cached, output_tokens=outp,
               reasoning_output_tokens=reasoning, total_tokens=inp + outp)
    return out


def _cost(value: Any) -> float:
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= MAX_COST:
        return float(value)
    return 0.0


def cost_usd(result: Any) -> float:
    """total_cost_usd of a result, bounded to 0..1e6, else 0."""
    return _cost(result.get("total_cost_usd")) if isinstance(result, Mapping) else 0.0


def _baseline(state: StreamState) -> dict:
    base = state.baseline if isinstance(state.baseline, Mapping) else {}
    out = {k: (_token(base.get(k)) or 0) for k in NEUTRAL_KEYS}
    out["cost_usd"] = _cost(base.get("cost_usd"))
    return out


def _text(value: Any, pattern) -> Optional[str]:
    return value if isinstance(value, str) and pattern.match(value) else None


def _model_id(value: Any) -> Optional[str]:
    """A short model identifier; paths and cloud ARNs (which can hold account ids) are refused."""
    text = _text(value, _MODEL)
    return None if text is None or text.lower().startswith("arn:") else text


def _tool_name(value: Any) -> str:
    return _text(value, _TOOL) or UNKNOWN_TOOL


def _record_denial(state: StreamState, entry: Any) -> None:
    if not isinstance(entry, Mapping):
        return
    tool_use_id = _text(entry.get("tool_use_id"), _TOOL_USE_ID)
    if tool_use_id is not None:
        if tool_use_id in state.denied_ids:
            return
        if len(state.denied_ids) < MAX_DENIED_IDS:
            state.denied_ids.append(tool_use_id)
    state.denied_count = min(state.denied_count + 1, MAX_TOKENS)
    name = _tool_name(entry.get("tool_name"))
    if name not in state.denied_tools and len(state.denied_tools) < MAX_DENIED_NAMES:
        state.denied_tools.append(name)


def _init(obj: Mapping, state: StreamState) -> list:
    session_id = _text(obj.get("session_id"), _SESSION)
    if session_id is None or state.init_seen:
        return []
    state.init_seen = True
    state.session_id = session_id
    state.model_id = _model_id(obj.get("model"))
    state.permission_mode = _text(obj.get("permissionMode"), _MODE)
    state.version = _text(obj.get("claude_code_version"), _VERSION)
    data = {"permission_mode": state.permission_mode, "model_id": state.model_id, "version": state.version}
    return [NeutralEvent("turn_started", session_id, state.turn_id, data)]


def _status(obj: Mapping) -> str:
    is_error = obj.get("is_error")
    reason = obj.get("terminal_reason")
    if (isinstance(reason, str) and reason.startswith("aborted")) \
            or obj.get("subtype") == "error_during_execution":
        return "unknown"  # checked first: an abort never reads as completed, whatever is_error says
    if is_error is False:
        return "completed"
    if is_error is True:
        return "failed"
    return "unknown"


def _result(obj: Mapping, state: StreamState) -> list:
    if state.seen_result:
        return []
    state.seen_result = True
    denials = obj.get("permission_denials")
    if isinstance(denials, list):
        for entry in denials[:MAX_DENIALS_PER_RESULT]:
            _record_denial(state, entry)
        extra = len(denials) - MAX_DENIALS_PER_RESULT
        if extra > 0:
            state.denied_count = min(state.denied_count + extra, MAX_TOKENS)
    base = _baseline(state)
    previous = state.last_totals or base
    model_usage = obj.get("modelUsage")
    if isinstance(model_usage, Mapping) and model_usage:
        usage = usage_from_model_usage(model_usage)
        totals = {k: max(base[k] + usage[k], previous[k]) for k in NEUTRAL_KEYS}
        totals["cost_usd"] = max(base["cost_usd"] + cost_usd(obj), previous["cost_usd"])
    else:
        totals = dict(previous)
    state.last_totals = totals
    events = [NeutralEvent("usage_updated", state.session_id, state.turn_id,
                           {"usage": {k: totals[k] for k in NEUTRAL_KEYS}, "cost_usd": totals["cost_usd"]})]
    status = _status(obj)
    error = None
    if status != "completed":
        api = obj.get("api_error_status")
        error = {"terminal_reason": _text(obj.get("terminal_reason"), _IDENT),
                 "api_error_status": api if type(api) is int and 100 <= api <= 599 else None,
                 "subtype": _text(obj.get("subtype"), _IDENT)}
    events.append(NeutralEvent("turn_completed", state.session_id, state.turn_id,
                               {"status": status, "error": error}))
    return events


def _message_text(value: Any, limit: int = MAX_MESSAGE_TEXT) -> Optional[str]:
    """Bounded plain text of one reply block, or None when it is empty. Control characters other than newline
    and tab are dropped; over-long text is truncated with a visible marker, never dropped silently."""
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.strip():
        return None
    if len(text) > limit:
        text = text[:max(0, limit - len(TRUNCATION_MARKER))] + TRUNCATION_MARKER
    return text


MAX_CHECK_TOOLS = 128
BACKGROUND_PREFIX = "Command running in background"


CHECK_INPUT_KEYS = frozenset({"command", "description", "timeout", "run_in_background"})


def _check_input_command(value: Any) -> Optional[str]:
    """The command of a Bash input that can count as checks evidence, or None. Only a foreground call of the plain
    shape counts: keys within command/description/timeout/run_in_background, run_in_background absent or False (a
    background call returns at once without the command's outcome), a string description and a positive integer
    timeout. Any other shape, an extra key or a non-string command is never evidence."""
    if not isinstance(value, Mapping) or not set(value) <= CHECK_INPUT_KEYS:
        return None
    if "run_in_background" in value and value["run_in_background"] is not False:
        return None
    if "description" in value and not isinstance(value["description"], str):
        return None
    if "timeout" in value and not (type(value["timeout"]) is int and value["timeout"] > 0):
        return None
    command = value.get("command")
    return command if isinstance(command, str) else None


def _check_calls(content: list, state: StreamState) -> list:
    """Delivery checks run only: one ``check_command`` event per main-session Bash tool_use (no command text).
    check_id is None (the caller fails the checks) for any command or input shape other than an approved one."""
    events = []
    if len(content) > MAX_MESSAGE_BLOCKS:
        # Blocks past the cap are not inspected: report one unmatched call so the checks fail, never silent.
        events.append(NeutralEvent("check_command", state.session_id, state.turn_id,
                                   {"tool_use_id": None, "check_id": None}))
    for block in content[:MAX_MESSAGE_BLOCKS]:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use" or block.get("name") != "Bash":
            continue
        tool_use_id = _text(block.get("id"), _TOOL_USE_ID)
        if tool_use_id is not None and tool_use_id in state.check_tools:
            continue  # a replayed line is reported once
        if tool_use_id is not None and len(state.check_tools) >= MAX_CHECK_TOOLS:
            tool_use_id = None  # still reported (as unmatched) so the caller fails the operation, never silent
        elif tool_use_id is not None:
            state.check_tools.add(tool_use_id)
        command = _check_input_command(block.get("input"))
        check_id = state.check_commands.get(command) if command is not None and tool_use_id is not None else None
        events.append(NeutralEvent("check_command", state.session_id, state.turn_id,
                                   {"tool_use_id": tool_use_id, "check_id": check_id if isinstance(check_id, str) else None}))
    return events


def _check_results(obj: Mapping, state: StreamState) -> list:
    """Delivery checks run only: the outcome of a reported Bash call, as a boolean. Nothing else is read."""
    message = obj.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if state.session_id is None or not isinstance(content, list):
        return []
    meta = obj.get("tool_result_meta")
    not_run = {entry.get("id") for entry in meta[:MAX_MESSAGE_BLOCKS] if isinstance(entry, Mapping)
               and entry.get("non_execution_kind") is not None} if isinstance(meta, list) else set()
    structured = obj.get("tool_use_result")
    # Any structured background marker on the line (e.g. backgroundTaskId) makes every result on it not ok.
    background_line = isinstance(structured, Mapping) and any(
        "background" in str(key).lower() and value not in (None, False, "") for key, value in structured.items())
    events = []
    for block in content[:MAX_MESSAGE_BLOCKS]:
        if not isinstance(block, Mapping) or block.get("type") != "tool_result":
            continue
        tool_use_id = _text(block.get("tool_use_id"), _TOOL_USE_ID)
        if tool_use_id is None or tool_use_id not in state.check_tools:
            continue
        body = block.get("content")
        texts = [body] if isinstance(body, str) else [
            item.get("text") for item in body[:MAX_MESSAGE_BLOCKS] if isinstance(item, Mapping)
            and isinstance(item.get("text"), str)] if isinstance(body, list) else []
        failed_text = bool(texts) and texts[0].lstrip().startswith("Exit code")
        # A command moved to the background (by the model, an automatic backgrounding or a timeout conversion) has
        # not finished: its immediate result is never success.
        background = (background_line or any(text.lstrip().startswith(BACKGROUND_PREFIX) for text in texts))
        ok = (block.get("is_error") is False and tool_use_id not in not_run and not failed_text and not background)
        events.append(NeutralEvent("check_result", state.session_id, state.turn_id,
                                   {"tool_use_id": tool_use_id, "ok": ok}))
    return events


def _assistant(obj: Mapping, state: StreamState, line: str) -> list:
    """One ``message`` event per text block of a top-level assistant line (the CLI writes one line per content
    block and several lines can share a message id, so the message id is never used as a key).

    ``event_id`` is ``claude|<uuid>|<block index>`` when the line has a valid uuid: the uuid is unique per line,
    so a replayed line (or the same line seen again after --resume) yields the same id whatever the turn. Without
    a uuid it is ``claude|<turn>|d<digest of the line>|<index>``: distinct lines never collide, identical repeated
    lines within a turn may (the turn keeps identical short replies of different turns apart).
    All reply text of one line together is bounded by MAX_LINE_MESSAGE_TEXT; once it is spent the rest is dropped."""
    if state.session_id is None:
        return []
    message = obj.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, list):
        return []
    checks = _check_calls(content, state) if isinstance(state.check_commands, Mapping) else []
    uuid = _text(obj.get("uuid"), _LINE_ID)
    prefix = f"claude|{uuid}" if uuid else \
        f"claude|{state.turn_id}|d{hashlib.sha256(line.encode('utf-8', 'ignore')).hexdigest()[:32]}"
    events, budget, dropped = [], MAX_LINE_MESSAGE_TEXT, 0
    for index, block in enumerate(content):
        is_text = isinstance(block, Mapping) and block.get("type") == "text" and _message_text(block.get("text"), 1) is not None
        if index >= MAX_MESSAGE_BLOCKS or budget <= len(TRUNCATION_MARKER):
            dropped += 1 if is_text else 0  # past the block cap or the line budget: not shown in full
            continue
        if not is_text:
            continue
        limit = min(MAX_MESSAGE_TEXT, budget)
        text = _message_text(block.get("text"), limit)
        if len(block["text"]) > limit and text.endswith(TRUNCATION_MARKER):
            dropped += 1  # shown, but truncated
        budget -= len(text)
        events.append(NeutralEvent("message", state.session_id, state.turn_id,
                                   {"text": text, "event_id": f"{prefix}|{index}"}))
    state.dropped_replies = min(state.dropped_replies + dropped, MAX_TOKENS)
    return events + checks


_AGENT_STATUS = {"completed": "completed", "failed": "failed", "error": "failed", "killed": "interrupted",
                 "stopped": "interrupted", "cancelled": "interrupted", "interrupted": "interrupted"}


def _subagent(state: StreamState, agent_id: Any, agent_type: Any, phase: str, status: Optional[str] = None) -> list:
    """One ``subagent`` event (lineage only: identity, bounded type, start or stop), once per phase per agent."""
    agent_id = _text(agent_id, _LINE_ID)
    if agent_id is None or state.session_id is None:
        return []
    known = state.agents.get(agent_id)
    if phase == "started":
        if known is not None:
            return []
        if len(state.agents) >= MAX_AGENTS:
            # Never silent: one "omitted" event per refused agent (a repeat of the same id is not counted twice).
            if agent_id in state.omitted:
                return []
            if len(state.omitted) < MAX_OMITTED_IDS:
                state.omitted.add(agent_id)
            return [NeutralEvent("subagent", state.session_id, state.turn_id,
                                 {"agent_id": agent_id, "agent_type": None, "phase": "omitted", "status": None})]
        state.agents[agent_id] = "started"
    else:
        if known != "started":
            return []
        state.agents[agent_id] = "stopped"
    return [NeutralEvent("subagent", state.session_id, state.turn_id,
                         {"agent_id": agent_id, "agent_type": _text(agent_type, _IDENT), "phase": phase,
                          "status": status})]


def _task_lineage(obj: Mapping, state: StreamState) -> list:
    """Lineage from the CLI's own ``task_*`` system lines. A start counts only for a ``local_agent`` task (other
    background tasks are not delegates); a stop only for an agent already seen starting. Nothing else is read."""
    sub = obj.get("subtype")
    if sub == "task_started":
        if obj.get("task_type") != "local_agent":
            return []
        return _subagent(state, obj.get("task_id"), obj.get("subagent_type"), "started")
    if sub == "task_updated":
        patch = obj.get("patch")
        status = patch.get("status") if isinstance(patch, Mapping) else None
    elif sub == "task_notification":
        status = obj.get("status")
    else:
        return []
    mapped = _AGENT_STATUS.get(status) if isinstance(status, str) else None
    if mapped is None:
        return []
    return _subagent(state, obj.get("task_id"), None, "stopped", mapped)


def translate_stream_line(line: str, state: StreamState) -> list:
    """Translate one stream line into zero or more NeutralEvents; total, bounded, mutates only state."""
    try:
        if not isinstance(line, str) or len(line) > MAX_LINE \
                or len(line.encode("utf-8", "ignore")) > MAX_LINE:
            if isinstance(line, str):
                state.dropped_replies = min(state.dropped_replies + 1, MAX_TOKENS)
            return []
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return []
        if obj.get("type") == "system" and str(obj.get("subtype", "")).startswith("task_"):
            return _task_lineage(obj, state)
        if obj.get("parent_tool_use_id") is not None or "agent_id" in obj:
            # Sub-agent lines never carry text into the conversation. At most they reveal that the agent exists.
            return _subagent(state, obj.get("agent_id"), obj.get("subagent_type"), "started") \
                if "agent_id" in obj else []
        # (main-agent lines continue below)
        kind, sub = obj.get("type"), obj.get("subtype")
        if kind == "system" and sub == "init":
            return _init(obj, state)
        if kind == "system" and sub == "permission_denied":
            if not state.seen_result:
                _record_denial(state, obj)
            return []
        if kind == "result":
            return _result(obj, state)
        if kind == "assistant":
            return _assistant(obj, state, line)
        if kind == "user" and isinstance(state.check_commands, Mapping):
            return _check_results(obj, state)
        return []
    except Exception:  # total by contract: junk in, nothing out
        return []

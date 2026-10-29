"""Claude stream-json parser: pure mapping from one output line to NeutralEvents.

Allow-list reading only. No text field of the stream is ever copied into an event or kept in the state:
not assistant or user messages, tool input, hook output, ``result.result``, ``message``, paths, or the
plugin and MCP inventories. Only short validated identifiers, bounded numbers and tool names survive.

Contracts for callers:
- Lines over 1 MiB (counted in UTF-8 bytes) yield []; the runner enforces its own larger line cap.
- If the init event has no valid session_id it is ignored, and a later result still emits events with
  thread_id None. The caller must treat thread_id None as "no session: ignore, the run is unknown".
- Only the first result counts. Later results are dropped entirely, so their usage and denials are lost.
"""
from dataclasses import dataclass, field
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
MAX_TOKENS = 10 ** 15
MAX_COST = 1e6
UNKNOWN_TOOL = "unknown_tool"

_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_MODEL = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_MODE = re.compile(r"[A-Za-z_-]{1,40}\Z")
_VERSION = re.compile(r"[0-9][0-9A-Za-z.\- ]{0,40}( \(Claude Code\))?\Z")
_TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
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


def translate_stream_line(line: str, state: StreamState) -> list:
    """Translate one stream line into zero or more NeutralEvents; total, bounded, mutates only state."""
    try:
        if not isinstance(line, str) or len(line) > MAX_LINE \
                or len(line.encode("utf-8", "ignore")) > MAX_LINE:
            return []
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return []
        if obj.get("parent_tool_use_id") is not None or "agent_id" in obj:
            return []
        kind, sub = obj.get("type"), obj.get("subtype")
        if kind == "system" and sub == "init":
            return _init(obj, state)
        if kind == "system" and sub == "permission_denied":
            if not state.seen_result:
                _record_denial(state, obj)
            return []
        if kind == "result":
            return _result(obj, state)
        return []
    except Exception:  # total by contract: junk in, nothing out
        return []

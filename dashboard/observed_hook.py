"""Parse hook events from the owner's own Claude Code sessions (observed sessions).

Pure functions, no I/O. Error codes and limits are the managed ones from ``backends.claude_hook``;
no request text is ever echoed into an exception. Only the fields named in ``ObservedEvent`` survive;
every other field (transcript paths, messages, tool responses) is dropped.

``PermissionRequest`` is parsed by the strict managed parser. The other events are parsed leniently:
the live ``PostToolUse`` and ``Stop`` payload shapes are not yet recorded (spike S11 pending), so a
``PostToolUse`` without ``tool_name`` or ``tool_input`` still parses (it then cannot match a card).
"""
from dataclasses import dataclass, field
import json
from typing import Any, Dict, Optional

from .backends.claude_hook import (MAX_BODY, HookRejected, HookRequest, _IDENT, _SESSION, _TOOL,
                                   _finite_float, _reject_constant, _text, _unique_pairs, parse_request)

MAX_CWD = 4096
KINDS = {
    "PermissionRequest": "permission_request",
    "PostToolUse": "post_tool_use",
    "Stop": "stop",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "SubagentStart": "subagent_start",
    "SubagentStop": "subagent_stop",
}


@dataclass(frozen=True)
class ObservedEvent:
    """One parsed event. ``tool_name``/``tool_input`` are set only for ``post_tool_use``. The path and
    the tool input are left out of ``repr`` so an accidental log line cannot carry them."""
    kind: str
    session_id: str
    cwd: Optional[str] = field(repr=False)
    request: Optional[HookRequest] = field(repr=False)
    agent_id: Optional[str]
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = field(default=None, repr=False)


def _load(body) -> dict:
    if not isinstance(body, (bytes, bytearray)):
        raise HookRejected("bad_shape")
    if len(body) > MAX_BODY:
        raise HookRejected("too_large")
    try:
        data = json.loads(bytes(body).decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except (ValueError, RecursionError):
        raise HookRejected("bad_json") from None
    if not isinstance(data, dict):
        raise HookRejected("bad_shape")
    return data


def parse_observed(body: bytes) -> ObservedEvent:
    data = _load(body)
    name = data.get("hook_event_name")
    kind = KINDS.get(name) if isinstance(name, str) else None
    if kind is None:
        raise HookRejected("bad_field")
    cwd = data.get("cwd")
    if cwd is not None and (not isinstance(cwd, str) or len(cwd) > MAX_CWD):
        raise HookRejected("bad_field")
    if kind == "permission_request":
        request = parse_request(body)
        return ObservedEvent(kind=kind, session_id=request.session_id, cwd=cwd, request=request,
                             agent_id=request.agent_id)
    session_id = _text(data, "session_id", _SESSION, required=True)
    agent_id = _text(data, "agent_id", _IDENT)
    tool_name, tool_input = None, None
    if kind == "post_tool_use":
        tool_name = _text(data, "tool_name", _TOOL)
        tool_input = data.get("tool_input")
        if tool_input is not None and not isinstance(tool_input, dict):
            raise HookRejected("bad_shape")
    return ObservedEvent(kind=kind, session_id=session_id, cwd=cwd, request=None, agent_id=agent_id,
                         tool_name=tool_name, tool_input=tool_input)

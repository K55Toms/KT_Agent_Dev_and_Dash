"""Claude PermissionRequest hook protocol: strict request parsing and the two exact replies.

Pure functions, no I/O. Error codes are fixed strings; request text (tool input, paths, session
ids) is never echoed into an exception or a reply. Only an allow-listed set of fields survives
parsing; every unknown field is dropped. The bound and nesting checks are the approval-review ones.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Any, Dict, Optional

from ..approval_review import ReviewError, bounded

MAX_BODY = 262144
DEFAULT_WAIT_SECONDS = 900
MIN_WAIT_SECONDS = 60
MAX_WAIT_SECONDS = 3600
HOOK_TIMEOUT_MARGIN = 60

_EVENT = "PermissionRequest"
_DENY_MESSAGE = "Declined in the dashboard."
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_IDENT = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_MODE = re.compile(r"[A-Za-z_-]{1,40}\Z")


class HookRejected(ValueError):
    """A hook request was refused. ``code`` is one of too_large, bad_json, bad_shape, bad_field."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HookRequest:
    session_id: str
    permission_mode: Optional[str]
    tool_name: str
    tool_input: Dict[str, Any]
    agent_id: Optional[str]
    agent_type: Optional[str]
    prompt_id: Optional[str]


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _reject_constant(_name):
    raise ValueError("constant")


def _text(data, key, pattern, required=False):
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not pattern.match(value):
        raise HookRejected("bad_field")
    return value


def parse_request(body: bytes) -> HookRequest:
    if not isinstance(body, (bytes, bytearray)):
        raise HookRejected("bad_shape")
    if len(body) > MAX_BODY:
        raise HookRejected("too_large")
    try:
        data = json.loads(bytes(body).decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise HookRejected("bad_json") from None
    if not isinstance(data, dict):
        raise HookRejected("bad_shape")
    if data.get("hook_event_name") != _EVENT:
        raise HookRejected("bad_field")
    session_id = _text(data, "session_id", _SESSION, required=True)
    tool_name = _text(data, "tool_name", _TOOL, required=True)
    mode = _text(data, "permission_mode", _MODE)
    agent_id = _text(data, "agent_id", _IDENT)
    agent_type = _text(data, "agent_type", _IDENT)
    prompt_id = _text(data, "prompt_id", _IDENT)
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        raise HookRejected("bad_shape")
    try:
        bounded(tool_input)
    except ReviewError as err:
        raise HookRejected("bad_shape" if err.code == "unsupported_shape" else "bad_field") from None
    return HookRequest(session_id=session_id, permission_mode=mode, tool_name=tool_name,
                       tool_input=deepcopy(tool_input), agent_id=agent_id, agent_type=agent_type,
                       prompt_id=prompt_id)


def _reply(decision: Dict[str, str]) -> bytes:
    body = {"hookSpecificOutput": {"hookEventName": _EVENT, "decision": decision}}
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def allow_reply() -> bytes:
    return _reply({"behavior": "allow"})


def deny_reply() -> bytes:
    return _reply({"behavior": "deny", "message": _DENY_MESSAGE})


def hook_timeout(wait: int) -> int:
    if type(wait) is not int or not MIN_WAIT_SECONDS <= wait <= MAX_WAIT_SECONDS:
        raise ValueError("wait_out_of_range")
    return wait + HOOK_TIMEOUT_MARGIN

"""Codex notification translator, capabilities and CodexBackend.

The translator is a set of pure functions. CodexBackend issues the Codex App Server
requests through a client it is given; it imports only ProtocolError from the dashboard.

Each branch mirrors how Dashboard.on_message in dashboard/server.py reads the same
native notification. The translator only reads; it never mutates the message and
never raises. Messages that carry an "id" are native requests and are routed by the
caller before translation.
"""
from copy import deepcopy
from typing import Any, Callable, Mapping, Optional

from dashboard.backends.base import ApprovalRequest, Capabilities, NeutralEvent, YES
from dashboard.codex_client import ProtocolError

CODEX_CAPABILITIES = Capabilities("codex", YES, YES, YES, YES, YES, YES)

# Native token-usage field -> neutral name; the one definition (server.py imports it as server.USAGE_KEYS).
USAGE_KEYS = {"inputTokens": "input_tokens", "cachedInputTokens": "cached_input_tokens",
              "outputTokens": "output_tokens", "reasoningOutputTokens": "reasoning_output_tokens",
              "totalTokens": "total_tokens"}
_TERMINAL = {"completed": "completed", "failed": "failed", "interrupted": "interrupted"}
_PLAN_STATUSES = ("pending", "inProgress", "completed")


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _unrecognized(method: Optional[str]) -> NeutralEvent:
    return NeutralEvent("unrecognized", None, None, {"method": method})


def _usage(params: dict) -> Optional[dict]:
    """The five counters, or None when the handler would ignore the update."""
    token_usage = params.get("tokenUsage", {})
    total = token_usage.get("total", {}) if isinstance(token_usage, dict) else None
    if not isinstance(total, dict):
        return None
    if not all(type(total.get(k)) is int and 0 <= total[k] <= 10 ** 15 for k in USAGE_KEYS):
        return None
    if total["cachedInputTokens"] > total["inputTokens"]:
        return None
    return {v: total[k] for k, v in USAGE_KEYS.items()}


def _steps(plan: Any) -> Optional[list]:
    """Ordinal labels and statuses only; model-authored text is never kept."""
    if not isinstance(plan, list):
        return None
    return [{"step": "Step " + str(i + 1),
             "status": x["status"] if isinstance(x.get("status"), str) and x["status"] in _PLAN_STATUSES else "pending"}
            for i, x in enumerate(plan[:100]) if isinstance(x, dict)]


def translate_notification(message: dict) -> NeutralEvent:
    """Translate one native Codex notification; total, never raises.

    Only a dict message is accepted: any other value, including a Mapping that is
    not a dict, gives "unrecognized", as does a non-dict "params".

    For turn/started and turn/completed the event's turn_id is turn.id only (None when
    it is missing or not a string; the handler then changes nothing), while the
    stale-turn filter in server.py compares turnId or turn.id. Other methods use
    turnId or turn.id.
    """
    if not isinstance(message, dict):
        return _unrecognized(None)
    method = _text(message.get("method"))
    params = message.get("params", {})
    if method is None or not isinstance(params, dict):
        return _unrecognized(method)
    turn = params.get("turn", {})
    if not isinstance(turn, dict):  # on_message drops every method when "turn" is not a dict
        return _unrecognized(method)
    thread_id = _text(params.get("threadId"))
    event_turn = _text(params.get("turnId") or turn.get("id"))

    if method in ("turn/started", "turn/completed"):
        if "turn" not in params:  # the handler reads params["turn"]["id"] directly
            return _unrecognized(method)
        # Only turn.id: the handler read params["turn"]["id"] and changed nothing without it.
        turn_id = _text(turn.get("id"))
        if method == "turn/started":
            return NeutralEvent("turn_started", thread_id, turn_id, {})
        status = turn.get("status")
        status = _TERMINAL.get(status, "unknown") if isinstance(status, str) else "unknown"
        return NeutralEvent("turn_completed", thread_id, turn_id,
                            {"status": status, "error": turn.get("error")})
    if method == "turn/plan/updated":
        return NeutralEvent("plan_updated", thread_id, event_turn, {"steps": _steps(params.get("plan", []))})
    if method == "thread/tokenUsage/updated":
        return NeutralEvent("usage_updated", thread_id, event_turn, {"usage": _usage(params)})
    if method == "model/rerouted":
        return NeutralEvent("model_changed", thread_id, event_turn,
                            {"model": params.get("toModel"), "service_tier": None, "rerouted": True})
    if method == "thread/settings/updated":
        settings = params.get("threadSettings", {})
        if not isinstance(settings, dict):  # the handler raised here without changing state
            return _unrecognized(method)
        return NeutralEvent("model_changed", thread_id, event_turn,
                            {"model": settings.get("model"), "service_tier": settings.get("serviceTier"),
                             "rerouted": False})
    if method == "error":
        return NeutralEvent("run_error", thread_id, event_turn,
                            {"error": params.get("error"), "will_retry": bool(params.get("willRetry", False))})
    if method == "serverRequest/resolved":
        return NeutralEvent("request_resolved", thread_id, event_turn, {"request_id": params.get("requestId")})
    return _unrecognized(method)


_DECISIONS = ("accept", "decline", "cancel")


def codex_approval_result(kind: str, decision: str, params: Mapping) -> dict:
    """Shape the native response for one reviewed approval decision.

    Raises ValueError for any decision other than accept, decline or cancel, so nothing
    unrecognised is ever written. params carries only what the dashboard has already
    reviewed and validated, and only an accept reads it: "context" (the reviewed native
    context: "permissions", "mode"), "content" (form values) and "answers". Nothing else
    from the caller crosses this boundary, and no session grant is ever produced.
    """
    if type(decision) is not str or decision not in _DECISIONS:
        raise ValueError("Unrecognised approval decision")
    accept = decision == "accept"
    if kind == "permissions":
        return {"permissions": deepcopy(params["context"]["permissions"]) if accept else {}, "scope": "turn"}
    if kind == "elicitation":
        return {"action": decision, "content":
                ({} if params["context"]["mode"] == "url" else deepcopy(params["content"])) if accept else None}
    if kind == "approval_question":
        # Only an accept can answer a question; a decline or cancel has no native shape
        # (the dashboard never offers one), so nothing is written for it.
        if not accept:
            raise ValueError("A question can only be answered")
        return {"answers": {key: {"answers": deepcopy(value)} for key, value in params["answers"].items()}}
    return {"decision": decision}


class CodexBackend:
    """Issues the Codex App Server requests the dashboard has always issued.

    The backend never creates, owns or closes a client. By default it asks get_client()
    at every use, so a client assigned to the dashboard later is the one that is used;
    a caller that already validated a specific client passes it with client=.
    Error classification, guards and response validation stay with the caller.
    """
    capabilities = CODEX_CAPABILITIES

    def __init__(self, get_client: Callable[[], Any]):
        self._get_client = get_client

    def _client(self, client=None):
        if client is None:
            client = self._get_client()
        if client is None:
            raise ProtocolError("Codex connection is not available")
        return client

    def translate(self, message: dict) -> NeutralEvent:
        return translate_notification(message)

    def _send(self, method: str, params: dict, guard=None, *, client=None):
        client = self._client(client)
        if guard is None:
            return client.request(method, params)
        guarded = getattr(client, "request_guarded", None)
        if not callable(guarded):
            raise ValueError("Recovery requires guarded native dispatch")
        return guarded(method, params, guard)

    def list_models(self, stop: Optional[Callable[[list], bool]] = None, *, client=None) -> list:
        """Collect up to 10 pages of model/list; stop early once stop(collected) is true."""
        cursor = None
        models: list = []
        for _ in range(10):
            catalog = self._client(client).request("model/list", {"includeHidden": True, "limit": 100, "cursor": cursor})
            if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
                raise ValueError("Invalid model catalog")
            models.extend(catalog["data"][:100])
            cursor = catalog.get("nextCursor")
            if cursor is None or (stop is not None and stop(models)):
                break
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError("Invalid model cursor")
        return models

    def start_thread(self, params: dict, guard=None, *, client=None):
        return self._send("thread/start", params, guard, client=client)

    def start_turn(self, params: dict, guard=None, *, client=None):
        return self._send("turn/start", params, guard, client=client)

    def steer(self, params: dict, *, client=None):
        return self._send("turn/steer", params, client=client)

    def interrupt(self, thread_id: str, turn_id: str, *, client=None) -> None:
        self._send("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, client=client)

    def answer_approval(self, request: ApprovalRequest, decision: str) -> None:
        """Write the shaped answer to the client that received the request.

        request.responder is (client, rpc_id); get_client() is never consulted, so the
        answer goes only to the connection that asked. The caller consumes its authority
        before calling and handles ProtocolError/OSError; failures propagate unchanged.
        """
        responder = request.responder
        if not isinstance(responder, tuple) or len(responder) != 2:
            raise ValueError("Approval request has no responder")
        client, rpc_id = responder
        result = codex_approval_result(request.kind, decision, request.params)
        client.respond(rpc_id, result)

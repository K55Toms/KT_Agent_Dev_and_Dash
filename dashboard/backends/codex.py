"""Codex notification translator and capabilities; pure functions, imports nothing from the dashboard.

Each branch mirrors how Dashboard.on_message in dashboard/server.py reads the same
native notification. The translator only reads; it never mutates the message and
never raises. Messages that carry an "id" are native requests and are routed by the
caller before translation.
"""
from typing import Any, Mapping, Optional

from dashboard.backends.base import Capabilities, NeutralEvent, YES

CODEX_CAPABILITIES = Capabilities("codex", YES, YES, YES, YES, YES, YES)

# Native token-usage field -> neutral name (same table as server.USAGE_KEYS).
_USAGE_KEYS = {"inputTokens": "input_tokens", "cachedInputTokens": "cached_input_tokens",
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
    if not all(type(total.get(k)) is int and 0 <= total[k] <= 10 ** 15 for k in _USAGE_KEYS):
        return None
    if total["cachedInputTokens"] > total["inputTokens"]:
        return None
    return {v: total[k] for k, v in _USAGE_KEYS.items()}


def _steps(plan: Any) -> Optional[list]:
    """Ordinal labels and statuses only; model-authored text is never kept."""
    if not isinstance(plan, list):
        return None
    return [{"step": "Step " + str(i + 1),
             "status": x["status"] if isinstance(x.get("status"), str) and x["status"] in _PLAN_STATUSES else "pending"}
            for i, x in enumerate(plan[:100]) if isinstance(x, dict)]


def translate_notification(message: Mapping) -> NeutralEvent:
    """Translate one native Codex notification; total, never raises."""
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
        turn_id = _text(turn.get("id")) or _text(params.get("turnId"))
        if method == "turn/started":
            return NeutralEvent("turn_started", thread_id, turn_id, {})
        status = turn.get("status")
        status = _TERMINAL.get(status, "unknown") if isinstance(status, str) else "unknown"
        return NeutralEvent("turn_completed", thread_id, turn_id,
                            {"status": status, "error": turn.get("error") or None})
    if method == "turn/plan/updated":
        return NeutralEvent("plan_updated", thread_id, event_turn, {"steps": _steps(params.get("plan", []))})
    if method == "thread/tokenUsage/updated":
        return NeutralEvent("usage_updated", thread_id, event_turn, {"usage": _usage(params)})
    if method == "model/rerouted":
        return NeutralEvent("model_changed", thread_id, event_turn,
                            {"model": params.get("toModel"), "service_tier": None, "rerouted": True})
    if method == "thread/settings/updated":
        settings = params.get("threadSettings", {})
        if not isinstance(settings, dict):
            settings = {}
        return NeutralEvent("model_changed", thread_id, event_turn,
                            {"model": settings.get("model"), "service_tier": settings.get("serviceTier"),
                             "rerouted": False})
    if method == "error":
        return NeutralEvent("run_error", thread_id, event_turn,
                            {"error": params.get("error"), "will_retry": bool(params.get("willRetry", False))})
    if method == "serverRequest/resolved":
        return NeutralEvent("request_resolved", thread_id, event_turn, {"request_id": params.get("requestId")})
    return _unrecognized(method)

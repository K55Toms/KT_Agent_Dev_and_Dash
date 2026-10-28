"""Provider-neutral types and the Backend protocol; imports nothing from the dashboard."""
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

YES = "yes"
NO = "no"
UNCONFIRMED = "unconfirmed"

EVENT_KINDS = ("turn_started", "turn_completed", "plan_updated", "usage_updated",
               "run_error", "model_changed", "request_resolved", "unrecognized")


class ProviderUnavailable(Exception):
    """Raised when no provider backend can serve the call."""


@dataclass(frozen=True)
class Capabilities:
    """What a provider supports; each capability is YES, NO or UNCONFIRMED."""
    provider: str
    guidance_while_running: str
    subagent_questions: str
    plan: str
    recovery: str
    assessment: str
    approval_alternative: str

    def __post_init__(self):
        for name in ("guidance_while_running", "subagent_questions", "plan", "recovery",
                     "assessment", "approval_alternative"):
            if getattr(self, name) not in (YES, NO, UNCONFIRMED):
                raise ValueError(f"invalid capability value for {name}")

    def public(self):
        """Return all seven fields as a plain dict."""
        return {"provider": self.provider, "guidance_while_running": self.guidance_while_running,
                "subagent_questions": self.subagent_questions, "plan": self.plan,
                "recovery": self.recovery, "assessment": self.assessment,
                "approval_alternative": self.approval_alternative}


@dataclass(frozen=True)
class NeutralEvent:
    """A provider message translated to one of EVENT_KINDS."""
    kind: str
    thread_id: Optional[str]
    turn_id: Optional[str]
    data: Mapping[str, Any]


@dataclass(frozen=True)
class ApprovalRequest:
    """A native approval request; the responder is opaque to the dashboard."""
    kind: str
    native_method: str
    liveness_key: tuple
    params: Mapping[str, Any]
    available_decisions: tuple
    responder: Any


class Backend(Protocol):
    """The calls the dashboard makes on a provider."""
    capabilities: Capabilities

    def translate(self, message: Mapping) -> NeutralEvent: ...
    def list_models(self, stop=None) -> list: ...
    def start_thread(self, params: Mapping, guard=None) -> Mapping: ...
    def start_turn(self, params: Mapping, guard=None) -> Mapping: ...
    def steer(self, params: Mapping) -> Mapping: ...
    def interrupt(self, thread_id: str, turn_id: str) -> None: ...
    def answer_approval(self, request: ApprovalRequest, decision: str) -> None: ...


class NoBackend:
    """Placeholder when no provider is configured; every call raises."""
    capabilities = Capabilities("none", NO, NO, NO, NO, NO, NO)

    def _unavailable(self, *args, **kwargs):
        raise ProviderUnavailable("No provider configured")

    translate = list_models = start_thread = start_turn = steer = interrupt = answer_approval = _unavailable

"""Claude backend stub: a selectable provider whose every call answers "not implemented yet"."""
from dashboard.backends.base import NO, UNCONFIRMED, Capabilities, ProviderUnavailable

CLAUDE_CAPABILITIES = Capabilities("claude", NO, NO, UNCONFIRMED, NO, NO, NO)


class ClaudeBackendStub:
    """Placeholder until the Claude backend exists; starts nothing and every call raises."""
    capabilities = CLAUDE_CAPABILITIES

    def _unavailable(self, *args, **kwargs):
        raise ProviderUnavailable("Claude backend is not implemented yet")

    translate = list_models = start_thread = start_turn = steer = interrupt = answer_approval = _unavailable

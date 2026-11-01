"""Provider backends and the start-up resolver, which fails closed."""
from typing import Any, Callable, Optional

from dashboard.backends.base import Backend, NoBackend
from dashboard.backends.claude import ClaudeBackendStub
from dashboard.backends.codex import CodexBackend


def resolve(name: Optional[str], get_client: Callable[[], Any]) -> Backend:
    """Only the exact strings "codex" and "claude" select a backend; anything else gets NoBackend."""
    if name == "codex":
        return CodexBackend(get_client)
    if name == "claude":
        return ClaudeBackendStub()
    return NoBackend()

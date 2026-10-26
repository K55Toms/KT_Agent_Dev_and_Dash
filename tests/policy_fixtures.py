"""Synthetic injected policy for effects-free protocol tests, never production approval."""
import hashlib
from dashboard.ponytail_policy import PolicyBundle


class SyntheticPolicy:
    def load(self):
        text = 'Synthetic approved policy bytes for isolated tests.\n'
        return PolicyBundle('0.0.0', hashlib.sha256(text.encode()).hexdigest(), text)

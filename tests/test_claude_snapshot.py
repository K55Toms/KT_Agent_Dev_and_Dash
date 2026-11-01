"""Claude cost, usage and pricing shapes in the snapshot (Task 10). Fake backend only."""
import json
from pathlib import Path
import tempfile
import unittest

from dashboard.backends.claude import ClaudeBackend
from dashboard.server import Dashboard, PRICING
from tests.policy_fixtures import SyntheticPolicy

CLAUDE_PRICING = {"unit": "usd-estimate", "source": "Claude Code client-side list-price estimate",
                  "speed_basis": "Not a billed amount; the subscription login is not billed per call"}
USAGE = {"total_tokens": 30, "input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 15,
         "reasoning_output_tokens": 0}
COST = {"basis": "estimated", "unit": "usd-estimate", "usd": 0.0123, "credits": None,
        "source": "Claude Code result.total_cost_usd (list price)", "pricing_date": None}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def make(self, backend=None):
        kwargs = {"backend": backend} if backend else {}
        app = Dashboard(self.root / ("c" if backend else "x"), policy_provider=SyntheticPolicy(), **kwargs)
        self.addCleanup(app.close)
        return app

    def test_claude_snapshot_has_usd_pricing_and_codex_snapshot_is_unchanged(self):
        claude = self.make(ClaudeBackend(claude_path="/synthetic/bin/claude", runner=lambda a, t: None))
        with claude.lock:
            claude.tasks["t1"] = {"id": "t1", "project_id": "p", "title": "T", "status": "completed",
                                  "provider": "claude", "usage": dict(USAGE), "cost": dict(COST)}
        snap = claude.snapshot()
        self.assertEqual(CLAUDE_PRICING, snap["pricing"])
        task = snap["tasks"][0]
        self.assertEqual(COST, task["cost"])
        self.assertEqual(USAGE, task["usage"])
        self.assertEqual("claude", task["provider"])
        self.assertEqual(snap, json.loads(json.dumps(snap)))
        # The module constant is not shared with the snapshot copy.
        snap["pricing"]["unit"] = "x"
        self.assertEqual("usd-estimate", claude.snapshot()["pricing"]["unit"])
        codex = self.make()
        self.assertEqual(PRICING, codex.snapshot()["pricing"])
        self.assertEqual("credits", codex.snapshot()["pricing"]["unit"])

    def test_claude_snapshot_exposes_only_denied_summary(self):
        claude = self.make(ClaudeBackend(claude_path="/synthetic/bin/claude", runner=lambda a, t: None))
        with claude.lock:
            claude.tasks["t1"] = {"id": "t1", "project_id": "p", "title": "T", "status": "completed", "provider": "claude",
                                  "claude": {"pid": 4242, "session_id": "s", "pid_started": "m", "denied_count": 2,
                                             "denied_tools": ["Bash", "Edit"]}}
        task = claude.snapshot()["tasks"][0]
        self.assertEqual({"denied_count": 2, "denied_tools": ["Bash", "Edit"]}, task["claude"])
        self.assertEqual(4242, claude.tasks["t1"]["claude"]["pid"])
        codex = self.make()
        with codex.lock:
            codex.tasks["c1"] = {"id": "c1", "project_id": "p", "title": "T", "status": "completed", "provider": "codex"}
        self.assertNotIn("claude", codex.snapshot()["tasks"][0])


if __name__ == "__main__":
    unittest.main()

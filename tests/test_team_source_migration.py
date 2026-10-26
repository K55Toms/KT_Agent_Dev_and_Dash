"""Migration guard: the role source reproduces the Codex roles captured before migration."""

import json
from pathlib import Path
import tomllib
import unittest

from dashboard.team import PROFILES
from team_source.policy import load_policy, validate
from team_source.roles import load_roles_dir, render_claude, render_codex, resolve

ROOT = Path(__file__).resolve().parents[1]
ROLES_DIR = ROOT / "team_source" / "roles"
MODELS = ROOT / "team_source" / "models.toml"
BASELINE = ROOT / "tests" / "fixtures" / "codex_roles_baseline.json"
BASELINE_KEYS = ("name", "description", "model", "model_reasoning_effort", "developer_instructions")
CODEX_ONLY_TERMS = ("ponytail", "ui-skills", "codex", "gpt-")
REVIEWERS = {"security_reviewer", "code_quality_reviewer"}
CODEX_ONLY_CLOSE = "<!-- /codex-only -->"
CLAUDE_ONLY_OPEN = "<!-- claude-only -->"
CLAUDE_ONLY_CLOSE = "<!-- /claude-only -->"
# Every claude-only block, per role and in order. Each block sits directly after a
# codex-only block: chief_of_staff replaces the spawn-override sentence; the others
# restore general guidance that shared lines with Ponytail or ui-skills text, in the
# role's own words (owner decision, 2026-10-26). No other role has a claude-only block.
EXPECTED_CLAUDE_ONLY = {
    "chief_of_staff": [
        (
            "A role's configured model applies unless an invocation overrides it; "
            "do not override a role's model without the owner's approval.",
        ),
    ],
    "code_quality_reviewer": [
        (
            "Judge simplicity only after correctness, safety and complete acceptance behaviour; fewer lines",
            "are not evidence of quality. Keep this role review-only.",
        ),
    ],
    "backend_developer": [
        ("Report actual checks, deliberate shortcuts and unverified risks.",),
    ],
    "frontend_developer": [
        ("Report actual checks, deliberate shortcuts and unverified risks.",),
        (
            "If the UI goal is unclear, ask one short question before dependent work.",
            "Retain security, accessibility and review gates.",
        ),
    ],
    "ui_designer": [
        (
            "If the UI goal is unclear, ask one short question before dependent work.",
            "Preserve accessibility, security and review gates.",
        ),
    ],
}


def claude_only_blocks(body):
    """Return (line before the block, block lines) for each claude-only block in body."""
    lines = body.split("\n")
    blocks = []
    index = 0
    while index < len(lines):
        if lines[index] == CLAUDE_ONLY_OPEN:
            end = lines.index(CLAUDE_ONLY_CLOSE, index)
            previous = lines[index - 1] if index else ""
            blocks.append((previous, tuple(lines[index + 1 : end])))
            index = end + 1
        else:
            index += 1
    return blocks


def load_baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


class RoleSourceMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = load_baseline()
        cls.roles = load_roles_dir(ROLES_DIR)
        cls.policy = load_policy(MODELS)

    def test_codex_render_of_source_equals_baseline_for_all_14_roles(self):
        # The baseline is the Codex roles as captured before migration, with one
        # owner-approved deviation (2026-10-26): the description of expert_escalation
        # says "escalation specialist" instead of "Astra specialist". Every other field
        # of every role is still the captured value and is compared strictly.
        self.assertEqual(len(self.baseline), 14)
        self.assertEqual(set(self.roles), set(self.baseline))
        for role_id, role in sorted(self.roles.items()):
            with self.subTest(role=role_id):
                codex = self.policy[role_id]["codex"]
                parsed = tomllib.loads(render_codex(role, codex.model, codex.effort))
                expected = self.baseline[role_id]
                self.assertEqual(
                    {key: parsed[key] for key in BASELINE_KEYS},
                    {key: expected[key] for key in BASELINE_KEYS},
                )

    def test_claude_render_contains_no_codex_only_terms(self):
        for role_id, role in sorted(self.roles.items()):
            claude = self.policy[role_id]["claude"]
            text = render_claude(
                role, claude.model, claude.effort, coordinator=role_id == "chief_of_staff"
            ).lower()
            for term in CODEX_ONLY_TERMS:
                with self.subTest(role=role_id, term=term):
                    self.assertNotIn(term, text)

    def test_source_has_exactly_the_14_dashboard_roles_and_validates(self):
        self.assertEqual(set(self.roles), set(PROFILES))
        validate(self.roles, self.policy, PROFILES)

    def test_reviewer_profile_only_for_security_and_code_quality_reviewers(self):
        for role_id, role in sorted(self.roles.items()):
            with self.subTest(role=role_id):
                expected = "reviewer" if role_id in REVIEWERS else "editor"
                self.assertEqual(role.profile, expected)

    def test_codex_blocks_are_whole_lines_of_the_original_text(self):
        for role_id, role in sorted(self.roles.items()):
            with self.subTest(role=role_id):
                self.assertEqual(
                    resolve(role.body, "codex"),
                    self.baseline[role_id]["developer_instructions"],
                )

    def test_claude_only_blocks_match_the_expected_table_exactly(self):
        with_block = {
            role_id for role_id, role in self.roles.items() if CLAUDE_ONLY_OPEN in role.body
        }
        self.assertEqual(with_block, set(EXPECTED_CLAUDE_ONLY))
        for role_id, expected_blocks in sorted(EXPECTED_CLAUDE_ONLY.items()):
            with self.subTest(role=role_id):
                found = claude_only_blocks(self.roles[role_id].body)
                self.assertEqual([lines for _, lines in found], expected_blocks)
                for previous, _ in found:
                    self.assertEqual(previous, CODEX_ONLY_CLOSE)
                claude_text = resolve(self.roles[role_id].body, "claude")
                position = 0
                for lines in expected_blocks:
                    block = "".join(line + "\n" for line in lines)
                    self.assertEqual(claude_text.count(block), 1)
                    found_at = claude_text.find(block)
                    self.assertGreaterEqual(found_at, position)
                    position = found_at + len(block)
                    for term in CODEX_ONLY_TERMS:
                        self.assertNotIn(term, block.lower())


if __name__ == "__main__":
    unittest.main()

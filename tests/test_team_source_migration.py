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
# Only the coordinator replaces a Codex-only sentence; every other role only drops text.
CLAUDE_ONLY_ROLES = {"chief_of_staff"}
CLAUDE_ONLY_MARKER = "<!-- claude-only -->"


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

    def test_claude_only_blocks_exist_only_where_expected(self):
        with_block = {
            role_id for role_id, role in self.roles.items() if CLAUDE_ONLY_MARKER in role.body
        }
        self.assertEqual(with_block, CLAUDE_ONLY_ROLES)


if __name__ == "__main__":
    unittest.main()

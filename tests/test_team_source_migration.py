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
CODEX_ONLY_OPEN = "<!-- codex-only -->"
CODEX_ONLY_CLOSE = "<!-- /codex-only -->"
CLAUDE_ONLY_OPEN = "<!-- claude-only -->"
CLAUDE_ONLY_CLOSE = "<!-- /claude-only -->"
MODEL_LINE = (
    "A role's configured model applies unless an invocation overrides it; "
    "do not override a role's model without the owner's approval."
)
REPORT_LINE = "Report actual checks, deliberate shortcuts and unverified risks."
UI_QUESTION_LINE = "If the UI goal is unclear, ask one short question before dependent work."
# Every claude-only block, per role and in order, as (first line of the codex-only block
# directly before it, the claude-only lines). chief_of_staff's first block presents the
# interrupted sentence "Require independent QA and reviews, / route findings ..." whole and
# replaces the spawn-override sentence; every other block restores general guidance that
# shared lines with Ponytail or ui-skills text, in the role's own words (owner decisions,
# 2026-10-26). No other role has a claude-only block.
EXPECTED_CLAUDE_ONLY = {
    "chief_of_staff": [
        (
            "Use technical_architect for cross-system design, platform_reliability_engineer for delivery",
            (
                "route findings to implementers, then obtain retest evidence. Never equate consensus with proof.",
                "Use technical_architect for cross-system design, platform_reliability_engineer for delivery",
                "and operations, and agent_evaluation_engineer for assessing the team itself.",
                "Follow team_source/models.toml for Claude models and effort. Use expert_escalation only for a bounded consequential problem.",
                MODEL_LINE,
            ),
        ),
        (
            "For Backend/Frontend implementation, include the installed ponytail:ponytail skill and Full mode",
            (
                "Keep evaluator follow-up proportional to the task. Do not",
                "weaken delivery gates without an agreed scope change.",
            ),
        ),
    ],
    "agent_evaluation_engineer": [
        (
            "Evaluate the Backend/Frontend Ponytail Full pilot defined in AGENTS.md. Check skill-loading",
            (
                "Check handoff evidence, complete acceptance outcomes, independent findings, remediation and rework.",
                "Record deliberate shortcuts and missing checks; distinguish static configuration from observed",
                "agent behaviour. Treat code volume as context, not a quality score, and report time/cost as unknown",
                "unless measured on comparable work.",
            ),
        ),
    ],
    "code_quality_reviewer": [
        (
            "Judge simplicity only after correctness, safety and complete acceptance behaviour; fewer lines",
            (
                "Judge simplicity only after correctness, safety and complete acceptance behaviour; fewer lines",
                "are not evidence of quality. Keep this role review-only.",
            ),
        ),
    ],
    "backend_developer": [
        ("Report the skill source loaded, actual checks, deliberate shortcuts and unverified risks.", (REPORT_LINE,)),
    ],
    "frontend_developer": [
        ("Report the skill source loaded, actual checks, deliberate shortcuts and unverified risks.", (REPORT_LINE,)),
        (
            "Before UI implementation, load the current installed ui-skills-root SKILL.md from the skill",
            (UI_QUESTION_LINE, "Retain security, accessibility and review gates."),
        ),
    ],
    "ui_designer": [
        (
            "Before UI design or prototyping, load the current installed ui-skills-root SKILL.md from the",
            (UI_QUESTION_LINE, "Preserve accessibility, security and review gates."),
        ),
    ],
}


def claude_only_blocks(body):
    """Return (first line of the codex-only block directly before it, its lines) per claude-only block.

    The first item is None when the claude-only block does not directly follow a codex-only block.
    """
    lines = body.split("\n")
    blocks = []
    index = 0
    while index < len(lines):
        if lines[index] == CLAUDE_ONLY_OPEN:
            end = lines.index(CLAUDE_ONLY_CLOSE, index)
            preceding = None
            if index and lines[index - 1] == CODEX_ONLY_CLOSE:
                opened = max(i for i in range(index - 1) if lines[i] == CODEX_ONLY_OPEN)
                preceding = lines[opened + 1]
            blocks.append((preceding, tuple(lines[index + 1 : end])))
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
                # Each block's lines and the codex-only block directly before it.
                self.assertEqual(claude_only_blocks(self.roles[role_id].body), expected_blocks)
                claude_text = resolve(self.roles[role_id].body, "claude")
                position = 0
                for _, lines in expected_blocks:
                    block = "".join(line + "\n" for line in lines)
                    self.assertEqual(claude_text.count(block), 1)
                    found_at = claude_text.find(block)
                    self.assertGreaterEqual(found_at, position)
                    position = found_at + len(block)
                    for term in CODEX_ONLY_TERMS:
                        self.assertNotIn(term, block.lower())


if __name__ == "__main__":
    unittest.main()

"""Model policy: models.toml loading, validation and cross-checks."""

from pathlib import Path
import tempfile
import tomllib
import unittest

from dashboard.team import PROFILES
from team_source.policy import Assignment, PolicyError, load_policy, validate
from team_source.roles import Role

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "team_source" / "models.toml"

CLAUDE_COLUMN = {
    "chief_of_staff": ("opus", "medium"),
    "product_manager": ("opus", "medium"),
    "ui_designer": ("opus", "medium"),
    "frontend_developer": ("opus", "medium"),
    "qa_engineer": ("opus", "medium"),
    "technical_architect": ("opus", "high"),
    "backend_developer": ("opus", "high"),
    "platform_reliability_engineer": ("opus", "high"),
    "security_reviewer": ("opus", "high"),
    "code_quality_reviewer": ("opus", "high"),
    "agent_evaluation_engineer": ("opus", "high"),
    "technical_writer": ("sonnet", "high"),
    "user_documentation_writer": ("sonnet", "medium"),
    "expert_escalation": ("opus", "low"),
}


def make_roles(ids):
    return {i: Role(id=i, description="d", profile="editor", body="b\n") for i in ids}


def make_policy(ids, **overrides):
    """Valid in-memory policy for ids; overrides maps (role, column) to an Assignment."""
    policy = {
        i: {"codex": Assignment("gpt-6.1-sol", "high"), "claude": Assignment("opus", "high")}
        for i in ids
    }
    for (role_id, column), assignment in overrides.items():
        policy[role_id][column] = assignment
    return policy


def load_text(text):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "models.toml"
        path.write_text(text, encoding="utf-8")
        return load_policy(path)


GOOD = (
    '[zeta_role.codex]\nmodel = "gpt-6.1-sol"\neffort = "high"\n'
    '[zeta_role.claude]\nmodel = "opus"\neffort = "high"\n'
)


class RealPolicyTests(unittest.TestCase):
    def test_loads_every_role_with_both_columns(self):
        policy = load_policy(MODELS)
        self.assertEqual(set(policy), set(PROFILES))
        for role_id, columns in policy.items():
            self.assertEqual(set(columns), {"codex", "claude"}, role_id)
            for assignment in columns.values():
                self.assertIsInstance(assignment, Assignment)

    def test_role_ids_must_equal_dashboard_profiles(self):
        policy = load_policy(MODELS)
        validate(make_roles(PROFILES), policy, PROFILES.keys())

    def test_real_policy_passes_validate(self):
        ids = sorted(PROFILES)
        self.assertEqual(len(ids), 14)
        validate(make_roles(ids), load_policy(MODELS), list(PROFILES))

    def test_codex_column_matches_current_agents_files(self):
        policy = load_policy(MODELS)
        files = sorted((ROOT / ".codex" / "agents").glob("*.toml"))
        self.assertEqual(len(files), 14)
        for path in files:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                policy[data["name"]]["codex"],
                Assignment(data["model"], data["model_reasoning_effort"]),
                data["name"],
            )

    def test_claude_column_matches_owner_decision(self):
        policy = load_policy(MODELS)
        actual = {r: (c["claude"].model, c["claude"].effort) for r, c in policy.items()}
        self.assertEqual(actual, CLAUDE_COLUMN)


class ValidateTests(unittest.TestCase):
    ids = ["role_alpha", "role_beta"]

    def check(self, policy, roles=None, profiles=None):
        validate(roles or make_roles(self.ids), policy, profiles or self.ids)

    def error(self, policy, **kwargs):
        with self.assertRaises(PolicyError) as caught:
            self.check(policy, **kwargs)
        return str(caught.exception)

    def test_valid_policy_passes(self):
        self.check(make_policy(self.ids))

    def test_missing_role_in_policy_raises(self):
        message = self.error(make_policy(["role_alpha"]))
        self.assertIn("policy does not match roles", message)
        self.assertIn("missing ['role_beta']", message)
        self.assertIn("extra none", message)

    def test_extra_role_in_policy_raises(self):
        message = self.error(make_policy(["role_alpha", "role_beta", "zeta_role"]))
        self.assertIn("policy does not match roles", message)
        self.assertIn("missing none", message)
        self.assertIn("extra ['zeta_role']", message)

    def test_profiles_mismatch_raises(self):
        message = self.error(make_policy(self.ids), profiles=["role_alpha", "zeta_role"])
        self.assertIn("policy does not match dashboard profiles", message)
        self.assertIn("missing ['zeta_role']", message)
        self.assertIn("extra ['role_beta']", message)

    def test_role_without_column_raises(self):
        policy = make_policy(self.ids)
        del policy["role_beta"]["claude"]
        self.assertIn("role role_beta: column claude is missing", self.error(policy))

    def test_unknown_claude_model_raises(self):
        policy = make_policy(self.ids)
        policy["role_alpha"]["claude"] = Assignment("gpt-6.1-sol", "high")
        self.assertIn(
            "role role_alpha, column claude: model 'gpt-6.1-sol' is not one of",
            self.error(policy),
        )

    def test_unknown_codex_effort_raises(self):
        policy = make_policy(self.ids)
        policy["role_beta"]["codex"] = Assignment("gpt-6.1-sol", "max")
        self.assertIn(
            "role role_beta, column codex: effort 'max' is not one of", self.error(policy)
        )

    def test_unknown_codex_model_raises(self):
        policy = make_policy(self.ids)
        policy["role_alpha"]["codex"] = Assignment("opus", "high")
        self.assertIn(
            "role role_alpha, column codex: model 'opus' is not one of", self.error(policy)
        )

    def test_unknown_claude_effort_raises(self):
        policy = make_policy(self.ids)
        policy["role_beta"]["claude"] = Assignment("opus", "extreme")
        self.assertIn(
            "role role_beta, column claude: effort 'extreme' is not one of", self.error(policy)
        )

    def test_fable_is_a_valid_claude_alias(self):
        policy = make_policy(self.ids)
        policy["role_alpha"]["claude"] = Assignment("fable", "low")
        self.check(policy)

    def test_claude_only_effort_max_is_valid_on_claude(self):
        policy = make_policy(self.ids)
        policy["role_alpha"]["claude"] = Assignment("haiku", "max")
        self.check(policy)


class LoadPolicyErrorTests(unittest.TestCase):
    def raises(self, text):
        with self.assertRaises(PolicyError) as caught:
            load_text(text)
        return str(caught.exception)

    def test_good_text_loads(self):
        self.assertEqual(load_text(GOOD)["zeta_role"]["claude"], Assignment("opus", "high"))

    def test_missing_column_table(self):
        message = self.raises(
            '[zeta_role.codex]\nmodel = "gpt-6.1-sol"\neffort = "high"\n'
        )
        self.assertIn("role zeta_role, column claude: table is missing", message)

    def test_missing_key(self):
        message = self.raises(GOOD.replace('effort = "high"\n[zeta_role.claude]', "[zeta_role.claude]"))
        self.assertIn("role zeta_role, column codex: missing key 'effort'", message)

    def test_non_string_value(self):
        message = self.raises(GOOD.replace('model = "opus"', "model = 5"))
        self.assertIn("role zeta_role, column claude: model must be a string, got 5", message)

    def test_unknown_key(self):
        message = self.raises(GOOD + 'speed = "fast"\n')
        self.assertIn("role zeta_role, column claude: unknown key 'speed'", message)

    def test_unknown_column(self):
        message = self.raises(GOOD + '[zeta_role.gemini]\nmodel = "x"\neffort = "y"\n')
        self.assertIn("role zeta_role: unknown column 'gemini'", message)


if __name__ == "__main__":
    unittest.main()

"""Shared model policy: load models.toml and check it against roles and dashboard profiles."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

COLUMNS = ("codex", "claude")
KEYS = ("model", "effort")
# Codex values match the sets dashboard/native_roles.py enforces.
CODEX_MODELS = frozenset({"gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra"})
CODEX_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})
# Claude values come from the Claude Code docs (Phase 0 finding); only low, medium
# and high have been observed against the live API.
CLAUDE_MODELS = frozenset({"opus", "sonnet", "haiku", "fable"})
CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
ALLOWED = {
    "codex": (CODEX_MODELS, CODEX_EFFORTS),
    "claude": (CLAUDE_MODELS, CLAUDE_EFFORTS),
}


class PolicyError(ValueError):
    """The model policy is malformed or inconsistent with the roles."""


@dataclass(frozen=True)
class Assignment:
    model: str
    effort: str


def _load_column(role_id, column, table):
    where = f"role {role_id}, column {column}"
    if not isinstance(table, dict):
        raise PolicyError(f"{where}: expected a table with model and effort")
    for key in table:
        if key not in KEYS:
            raise PolicyError(f"{where}: unknown key {key!r}")
    for key in KEYS:
        if key not in table:
            raise PolicyError(f"{where}: missing key {key!r}")
        if not isinstance(table[key], str):
            raise PolicyError(f"{where}: {key} must be a string, got {table[key]!r}")
    return Assignment(model=table["model"], effort=table["effort"])


def load_policy(path):
    """Read models.toml into {role id: {"codex": Assignment, "claude": Assignment}}."""
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    policy = {}
    for role_id, columns in data.items():
        if not isinstance(columns, dict):
            raise PolicyError(f"role {role_id}: expected tables named codex and claude")
        for column in columns:
            if column not in COLUMNS:
                raise PolicyError(
                    f"role {role_id}: unknown column {column!r}; expected codex or claude"
                )
        for column in COLUMNS:
            if column not in columns:
                raise PolicyError(f"role {role_id}, column {column}: table is missing")
        policy[role_id] = {
            column: _load_column(role_id, column, columns[column]) for column in COLUMNS
        }
    return policy


def validate(roles, policy, profiles):
    """Check policy ids equal the role ids and the dashboard profiles, and values are allowed."""
    policy_ids = set(policy)
    for label, expected in (("roles", set(roles)), ("dashboard profiles", set(profiles))):
        missing = sorted(expected - policy_ids)
        extra = sorted(policy_ids - expected)
        if missing or extra:
            raise PolicyError(
                f"policy does not match {label}: missing {missing or 'none'}, "
                f"extra {extra or 'none'}"
            )
    for role_id in sorted(policy):
        for column in COLUMNS:
            assignment = policy[role_id].get(column)
            if assignment is None:
                raise PolicyError(f"role {role_id}: column {column} is missing")
            models, efforts = ALLOWED[column]
            if assignment.model not in models:
                raise PolicyError(
                    f"role {role_id}, column {column}: model {assignment.model!r} "
                    f"is not one of {', '.join(sorted(models))}"
                )
            if assignment.effort not in efforts:
                raise PolicyError(
                    f"role {role_id}, column {column}: effort {assignment.effort!r} "
                    f"is not one of {', '.join(sorted(efforts))}"
                )

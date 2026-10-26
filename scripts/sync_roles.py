"""Generate .codex/agents/*.toml and .claude/agents/*.md from team_source, or check them for drift.

Usage: python3 scripts/sync_roles.py [--check]
The optional --root PATH reads and writes another repo skeleton (used by tests only).
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from team_source.policy import load_policy, validate  # noqa: E402
from team_source.roles import load_roles_dir, render_claude, render_codex  # noqa: E402

TARGETS = ((".codex/agents", ".toml"), (".claude/agents", ".md"))


def render_all(root):
    """Render every expected output in memory, keyed by path relative to root."""
    roles = load_roles_dir(root / "team_source" / "roles")
    policy = load_policy(root / "team_source" / "models.toml")
    validate(roles, policy, profiles=roles.keys())
    outputs = {}
    for role_id, role in roles.items():
        codex, claude = policy[role_id]["codex"], policy[role_id]["claude"]
        outputs[f".codex/agents/{role_id}.toml"] = render_codex(role, codex.model, codex.effort)
        outputs[f".claude/agents/{role_id}.md"] = render_claude(
            role, claude.model, claude.effort, coordinator=(role.id == "chief_of_staff")
        )
    return outputs


def sync(root, *, check):
    """Write (or with check=True only compare) the generated files; return the problems found."""
    root = Path(root)
    outputs = {name: text.encode("utf-8") for name, text in render_all(root).items()}
    problems = []
    for name, data in outputs.items():
        path = root / name
        current = path.read_bytes() if path.is_file() else None
        if current == data:
            continue
        if check:
            problems.append(f"{name}: {'missing' if current is None else 'stale'}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    for directory, _suffix in TARGETS:
        folder = root / directory
        if folder.is_dir():
            for entry in sorted(folder.iterdir()):
                if f"{directory}/{entry.name}" not in outputs:
                    problems.append(f"{directory}/{entry.name}: unexpected, not generated from team_source")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 on drift")
    parser.add_argument("--root", type=Path, default=ROOT, help="repo root (tests only)")
    args = parser.parse_args(argv)
    problems = sync(args.root.resolve(), check=args.check)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("role files are in sync" if args.check else "role files written (28 files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

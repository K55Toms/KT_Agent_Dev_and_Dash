"""Generate .codex/agents/*.toml and .claude/agents/*.md from team_source, or check them for drift.

Usage: python3 scripts/sync_roles.py [--check]
The optional --root PATH reads and writes another repo skeleton (used by tests only).
"""

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# Appended, not inserted first: a root-level file such as json.py must not shadow the standard library.
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

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


def unsafe_paths(root, names):
    """Report output locations that are symlinks, not directories, or not regular files.

    Writing through such a path could change a file outside the agent folders, so any
    finding stops the sync before it reads or writes a generated file.
    """
    problems = []
    folders = {top for top, _suffix in TARGETS} | {top.split("/")[0] for top, _suffix in TARGETS}
    for folder in sorted(folders):
        path = root / folder
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            problems.append(f"{folder}: unsafe, symlink or not a directory")
    if problems:
        return problems
    for name in names:
        path = root / name
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or path.resolve().parent != path.parent.resolve():
            problems.append(f"{name}: unsafe, symlink or not a regular file")
    return problems


def default_mode():
    """The mode a plain write would give a new file under the current umask."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def write_atomically(path, data, mode):
    """Write data to a hidden temp file beside path, then rename it over path."""
    # The temp name starts with a dot and ends in .tmp, so a crash cannot leave a loadable role file.
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def sync(root, *, check):
    """Write (or with check=True only compare) the generated files; return the problems found."""
    root = Path(root)
    outputs = {name: text.encode("utf-8") for name, text in render_all(root).items()}
    unsafe = unsafe_paths(root, outputs)
    if unsafe:
        return unsafe
    problems = []
    pending = []
    for name, data in outputs.items():
        path = root / name
        current = path.read_bytes() if path.exists() else None
        if current == data:
            continue
        if check:
            problems.append(f"{name}: {'missing' if current is None else 'stale'}")
        else:
            pending.append((path, data))
    mode = default_mode()
    for path, data in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(path, data, mode)
    for directory, suffix in TARGETS:
        folder = root / directory
        if folder.is_dir():
            for entry in sorted(folder.iterdir()):
                # Other plain files (for example .DS_Store) are not role files and are ignored.
                # The extension test ignores letter case, so Extra.MD is reported too.
                if not (entry.is_dir() or entry.name.lower().endswith(suffix)):
                    continue
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

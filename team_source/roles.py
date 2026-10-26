"""Parse role source Markdown files with codex-only and claude-only blocks."""

from dataclasses import dataclass
import json
from pathlib import Path

HARNESSES = ("codex", "claude")
PROFILES = ("editor", "reviewer")
KEYS = ("id", "description", "profile")
MARKERS = {
    "<!-- codex-only -->": ("open", "codex"),
    "<!-- /codex-only -->": ("close", "codex"),
    "<!-- claude-only -->": ("open", "claude"),
    "<!-- /claude-only -->": ("close", "claude"),
}


class RoleSourceError(ValueError):
    """A role source file is malformed."""


@dataclass(frozen=True)
class Role:
    id: str
    description: str
    profile: str
    body: str


def _lines(text):
    """Split on newline only, keeping each line's newline."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _marker(line):
    return MARKERS.get(line.strip())


def _scan_blocks(lines, where, first_line):
    """Yield (line, harness or None, is_marker) while checking marker balance."""
    current = None
    opened_at = 0
    for number, line in enumerate(lines, start=first_line):
        marker = _marker(line)
        if marker is None:
            yield line, current, False
            continue
        kind, harness = marker
        if kind == "open":
            if current is not None:
                raise RoleSourceError(
                    f"{where}: line {number}: nested {harness}-only block "
                    f"inside {current}-only block opened at line {opened_at}"
                )
            current, opened_at = harness, number
        else:
            if current is None:
                raise RoleSourceError(
                    f"{where}: line {number}: closing {harness}-only marker has no opening marker"
                )
            if current != harness:
                raise RoleSourceError(
                    f"{where}: line {number}: closing {harness}-only marker "
                    f"does not match {current}-only block opened at line {opened_at}"
                )
            current = None
        yield line, current, True
    if current is not None:
        raise RoleSourceError(
            f"{where}: line {opened_at}: {current}-only block is never closed"
        )


def _parse_front_matter(lines, source):
    if not lines or lines[0].strip() != "---":
        raise RoleSourceError(f"{source}: line 1: front matter must start with ---")
    values = {}
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            missing = [key for key in KEYS if key not in values]
            if missing:
                raise RoleSourceError(
                    f"{source}: front matter is missing key(s): {', '.join(missing)}"
                )
            return values, number
        key, separator, raw = line.partition(":")
        if not separator or key.strip() != key or not key:
            raise RoleSourceError(f'{source}: line {number}: expected key: "value"')
        if key not in KEYS:
            raise RoleSourceError(f"{source}: line {number}: unknown key {key!r}")
        if key in values:
            raise RoleSourceError(f"{source}: line {number}: duplicate key {key!r}")
        try:
            value = json.loads(raw)
        except ValueError:
            raise RoleSourceError(
                f"{source}: line {number}: value of {key} is not valid JSON"
            ) from None
        if not isinstance(value, str):
            raise RoleSourceError(f"{source}: line {number}: value of {key} must be a JSON string")
        values[key] = value
    raise RoleSourceError(f"{source}: front matter has no closing ---")


def parse_role(text, source):
    """Parse one role source file; source labels errors (usually the file path)."""
    lines = _lines(text)
    values, end = _parse_front_matter(lines, source)
    if not values["id"]:
        raise RoleSourceError(f"{source}: id must not be empty")
    where = f"{source} (role {values['id']})"
    if values["profile"] not in PROFILES:
        raise RoleSourceError(
            f"{where}: profile must be one of {', '.join(PROFILES)}, got {values['profile']!r}"
        )
    body_lines = lines[end:]
    for _ in _scan_blocks(body_lines, where, end + 1):
        pass
    return Role(
        id=values["id"],
        description=values["description"],
        profile=values["profile"],
        body="".join(body_lines),
    )


def resolve(body, harness):
    """Keep blocks for harness, drop the other harness's blocks and all marker lines."""
    if harness not in HARNESSES:
        raise RoleSourceError(f"unknown harness {harness!r}; expected codex or claude")
    return "".join(
        line
        for line, block, is_marker in _scan_blocks(_lines(body), "body", 1)
        if not is_marker and block in (None, harness)
    )


def load_roles_dir(directory):
    """Parse every *.md file in directory into roles keyed by id."""
    paths = sorted(Path(directory).glob("*.md"))
    if not paths:
        raise RoleSourceError(f"{directory}: no role files (*.md) found")
    roles = {}
    for path in paths:
        role = parse_role(path.read_text(encoding="utf-8"), str(path))
        if role.id != path.stem:
            raise RoleSourceError(
                f"{path}: file name stem {path.stem!r} does not match role id {role.id!r}"
            )
        if role.id in roles:
            raise RoleSourceError(f"{path}: duplicate role id {role.id!r}")
        roles[role.id] = role
    return roles

"""Parse role source Markdown files with codex-only and claude-only blocks."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib

HARNESSES = ("codex", "claude")
PROFILES = ("editor", "reviewer")
KEYS = ("id", "description", "profile")
BARE_VALUE = re.compile(r"[A-Za-z0-9._-]+")
ROLE_ID = re.compile(r"[a-z][a-z0-9_]*")  # used with fullmatch, so a trailing newline fails
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
    if not ROLE_ID.fullmatch(values["id"]):
        # repr() keeps a newline or other control character in the id out of the message layout.
        raise RoleSourceError(
            f"{source}: id {values['id']!r} must match ^[a-z][a-z0-9_]*$ "
            "(a lowercase letter, then lowercase letters, digits or underscores)"
        )
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


def render_codex(role, model, effort):
    """Render a Codex agent TOML file; verify by parsing it back."""
    instructions = resolve(role.body, "codex")
    if '"""' in instructions or "\\" in instructions:
        raise RoleSourceError(
            f"role {role.id}: Codex instructions must not contain a triple quote or backslash"
        )
    expected = {
        "name": role.id,
        "model": model,
        "model_reasoning_effort": effort,
        "description": role.description,
        "developer_instructions": instructions,
    }
    text = (
        f"# Generated from team_source/roles/{role.id}.md and team_source/models.toml"
        " by scripts/sync_roles.py.\n"
        "# Edit those files, then run: python3 scripts/sync_roles.py\n"
    )
    text += "".join(
        f"{key} = {json.dumps(expected[key], ensure_ascii=False)}\n"
        for key in list(expected)[:-1]
    )
    text += f'developer_instructions = """\n{instructions}"""\n'
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RoleSourceError(f"role {role.id}: rendered Codex TOML is invalid: {error}") from None
    if parsed != expected:
        raise RoleSourceError(f"role {role.id}: rendered Codex TOML does not match the role source")
    return text


def render_claude(role, model, effort, *, coordinator):
    """Render a Claude subagent Markdown file; reviewers are read-only, workers cannot delegate."""
    for label, value in (("model", model), ("effort", effort)):
        if not BARE_VALUE.fullmatch(value):
            raise RoleSourceError(
                f"role {role.id}: {label} {value!r} may only use letters, digits, . _ and -"
            )
    lines = [
        "---",
        f"name: {role.id}",
        f"description: {json.dumps(role.description, ensure_ascii=False)}",
        f"model: {model}",
        f"effort: {effort}",
    ]
    expected = ["name", "description", "model", "effort"]
    if role.profile == "reviewer":
        lines.append("tools: Read, Grep, Glob")
        expected.append("tools")
    if not coordinator:
        lines.append("disallowedTools: Agent")
        expected.append("disallowedTools")
    lines.append("---")
    header = "\n".join(lines) + "\n"
    # Parse the front matter back, as render_codex does for TOML: the keys between the two
    # fences must be exactly the expected list, so no value can smuggle in another key.
    rendered = header.split("\n")
    keys = [line.partition(":")[0] for line in rendered[1 : rendered.index("---", 1)]]
    if keys != expected:
        raise RoleSourceError(
            f"role {role.id!r}: rendered Claude front matter keys {keys} do not match {expected}"
        )
    return header + resolve(role.body, "claude")

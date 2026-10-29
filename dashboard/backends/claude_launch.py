"""Claude launch builder: roles, project instructions, child environment and argv.

Pure functions, no process is started here. Error messages are fixed strings; values (prompts,
paths, environment values) are never echoed into them.
"""
import json
import os
import re
import stat
from pathlib import Path
from typing import Mapping, Optional

from team_source.policy import CLAUDE_EFFORTS, CLAUDE_MODELS

MAX_FILE_BYTES = 65536
MAX_PROMPT_CHARS = 16000
MAX_ARGV_BYTES = 900000
ENV_NAMES = frozenset({"PATH", "HOME", "USER", "LANG", "TMPDIR", "SHELL", "TERM"})
ENV_PREFIXES = ("LC_",)
ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")
IMPORT_RE = re.compile(r"^@([^\s@]\S*)$")


def _read_text(path: Path, limit: int, error: str) -> str:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(error)
        data = path.read_bytes()
        if len(data) > limit:
            raise ValueError(error)
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise ValueError(error) from None


def _split_list(value):
    items = [part.strip() for part in value.split(",")]
    return [item for item in items if item] or None


def _parse_role(path: Path) -> dict:
    error = "Invalid role file"
    text = _read_text(path, MAX_FILE_BYTES, error)
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(error)
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError(error)
    fields = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(error)
        key, value = key.strip(), value.strip()
        if key in fields:
            raise ValueError(error)
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValueError(error) from None
            if not isinstance(value, str):
                raise ValueError(error)
        fields[key] = value
    role_id = fields.get("name")
    if role_id != path.stem or not ROLE_RE.match(role_id):
        raise ValueError(error)
    model = fields.get("model")
    effort = fields.get("effort")
    if model not in CLAUDE_MODELS or effort not in CLAUDE_EFFORTS:
        raise ValueError("Invalid role model or effort")
    description = fields.get("description")
    if not description:
        raise ValueError(error)
    body = "\n".join(lines[end + 1:])
    if body.startswith("\n"):
        body = body[1:]
    return {
        "id": role_id,
        "label": role_id.replace("_", " ").title(),
        "model": model,
        "profile_model": model,
        "reasoning": effort,
        "instructions": body,
        "description": description,
        "tools": _split_list(fields["tools"]) if "tools" in fields else None,
        "disallowed_tools": (
            _split_list(fields["disallowedTools"]) if "disallowedTools" in fields else None
        ),
    }


def load_claude_roles(root) -> dict:
    """Read <root>/.claude/agents/*.md into {role_id: role}."""
    directory = Path(root) / ".claude" / "agents"
    roles = {}
    try:
        files = sorted(directory.glob("*.md"))
    except OSError:
        raise ValueError("Invalid role file") from None
    for path in files:
        role = _parse_role(path)
        roles[role["id"]] = role
    return roles


def agents_json(role: Mapping) -> str:
    """The --agents JSON for one role, in the shape proven live."""
    definition = {"description": role["description"], "prompt": role["instructions"]}
    if role.get("tools"):
        definition["tools"] = list(role["tools"])
    definition["model"] = role["model"]
    return json.dumps({role["id"]: definition}, separators=(",", ":"), ensure_ascii=True)


def _check_text(text: str) -> None:
    for char in text:
        if char not in "\n\t" and (ord(char) < 32 or ord(char) == 127):
            raise ValueError("Invalid project instructions")


def expand_project_instructions(project, max_bytes: int = MAX_FILE_BYTES) -> str:
    """Return <project>/CLAUDE.md with exact `@relative/path` lines replaced (one level)."""
    error = "Invalid project instructions"
    project = Path(project)
    main = project / "CLAUDE.md"
    try:
        main.lstat()
    except FileNotFoundError:
        return ""
    except OSError:
        raise ValueError(error) from None
    text = _read_text(main, max_bytes, error)
    _check_text(text)
    try:
        base = project.resolve(strict=True)
    except OSError:
        raise ValueError(error) from None
    out = []
    for line in text.split("\n"):
        match = IMPORT_RE.match(line)
        if not match:
            out.append(line)
            continue
        rel = Path(match.group(1))
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(error)
        target = base / rel
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(base)
        except (OSError, ValueError):
            raise ValueError(error) from None
        imported = _read_text(target, max_bytes, error)
        _check_text(imported)
        out.append(imported.rstrip("\n"))
    return "\n".join(out)


def child_environment(parent: Mapping) -> dict:
    """Keep only the allow-listed names; values are copied unchanged."""
    env = {}
    for name, value in parent.items():
        if not isinstance(name, str) or not isinstance(value, str) or "\0" in value:
            continue
        if name in ENV_NAMES or name.startswith(ENV_PREFIXES):
            env[name] = value
    return env


def build_argv(
    claude_path: str,
    *,
    prompt: str,
    alias: str,
    role_name: str,
    role_json: str,
    instructions: str,
    safety: str,
    effort: Optional[str] = None,
    resume: Optional[str] = None,
) -> list:
    bad = ValueError("Invalid instruction")
    if not isinstance(prompt, str) or "\0" in prompt:
        raise bad
    trimmed = prompt.strip()
    if not trimmed or len(prompt) > MAX_PROMPT_CHARS or prompt.lstrip().startswith("-"):
        raise bad
    if prompt.startswith("-"):
        raise bad
    if not isinstance(claude_path, str) or not claude_path or "\0" in claude_path:
        raise ValueError("Invalid launch arguments")
    if alias not in CLAUDE_MODELS:
        raise ValueError("Invalid launch arguments")
    if not isinstance(role_name, str) or not ROLE_RE.match(role_name):
        raise ValueError("Invalid launch arguments")
    if not isinstance(role_json, str) or "\0" in role_json:
        raise ValueError("Invalid launch arguments")
    if effort is not None and effort not in CLAUDE_EFFORTS:
        raise ValueError("Invalid launch arguments")
    if resume is not None and (not isinstance(resume, str) or not SESSION_RE.match(resume)):
        raise ValueError("Invalid launch arguments")
    if not isinstance(safety, str) or not isinstance(instructions, str):
        raise ValueError("Invalid launch arguments")
    if "\0" in safety or "\0" in instructions:
        raise ValueError("Invalid launch arguments")
    appended = safety + ("\n\n" + instructions if instructions else "")
    argv = [
        claude_path, "-p", prompt, "--output-format", "stream-json", "--verbose",
        "--setting-sources", "user", "--model", alias, "--agents", role_json,
        "--agent", role_name, "--append-system-prompt", appended,
    ]
    if effort is not None:
        argv += ["--effort", effort]
    if resume is not None:
        argv += ["--resume", resume]
    if sum(len(item.encode("utf-8")) + 1 for item in argv) > MAX_ARGV_BYTES:
        raise ValueError("Invalid launch arguments")
    return argv

"""Claude launch builder: roles, project instructions, child environment and argv.

Pure functions, no process is started here. Error messages are fixed strings; values (prompts,
paths, environment values) are never echoed into them.
"""
import json
import os
import re
import secrets
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
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
IMPORT_RE = re.compile(r"^@([^\s@]\S*)$")
RUNS_DIR = "claude-runs"
HOOK_URL_RE = re.compile(r"http://127\.0\.0\.1:([0-9]{1,5})/hook/managed/([A-Za-z0-9_-]{1,128})\Z")


def _read_text(path: Path, limit: int, error: str) -> str:
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(error)
        chunks, total = [], 0
        while total <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > limit:
            raise ValueError(error)
        return b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise ValueError(error) from None
    finally:
        if fd is not None:
            os.close(fd)


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
    if not description or not description.strip():
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
    """Read <root>/.claude/agents/*.md into {role_id: role}.

    Dotfiles are skipped. Role files with a BOM are refused (front matter must start with ---).
    """
    directory = Path(root) / ".claude" / "agents"
    roles = {}
    try:
        files = sorted(p for p in directory.glob("*.md") if not p.name.startswith("."))
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
    """Return <project>/CLAUDE.md with exact `@relative/path` lines replaced (one level).

    Project files are trusted project content. The expansion is line based, so an import inside
    a fenced code block is expanded too. Paths with a dotfile component are refused. CRLF files
    are refused by the control character rule (\r).
    """
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
        if rel.is_absolute() or any(part.startswith(".") for part in rel.parts):
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
    settings_path: Optional[Path] = None,
) -> list:
    bad = ValueError("Invalid instruction")
    if not isinstance(prompt, str) or "\0" in prompt:
        raise bad
    if not isinstance(alias, str):
        raise ValueError("Invalid launch arguments")
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
    if not isinstance(role_json, str) or "\0" in role_json or not role_json.startswith("{"):
        raise ValueError("Invalid launch arguments")
    if effort is not None and effort not in CLAUDE_EFFORTS:
        raise ValueError("Invalid launch arguments")
    if resume is not None and (not isinstance(resume, str) or not SESSION_RE.match(resume)):
        raise ValueError("Invalid launch arguments")
    if not isinstance(safety, str) or not safety.strip() or safety.startswith("-"):
        raise ValueError("Invalid launch arguments")
    if not isinstance(instructions, str):
        raise ValueError("Invalid launch arguments")
    if "\0" in safety or "\0" in instructions:
        raise ValueError("Invalid launch arguments")
    if settings_path is not None:
        text = str(settings_path)
        if (not isinstance(settings_path, Path) or not settings_path.is_absolute() or "\0" in text
                or text.startswith("-")):
            raise ValueError("Invalid launch arguments")
    appended = safety + ("\n\n" + instructions if instructions else "")
    argv = [
        claude_path, "-p", prompt, "--output-format", "stream-json", "--verbose",
        "--setting-sources", "user",
    ]
    if settings_path is not None:
        argv += ["--settings", str(settings_path)]
    argv += [
        "--model", alias, "--agents", role_json,
        "--agent", role_name, "--append-system-prompt", appended,
    ]
    if effort is not None:
        argv += ["--effort", effort]
    if resume is not None:
        argv += ["--resume", resume]
    if sum(len(item.encode("utf-8")) + 1 for item in argv) > MAX_ARGV_BYTES:
        raise ValueError("Invalid launch arguments")
    return argv


def _runs_dir(state_dir) -> Path:
    base = Path(state_dir)
    runs = base / RUNS_DIR
    try:
        os.mkdir(runs, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(runs)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Invalid settings location")
    os.chmod(runs, 0o700)
    return runs


def write_run_settings(state_dir, url: str, timeout: int) -> Path:
    """Write the per-run --settings file: exactly one PermissionRequest http hook, nothing else.

    The file is 0600 in a 0700 ``claude-runs`` folder, written through a temp file and renamed. The
    URL (which carries the run token) is never echoed into an error.
    """
    match = HOOK_URL_RE.match(url) if isinstance(url, str) else None
    if match is None or not 1 <= int(match.group(1)) <= 65535:
        raise ValueError("Invalid hook url")
    if type(timeout) is not int or timeout < 1:
        raise ValueError("Invalid hook timeout")
    body = json.dumps(
        {"hooks": {"PermissionRequest": [{"hooks": [{"type": "http", "url": url, "timeout": timeout}]}]}},
        sort_keys=True, separators=(",", ":")) + "\n"
    try:
        runs = _runs_dir(state_dir)
        name = "run-" + secrets.token_hex(12) + ".json"
        temporary = runs / (".tmp-" + name)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            final = runs / name
            os.replace(temporary, final)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return final
    except OSError:
        raise ValueError("Invalid settings location") from None


def remove_run_settings(path) -> None:
    """Delete a settings file made by write_run_settings. Idempotent; refuses anything else."""
    error = ValueError("Invalid settings path")
    if not isinstance(path, (str, Path)):
        raise error
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.parent.name != RUNS_DIR:
        raise error
    if not re.fullmatch(r"run-[0-9a-f]{24}\.json", path.name):
        raise error
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError:
        raise error from None
    if not stat.S_ISREG(info.st_mode):
        raise error
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        raise error from None

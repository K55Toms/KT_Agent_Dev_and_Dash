"""Bounded, read-only previews of Git-visible source files in registered projects."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import selectors
import shutil
import stat
import subprocess
import tempfile
import time

from scripts.security_check import CONFIG, VERSION, forbidden

MAX_FILE_BYTES = 256 * 1024
MAX_GIT_BYTES = 2 * 1024 * 1024
MAX_FILES = 1000
MAX_CANDIDATES = 5000
CONFIG_DIGEST = "3eee5ec1b4b3490c08544dd1c38c6f98245679a8018a797315f65239e0b9f29f"
EXCLUDED_PARTS = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules",
                  "dist", "build", "coverage", ".next", ".cache", "target", ".pytest_cache"}


class FileAccessError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class SensitiveContentError(FileAccessError):
    """The reviewed scanner completed and returned its findings-only exit code."""
    def __init__(self):
        super().__init__(403, "Preview blocked: sensitive-content findings. No content has been returned.")


def checked_path(value):
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096
            or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise FileAccessError(400, "Choose a valid relative source-file path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).is_absolute():
        raise FileAccessError(400, "Absolute paths and traversal are forbidden")
    if forbidden(value) or any(part.lower() in EXCLUDED_PARTS for part in parts):
        raise FileAccessError(403, "Credential, runtime and build paths cannot be browsed")
    return parts


@contextmanager
def root_descriptor(root):
    root = Path(root)
    if not root.is_absolute():
        raise FileAccessError(403, "Registered project root is unavailable")
    if forbidden(root.as_posix()) or any(part.lower() in EXCLUDED_PARTS for part in root.parts):
        raise FileAccessError(403, "Credential, runtime and build roots cannot be browsed")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.parts[1:]:
            next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor
    except OSError:
        raise FileAccessError(403, "Project paths must be existing directories without symbolic links") from None
    finally:
        os.close(descriptor)


@contextmanager
def source_descriptor(root_fd, parts):
    parent = os.dup(root_fd)
    target = None
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        target = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(target)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise FileAccessError(403, "Only regular source files without hardlinks may be previewed")
        yield target, info
    except OSError:
        raise FileAccessError(403, "Source file is unavailable or contains an unsafe link") from None
    finally:
        if target is not None:
            os.close(target)
        os.close(parent)


def _bounded_command(argv, cwd, env, data=None, maximum=MAX_GIT_BYTES, timeout=8):
    """Bound output while draining it; never collect stderr or invoke a shell."""
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if data else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise FileAccessError(503, "Required local file-review tooling is unavailable") from None
    output = bytearray()
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    remaining = memoryview(data or b"")
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        if data:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
        while selector.get_map():
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise FileAccessError(503, "Local file review exceeded its time limit")
            for key, _events in selector.select(min(wait, 1)):
                if key.fileobj is process.stdout:
                    chunk = os.read(process.stdout.fileno(), min(65536, maximum + 1 - len(output)))
                    if not chunk:
                        selector.unregister(process.stdout)
                    else:
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise FileAccessError(503, "Project file listing exceeds the safe output limit")
                else:
                    try:
                        written = os.write(process.stdin.fileno(), remaining[:65536])
                        remaining = remaining[written:]
                    except BrokenPipeError:
                        remaining = memoryview(b"")
                    if not remaining:
                        selector.unregister(process.stdin)
                        process.stdin.close()
        try:
            code = process.wait(timeout=max(.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise FileAccessError(503, "Local file review exceeded its time limit") from None
        return code, bytes(output)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stdout.close()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()


def _git(root, *args, data=None):
    # Ignore ambient Git injection and global/system config; project ignore rules remain active.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    # check-ignore takes literal filenames and rejects Git's literal-pathspecs mode.
    literal = ["--literal-pathspecs"] if args and args[0] == "ls-files" else []
    return _bounded_command(["git", "--no-optional-locks", *literal, "-c", "core.fsmonitor=false",
                             "-c", "core.untrackedCache=false", *args], root, env, data=data)


def _worktree(root):
    code, output = _git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or output.strip() != b"true":
        raise FileAccessError(422, "File browsing requires a Git working tree. Register an existing Git project or initialize Git locally first.")


def _visible(root, paths):
    if not paths:
        return set()
    data = b"\0".join(path.encode("utf-8") for path in paths) + b"\0"
    code, output = _git(root, "check-ignore", "--no-index", "--stdin", "-z", data=data)
    if code not in (0, 1):
        raise FileAccessError(503, "Git ignore policy could not be verified")
    ignored = set(output.split(b"\0"))
    return {path for path in paths if path.encode("utf-8") not in ignored}


def _same_root(root, root_fd):
    try:
        current = os.stat(root, follow_symlinks=False)
        opened = os.fstat(root_fd)
        if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
            return
    except OSError:
        pass
    raise FileAccessError(403, "Registered project directory changed during file review")


def list_files(root):
    with root_descriptor(root) as root_fd:
        _worktree(root)
        code, output = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if code != 0:
            raise FileAccessError(503, "Git-visible source files could not be listed")
        _same_root(root, root_fd)
        raw_paths = output.split(b"\0")
        candidates = []
        truncated = len(raw_paths) - 1 > MAX_CANDIDATES
        for raw in raw_paths[:MAX_CANDIDATES]:
            if not raw:
                continue
            try:
                path = raw.decode("utf-8")
                checked_path(path)
                candidates.append(path)
            except (UnicodeError, FileAccessError):
                continue
        visible = _visible(root, candidates)
        files = []
        for path in sorted(set(candidates)):
            if path not in visible:
                continue
            try:
                with source_descriptor(root_fd, checked_path(path)) as (_descriptor, info):
                    files.append({"path": path, "size": info.st_size})
            except FileAccessError:
                continue
            if len(files) > MAX_FILES:
                truncated = True
                break
        _same_root(root, root_fd)
        return {"files": files[:MAX_FILES], "limit_reached": truncated}


def scan_preview(data):
    try:
        descriptor = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
                raise FileAccessError(503, "Preview blocked: secret scanner configuration requires review")
            configuration = os.read(descriptor, 65537)
            if hashlib.sha256(configuration).hexdigest() != CONFIG_DIGEST:
                raise FileAccessError(503, "Preview blocked: secret scanner configuration requires review")
        finally:
            os.close(descriptor)
    except OSError:
        raise FileAccessError(503, "Preview blocked: secret scanner configuration is unavailable") from None
    executable = shutil.which("gitleaks")
    if not executable:
        raise FileAccessError(503, "Preview blocked: the reviewed secret scanner is unavailable")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GITLEAKS_")}
    with tempfile.TemporaryDirectory(prefix="dashboard-preview-scan-") as control:
        policy = Path(control) / "policy.toml"
        policy.write_bytes(configuration)
        code, version = _bounded_command([executable, "version"], control, env, maximum=1024, timeout=5)
        if code != 0 or version.strip() != VERSION.encode("ascii"):
            raise FileAccessError(503, "Preview blocked: secret scanner version requires review")
        try:
            result = subprocess.run([
                executable, "stdin", "--config", str(policy), "--redact=100", "--no-banner", "--no-color",
                "--ignore-gitleaks-allow", "--gitleaks-ignore-path", control, "--exit-code", "42",
                "--max-decode-depth", "5", "--max-archive-depth", "3", "--timeout", "10",
            ], cwd=control, env=env, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
        except (OSError, subprocess.TimeoutExpired):
            raise FileAccessError(503, "Preview blocked: secret scanning could not complete") from None
        if result.returncode == 42:
            raise SensitiveContentError()
        if result.returncode != 0:
            raise FileAccessError(503, "Preview blocked: secret scanning could not complete")


def preview_file(root, path):
    parts = checked_path(path)
    with root_descriptor(root) as root_fd:
        _worktree(root)
        code, output = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", path)
        if code != 0:
            raise FileAccessError(503, "Git-visible source policy could not be verified")
        if path.encode("utf-8") not in output.split(b"\0"):
            raise FileAccessError(404, "File is not a Git-visible source file")
        if path not in _visible(root, [path]):
            raise FileAccessError(403, "Ignored source files cannot be previewed, even when tracked")
        _same_root(root, root_fd)
        with source_descriptor(root_fd, parts) as (descriptor, info):
            if info.st_size > MAX_FILE_BYTES:
                raise FileAccessError(413, "Preview exceeds the 256 KiB text-file limit")
            chunks = bytearray()
            while len(chunks) <= MAX_FILE_BYTES:
                chunk = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if len(chunks) > MAX_FILE_BYTES:
                raise FileAccessError(413, "Preview exceeds the 256 KiB text-file limit")
        data = bytes(chunks)
        try:
            content = data.decode("utf-8")
        except UnicodeError:
            raise FileAccessError(415, "Only UTF-8 text files can be previewed") from None
        if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in content):
            raise FileAccessError(415, "Binary and control-character content cannot be previewed")
        scan_preview(data)
        _same_root(root, root_fd)
        return {"path": path, "content": content, "line_count": len(content.splitlines()), "size": len(data)}

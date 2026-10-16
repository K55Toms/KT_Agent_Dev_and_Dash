"""Bounded Git status and explicit, scanned publication of an already committed SHA.

Never stages, commits, fetches, or returns Git/scanner diagnostics. Repository creation
is a separate explicit operation and never uploads source.
The server must also exclude overlapping managed runs during publication.
"""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time

from scripts.security_check import CONFIG, VERSION, forbidden
from .project_files import EXCLUDED_PARTS, FileAccessError, root_descriptor

CONFIG_DIGEST = "3eee5ec1b4b3490c08544dd1c38c6f98245679a8018a797315f65239e0b9f29f"
MAX_OUTPUT = 8 * 1024 * 1024
MAX_CHANGES = 5000
MAX_COMMITS = 2000
MAX_OBJECTS = 100000
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
REPOSITORY_NAME = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}\Z")
GITHUB = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})\Z"
)


class GitServiceError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def _environment(scan=False):
    # Authentication remains Git's own responsibility; never inspect credential stores.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("GIT_", "GITLEAKS_"))}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    if scan:
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="core.fsmonitor", GIT_CONFIG_VALUE_0="false",
                   GIT_CONFIG_KEY_1="core.untrackedCache", GIT_CONFIG_VALUE_1="false",
                   GIT_CONFIG_KEY_2="log.showSignature", GIT_CONFIG_VALUE_2="false")
    return env


def _creation_environment():
    # Authentication stays CLI-owned. Never inspect or copy credentials into config.
    env = _environment()
    for key in tuple(env):
        if ((key.startswith("GH_") and key not in {"GH_TOKEN", "GH_CONFIG_DIR"})
                or key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}):
            del env[key]
    env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat", NO_COLOR="1")
    return env


def _bounded(argv, root, env, data=None, maximum=MAX_OUTPUT, timeout=10):
    """Discard stderr and bound stdout, stdin, time, and descendant lifetime."""
    try:
        process = subprocess.Popen(argv, cwd=root, env=env, start_new_session=True,
                                   stdin=subprocess.PIPE if data else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise GitServiceError(503, "Required Git publication tooling is unavailable") from None
    deadline = time.monotonic() + timeout
    output = bytearray()
    remaining = memoryview(data or b"")
    selector = selectors.DefaultSelector()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        if data:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
        while selector.get_map():
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise GitServiceError(503, "Git operation exceeded its safe time limit; publication outcome may be unknown")
            for key, _events in selector.select(min(wait, 1)):
                if key.fileobj is process.stdout:
                    chunk = os.read(process.stdout.fileno(), min(65536, maximum + 1 - len(output)))
                    if not chunk:
                        selector.unregister(process.stdout)
                    else:
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise GitServiceError(503, "Git operation exceeded its safe output limit")
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
            raise GitServiceError(503, "Git operation exceeded its safe time limit; publication outcome may be unknown") from None
        return code, bytes(output)
    finally:
        selector.close()
        # A finished parent can leave descendants holding pipes or running helpers.
        # Each command owns its separate process group, which must not outlive it.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait(timeout=3)
        process.stdout.close()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()


def _text(data):
    try:
        value = data.decode("utf-8").strip()
    except UnicodeError:
        return None
    if len(value) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _safe_remote(value):
    if not isinstance(value, str):
        return None
    match = GITHUB.fullmatch(value)
    if not match:
        return None
    name = match[2].removesuffix(".git")
    if not name or name in (".", ".."):
        return None
    return match[1] + "/" + name


def _visible_path(raw):
    try:
        path = raw.decode("utf-8")
    except UnicodeError:
        return None
    parts = path.split("/")
    if (not path or len(raw) > 4096 or "\\" in path or PurePosixPath(path).is_absolute()
            or any(part in ("", ".", "..") for part in parts)
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or forbidden(path) or any(part.lower() in EXCLUDED_PARTS for part in parts)):
        return None
    return path


class GitService:
    def __init__(self, runner=None):
        self._run = runner or _bounded
        self._publish_lock = threading.Lock()

    def _git(self, root, *args, data=None, timeout=10, maximum=MAX_OUTPUT):
        return self._run(["git", "--no-pager", "--no-optional-locks", "--no-replace-objects", "--no-lazy-fetch",
                          "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                          "-c", "log.showSignature=false",
                          *args], root, _environment(), data=data, timeout=timeout, maximum=maximum)

    def _require(self, root, *args, **kwargs):
        code, output = self._git(root, *args, **kwargs)
        if code != 0:
            raise GitServiceError(503, "Git state could not be verified safely")
        return output

    def _config(self, root, name, regexp=False):
        args = ("config", "--null", "--get-regexp" if regexp else "--get-all", name)
        code, output = self._git(root, *args)
        if code not in (0, 1):
            raise GitServiceError(503, "Git destination configuration could not be verified")
        return output.split(b"\0")[:-1] if code == 0 else []

    def _config_names(self, root, pattern, local=False):
        args = ["config", "--null", "--name-only"]
        if local:
            args.extend(("--local", "--includes"))
        code, output = self._git(root, *args, "--get-regexp", pattern)
        if code not in (0, 1):
            raise GitServiceError(503, "Git execution settings could not be verified")
        return output.split(b"\0")[:-1] if code == 0 else []

    def _guard_read_config(self, root):
        # Even read-only `git status` executes clean/process filters on modified files.
        # Reject configured drivers before status, without reading file content or commands.
        if self._config_names(root, r"^filter\..*\.(clean|process)$"):
            raise GitServiceError(403, "Git status is unavailable: configured clean/process filters require independent review")
        index = self._require(root, "ls-files", "--stage", "-z")
        if any(entry.startswith(b"160000 ") for entry in index.split(b"\0")):
            raise GitServiceError(403, "Git status is unavailable: submodule execution requires independent review")

    def _destination(self, root):
        urls = self._config(root, "remote.origin.url")
        pushes = self._config(root, "remote.origin.pushurl")
        if len(urls) != 1 or (pushes and pushes != urls):
            return None, None, "Configure one matching GitHub origin fetch/push URL locally before publishing"
        remote = _text(urls[0])
        repository = _safe_remote(remote)
        if not repository or (remote and remote.encode("utf-8") != urls[0]):
            return None, None, "Origin must be a GitHub HTTPS or git@github.com SSH URL without embedded credentials"
        for entry in self._config(root, r"^url\..*\.(insteadof|pushinsteadof)$", regexp=True):
            _key, separator, prefix = entry.partition(b"\n")
            if not separator or remote.encode("utf-8").startswith(prefix):
                return remote, repository, "An applicable Git URL rewrite must be reviewed and removed before publishing"
        # A URL-shaped configured remote name could otherwise resolve as a remote alias.
        if self._config_names(root, "^remote\\." + re.escape(remote) + r"\."):
            return remote, repository, "An ambiguous Git remote alias prevents verified publication"
        if self._config_names(root, r"^(core\.(sshcommand|gitproxy)|ssh\.variant|remote\..*\.(vcs|receivepack|uploadpack|proxy)|(http|https)(\..*)?\.(proxy|followredirects|sslverify|curloptresolve)|push\.(pushoption|gpgsign))$"):
            return remote, repository, "Custom Git transport or push settings require independent review before publishing"
        if self._config_names(root, r"^credential\.", local=True):
            return remote, repository, "Repository-local credential settings require independent review before publishing"
        if not remote.startswith("https://"):
            return remote, repository, "Dashboard publication requires a GitHub HTTPS origin; SSH configuration cannot be verified without reading private user settings"
        return remote, repository, None

    def _creation_reason(self, root, remote=None):
        # Any origin setting counts as existing, even an empty URL or push-only origin.
        if self._config_names(root, r"^remote\.origin\."):
            return "An origin is already configured; repository creation will not change it"
        if self._config_names(root, r"^(core\.(sshcommand|gitproxy)|ssh\.variant|remote\..*\.(vcs|receivepack|uploadpack|proxy)|(http|https)(\..*)?\.(proxy|followredirects|sslverify|curloptresolve)|push\.(pushoption|gpgsign))$"):
            return "Custom Git transport settings require independent review before repository creation"
        if self._config_names(root, r"^credential\.", local=True):
            return "Repository-local credential settings require independent review before repository creation"
        for entry in self._config(root, r"^url\..*\.(insteadof|pushinsteadof)$", regexp=True):
            _key, separator, prefix = entry.partition(b"\n")
            if not separator or (remote and remote.encode("utf-8").startswith(prefix)) or not remote:
                return "Git URL rewrites require independent review before repository creation"
        if remote and self._config_names(root, "^remote\\." + re.escape(remote) + r"\."):
            return "An ambiguous Git remote alias prevents verified repository creation"
        return None

    @staticmethod
    def _unchanged_root(root, descriptor):
        try:
            opened, current = os.fstat(descriptor), os.stat(root, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino):
                return
        except OSError:
            pass
        raise GitServiceError(403, "Registered project directory changed during Git review")

    def status(self, project_path):
        root = Path(project_path)
        try:
            with root_descriptor(root) as descriptor:
                result = self._status(root)
                self._unchanged_root(root, descriptor)
                return result
        except FileAccessError as error:
            raise GitServiceError(error.status, str(error)) from None

    def _status(self, root):
        result = {"is_repository": False, "branch": None, "head": None, "remote": None,
                  "repository": None, "upstream": None, "ahead": None, "behind": None,
                  "changes": [], "counts": {"staged": 0, "modified": 0, "untracked": 0},
                  "hidden_changes": 0, "clean": False, "can_publish": False,
                  "can_create_repository": False,
                  "create_repository_reason": "This registered directory is not a Git working-tree root",
                  "reason": "This registered directory is not a Git working-tree root",
                  "last_checked": datetime.now(timezone.utc).isoformat()}
        code, inside = self._git(root, "rev-parse", "--is-inside-work-tree")
        if code != 0 or inside.strip() != b"true":
            return result
        toplevel = _text(self._require(root, "rev-parse", "--show-toplevel"))
        if not toplevel or Path(toplevel).resolve() != root:
            return result
        result["is_repository"] = True
        self._guard_read_config(root)
        creation_reason = self._creation_reason(root)
        result.update(can_create_repository=creation_reason is None, create_repository_reason=creation_reason)
        code, branch = self._git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        branch = _text(branch) if code == 0 else None
        if branch:
            code, _unused = self._git(root, "check-ref-format", "refs/heads/" + branch)
            if code != 0:
                branch = None
        result["branch"] = branch
        code, head = self._git(root, "rev-parse", "--verify", "HEAD^{commit}")
        head = _text(head) if code == 0 else None
        result["head"] = head if head and SHA.fullmatch(head) else None
        remote, repository, destination_error = self._destination(root)
        result.update(remote=remote, repository=repository)
        raw = self._require(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                            "--no-renames", "--ignore-submodules=none")
        entries = [entry for entry in raw.split(b"\0") if entry]
        if len(entries) > MAX_CHANGES:
            raise GitServiceError(503, "Git changes exceed the safe listing limit")
        paths = []
        for entry in entries:
            if len(entry) < 4 or entry[2:3] != b" ":
                raise GitServiceError(503, "Git change data is unsupported")
            path = _visible_path(entry[3:])
            if path is None:
                result["hidden_changes"] += 1
            else:
                paths.append((path, entry[:2]))
        ignored = set()
        if paths:
            data = b"\0".join(path.encode("utf-8") for path, _status in paths) + b"\0"
            code, output = self._git(root, "check-ignore", "--no-index", "--stdin", "-z", data=data)
            if code not in (0, 1):
                raise GitServiceError(503, "Git ignore policy could not be verified")
            ignored = set(output.split(b"\0"))
        for path, status in paths:
            if path.encode("utf-8") in ignored:
                result["hidden_changes"] += 1
                continue
            try:
                label = status.decode("ascii")
            except UnicodeError:
                raise GitServiceError(503, "Git change data is unsupported") from None
            result["changes"].append({"path": path, "status": label})
            if label == "??":
                result["counts"]["untracked"] += 1
            else:
                result["counts"]["staged"] += int(label[0] != " ")
                result["counts"]["modified"] += int(label[1] != " ")
        result["clean"] = not entries
        if branch and result["head"]:
            code, output = self._git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
            if code == 0:
                result["upstream"] = _text(output)
                code, output = self._git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
                if code == 0 and re.fullmatch(rb"\d+\s+\d+\s*", output):
                    result["ahead"], result["behind"] = map(int, output.split())
        shallow = self._require(root, "rev-parse", "--is-shallow-repository").strip()
        if not result["head"]:
            reason = "Create a reviewed commit locally before publishing"
        elif not branch:
            reason = "Detached HEAD cannot be published; select a local branch first"
        elif not result["clean"]:
            reason = "Review and commit or remove local changes before publishing; the dashboard does not stage or commit"
        elif shallow != b"false":
            reason = "Shallow history cannot pass the full-history publication policy"
        else:
            reason = destination_error
        result.update(can_publish=reason is None, reason=reason)
        return result

    def _scan(self, root, head):
        executable = shutil.which("gitleaks")
        if not executable:
            raise GitServiceError(503, "Publication blocked: the reviewed secret scanner is unavailable")
        descriptor = None
        try:
            descriptor = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
                raise GitServiceError(503, "Publication blocked: secret-scanner policy requires review")
            policy = os.read(descriptor, 65537)
            if hashlib.sha256(policy).hexdigest() != CONFIG_DIGEST:
                raise GitServiceError(503, "Publication blocked: secret-scanner policy requires review")
        except OSError:
            raise GitServiceError(503, "Publication blocked: secret-scanner policy is unavailable") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        deadline = time.monotonic() + 90

        def remaining():
            duration = deadline - time.monotonic()
            if duration <= 0:
                raise GitServiceError(503, "Publication blocked: full-history security checks exceeded their time limit")
            return min(20, duration)

        graft = _text(self._require(root, "rev-parse", "--git-path", "info/grafts", timeout=remaining()))
        if not graft or (root / graft).exists():
            raise GitServiceError(403, "Publication blocked: grafted history requires independent review")
        commits = self._require(root, "rev-list", "--all", head, "--", timeout=remaining()).splitlines()
        if len(commits) > MAX_COMMITS or not commits or any(not SHA.fullmatch(item.decode("ascii", "replace")) for item in commits):
            raise GitServiceError(503, "Publication blocked: history exceeds the supported full-review limit")
        # Inspect all historical filenames/modes before reading any source or message content.
        for commit in commits:
            tree = self._require(root, "ls-tree", "-r", "-z", commit.decode("ascii"), timeout=remaining())
            for entry in filter(None, tree.split(b"\0")):
                metadata, separator, path = entry.partition(b"\t")
                if not separator:
                    raise GitServiceError(503, "Publication blocked: historical file metadata is unsupported")
                name = _visible_path(path)
                if (name is None or forbidden(name) or metadata.split()[0] not in (b"100644", b"100755")):
                    raise GitServiceError(403, "Publication blocked: a forbidden historical path, link, or submodule requires review; no content was displayed")
        with tempfile.TemporaryDirectory(prefix="dashboard-publish-scan-") as control:
            env = _environment(scan=True)
            # Use an immutable-for-this-run copy of the exact reviewed bytes.
            policy_file = Path(control) / "policy.toml"
            policy_file.write_bytes(policy)
            code, version = self._run([executable, "version"], control, env, timeout=remaining(), maximum=1024)
            if code != 0 or version.strip() != VERSION.encode("ascii"):
                raise GitServiceError(503, "Publication blocked: secret-scanner version requires review")

            def scan(*args, data=None):
                command = [executable, *args, "--config", str(policy_file), "--redact=100", "--no-banner", "--no-color",
                           "--ignore-gitleaks-allow", "--gitleaks-ignore-path", control,
                           "--max-decode-depth", "5", "--max-archive-depth", "3", "--timeout", "20"]
                code, _discard = self._run(command, control, env, data=data, timeout=remaining(), maximum=1024)
                if code != 0:
                    raise GitServiceError(403, "Publication blocked: possible sensitive content or scanner error; no content was displayed")

            scan("git", str(root), "--log-opts=--all --full-history --no-ext-diff --no-textconv " + head)
            scan("stdin", data=self._require(root, "log", "--all", "--format=%B", head, "--", timeout=remaining()))
            objects = self._require(root, "rev-list", "--objects", "--all", head, "--", timeout=remaining()).splitlines()
            if len(objects) > MAX_OBJECTS:
                raise GitServiceError(503, "Publication blocked: object inventory exceeds the safe review limit")
            ids = [entry.split(b" ", 1)[0] for entry in objects]
            if any(not SHA.fullmatch(item.decode("ascii", "replace")) for item in ids):
                raise GitServiceError(503, "Publication blocked: object inventory is unsupported")
            types = self._require(root, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                                  data=b"\n".join(ids) + b"\n", timeout=remaining()).splitlines()
            if len(types) != len(ids):
                raise GitServiceError(503, "Publication blocked: object inventory could not be verified")
            blob_batch = bytearray()
            for entry in types:
                oid, separator, kind = entry.partition(b" ")
                if not separator or kind not in (b"tag", b"commit", b"tree", b"blob"):
                    raise GitServiceError(503, "Publication blocked: historical objects are unavailable")
                if kind in (b"blob", b"commit", b"tag"):
                    # Git attributes may suppress diffs for arbitrary files. Scan every raw
                    # reachable blob independently of Git's diff/text/binary classification.
                    blob = self._require(root, "cat-file", kind.decode("ascii"), oid.decode("ascii"), timeout=remaining())
                    if blob_batch and len(blob_batch) + len(blob) + 2 > MAX_OUTPUT:
                        scan("stdin", data=bytes(blob_batch))
                        blob_batch.clear()
                    blob_batch.extend(b"\n" + blob + b"\n")
            if blob_batch:
                scan("stdin", data=bytes(blob_batch))

    def create_repository(self, project_path, data):
        if (not isinstance(data, dict) or set(data) != {"owner", "name", "visibility", "confirmed"}
                or data.get("confirmed") is not True
                or not isinstance(data.get("owner"), str) or not OWNER.fullmatch(data["owner"])
                or "--" in data["owner"]
                or not isinstance(data.get("name"), str) or not REPOSITORY_NAME.fullmatch(data["name"])
                or not re.search(r"[A-Za-z0-9]", data["name"])
                or data["name"].lower().endswith(".git")
                or data.get("visibility") not in ("public", "private")):
            raise GitServiceError(400, "Confirm a valid GitHub owner, repository name, and public or private visibility")
        executable = shutil.which("gh")
        if not executable:
            raise GitServiceError(503, "Repository creation requires the installed GitHub CLI; authenticate locally outside the dashboard")
        repository = data["owner"] + "/" + data["name"]
        remote = "https://github.com/" + repository + ".git"
        root = Path(project_path)
        with self._publish_lock:
            try:
                with root_descriptor(root) as descriptor:
                    first = self._status(root)
                    if not first["can_create_repository"] or self._creation_reason(root, remote):
                        raise GitServiceError(409, "Repository creation is unavailable; refresh Git status and review the existing origin or Git configuration")
                    self._unchanged_root(root, descriptor)
                    # No project cwd, --source, --clone, or --push: this creates an empty
                    # remote only. An uncertain remote outcome must never be replayed.
                    try:
                        with tempfile.TemporaryDirectory(prefix="dashboard-create-") as isolated:
                            code, _discard = self._run(
                                [executable, "repo", "create", repository, "--" + data["visibility"]],
                                Path(isolated), _creation_environment(), timeout=60, maximum=65536)
                    except GitServiceError:
                        raise GitServiceError(502, "Repository creation outcome is unknown; verify the exact repository on GitHub before retrying. No source was uploaded.") from None
                    if code != 0:
                        raise GitServiceError(502, "Repository creation did not report success; verify the exact repository on GitHub before retrying. No source was uploaded.")
                    result = {"created": True, "attached": False, "repository": repository,
                              "remote": remote, "visibility": data["visibility"], "status": None}
                    # After creation a local race/failure is a partial success. Never
                    # delete the remote, overwrite a newly added origin, or create again.
                    try:
                        self._unchanged_root(root, descriptor)
                        current = self._status(root)
                        if not current["can_create_repository"] or self._creation_reason(root, remote):
                            raise GitServiceError(409, "Origin or Git configuration changed")
                        code, _discard = self._git(root, "remote", "add", "origin", remote)
                        if code != 0:
                            raise GitServiceError(409, "Origin could not be attached")
                        self._unchanged_root(root, descriptor)
                        result["status"] = self._status(root)
                        result["attached"] = result["status"]["remote"] == remote
                    except GitServiceError:
                        pass
                    if not result["attached"]:
                        result["warning"] = "The empty GitHub repository was created, but origin could not be verified. Review the local origin manually; do not repeat repository creation. No source was uploaded."
                    return result
            except FileAccessError as error:
                raise GitServiceError(error.status, str(error)) from None

    def publish(self, project_path, data):
        if (not isinstance(data, dict) or set(data) != {"head", "branch", "remote", "confirmed"}
                or data.get("confirmed") is not True
                or not isinstance(data.get("head"), str) or not SHA.fullmatch(data["head"])
                or not isinstance(data.get("branch"), str) or not data["branch"]
                or len(data["branch"]) > 1024 or not _safe_remote(data.get("remote"))):
            raise GitServiceError(400, "Confirm the exact reviewed commit, branch, and GitHub destination")
        root = Path(project_path)
        with self._publish_lock:
            try:
                with root_descriptor(root) as descriptor:
                    code, _unused = self._git(root, "check-ref-format", "refs/heads/" + data["branch"])
                    if code != 0:
                        raise GitServiceError(400, "Choose a valid branch before publishing")
                    first = self._status(root)
                    self._review_matches(first, data)
                    self._scan(root, data["head"])
                    current = self._status(root)
                    self._review_matches(current, data)
                    self._unchanged_root(root, descriptor)
                    # Captured URL and full SHA avoid mutable origin/HEAD refspec races.
                    # Normal Git hooks and credential handling remain enabled. No tag/ref fan-out.
                    code, _discard = self._git(
                        root, "-c", "push.followTags=false", "-c", "push.recurseSubmodules=no",
                        "-c", "http.followRedirects=false", "-c", "http.sslVerify=true",
                        "push", "--porcelain", "--no-force", "--no-force-with-lease", "--no-force-if-includes",
                        "--no-follow-tags", "--recurse-submodules=no", "--verify", "--",
                        data["remote"], data["head"] + ":refs/heads/" + data["branch"], timeout=60, maximum=1024 * 1024)
                    if code != 0:
                        raise GitServiceError(502, "Publication did not report success; verify GitHub state before retrying. Authentication and hook errors must be resolved locally.")
                    return {"published": True, "head": data["head"], "branch": data["branch"],
                            "remote": data["remote"], "repository": first["repository"], "status": self._status(root)}
            except FileAccessError as error:
                raise GitServiceError(error.status, str(error)) from None

    @staticmethod
    def _review_matches(state, data):
        if (not state["can_publish"] or any(state[key] != data[key] for key in ("head", "branch", "remote"))):
            raise GitServiceError(409, "Publication blocked: Git state changed or requires review. Refresh the Git panel before confirming again.")

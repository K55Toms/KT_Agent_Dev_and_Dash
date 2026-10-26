"""Private, checked native role snapshots for dashboard-owned delegation."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

from .project_files import FileAccessError, scan_preview
from .team import PROFILES
from .ponytail_policy import PonytailPolicy, PolicyBundle, PolicyError, policy_instructions


class NativeRoles:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        self.lock = threading.Lock()
        self.temporary = None
        self.registered = None
        self.fingerprint = None

    def config(self, roles, safety, policy=None):
        with self.lock:
            policy = PonytailPolicy().load() if policy is None else policy
            if (not isinstance(policy, PolicyBundle) or not policy.text
                    or len(policy.text.encode('utf-8')) > 32768
                    or hashlib.sha256(policy.text.encode('utf-8')).hexdigest() != policy.digest):
                raise PolicyError('Approved Ponytail policy snapshot is invalid.')
            if not isinstance(roles, dict) or set(roles) != set(PROFILES):
                raise ValueError("Configured team roles are incomplete or unsupported")
            snapshots = {}
            for role_id, role in roles.items():
                if (not isinstance(role, dict) or role.get("model") not in
                        {"gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra"}
                        or role.get("reasoning") not in {"low", "medium", "high", "xhigh"}
                        or not isinstance(role.get("instructions"), str)
                        or not 1 <= len(role["instructions"].encode("utf-8")) <= 32768):
                    raise ValueError("Configured team role cannot be registered")
                # Native roles replace developer instructions rather than appending;
                # each snapshot therefore carries the shared baseline explicitly.
                instructions = policy_instructions(role_id, role['instructions'], policy)
                payload = {"model": role["model"], "model_reasoning_effort": role["reasoning"],
                           "developer_instructions": safety + "\n" + instructions}
                snapshots[role_id] = ("\n".join(key + " = " + json.dumps(value, ensure_ascii=False)
                                              for key, value in payload.items()) + "\n").encode("utf-8")
            fingerprint = hashlib.sha256(b'\n'.join(
                role_id.encode('ascii') + b'\0' + snapshots[role_id]
                for role_id in sorted(snapshots))).hexdigest()
            if self.registered is not None:
                if fingerprint != self.fingerprint:
                    raise PolicyError('Registered agent policy changed. Reload the dashboard when idle before starting work.')
                self._verify_cached(snapshots)
                return deepcopy(self.registered)
            # Scan before any persistent write. Only static reviewed role text enters
            # this sink; task instructions and native messages are never included.
            try:
                scan_preview(b"\n".join(snapshots.values()))
            except FileAccessError:
                raise ValueError("Native role content checks did not complete") from None
            parent = os.open(self.directory.anchor, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in self.directory.parts[1:]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.close(parent)
                    parent = child
                info = os.fstat(parent)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError("Native role storage must be private and owned")
                temporary = tempfile.TemporaryDirectory(prefix="native-roles-", dir=self.directory)
                try:
                    directory = os.open(temporary.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        for role_id, content in snapshots.items():
                            fd = os.open(role_id + ".toml", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=directory)
                            with os.fdopen(fd, "wb") as file:
                                info = os.fstat(file.fileno())
                                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                                        or info.st_uid != os.getuid()):
                                    raise ValueError("Native role files must be owned regular files")
                                os.fchmod(file.fileno(), 0o600)
                                file.write(content)
                    finally:
                        os.close(directory)
                    registration = {"enabled": True, "max_concurrent_threads_per_session": 3}
                    registration.update({role_id: {"description": PROFILES[role_id][1],
                                                  "config_file": str(Path(temporary.name) / (role_id + ".toml"))}
                                         for role_id in snapshots})
                    self.temporary, self.registered = temporary, registration
                    self.fingerprint = fingerprint
                except BaseException:
                    temporary.cleanup()
                    raise
            finally:
                os.close(parent)
            return deepcopy(self.registered)

    def _verify_cached(self, snapshots):
        """Cached filenames must still contain the approved bytes before reuse."""
        path = Path(self.temporary.name)
        parent = descriptor = None
        try:
            parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            for part in path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PolicyError('Registered agent snapshots require repair before starting work.')
            for role_id, expected in snapshots.items():
                descriptor = os.open(role_id + '.toml', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
                info = os.fstat(descriptor)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != len(expected)
                        or os.read(descriptor, len(expected) + 1) != expected):
                    raise PolicyError('Registered agent snapshots changed. Reload the dashboard when idle.')
                os.close(descriptor)
                descriptor = None
        except OSError:
            raise PolicyError('Registered agent snapshots are unavailable. Reload the dashboard when idle.') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if parent is not None:
                os.close(parent)

    def close(self):
        with self.lock:
            if self.temporary is not None:
                self.temporary.cleanup()
                self.temporary = None
                self.registered = None
                self.fingerprint = None

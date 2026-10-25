"""Private, checked native role snapshots for dashboard-owned delegation."""

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

from .project_files import FileAccessError, scan_preview
from .team import PROFILES


class NativeRoles:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        self.lock = threading.Lock()
        self.temporary = None
        self.registered = None

    def config(self, roles, safety):
        with self.lock:
            if self.registered is not None:
                return deepcopy(self.registered)
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
                payload = {"model": role["model"], "model_reasoning_effort": role["reasoning"],
                           "developer_instructions": safety + "\n" + role["instructions"]}
                snapshots[role_id] = ("\n".join(key + " = " + json.dumps(value, ensure_ascii=False)
                                              for key, value in payload.items()) + "\n").encode("utf-8")
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
                except BaseException:
                    temporary.cleanup()
                    raise
            finally:
                os.close(parent)
            return deepcopy(self.registered)

    def close(self):
        with self.lock:
            if self.temporary is not None:
                self.temporary.cleanup()
                self.temporary = None
                self.registered = None

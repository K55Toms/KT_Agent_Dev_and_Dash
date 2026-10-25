"""Single production dashboard owner and nonsecret OS boot provenance."""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid


def boot_identity():
    """Return a trusted OS boot digest, never a synthetic dashboard generation."""
    if sys.platform != 'darwin':
        return None
    try:
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode or len(result.stdout) > 128:
        return None
    try:
        value = result.stdout.decode('ascii').strip().lower()
    except UnicodeError:
        return None
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        return None
    return hashlib.sha256(('darwin-boot:' + value).encode('ascii')).hexdigest()


class RuntimeOwner:
    """An OS-held lock; its file's presence alone never establishes ownership."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.descriptor = None
        self.owner_id = uuid.uuid4().hex
        self.boot_id = None

    @property
    def exclusive(self):
        return self.descriptor is not None

    def __enter__(self):
        if not self.directory.is_absolute():
            raise ValueError('Runtime ownership requires an absolute directory')
        for path in (self.directory, *self.directory.parents):
            if path.is_symlink():
                raise ValueError('Runtime ownership paths must not contain links')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.stat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError('Runtime ownership directory must be private and owned')
        descriptor = os.open(self.directory / 'dashboard-owner.lock',
                             os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('Runtime ownership lock must be a private owned regular file')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another dashboard owns this runtime; use its existing service') from None
            self.descriptor = descriptor
            self.boot_id = boot_identity()
            return self
        except BaseException:
            os.close(descriptor)
            raise

    def __exit__(self, *_args):
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            self.boot_id = None
            os.close(descriptor)

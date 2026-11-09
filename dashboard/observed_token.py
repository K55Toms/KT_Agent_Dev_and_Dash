"""Per-install token for observed Claude Code sessions.

The token lives only in one private file. It never appears in repr, str, exceptions or logs.
A file with the wrong mode, owner, link count or type is reported, never repaired or replaced.
"""

import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import threading

TOKEN_NAME = "observed-token"
_FORMAT = re.compile(rb"[A-Za-z0-9_-]{43,128}\Z")
_MAX_BYTES = 256
_MESSAGES = {
    "unreadable": "The observed sessions token file is unreadable or unsafe",
    "permissions": "The observed sessions token file or its folder has the wrong permissions",
}


class TokenFileError(Exception):
    """Carries only a reason, never token material."""

    def __init__(self, reason):
        super().__init__(_MESSAGES[reason])
        self.reason = reason


def default_config_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KT Agent Dashboard"
    base = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(base) if base and os.path.isabs(base) else Path.home() / ".config"
    return base / "kt-agent-dashboard"


class TokenFile:
    def __init__(self, directory):
        self._directory = Path(directory).absolute()
        self._lock = threading.Lock()

    def __repr__(self):
        return "TokenFile(directory=%r)" % str(self._directory)

    __str__ = __repr__

    # -- reading ---------------------------------------------------------------------------------
    def _open_directory(self, create=False):
        """Open every component without following a link (like settings._directory).

        Returns (fd, created). Raises FileNotFoundError when a component is absent and create is false,
        and OSError for a symlinked or unopenable component. With create, missing components are made
        0700; created reports whether the final folder was made here.
        """
        parts = self._directory.parts
        fd = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
        created = False
        try:
            for index, part in enumerate(parts[1:], 1):
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        created = index == len(parts) - 1
                    except FileExistsError:
                        pass
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd, created
        except BaseException:
            os.close(fd)
            raise

    def _check_directory(self, fd):
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return "unreadable"
        if stat.S_IMODE(info.st_mode) != 0o700:
            return "permissions"
        return None

    def _read(self, directory):
        """Return (reason, token_bytes). reason is None only for a usable file; (None, None) means absent."""
        try:
            fd = os.open(TOKEN_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return None, None
        except OSError:
            return "unreadable", None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > _MAX_BYTES:
                return "unreadable", None
            if stat.S_IMODE(info.st_mode) != 0o600:
                return "permissions", None
            data = os.read(fd, _MAX_BYTES + 1)
            if len(data) > _MAX_BYTES or not _FORMAT.fullmatch(data):
                return "unreadable", None
            return None, data
        except OSError:
            return "unreadable", None
        finally:
            os.close(fd)

    def _inspect(self):
        """Return (reason, token_bytes) for the directory and file; the directory fd is closed here."""
        try:
            directory, _ = self._open_directory()
        except FileNotFoundError:
            return None, None
        except OSError:
            return "unreadable", None
        try:
            reason = self._check_directory(directory)
            if reason:
                return reason, None
            return self._read(directory)
        finally:
            os.close(directory)

    def status(self):
        """None when usable (or not created yet), else "unreadable" or "permissions"."""
        with self._lock:
            return self._inspect()[0]

    def matches(self, candidate):
        if not isinstance(candidate, str) or not candidate:
            return False
        try:
            probe = candidate.encode("utf-8")
        except UnicodeError:
            return False
        with self._lock:
            reason, token = self._inspect()
        if reason is not None or token is None:
            return False
        return hmac.compare_digest(probe, token)

    # -- writing ---------------------------------------------------------------------------------
    def _prepare_directory(self):
        """Open the directory, creating it 0700 when absent; refuse anything unsafe."""
        try:
            directory, created = self._open_directory(create=True)
        except OSError:
            raise TokenFileError("unreadable") from None
        try:
            if created and os.fstat(directory).st_uid == os.getuid():
                os.fchmod(directory, 0o700)  # we just made it; the umask cannot have widened it
        except OSError:
            os.close(directory)
            raise TokenFileError("unreadable") from None
        reason = self._check_directory(directory)
        if reason:
            os.close(directory)
            raise TokenFileError(reason)
        return directory

    @staticmethod
    def _write(directory, name, value):
        """Create name exclusively and write value. Our own half-written file is removed on failure;
        a failure to create it (including FileExistsError) leaves whatever is there alone."""
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            try:
                os.fchmod(fd, 0o600)
                data = value.encode("ascii")
                if os.write(fd, data) != len(data):
                    raise OSError("short write")
                os.fsync(fd)
            finally:
                os.close(fd)
        except BaseException:
            try:
                os.unlink(name, dir_fd=directory)
            except OSError:
                pass
            raise

    def token(self):
        with self._lock:
            directory = self._prepare_directory()
            try:
                reason, token = self._read(directory)
                if reason:
                    raise TokenFileError(reason)
                if token is not None:
                    return token.decode("ascii")
                value = secrets.token_urlsafe(32)
                try:
                    self._write(directory, TOKEN_NAME, value)
                except FileExistsError:
                    reason, token = self._read(directory)  # lost a race with another process: use theirs
                    if reason or token is None:
                        raise TokenFileError(reason or "unreadable") from None
                    return token.decode("ascii")
                except OSError:
                    raise TokenFileError("unreadable") from None
                try:
                    os.fsync(directory)
                except OSError:
                    raise TokenFileError("unreadable") from None
                return value
            finally:
                os.close(directory)

    def rotate(self):
        with self._lock:
            directory = self._prepare_directory()
            temporary = ".observed-token-" + secrets.token_hex(12) + ".tmp"
            created = False
            try:
                reason, _ = self._read(directory)
                if reason:
                    raise TokenFileError(reason)
                value = secrets.token_urlsafe(32)
                try:
                    self._write(directory, temporary, value)
                    created = True
                    os.replace(temporary, TOKEN_NAME, src_dir_fd=directory, dst_dir_fd=directory)
                    created = False
                    os.fsync(directory)
                except OSError:
                    raise TokenFileError("unreadable") from None
                return value
            finally:
                if created:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except OSError:
                        pass
                os.close(directory)

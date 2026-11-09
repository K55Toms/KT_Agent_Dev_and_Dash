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
    def _open_directory(self):
        """Open the final component without following a link. Raises OSError if absent or a link."""
        return os.open(self._directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

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
            directory = self._open_directory()
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
            try:
                directory = self._open_directory()
            except FileNotFoundError:
                self._directory.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.mkdir(self._directory, 0o700)
                except FileExistsError:
                    pass
                directory = self._open_directory()
                info = os.fstat(directory)
                if info.st_uid == os.getuid() and stat.S_ISDIR(info.st_mode) and not os.listdir(directory):
                    os.fchmod(directory, 0o700)  # we just made it; the umask cannot have widened it
        except OSError:
            raise TokenFileError("unreadable") from None
        reason = self._check_directory(directory)
        if reason:
            os.close(directory)
            raise TokenFileError(reason)
        return directory

    @staticmethod
    def _write(directory, name, value, flags):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | flags, 0o600, dir_fd=directory)
        try:
            os.fchmod(fd, 0o600)
            data = value.encode("ascii")
            if os.write(fd, data) != len(data):
                raise OSError("short write")
            os.fsync(fd)
        finally:
            os.close(fd)

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
                    self._write(directory, TOKEN_NAME, value, 0)
                except FileExistsError:
                    reason, token = self._read(directory)  # lost a race with another process: use theirs
                    if reason or token is None:
                        raise TokenFileError(reason or "unreadable") from None
                    return token.decode("ascii")
                except OSError:
                    try:
                        os.unlink(TOKEN_NAME, dir_fd=directory)  # our own half-written file
                    except OSError:
                        pass
                    raise TokenFileError("unreadable") from None
                os.fsync(directory)
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
                    self._write(directory, temporary, value, 0)
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

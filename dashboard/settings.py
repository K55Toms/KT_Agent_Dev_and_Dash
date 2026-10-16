"""Validated, nonsecret dashboard preferences and bounded local PNG branding."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import threading
import tomllib
import unicodedata
import zlib

from dashboard.project_files import FileAccessError, scan_preview


DEFAULTS = {
    "theme": "hybrid",
    "dashboard_name": "Kristian’s Rebellion Builders",
    "logo_path": "/brand-logo.png",
    "github_username": "K55Toms",
    "github_visibility": "private",
}
MAX_LOGO_BYTES = 1024 * 1024
_LOGO = re.compile(r"/api/logo/([0-9a-f]{64})\.png\Z")


class SettingsError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _validate(data, *, complete):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS) or (complete and set(data) != set(DEFAULTS)):
        raise SettingsError(400, "Settings must contain only the supported fields")
    result = DEFAULTS | data
    if any(not isinstance(value, str) for value in result.values()):
        raise SettingsError(400, "Settings values must be text")
    if result["theme"] not in {"hybrid", "terminal", "rebel"}:
        raise SettingsError(400, "Choose Hybrid, Terminal or Rebel")
    name = result["dashboard_name"]
    if not 1 <= len(name) <= 80 or name != name.strip() or any(unicodedata.category(c).startswith("C") for c in name):
        raise SettingsError(400, "Dashboard name must be 1–80 visible characters without surrounding whitespace")
    # Preferences are public, tracked configuration. Reject credential-shaped text,
    # never echo the offending value in errors; this is not a general secret scanner.
    if re.search(r"(?i)(?:password|passwd|secret|token|api[_ -]?key)\s*[:=]|(?:gh[pousr]_|github_pat_|sk-)[a-zA-Z0-9_-]{12,}", name):
        raise SettingsError(400, "Dashboard name must not contain credential-like text")
    if result["logo_path"] != "/brand-logo.png" and not _LOGO.fullmatch(result["logo_path"]):
        raise SettingsError(400, "Choose the original logo or an uploaded PNG")
    username = result["github_username"]
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username) or "--" in username:
        raise SettingsError(400, "GitHub account must contain 1–39 letters, numbers or single internal hyphens")
    if result["github_visibility"] not in {"private", "public"}:
        raise SettingsError(400, "GitHub visibility must be private or public")
    return result


def _regular(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise SettingsError(500, "Settings storage must use owned regular files without links")
    return info


def _scan_settings(data, *, loading=False):
    try:
        scan_preview(data)
    except FileAccessError as error:
        if error.status == 503:
            raise SettingsError(503, "Settings are unavailable because the reviewed secret scanner could not complete") from None
        status = 500 if loading else 400
        raise SettingsError(status, "Settings contain possible sensitive content or scanning failed; no values have been returned or saved") from None


def _serialize(data):
    return ("# Nonsecret preferences only. Also editable through dashboard Settings.\n" + "\n".join(
        key + " = " + json.dumps(value, ensure_ascii=False) for key, value in data.items()) + "\n").encode("utf-8")


def _directory(path):
    """Open every component without following links, including parents."""
    path = Path(path).absolute()
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _png(data):
    """Validate plain PNG only; reject metadata and compressed-data surprises."""
    error = SettingsError(400, "Use a plain, noninterlaced PNG up to 1 MiB and 2048 pixels per side, without metadata")
    if not isinstance(data, bytes) or not 45 <= len(data) <= MAX_LOGO_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise error
    position = 8
    header = None
    compressed = bytearray()
    palette = None
    transparency = False
    ended = False
    saw_idat = False
    while position < len(data):
        if position + 12 > len(data):
            raise error
        length, = struct.unpack_from(">I", data, position)
        kind = data[position + 4:position + 8]
        end = position + 12 + length
        if end > len(data):
            raise error
        body = data[position + 8:end - 4]
        crc, = struct.unpack_from(">I", data, end - 4)
        if zlib.crc32(kind + body) & 0xffffffff != crc or ended:
            raise error
        if kind == b"IHDR":
            if header is not None or position != 8 or length != 13:
                raise error
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            if not 1 <= width <= 2048 or not 1 <= height <= 2048 or depth != 8 or color not in {0, 2, 3, 4, 6} or compression or filtering or interlace:
                raise error
            header = (width, height, color)
        elif header is None:
            raise error
        elif kind == b"PLTE":
            if palette is not None or saw_idat or not 3 <= length <= 768 or length % 3 or header[2] in {0, 4}:
                raise error
            palette = length // 3
        elif kind == b"tRNS":
            expected = {0: 2, 2: 6}.get(header[2])
            if transparency or saw_idat or (header[2] == 3 and (palette is None or not 1 <= length <= palette)) or (header[2] != 3 and length != expected):
                raise error
            transparency = True
        elif kind == b"IDAT":
            if header[2] == 3 and palette is None:
                raise error
            saw_idat = True
            compressed.extend(body)
        elif kind == b"IEND":
            if length or not saw_idat or end != len(data):
                raise error
            ended = True
        else:
            raise error
        position = end
    if not ended or header is None:
        raise error
    width, height, color = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    stride = width * channels + 1
    expected_size = stride * height
    if expected_size > 16 * 1024 * 1024:
        raise error
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected_size + 1)
    except zlib.error:
        raise error from None
    if len(raw) != expected_size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or any(raw[index] > 4 for index in range(0, len(raw), stride)):
        raise error


class SettingsStore:
    def __init__(self, repo_root, config_path=None):
        self.root = Path(repo_root).absolute()
        self.path = Path(config_path).absolute() if config_path is not None else self.root / "dashboard" / "config.toml"
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            directory = None
            fd = None
            try:
                directory = _directory(self.path.parent)
                try:
                    fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                except FileNotFoundError:
                    return dict(DEFAULTS)
                info = _regular(fd)
                if info.st_size > 8192:
                    raise SettingsError(500, "Settings file is too large")
                raw = os.read(fd, 8193)
                if len(raw) > 8192:
                    raise SettingsError(500, "Settings file is too large")
                try:
                    result = _validate(tomllib.loads(raw.decode("utf-8")), complete=False)
                except (ValueError, UnicodeError, SettingsError):
                    raise SettingsError(500, "Settings file is invalid; correct its supported fields before saving") from None
                _scan_settings(raw, loading=True)
                return result
            except OSError:
                raise SettingsError(500, "Settings file is unavailable or uses an unsafe path") from None
            finally:
                if fd is not None:
                    os.close(fd)
                if directory is not None:
                    os.close(directory)

    def save(self, data):
        validated = _validate(data, complete=True)
        proposed = _serialize(validated)
        _scan_settings(proposed)
        if validated["logo_path"] != "/brand-logo.png":
            self.read_logo(_LOGO.fullmatch(validated["logo_path"])[1])
        with self.lock:
            # Refuse to silently erase unsupported/corrupt existing configuration.
            self.load()
            directory = None
            temporary = ".config-" + secrets.token_hex(12) + ".tmp"
            try:
                directory = _directory(self.path.parent)
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as output:
                    output.write(proposed)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
                return dict(validated)
            except OSError:
                raise SettingsError(500, "Settings could not be saved safely") from None
            finally:
                if directory is not None:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass
                    os.close(directory)

    def _branding(self):
        directory = _directory(self.root)
        try:
            for part in (".local", "branding"):
                try:
                    os.mkdir(part, 0o700, dir_fd=directory)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
                if os.fstat(directory).st_uid != os.getuid():
                    raise SettingsError(500, "Logo directory must be owned by the current user")
                os.fchmod(directory, 0o700)
            return directory
        except BaseException:
            os.close(directory)
            raise

    def upload_logo(self, data):
        _png(data)
        identifier = hashlib.sha256(data).hexdigest()
        directory = None
        temporary = ".upload-" + secrets.token_hex(12)
        with self.lock:
            try:
                directory = self._branding()
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, identifier + ".png", src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
                return "/api/logo/" + identifier + ".png"
            except OSError:
                raise SettingsError(500, "Logo could not be stored safely") from None
            finally:
                if directory is not None:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass
                    os.close(directory)

    def read_logo(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise SettingsError(404, "Logo is unavailable")
        directory = None
        fd = None
        try:
            directory = self._branding()
            fd = os.open(identifier + ".png", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            info = _regular(fd)
            if info.st_size > MAX_LOGO_BYTES:
                raise SettingsError(404, "Logo is unavailable")
            data = os.read(fd, MAX_LOGO_BYTES + 1)
            if hashlib.sha256(data).hexdigest() != identifier:
                raise SettingsError(404, "Logo is unavailable")
            _png(data)
            return data
        except (OSError, SettingsError):
            raise SettingsError(404, "Logo is unavailable") from None
        finally:
            if fd is not None:
                os.close(fd)
            if directory is not None:
                os.close(directory)

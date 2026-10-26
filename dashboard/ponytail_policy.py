"""Approved installed skill bytes, never a browser-selected policy or source path."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat

from .project_files import FileAccessError, scan_preview

APPROVED_VERSION = '5.3.2'
APPROVED_SHA256 = '9badd22a32e19cb884e46dfa8d3aae82bb81dfa5484105b8b4f0262df823a509'
MAX_POLICY_BYTES = 32768
PILOT_ROLES = frozenset({'backend_developer', 'frontend_developer'})


class PolicyError(ValueError):
    """Fixed diagnostics only; no upstream source or operating-system errors."""


@dataclass(frozen=True)
class PolicyBundle:
    version: str
    digest: str
    text: str

    @property
    def metadata(self):
        return {'name': 'ponytail', 'mode': 'full', 'version': self.version,
                'sha256': self.digest}


class PonytailPolicy:
    def __init__(self, cache_root=None, *, version=APPROVED_VERSION, digest=APPROVED_SHA256):
        # Alternate roots/pins are an internal testing seam, never HTTP input.
        self.cache_root = Path(cache_root) if cache_root is not None else (
            Path.home() / '.codex' / 'plugins' / 'cache' / 'ponytail' / 'ponytail')
        if (not self.cache_root.is_absolute() or not isinstance(version, str)
                or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}', version)
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise PolicyError('Approved Ponytail policy configuration is invalid.')
        self.version, self.digest = version, digest

    def load(self):
        source = self.cache_root / self.version / 'skills' / 'ponytail' / 'SKILL.md'
        parent = descriptor = None
        try:
            parent = os.open(source.anchor, os.O_RDONLY | os.O_DIRECTORY)
            for part in source.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            descriptor = os.open(source.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                                 dir_fd=parent)
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != os.getuid() or not 0 < before.st_size <= MAX_POLICY_BYTES):
                raise PolicyError('Approved Ponytail source is not a bounded owned regular file.')
            content = bytearray()
            while len(content) <= MAX_POLICY_BYTES:
                chunk = os.read(descriptor, min(8192, MAX_POLICY_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
            after = os.fstat(descriptor)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if (len(content) > MAX_POLICY_BYTES or len(content) != before.st_size
                    or identity(before) != identity(after)):
                raise PolicyError('Approved Ponytail source changed while being read.')
        except PolicyError:
            raise
        except (OSError, ValueError):
            raise PolicyError('Approved Ponytail source is unavailable. Repair the approved plugin installation.') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if parent is not None:
                os.close(parent)
        content = bytes(content)
        if hashlib.sha256(content).hexdigest() != self.digest:
            raise PolicyError('Installed Ponytail differs from the approved policy. Review the update before starting work.')
        try:
            text = content.decode('utf-8')
            if any(ord(char) < 32 and char not in '\n\r\t' for char in text):
                raise ValueError()
            scan_preview(content)
        except (UnicodeError, ValueError, FileAccessError):
            raise PolicyError('Approved Ponytail policy content checks did not pass.') from None
        return PolicyBundle(self.version, self.digest, text)


def policy_instructions(role_id, instructions, policy):
    if role_id not in PILOT_ROLES:
        return instructions
    return (instructions + '\n\nApproved Ponytail Full policy (' + policy.version + ', SHA-256 ' +
            policy.digest + '). Apply within the assigned role; all existing security, approval, '
            'documentation and acceptance requirements remain mandatory.\n' + policy.text)

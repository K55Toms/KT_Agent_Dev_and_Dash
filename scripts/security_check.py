#!/usr/bin/env python3
"""Scan the Git index or all reachable history; never print blob contents."""
import fnmatch
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.gitleaks.toml'
VERSION = '8.30.1'
DENIED_DIRS = {
    '.aws', '.azure', '.gcp', '.ssh', '.kube', 'secrets', '.secrets',
    'credentials', '.credentials', '.local', 'artifacts',
}
DENIED_FILES = (
    '.env', '.env.*', '*.env', '.envrc', '*.pem', '*.key', '*.p12', '*.pfx',
    '*.jks', '*.keystore', 'id_rsa*', 'id_ed25519*', 'credentials.json',
    '*service-account*.json', '.npmrc', '.netrc', '.pypirc', '*.tfstate',
    '*.tfstate.*', '*.tfvars', '*.tfvars.json', '*.log', '*.sqlite*', '*.db',
    '.gitleaksignore', '*.zip', '*.tar', '*.gz', '*.7z',
)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def forbidden(path):
    p = PurePosixPath(path.lower())
    if any(part in DENIED_DIRS for part in p.parts):
        return True
    if any(fnmatch.fnmatchcase(p.name, pattern) for pattern in DENIED_FILES):
        return True
    if '.codex' in p.parts:
        return not (path == '.codex/config.toml' or (
            path.startswith('.codex/agents/') and len(p.parts) == 3
            and path.endswith('.toml')))
    return False


def scanner(*args, data=None):
    # No ambient config, allow comments, or local ignore files may silence findings.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GITLEAKS_')}
    with tempfile.TemporaryDirectory(prefix='team-scan-control-') as control:
        command = [
            'gitleaks', *args, '--config', str(CONFIG), '--redact=100',
            '--no-banner', '--no-color', '--ignore-gitleaks-allow',
            '--gitleaks-ignore-path', control, '--max-decode-depth', '5',
            '--max-archive-depth', '3',
        ]
        result = subprocess.run(command, cwd=control, env=env, input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Scanner diagnostics can contain source snippets: do not echo them.
        raise RuntimeError('Secret scan blocked: possible credential or scanner error. '
                           'Inspect locally with redaction; do not paste values into chat or docs.')


def staged():
    entries = git('ls-files', '--stage', '-z').split(b'\0')
    with tempfile.TemporaryDirectory(prefix='team-index-scan-') as directory:
        for entry in filter(None, entries):
            metadata, raw_path = entry.split(b'\t', 1)
            mode, oid, stage = metadata.decode().split()
            path = os.fsdecode(raw_path)
            if forbidden(path):
                raise RuntimeError(f'Forbidden tracked path: {path!r}. Keep credentials outside Git.')
            if mode not in ('100644', '100755') or stage != '0':
                raise RuntimeError(f'Unsupported index entry: {path!r}; symlinks/submodules/conflicts require review.')
            target = Path(directory) / path
            if '..' in PurePosixPath(path).parts or PurePosixPath(path).is_absolute():
                raise RuntimeError('Unsafe Git path.')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(git('cat-file', 'blob', oid))
        # Scan full staged blobs, including unchanged tracked files and documentation.
        scanner('dir', directory)


def history(refs=()):
    commits = git('rev-list', '--all', *refs).decode().splitlines()
    if not commits:
        return
    # Check every historical tree so a deleted credential filename still blocks push.
    for commit in commits:
        for entry in filter(None, git('ls-tree', '-r', '-z', commit).split(b'\0')):
            metadata, raw_path = entry.split(b'\t', 1)
            path = os.fsdecode(raw_path)
            if forbidden(path) or metadata.split()[0] not in (b'100644', b'100755'):
                raise RuntimeError(f'Forbidden historical path: {path!r}. Review history before pushing.')
    scanner('git', str(ROOT), '--log-opts=' + ' '.join(('--all', '--full-history', *refs)))
    scanner('stdin', data=git('log', '--all', '--format=%B', *refs))
    # Tag annotations are separate Git objects, not commit messages or file diffs.
    for entry in git('rev-list', '--objects', '--all', *refs).splitlines():
        oid = entry.split(b' ', 1)[0].decode('ascii')
        if git('cat-file', '-t', oid).strip() == b'tag':
            scanner('stdin', data=git('cat-file', 'tag', oid))


def push():
    refs = []
    # Git supplies the actual outgoing objects here, including explicit SHA pushes
    # that are not reachable from any local ref. Never interpolate unvalidated input.
    for line in sys.stdin:
        fields = line.split()
        if len(fields) != 4:
            raise RuntimeError('Malformed pre-push input; push blocked.')
        oid = fields[1]
        if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', oid):
            raise RuntimeError('Invalid outgoing object ID; push blocked.')
        if set(oid) == {'0'}:
            continue
        # Product refs must resolve to commits; reject arbitrary blob/tree pushes.
        git('rev-parse', '--verify', oid + '^{commit}')
        refs.append(oid)
    history(tuple(refs))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('staged', 'history', 'push'):
        raise RuntimeError('Usage: python3 scripts/security_check.py staged|history|push')
    if not shutil.which('gitleaks'):
        raise RuntimeError('Gitleaks missing: commit/push blocked. Run scripts/bootstrap.sh after installing it.')
    version = subprocess.check_output(['gitleaks', 'version'], text=True).strip()
    if version != VERSION:
        raise RuntimeError(f'Gitleaks {VERSION} required; review upgrades explicitly.')
    globals()[sys.argv[1]]()
    print(f'Security check passed: {sys.argv[1]}.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'BLOCKED: {error}', file=sys.stderr)
        sys.exit(1)

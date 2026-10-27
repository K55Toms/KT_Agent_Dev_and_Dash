#!/usr/bin/env python3
"""Scan the Git index or all reachable history; never print blob contents."""
import fnmatch
import hashlib
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.gitleaks.toml'
VERSION = '8.30.1'
CONFIG_DIGEST = '3eee5ec1b4b3490c08544dd1c38c6f98245679a8018a797315f65239e0b9f29f'
MAX_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_COMMITS = 2000
MAX_OBJECTS = 100000
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
    # Claude Code project MCP servers, personal memory and local state/credentials.
    # Names are matched lower-cased, so 'claude.local.md' also covers CLAUDE.local.md.
    '.mcp.json', 'claude.local.md', '.claude.json', '.credentials.json',
)


def environment(index=None):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('GIT_', 'GITLEAKS_'))}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0',
               GIT_CONFIG_COUNT='3', GIT_CONFIG_KEY_0='log.showSignature', GIT_CONFIG_VALUE_0='false',
               GIT_CONFIG_KEY_1='core.fsmonitor', GIT_CONFIG_VALUE_1='false',
               GIT_CONFIG_KEY_2='core.untrackedCache', GIT_CONFIG_VALUE_2='false')
    if index is not None:
        env['GIT_INDEX_FILE'] = str(index)
    return env


def bounded(command, *, cwd=ROOT, data=None, maximum=MAX_BYTES, timeout=30, index=None):
    # Raw Git/scanner diagnostics may contain credentials: never retain stderr.
    try:
        process = subprocess.Popen(command, cwd=cwd, env=environment(index=index), start_new_session=True,
                                   stdin=subprocess.PIPE if data else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise RuntimeError('Required local security tooling is unavailable.') from None
    deadline = time.monotonic() + timeout
    output = bytearray()
    pending = memoryview(data or b'')
    selector = selectors.DefaultSelector()
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        if data:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Security check exceeded its safe time limit; publication blocked.')
            for key, _events in selector.select(min(remaining, 1)):
                if key.fileobj is process.stdout:
                    chunk = os.read(process.stdout.fileno(), min(65536, maximum + 1 - len(output)))
                    if not chunk:
                        selector.unregister(process.stdout)
                    else:
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise RuntimeError('Security check exceeded its safe output limit; publication blocked.')
                else:
                    try:
                        count = os.write(process.stdin.fileno(), pending[:65536])
                        pending = pending[count:]
                    except BrokenPipeError:
                        pending = memoryview(b'')
                    if not pending:
                        selector.unregister(process.stdin)
                        process.stdin.close()
        try:
            code = process.wait(timeout=max(.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise RuntimeError('Security check exceeded its safe time limit; publication blocked.') from None
        return code, bytes(output)
    finally:
        selector.close()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait(timeout=3)
        process.stdout.close()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()


def git(*args, data=None, timeout=30, index=None):
    code, output = bounded(['git', '--no-pager', '--no-optional-locks', '--no-replace-objects',
                            '--no-lazy-fetch', '-c', 'log.showSignature=false', '-c', 'core.fsmonitor=false',
                            '-c', 'core.untrackedCache=false', *args], data=data, timeout=timeout, index=index)
    if code:
        raise RuntimeError('Git security metadata could not be verified; publication blocked.')
    return output


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
    # Only generated role files may be tracked under .claude; settings (hooks, permissions)
    # and other Claude Code state need a reviewed policy change first.
    if '.claude' in p.parts:
        return not (path.startswith('.claude/agents/') and len(p.parts) == 3
                    and path.endswith('.md'))
    return False


def reviewed_policy():
    descriptor = None
    try:
        descriptor = os.open(CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
            raise RuntimeError('Secret-scanner policy requires explicit review.')
        policy = os.read(descriptor, 65537)
        if hashlib.sha256(policy).hexdigest() != CONFIG_DIGEST:
            raise RuntimeError('Secret-scanner policy requires explicit review.')
        return policy
    except OSError:
        raise RuntimeError('Reviewed secret-scanner policy is unavailable.') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def scanner(*args, data=None, timeout=30):
    # No ambient config, allow comments, or local ignore files may silence findings.
    policy = reviewed_policy()
    with tempfile.TemporaryDirectory(prefix='team-scan-control-') as control:
        policy_file = Path(control) / 'policy.toml'
        policy_file.write_bytes(policy)
        command = [
            'gitleaks', *args, '--config', str(policy_file), '--redact=100',
            '--no-banner', '--no-color', '--ignore-gitleaks-allow',
            '--gitleaks-ignore-path', control, '--max-decode-depth', '5',
            '--max-archive-depth', '3', '--timeout', '30',
        ]
        code, _discard = bounded(command, cwd=control, data=data, timeout=timeout, maximum=1024)
    if code:
        # Scanner diagnostics can contain source snippets: do not echo them.
        raise RuntimeError('Secret scan blocked: possible credential or scanner error. '
                           'Inspect locally with redaction; do not paste values into chat or docs.')


def staged():
    deadline = time.monotonic() + 90
    index = selected_index()
    entries = git('ls-files', '--stage', '-z', index=index).split(b'\0')
    if len(entries) > MAX_OBJECTS:
        raise RuntimeError('Index exceeds the bounded security-review limit.')
    checked = []
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b'\t', 1)
        mode, oid, stage = metadata.decode().split()
        path = os.fsdecode(raw_path)
        if forbidden(path):
            raise RuntimeError(f'Forbidden tracked path: {path!r}. Keep credentials outside Git.')
        if mode not in ('100644', '100755') or stage != '0':
            raise RuntimeError(f'Unsupported index entry: {path!r}; symlinks/submodules/conflicts require review.')
        if '..' in PurePosixPath(path).parts or PurePosixPath(path).is_absolute():
            raise RuntimeError('Unsafe Git path.')
        checked.append((path, oid))
    total = 0
    with tempfile.TemporaryDirectory(prefix='team-index-scan-') as directory:
        for path, oid in checked:
            target = Path(directory) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            blob = git('cat-file', 'blob', oid, timeout=remaining(deadline))
            total += len(blob)
            if total > MAX_TOTAL_BYTES:
                raise RuntimeError('Index content exceeds the bounded security-review limit.')
            target.write_bytes(blob)
        # Scan full staged blobs, including unchanged tracked files and documentation.
        scanner('dir', directory, timeout=remaining(deadline))


def selected_index():
    # Git's commit --only/-a hooks can receive a temporary, actual commit index.
    # Never silently scan the ordinary index when Git selected another one.
    value = os.environ.get('GIT_INDEX_FILE')
    if value is None:
        return None
    if not value or len(value) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RuntimeError('The selected commit index could not be validated.')
    directory = Path(os.fsdecode(git('rev-parse', '--absolute-git-dir').strip())).resolve()
    candidate = ROOT / value
    try:
        info = candidate.stat(follow_symlinks=False)
        if (candidate.parent.resolve() != directory or candidate.is_symlink()
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES):
            raise RuntimeError('Commit index must be a private regular file in this repository Git metadata directory.')
    except OSError:
        raise RuntimeError('The selected commit index is unavailable; commit blocked.') from None
    return candidate.absolute()


def remaining(deadline):
    duration = deadline - time.monotonic()
    if duration <= 0:
        raise RuntimeError('Security check exceeded its safe time limit; publication blocked.')
    return min(30, duration)


def history(refs=()):
    deadline = time.monotonic() + 90
    if git('rev-parse', '--is-shallow-repository').strip() != b'false':
        raise RuntimeError('Shallow history cannot pass the full-history security policy.')
    graft = os.fsdecode(git('rev-parse', '--git-path', 'info/grafts').strip())
    if not graft or (ROOT / graft).exists():
        raise RuntimeError('Grafted history requires independent review before publication.')
    commits = git('rev-list', '--all', *refs, '--').decode().splitlines()
    if not commits:
        return
    if len(commits) > MAX_COMMITS:
        raise RuntimeError('History exceeds the bounded security-review limit.')
    # Check every historical tree so a deleted credential filename still blocks push.
    for commit in commits:
        for entry in filter(None, git('ls-tree', '-r', '-z', commit, timeout=remaining(deadline)).split(b'\0')):
            metadata, raw_path = entry.split(b'\t', 1)
            path = os.fsdecode(raw_path)
            if forbidden(path) or metadata.split()[0] not in (b'100644', b'100755'):
                raise RuntimeError(f'Forbidden historical path: {path!r}. Review history before pushing.')
    scanner('git', str(ROOT), '--log-opts=' + ' '.join((
        '--all', '--full-history', '--no-ext-diff', '--no-textconv', *refs)), timeout=remaining(deadline))
    # Scan raw objects too: attributes, binary classification, signature display, and
    # diff settings must never hide bytes from the pre-push security boundary.
    objects = git('rev-list', '--objects', '--all', *refs, '--', timeout=remaining(deadline)).splitlines()
    if len(objects) > MAX_OBJECTS:
        raise RuntimeError('Object inventory exceeds the bounded security-review limit.')
    ids = [entry.split(b' ', 1)[0] for entry in objects]
    if any(not re.fullmatch(rb'(?:[0-9a-f]{40}|[0-9a-f]{64})', oid) for oid in ids):
        raise RuntimeError('Unsupported historical object identity.')
    types = git('cat-file', '--batch-check=%(objectname) %(objecttype)',
                data=b'\n'.join(ids) + b'\n', timeout=remaining(deadline)).splitlines()
    if len(types) != len(ids):
        raise RuntimeError('Historical object inventory could not be verified.')
    batch = bytearray()
    total = 0
    for entry in types:
        oid, separator, kind = entry.partition(b' ')
        if not separator or kind not in (b'blob', b'commit', b'tag', b'tree'):
            raise RuntimeError('Historical object inventory could not be verified.')
        if kind in (b'blob', b'commit', b'tag'):
            raw = git('cat-file', kind.decode('ascii'), oid.decode('ascii'), timeout=remaining(deadline))
            total += len(raw)
            if total > MAX_TOTAL_BYTES:
                raise RuntimeError('Historical content exceeds the bounded security-review limit.')
            if batch and len(batch) + len(raw) + 2 > MAX_BYTES:
                scanner('stdin', data=bytes(batch), timeout=remaining(deadline))
                batch.clear()
            batch.extend(b'\n' + raw + b'\n')
    if batch:
        scanner('stdin', data=bytes(batch), timeout=remaining(deadline))


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
    code, version = bounded(['gitleaks', 'version'], maximum=1024, timeout=5)
    if code or version.strip() != VERSION.encode('ascii'):
        raise RuntimeError(f'Gitleaks {VERSION} required; review upgrades explicitly.')
    globals()[sys.argv[1]]()
    print(f'Security check passed: {sys.argv[1]}.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'BLOCKED: {error}', file=sys.stderr)
        sys.exit(1)

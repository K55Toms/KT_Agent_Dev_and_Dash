"""Integration tests use disposable repositories and synthetic values only."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


CLAUDE_FORBIDDEN = (
    '.claude/settings.json', '.claude/settings.local.json', '.claude/agents/sub/x.md',
    '.claude/commands/a.md', '.mcp.json', 'CLAUDE.local.md', '.claude.json', '.credentials.json',
)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.fresh_repo()

    def fresh_repo(self):
        self.temp = tempfile.TemporaryDirectory(prefix='team-security-test-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for name in ('scripts', '.githooks'):
            shutil.copytree(ROOT / name, self.repo / name)
        for name in ('.gitleaks.toml', '.gitignore'):
            shutil.copy2(ROOT / name, self.repo / name)
        self.run_command('git', 'init', '-b', 'main')
        self.run_command('git', 'config', 'user.name', 'Security Test')
        self.run_command('git', 'config', 'user.email', 'test@example.invalid')
        self.run_command('sh', 'scripts/bootstrap.sh')

    def run_command(self, *args, expected=0, env=None, data=None):
        result = subprocess.run(args, cwd=self.repo, env=env,
                                input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, expected,
                         f'Unexpected exit status for {args[0]} (output suppressed).')
        return result

    def write(self, path, value):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def stage(self, path):
        self.run_command('git', 'add', '--', path)

    def check(self, mode='staged', expected=0):
        return self.run_command('python3', 'scripts/security_check.py', mode, expected=expected)

    @staticmethod
    def secret():
        # Construct a recognizable but nonfunctional token only in a disposable test.
        return 'gh' + 'p_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'

    def test_safe_documentation_and_placeholder_pass(self):
        self.write('docs/setup.md', 'Set API_KEY in your runtime environment.\n'
                   + 'pass' + 'word = "<REDACTED>"\n')
        self.stage('docs/setup.md')
        self.check()
        self.run_command('git', 'commit', '-m', 'Add safe documentation')
        self.check('history')

    def test_documentation_secret_blocks_commit_without_echoing_value(self):
        token = self.secret()
        self.write('docs/setup.md', token)
        self.stage('docs/setup.md')
        result = self.run_command('git', 'commit', '-m', 'Test docs rejection', expected=1)
        self.assertNotIn(token.encode(), result.stdout + result.stderr)

    def test_low_entropy_password_in_docs_is_blocked(self):
        self.write('docs/setup.md', 'pass' + 'word = "simple-test-value"\n')
        self.stage('docs/setup.md')
        self.check(expected=1)

    def test_unquoted_yaml_password_is_blocked(self):
        self.write('docs/setup.md', 'pass' + 'word: simple-test-value\n')
        self.stage('docs/setup.md')
        self.check(expected=1)

    def test_json_password_is_blocked(self):
        self.write('docs/setup.md', '{"pass' + 'word": "simple-test-value"}\n')
        self.stage('docs/setup.md')
        self.check(expected=1)

    def test_ignored_credential_file_and_force_added_path(self):
        self.write('.env', 'NON_SECRET_SETTING=1\n')
        self.run_command('git', 'check-ignore', '.env')
        self.run_command('git', 'add', '-f', '.env')
        self.check(expected=1)

    def test_staged_secret_cannot_hide_behind_clean_worktree(self):
        self.write('docs/setup.md', self.secret())
        self.stage('docs/setup.md')
        self.write('docs/setup.md', 'Safe working copy.\n')
        self.check(expected=1)

    def test_inline_allow_comment_does_not_bypass_scan(self):
        self.write('docs/setup.md', self.secret() + ' # gitleaks:' + 'allow\n')
        self.stage('docs/setup.md')
        self.check(expected=1)

    def test_deleted_historical_secret_blocks_push_hook(self):
        self.write('docs/setup.md', self.secret())
        self.stage('docs/setup.md')
        # Deliberately simulate an earlier bypass ONLY inside this disposable test repository.
        self.run_command('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Synthetic history')
        self.write('docs/setup.md', 'Safe current documentation.\n')
        self.stage('docs/setup.md')
        self.run_command('git', 'commit', '-m', 'Remove synthetic value')
        self.check()
        self.check('history', expected=1)
        self.run_command('sh', '.githooks/pre-push', expected=1, data=b'')

    def test_historical_credential_filename_blocks_push(self):
        self.write('.env', 'NON_SECRET_SETTING=1\n')
        self.run_command('git', 'add', '-f', '.env')
        self.run_command('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Synthetic path')
        self.run_command('git', 'rm', '.env')
        self.run_command('git', 'commit', '-m', 'Remove synthetic path')
        self.check('history', expected=1)

    def test_missing_scanner_fails_closed(self):
        env = os.environ.copy()
        env['PATH'] = '/path-that-does-not-exist'
        import sys
        self.run_command(sys.executable, 'scripts/security_check.py', 'staged',
                         expected=1, env=env)

    def test_symlink_is_blocked(self):
        (self.repo / 'linked').symlink_to('/nonexistent-test-path')
        self.stage('linked')
        self.check(expected=1)

    def test_commit_message_secret_blocks_history(self):
        self.write('docs/setup.md', 'Safe document.\n')
        self.stage('docs/setup.md')
        self.run_command('git', 'commit', '-m', self.secret())
        self.check('history', expected=1)

    def test_annotated_and_nested_tag_messages_are_blocked(self):
        self.write('docs/setup.md', 'Safe document.\n')
        self.stage('docs/setup.md')
        self.run_command('git', 'commit', '-m', 'Safe commit')
        self.run_command('git', 'tag', '-a', 'inner', '-m', self.secret())
        self.run_command('git', 'tag', '-a', 'outer', 'inner', '-m', 'Safe outer tag')
        self.run_command('git', 'tag', '-d', 'inner')
        self.check('history', expected=1)

    def test_unreferenced_outgoing_commit_is_blocked(self):
        self.write('docs/setup.md', self.secret())
        self.stage('docs/setup.md')
        tree = self.run_command('git', 'write-tree').stdout.decode().strip()
        oid = self.run_command('git', 'commit-tree', tree, '-m', 'Synthetic orphan').stdout.decode().strip()
        self.write('docs/setup.md', 'Safe document.\n')
        self.stage('docs/setup.md')
        self.run_command('git', 'commit', '-m', 'Safe referenced commit')
        self.check('history')
        hook_input = f'{oid} {oid} refs/heads/test {"0" * 40}\n'.encode()
        self.run_command('sh', '.githooks/pre-push', expected=1, data=hook_input)

    def test_safe_outgoing_commit_passes(self):
        self.write('docs/setup.md', 'Safe document.\n')
        self.stage('docs/setup.md')
        self.run_command('git', 'commit', '-m', 'Safe commit')
        oid = self.run_command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
        hook_input = f'refs/heads/main {oid} refs/heads/main {"0" * 40}\n'.encode()
        self.run_command('sh', '.githooks/pre-push', data=hook_input)

    def test_raw_historical_blob_ignores_diff_suppression(self):
        self.write('.gitattributes', 'hidden.txt -diff\n')
        self.write('hidden.txt', self.secret())
        self.stage('.gitattributes')
        self.stage('hidden.txt')
        # Historical bypass simulation is confined to this disposable repository.
        self.run_command('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Synthetic diff-hidden source')
        self.write('hidden.txt', 'Current safe source.\n')
        self.stage('hidden.txt')
        self.run_command('git', 'commit', '-m', 'Remove synthetic historical content')
        result = self.check('history', expected=1)
        self.assertNotIn(self.secret().encode(), result.stdout + result.stderr)

    def test_raw_binary_blob_is_scanned(self):
        (self.repo / 'binary.dat').write_bytes(b'\0' + self.secret().encode() + b'\0')
        self.stage('binary.dat')
        self.run_command('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Synthetic binary source')
        self.run_command('git', 'rm', 'binary.dat')
        self.run_command('git', 'commit', '-m', 'Remove synthetic binary source')
        self.check('history', expected=1)

    def test_replace_refs_cannot_hide_original_history(self):
        self.write('source.txt', 'Safe initial source.\n')
        self.stage('source.txt')
        self.run_command('git', 'commit', '-m', 'Safe initial revision')
        initial = self.run_command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
        self.write('source.txt', self.secret())
        self.stage('source.txt')
        self.run_command('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Synthetic contaminated revision')
        bad = self.run_command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
        self.write('source.txt', 'Safe current source.\n')
        self.stage('source.txt')
        self.run_command('git', 'commit', '-m', 'Current safe revision')
        self.run_command('git', 'replace', bad, initial)
        self.check('history', expected=1)

    def test_signature_display_does_not_execute_external_verifier(self):
        self.write('source.txt', 'Safe source.\n')
        self.stage('source.txt')
        self.run_command('git', 'commit', '-m', 'Safe revision')
        head = self.run_command('git', 'rev-parse', 'HEAD').stdout.decode().strip()
        tree = self.run_command('git', 'rev-parse', 'HEAD^{tree}').stdout.decode().strip()
        signed = ('tree ' + tree + '\nparent ' + head + '\n'
                  'author Synthetic Test <test@example.invalid> 1 +0000\n'
                  'committer Synthetic Test <test@example.invalid> 1 +0000\n'
                  'gpgsig -----BEGIN PGP SIGNATURE-----\n synthetic-signature\n'
                  ' -----END PGP SIGNATURE-----\n\nSynthetic signed revision.\n').encode()
        oid = self.run_command('git', 'hash-object', '-t', 'commit', '-w', '--stdin', data=signed).stdout.decode().strip()
        self.run_command('git', 'update-ref', 'refs/heads/main', oid)
        with tempfile.TemporaryDirectory(prefix='team-signature-test-') as helpers:
            marker = Path(helpers) / 'executed'
            program = Path(helpers) / 'verifier'
            program.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\nexit 1\n")
            program.chmod(0o700)
            self.run_command('git', 'config', 'log.showSignature', 'true')
            self.run_command('git', 'config', 'gpg.program', str(program))
            self.check('history')
            self.assertFalse(marker.exists())

    def test_shallow_and_grafted_history_fail_closed(self):
        self.write('source.txt', 'Safe source.\n')
        self.stage('source.txt')
        self.run_command('git', 'commit', '-m', 'Safe revision')
        head = self.run_command('git', 'rev-parse', 'HEAD').stdout.decode()
        (self.repo / '.git/shallow').write_text(head)
        self.check('history', expected=1)
        (self.repo / '.git/shallow').unlink()
        (self.repo / '.git/info/grafts').write_text(head)
        self.check('history', expected=1)

    def test_ambient_scanner_suppression_and_git_dir_injection_are_ignored(self):
        self.write('docs/setup.md', self.secret())
        self.stage('docs/setup.md')
        env = os.environ.copy()
        env['GITLEAKS_CONFIG'] = '/nonexistent-synthetic-policy'
        env['GIT_DIR'] = '/nonexistent-synthetic-repository'
        result = self.run_command('python3', 'scripts/security_check.py', 'staged', expected=1, env=env)
        self.assertNotIn(self.secret().encode(), result.stdout + result.stderr)

    def test_unreviewed_scanner_config_fails_closed(self):
        self.write('docs/setup.md', 'Safe source.\n')
        self.stage('docs/setup.md')
        (self.repo / '.gitleaks.toml').write_text('title = "Synthetic unreviewed policy"\n')
        self.check(expected=1)

    def test_git_selected_commit_index_is_scanned(self):
        self.write('source.txt', 'Safe indexed source.\n')
        self.stage('source.txt')
        self.run_command('git', 'commit', '-m', 'Safe initial revision')
        alternate = self.repo / '.git/commit-index'
        shutil.copy2(self.repo / '.git/index', alternate)
        self.write('source.txt', self.secret())
        env = os.environ.copy()
        env['GIT_INDEX_FILE'] = str(alternate)
        self.run_command('git', 'add', '--', 'source.txt', env=env)
        self.write('source.txt', 'Safe working tree again.\n')
        self.check()
        result = self.run_command('python3', 'scripts/security_check.py', 'staged', expected=1, env=env)
        self.assertNotIn(self.secret().encode(), result.stdout + result.stderr)

    def test_unreviewed_claude_paths_and_local_files_are_blocked_when_staged(self):
        for path in CLAUDE_FORBIDDEN:
            with self.subTest(path=path):
                self.write(path, '{"synthetic": 1}\n')
                self.run_command('git', 'add', '-f', '--', path)
                result = self.check(expected=1)
                self.assertIn(b'Forbidden tracked path', result.stderr)
                self.run_command('git', 'rm', '-q', '--cached', '--', path)
                (self.repo / path).unlink()
        self.write('.claude/settings.json', '{"synthetic": 1}\n')
        self.run_command('git', 'add', '-f', '--', '.claude/settings.json')
        self.run_command('git', 'commit', '-m', 'Synthetic unreviewed settings', expected=1)

    def test_generated_claude_agent_file_is_allowed(self):
        self.write('.claude/agents/qa_engineer.md', '---\nname: qa_engineer\n---\nSafe role text.\n')
        self.stage('.claude/agents/qa_engineer.md')
        self.check()
        self.run_command('git', 'commit', '-m', 'Add generated role file')
        self.check('history')

    def test_claude_local_memory_file_is_git_ignored(self):
        self.write('CLAUDE.local.md', 'Synthetic personal note.\n')
        self.run_command('git', 'check-ignore', 'CLAUDE.local.md')

    def test_unreviewed_claude_paths_in_history_block_push(self):
        for path in CLAUDE_FORBIDDEN:
            with self.subTest(path=path):
                self.fresh_repo()
                self.write(path, '{"synthetic": 1}\n')
                self.run_command('git', 'add', '-f', '--', path)
                # Deliberately simulate an earlier bypass ONLY inside this disposable test repository.
                self.run_command('git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'Synthetic path')
                self.run_command('git', 'rm', '-q', '--', path)
                self.run_command('git', 'commit', '-m', 'Remove synthetic path')
                result = self.check('history', expected=1)
                self.assertIn(b'Forbidden historical path', result.stderr)

    def test_forbidden_claude_rule_truth_table(self):
        from scripts.security_check import forbidden
        allowed = ('.claude/agents/qa_engineer.md', '.codex/agents/x.toml', '.codex/config.toml',
                   'CLAUDE.md', 'docs/claude-code-setup.md', 'tests/test_claude_docs.py')
        blocked = CLAUDE_FORBIDDEN + (
            '.claude/agents/Extra.MD', '.CLAUDE/settings.json', '.Claude/agents/x.md',
            'docs/.claude/settings.json', '.claude', '.claude/agents', 'sub/.mcp.json',
            'claude.local.md', 'sub/CLAUDE.local.md', '.Claude.json', '.CREDENTIALS.json',
        )
        for path in allowed:
            self.assertFalse(forbidden(path), path)
        for path in blocked:
            self.assertTrue(forbidden(path), path)

    def test_codex_path_policy_is_unchanged(self):
        for path in ('.codex/agents/x.toml', '.codex/config.toml'):
            with self.subTest(path=path):
                self.write(path, 'name = "synthetic"\n')
                self.run_command('git', 'add', '-f', '--', path)
                self.check()
        self.run_command('git', 'commit', '-m', 'Add reviewed Codex configuration')
        self.check('history')
        for path in ('.codex/auth.json', '.codex/agents/sub/x.toml', '.codex/agents/x.md'):
            with self.subTest(path=path):
                self.write(path, 'name = "synthetic"\n')
                self.run_command('git', 'add', '-f', '--', path)
                self.check(expected=1)
                self.run_command('git', 'rm', '-q', '--cached', '--', path)

    def test_commit_only_actual_temporary_index_cannot_bypass_scan(self):
        self.write('source.txt', 'Safe indexed source.\n')
        self.stage('source.txt')
        self.run_command('git', 'commit', '-m', 'Safe initial revision')
        self.write('source.txt', self.secret())
        result = self.run_command('git', 'commit', '--only', 'source.txt', '-m', 'Synthetic unstaged contamination', expected=1)
        self.assertNotIn(self.secret().encode(), result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

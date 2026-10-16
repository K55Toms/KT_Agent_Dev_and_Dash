"""Integration tests use disposable repositories and synthetic values only."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SecurityTests(unittest.TestCase):
    def setUp(self):
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


if __name__ == '__main__':
    unittest.main()

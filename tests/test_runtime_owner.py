"""Real OS locking and synthetic boot-source validation, without model work."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard.runtime_owner import RuntimeOwner, boot_identity


class RuntimeOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name).resolve() / 'state'

    def tearDown(self):
        self.temp.cleanup()

    def test_second_owner_rejected_and_file_can_remain_after_exit(self):
        with patch('dashboard.runtime_owner.boot_identity', return_value='boot-digest'):
            with RuntimeOwner(self.path) as first:
                self.assertTrue(first.exclusive)
                self.assertEqual('boot-digest', first.boot_id)
                with self.assertRaisesRegex(ValueError, 'Another dashboard'):
                    with RuntimeOwner(self.path):
                        self.fail('Second owner acquired the lock')
            self.assertFalse(first.exclusive)
            self.assertIsNone(first.boot_id)
            self.assertTrue((self.path / 'dashboard-owner.lock').exists())
            with RuntimeOwner(self.path) as second:
                self.assertTrue(second.exclusive)
                self.assertNotEqual(first.owner_id, second.owner_id)

    def test_link_or_nonprivate_lock_is_rejected(self):
        self.path.mkdir(mode=0o700)
        target = self.path / 'target'
        target.write_text('synthetic')
        lock = self.path / 'dashboard-owner.lock'
        lock.symlink_to(target)
        with self.assertRaises(OSError):
            with RuntimeOwner(self.path):
                self.fail('Linked lock accepted')
        lock.unlink()
        lock.write_text('synthetic')
        lock.chmod(0o644)
        with self.assertRaises(ValueError):
            with RuntimeOwner(self.path):
                self.fail('Nonprivate lock accepted')

    def test_boot_source_failure_never_falls_back_to_generation(self):
        with patch('dashboard.runtime_owner.sys.platform', 'darwin'):
            for output, code in ((b'unavailable', 0), (b'', 1), (b'x' * 129, 0)):
                with self.subTest(output_length=len(output), code=code):
                    result = subprocess.CompletedProcess([], code, stdout=output)
                    with patch('dashboard.runtime_owner.subprocess.run', return_value=result):
                        self.assertIsNone(boot_identity())
            with patch('dashboard.runtime_owner.subprocess.run', side_effect=OSError):
                self.assertIsNone(boot_identity())

    def test_boot_digest_stable_within_boot_changes_between_boots(self):
        outputs = [b'00000000-0000-4000-8000-000000000001\n',
                   b'00000000-0000-4000-8000-000000000001\n',
                   b'00000000-0000-4000-8000-000000000002\n']
        with patch('dashboard.runtime_owner.sys.platform', 'darwin'), patch(
                'dashboard.runtime_owner.subprocess.run', side_effect=[
                    subprocess.CompletedProcess([], 0, stdout=output) for output in outputs]):
            first, same, later = boot_identity(), boot_identity(), boot_identity()
        self.assertEqual(first, same)
        self.assertNotEqual(first, later)
        self.assertEqual(64, len(first))

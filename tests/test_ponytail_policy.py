import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.ponytail_policy import PonytailPolicy, PolicyError, policy_instructions
from dashboard.project_files import FileAccessError
from tests.policy_fixtures import SyntheticPolicy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.source = self.root / '5.3.2/skills/ponytail/SKILL.md'
        self.source.parent.mkdir(parents=True)
        self.bytes = b'Synthetic approved policy.\n'
        self.source.write_bytes(self.bytes)
        self.provider = PonytailPolicy(self.root, digest=hashlib.sha256(self.bytes).hexdigest())

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_approved_bytes_are_scanned_and_immutable(self):
        with patch('dashboard.ponytail_policy.scan_preview') as scan:
            bundle = self.provider.load()
        scan.assert_called_once_with(self.bytes)
        self.assertEqual(self.bytes, bundle.text.encode())
        self.assertEqual(hashlib.sha256(self.bytes).hexdigest(), bundle.digest)
        with self.assertRaises(AttributeError):
            bundle.text = 'different'

    def test_missing_or_changed_source_blocks_every_load(self):
        with patch('dashboard.ponytail_policy.scan_preview'):
            self.provider.load()
            self.source.write_bytes(b'SYNTHETIC_CHANGED_POLICY')
            with self.assertRaises(PolicyError):
                self.provider.load()
            self.source.unlink()
            with self.assertRaises(PolicyError):
                self.provider.load()

    def test_symlink_source_and_symlink_ancestry_are_rejected(self):
        target = self.root / 'other'
        self.source.rename(target)
        self.source.symlink_to(target)
        with self.assertRaises(PolicyError):
            self.provider.load()
        self.source.unlink()
        self.source.parent.rename(self.root / 'other-directory')
        self.source.parent.symlink_to(self.root / 'other-directory', target_is_directory=True)
        with self.assertRaises(PolicyError):
            self.provider.load()

    def test_oversize_hardlink_and_scanner_failures_block(self):
        self.source.write_bytes(b'x' * 32769)
        with self.assertRaises(PolicyError):
            self.provider.load()
        self.source.write_bytes(self.bytes)
        (self.root / 'linked').hardlink_to(self.source)
        with self.assertRaises(PolicyError):
            self.provider.load()
        (self.root / 'linked').unlink()
        for error in (FileAccessError(403, 'SYNTHETIC_PRIVATE'), FileAccessError(503, 'SYNTHETIC_PRIVATE')):
            with patch('dashboard.ponytail_policy.scan_preview', side_effect=error):
                with self.assertRaises(PolicyError) as caught:
                    self.provider.load()
                self.assertNotIn('SYNTHETIC_PRIVATE', str(caught.exception))

    def test_only_pilot_roles_receive_approved_skill_text(self):
        bundle = SyntheticPolicy().load()
        for role in ('backend_developer', 'frontend_developer'):
            instructions = policy_instructions(role, 'Existing role baseline.', bundle)
            self.assertTrue(instructions.startswith('Existing role baseline.'))
            self.assertIn(bundle.text, instructions)
            self.assertIn(bundle.digest, instructions)
        self.assertEqual('Review only.', policy_instructions('code_quality_reviewer', 'Review only.', bundle))

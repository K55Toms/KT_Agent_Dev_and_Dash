import os
from pathlib import Path
import stat
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from dashboard.native_roles import NativeRoles
from dashboard.ponytail_policy import PolicyBundle, PolicyError
from tests.policy_fixtures import SyntheticPolicy
from dashboard.project_files import FileAccessError
from dashboard.server import SAFETY_INSTRUCTIONS, load_roles


class NativeRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        self.native = NativeRoles(self.root)
        self.roles = load_roles()
        self.policy = SyntheticPolicy().load()

    def tearDown(self):
        self.native.close()
        self.temp.cleanup()

    def test_registered_roles_are_private_scanned_allowlisted_and_keep_baseline(self):
        with patch("dashboard.native_roles.scan_preview") as scanner:
            config = self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
            again = self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
        scanner.assert_called_once()
        self.assertEqual(config, again)
        self.assertIs(config["enabled"], True)
        self.assertEqual(3, config["max_concurrent_threads_per_session"])
        self.assertEqual(set(self.roles), set(config) - {"enabled", "max_concurrent_threads_per_session"})
        paths = []
        for role_id, role in self.roles.items():
            path = Path(config[role_id]["config_file"])
            paths.append(path)
            self.assertTrue(path.is_relative_to(self.root))
            self.assertTrue(path.is_absolute())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))
            self.assertEqual(os.getuid(), path.stat().st_uid)
            self.assertEqual(1, path.stat().st_nlink)
            parsed = tomllib.loads(path.read_text())
            self.assertEqual({"model", "model_reasoning_effort", "developer_instructions"}, set(parsed))
            self.assertEqual(role["model"], parsed["model"])
            self.assertEqual(role["reasoning"], parsed["model_reasoning_effort"])
            baseline = SAFETY_INSTRUCTIONS + "\n" + role["instructions"]
            if role_id in {'backend_developer', 'frontend_developer'}:
                self.assertTrue(parsed['developer_instructions'].startswith(baseline))
                self.assertIn(self.policy.text, parsed['developer_instructions'])
            else:
                self.assertEqual(baseline, parsed['developer_instructions'])
            self.assertIn(path.read_bytes(), scanner.call_args.args[0])
        # Returning a config must not expose mutable registration state.
        again["backend_developer"]["config_file"] = "/untrusted"
        self.assertNotEqual("/untrusted", self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)["backend_developer"]["config_file"])
        self.native.close()
        self.assertTrue(all(not path.exists() for path in paths))

    def test_failed_scan_creates_no_snapshot_and_exposes_no_content(self):
        for status in (403, 503):
            with self.subTest(status=status), patch("dashboard.native_roles.scan_preview",
                                                  side_effect=FileAccessError(status, "SYNTHETIC_PRIVATE_SCAN_ERROR")):
                with self.assertRaisesRegex(ValueError, "Native role content checks did not complete") as error:
                    self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
                self.assertNotIn("SYNTHETIC_PRIVATE", str(error.exception))
                self.assertEqual([], list(self.root.iterdir()))

    def test_unknown_roles_models_efforts_and_oversized_text_are_rejected_before_scan(self):
        cases = [dict(self.roles, arbitrary=self.roles["backend_developer"]),
                 {key: value for key, value in self.roles.items() if key != "backend_developer"}]
        for field, value in (("model", "unreviewed-model"), ("reasoning", "arbitrary"),
                             ("instructions", "x" * 32769), ("instructions", None)):
            changed = {key: dict(role) for key, role in self.roles.items()}
            changed["backend_developer"][field] = value
            cases.append(changed)
        for roles in cases:
            with self.subTest(), patch("dashboard.native_roles.scan_preview") as scanner:
                with self.assertRaises(ValueError):
                    self.native.config(roles, SAFETY_INSTRUCTIONS, self.policy)
                scanner.assert_not_called()
                self.assertEqual([], list(self.root.iterdir()))

    def test_symlink_or_nonprivate_runtime_directory_is_rejected(self):
        linked = self.root / "linked"
        actual = self.root / "actual"
        actual.mkdir(mode=0o700)
        linked.symlink_to(actual, target_is_directory=True)
        public = self.root / "public"
        public.mkdir(mode=0o755)
        # mkdir's mode is reduced by the caller's umask; establish the actual
        # nonprivate fixture explicitly so this also tests under umask 077.
        public.chmod(0o755)
        with patch("dashboard.native_roles.scan_preview"):
            for directory in (linked, public):
                with self.subTest(directory=directory.name):
                    candidate = NativeRoles(directory)
                    with self.assertRaises((ValueError, OSError)):
                        candidate.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
                    candidate.close()
        self.assertEqual([], list(actual.iterdir()))
        self.assertEqual([], list(public.iterdir()))

    def test_cached_role_change_blocks_without_removing_previous_snapshots(self):
        with patch('dashboard.native_roles.scan_preview'):
            config = self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
            changed = {key: dict(value) for key, value in self.roles.items()}
            changed['backend_developer']['instructions'] += '\nA different policy context.'
            with self.assertRaises(PolicyError):
                self.native.config(changed, SAFETY_INSTRUCTIONS, self.policy)
        self.assertTrue(Path(config['backend_developer']['config_file']).is_file())

    def test_default_policy_is_revalidated_even_with_cached_snapshots(self):
        provider = SyntheticPolicy()
        with patch('dashboard.native_roles.PonytailPolicy', return_value=provider), \
                patch('dashboard.native_roles.scan_preview'):
            self.native.config(self.roles, SAFETY_INSTRUCTIONS)
            with patch.object(provider, 'load', side_effect=PolicyError('Source changed.')):
                with self.assertRaises(PolicyError):
                    self.native.config(self.roles, SAFETY_INSTRUCTIONS)

    def test_mismatched_policy_bytes_cannot_create_registered_profiles(self):
        forged = PolicyBundle(self.policy.version, self.policy.digest, self.policy.text + 'changed')
        with self.assertRaises(PolicyError):
            self.native.config(self.roles, SAFETY_INSTRUCTIONS, forged)
        self.assertEqual([], list(self.root.iterdir()))

    def test_cached_fingerprint_binds_role_identity_not_only_ordered_prompt_bytes(self):
        with patch('dashboard.native_roles.scan_preview'):
            self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
            swapped = {('frontend_developer' if key == 'backend_developer' else
                        'backend_developer' if key == 'frontend_developer' else key): value
                       for key, value in self.roles.items()}
            with self.assertRaises(PolicyError):
                self.native.config(swapped, SAFETY_INSTRUCTIONS, self.policy)

    def test_cached_file_tampering_or_missing_file_blocks_reuse(self):
        with patch('dashboard.native_roles.scan_preview'):
            config = self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
            path = Path(config['backend_developer']['config_file'])
            path.write_text('SYNTHETIC_CHANGED_SNAPSHOT')
            with self.assertRaises(PolicyError):
                self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)
            path.unlink()
            with self.assertRaises(PolicyError):
                self.native.config(self.roles, SAFETY_INSTRUCTIONS, self.policy)


if __name__ == "__main__":
    unittest.main()

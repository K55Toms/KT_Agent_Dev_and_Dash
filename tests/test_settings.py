import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from dashboard.settings import DEFAULTS, MAX_LOGO_BYTES, SettingsError, SettingsStore


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)


def png(*, width=1, height=1, raw=None, extra=b"", trailing=b"", interlace=0):
    if raw is None:
        raw = (b"\x00" + b"\x10\x20\x30" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, interlace))
            + extra + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"") + trailing)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name)
        (self.root / "dashboard").mkdir()
        self.store = SettingsStore(self.root)
        self.config = self.root / "dashboard" / "config.toml"

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_and_legacy_theme_config(self):
        self.assertEqual(self.store.load(), DEFAULTS)
        self.config.write_text('theme = "rebel"\n')
        self.assertEqual(self.store.load(), DEFAULTS | {"theme": "rebel"})

    def test_round_trip_all_fields_and_private_file(self):
        desired = DEFAULTS | {"dashboard_name": 'My "Quoted" Builders', "theme": "terminal", "github_username": "test-org", "github_visibility": "public"}
        self.assertEqual(self.store.save(desired), desired)
        self.assertEqual(self.store.load(), desired)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertEqual(list(self.config.parent.glob(".config-*")), [])

    def test_unknown_corrupt_or_oversized_config_never_overwritten(self):
        for body in ('theme = "hybrid"\nunsupported = true\n', "not valid = TOML", "x" * 8193):
            with self.subTest(body_length=len(body)):
                self.config.write_text(body)
                with self.assertRaises(SettingsError):
                    self.store.load()
                with self.assertRaises(SettingsError):
                    self.store.save(dict(DEFAULTS))
                self.assertEqual(self.config.read_text(), body)

    def test_strict_schema_and_invalid_values(self):
        invalid = [{}, DEFAULTS | {"unknown": "x"}, DEFAULTS | {"theme": "light"}, DEFAULTS | {"theme": 1},
                   DEFAULTS | {"dashboard_name": ""}, DEFAULTS | {"dashboard_name": "a" * 81},
                   DEFAULTS | {"dashboard_name": " Padded"}, DEFAULTS | {"dashboard_name": "line\nbreak"},
                   DEFAULTS | {"dashboard_name": "spoof\u202ename"}, DEFAULTS | {"logo_path": "/etc/passwd"},
                   DEFAULTS | {"logo_path": "https://example.com/logo.png"}, DEFAULTS | {"github_visibility": "internal"}]
        for username in ("-name", "name-", "a--b", "two words", "user/repo", "a" * 40):
            invalid.append(DEFAULTS | {"github_username": username})
        for data in invalid:
            with self.subTest(field_values=data):
                with self.assertRaises(SettingsError) as error:
                    self.store.save(data)
                self.assertEqual(error.exception.status, 400)
        self.assertFalse(self.config.exists())

    def test_config_paths_reject_symlink_and_hardlink(self):
        outside = self.root / "other.toml"
        outside.write_text('theme = "rebel"\n')
        self.config.symlink_to(outside)
        with self.assertRaises(SettingsError):
            self.store.load()
        with self.assertRaises(SettingsError):
            self.store.save(dict(DEFAULTS))
        self.config.unlink()
        os.link(outside, self.config)
        with self.assertRaises(SettingsError):
            self.store.load()
        self.assertEqual(outside.read_text(), 'theme = "rebel"\n')

    def test_config_parent_symlink_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root / "dashboard", target_is_directory=True)
        unsafe = SettingsStore(self.root, alias / "config.toml")
        with self.assertRaises(SettingsError):
            unsafe.load()

    def test_failed_atomic_replace_preserves_original(self):
        self.store.save(dict(DEFAULTS))
        original = self.config.read_bytes()
        with patch("dashboard.settings.os.replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(SettingsError):
                self.store.save(DEFAULTS | {"theme": "rebel"})
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(list(self.config.parent.glob(".config-*")), [])

    def test_reviewed_secret_policy_blocks_assignments_before_save_and_load(self):
        self.store.save(dict(DEFAULTS))
        original = self.config.read_bytes()
        for field in ("pwd", "access_token", "client_secret", "auth_token", "api-key", "passwd"):
            # Nonfunctional synthetic content only, constructed for scanner regressions.
            synthetic = "Test " + field + "=demo-not-a-real-credential"
            with self.subTest(assignment=field):
                with self.assertRaises(SettingsError) as error:
                    self.store.save(DEFAULTS | {"dashboard_name": synthetic})
                self.assertEqual(error.exception.status, 400)
                self.assertNotIn(synthetic, str(error.exception))
                self.assertEqual(self.config.read_bytes(), original)
                self.config.write_bytes(original.replace(DEFAULTS["dashboard_name"].encode(), synthetic.encode()))
                with self.assertRaises(SettingsError) as error:
                    self.store.load()
                self.assertNotIn(synthetic, str(error.exception))
                self.config.write_bytes(original)
        self.assertEqual(list(self.config.parent.glob(".config-*")), [])

    def test_unavailable_or_wrong_scanner_preserves_previous_config(self):
        self.store.save(dict(DEFAULTS))
        original = self.config.read_bytes()
        for mocked in (patch("dashboard.project_files.shutil.which", return_value=None),
                       patch("dashboard.project_files._bounded_command", return_value=(0, b"unreviewed-version"))):
            with mocked:
                for action in (lambda: self.store.save(DEFAULTS | {"theme": "rebel"}), self.store.load):
                    with self.assertRaises(SettingsError) as error:
                        action()
                    self.assertEqual(error.exception.status, 503)
                self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(list(self.config.parent.glob(".config-*")), [])

    def test_logo_upload_is_immutable_validated_private_and_referenced(self):
        content = png()
        identifier = hashlib.sha256(content).hexdigest()
        path = self.store.upload_logo(content)
        self.assertEqual(path, "/api/logo/" + identifier + ".png")
        self.assertEqual(self.store.read_logo(identifier), content)
        desired = DEFAULTS | {"logo_path": path}
        self.store.save(desired)
        self.assertEqual(self.store.load(), desired)
        self.assertEqual(self.store.upload_logo(content), path)
        location = self.root / ".local" / "branding"
        self.assertEqual(stat.S_IMODE(location.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(location.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((location / (identifier + ".png")).stat().st_mode), 0o600)
        self.assertEqual(len(list(location.iterdir())), 1)

    def test_reject_unsupported_png_and_decompression_limits(self):
        invalid = [b"<svg/>", png(interlace=1), png(width=2049), png(width=0), png(trailing=b"x"),
                   png(raw=b"\x05\x01\x02\x03"), png(raw=b"\x00"), png(raw=b"\x00" * 100000),
                   png(extra=chunk(b"tEXt", b"private metadata")), png(extra=chunk(b"acTL", b"\x00" * 8)),
                   png()[:-1], png() + b"x" * MAX_LOGO_BYTES]
        bad_crc = bytearray(png())
        bad_crc[32] ^= 1
        invalid.append(bytes(bad_crc))
        for content in invalid:
            with self.subTest(content_length=len(content)):
                with self.assertRaises(SettingsError) as error:
                    self.store.upload_logo(content)
                self.assertEqual(error.exception.status, 400)
        self.assertFalse((self.root / ".local").exists())

    def test_nonexistent_tampered_symlink_or_hardlinked_logo_unavailable(self):
        with self.assertRaises(SettingsError):
            self.store.save(DEFAULTS | {"logo_path": "/api/logo/" + "a" * 64 + ".png"})
        content = png()
        identifier = hashlib.sha256(content).hexdigest()
        self.store.upload_logo(content)
        location = self.root / ".local" / "branding" / (identifier + ".png")
        location.write_bytes(b"corrupt")
        with self.assertRaises(SettingsError):
            self.store.read_logo(identifier)
        location.unlink()
        outside = self.root / "other.png"
        outside.write_bytes(content)
        location.symlink_to(outside)
        with self.assertRaises(SettingsError):
            self.store.read_logo(identifier)
        location.unlink()
        os.link(outside, location)
        with self.assertRaises(SettingsError):
            self.store.read_logo(identifier)
        with self.assertRaises(SettingsError):
            self.store.read_logo("../other")

    def test_runtime_symlink_rejected_without_writing_outside(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / ".local").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SettingsError):
            self.store.upload_logo(png())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard import observed_token
from dashboard.observed_token import TokenFile, TokenFileError, default_config_dir


class TokenFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "config"
        self.file = self.directory / observed_token.TOKEN_NAME

    def test_token_created_once_with_modes(self):
        first = TokenFile(self.directory)
        token = first.token()
        self.assertGreaterEqual(len(token), 43)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertEqual(self.file.read_text(), token)
        self.assertEqual(first.token(), token)
        self.assertEqual(TokenFile(self.directory).token(), token)
        self.assertIsNone(first.status())
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [observed_token.TOKEN_NAME])

    def test_token_is_random_per_install(self):
        other = Path(self.temp.name) / "other"
        self.assertNotEqual(TokenFile(self.directory).token(), TokenFile(other).token())

    def test_rotate_invalidates_old_token(self):
        files = TokenFile(self.directory)
        old = files.token()
        new = files.rotate()
        self.assertNotEqual(old, new)
        self.assertFalse(files.matches(old))
        self.assertTrue(files.matches(new))
        self.assertEqual(files.token(), new)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [observed_token.TOKEN_NAME])

    def test_rotate_on_missing_file_creates_one(self):
        files = TokenFile(self.directory)
        new = files.rotate()
        self.assertEqual(files.token(), new)

    def test_matches_is_false_for_other_and_empty_candidates(self):
        files = TokenFile(self.directory)
        token = files.token()
        self.assertTrue(files.matches(token))
        for bad in ("", "x", token[:-1], token + "x", token.upper(), None, 5, b"abc", token.encode(), "\ud800", "é" * 40):
            self.assertFalse(files.matches(bad), repr(bad))

    def test_matches_does_not_create_the_file(self):
        self.assertFalse(TokenFile(self.directory).matches("anything"))
        self.assertFalse(self.file.exists())

    def test_wrong_mode_reports_permissions_and_never_rewrites(self):
        files = TokenFile(self.directory)
        token = files.token()
        os.chmod(self.file, 0o644)
        self.assertEqual(files.status(), "permissions")
        self.assertFalse(files.matches(token))
        with self.assertRaises(TokenFileError) as caught:
            files.token()
        self.assertEqual(caught.exception.reason, "permissions")
        with self.assertRaises(TokenFileError):
            files.rotate()
        self.assertEqual(self.file.read_text(), token)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), [observed_token.TOKEN_NAME])

    def test_open_directory_reports_permissions(self):
        files = TokenFile(self.directory)
        token = files.token()
        os.chmod(self.directory, 0o755)
        self.assertEqual(files.status(), "permissions")
        self.assertFalse(files.matches(token))
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o755)

    def test_symlink_or_foreign_file_reports_unreadable(self):
        files = TokenFile(self.directory)
        token = files.token()
        # foreign owner
        with patch.object(observed_token.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(files.status(), "unreadable")
            self.assertFalse(files.matches(token))
        # hard link
        link = self.directory / "other-name"
        os.link(self.file, link)
        self.assertEqual(files.status(), "unreadable")
        self.assertFalse(files.matches(token))
        link.unlink()
        self.assertIsNone(files.status())
        # symlink in place of the file
        target = Path(self.temp.name) / "target"
        target.write_text(token)
        os.chmod(target, 0o600)
        self.file.unlink()
        os.symlink(target, self.file)
        self.assertEqual(files.status(), "unreadable")
        self.assertFalse(files.matches(token))
        with self.assertRaises(TokenFileError):
            files.token()
        with self.assertRaises(TokenFileError):
            files.rotate()
        self.assertTrue(self.file.is_symlink())
        self.assertEqual(target.read_text(), token)

    def test_symlinked_directory_reports_unreadable(self):
        real = Path(self.temp.name) / "real"
        TokenFile(real).token()
        os.symlink(real, self.directory)
        files = TokenFile(self.directory)
        self.assertEqual(files.status(), "unreadable")
        with self.assertRaises(TokenFileError):
            files.token()

    def test_non_regular_or_malformed_file_reports_unreadable_and_is_kept(self):
        files = TokenFile(self.directory)
        files.token()
        for content in (b"", b"short", b"x" * 5000, b"has space and newline\n" * 3):
            self.file.write_bytes(content)
            os.chmod(self.file, 0o600)
            self.assertEqual(files.status(), "unreadable", content[:10])
            with self.assertRaises(TokenFileError):
                files.token()
            self.assertEqual(self.file.read_bytes(), content)
        self.file.unlink()
        self.file.mkdir()
        self.assertEqual(files.status(), "unreadable")

    def test_token_not_in_repr_or_exceptions(self):
        files = TokenFile(self.directory)
        token = files.token()
        self.assertNotIn(token, repr(files))
        self.assertNotIn(token, str(files))
        os.chmod(self.file, 0o644)
        for call in (files.token, files.rotate):
            with self.assertRaises(TokenFileError) as caught:
                call()
            error = caught.exception
            self.assertNotIn(token, str(error))
            self.assertNotIn(token, repr(error))
            self.assertNotIn(token, repr(error.args))
            self.assertIsNone(error.__cause__)
            self.assertTrue(error.__suppress_context__ or error.__context__ is None)

    def test_creation_does_not_follow_a_planted_symlink(self):
        self.directory.mkdir(mode=0o700)
        target = Path(self.temp.name) / "victim"
        os.symlink(target, self.file)
        with self.assertRaises(TokenFileError):
            TokenFile(self.directory).token()
        self.assertFalse(target.exists())


class DefaultConfigDirTests(unittest.TestCase):
    def test_macos(self):
        with patch.object(observed_token.sys, "platform", "darwin"), patch.object(Path, "home", return_value=Path("/Users/example")):
            self.assertEqual(default_config_dir(), Path("/Users/example/Library/Application Support/KT Agent Dashboard"))

    def test_linux_uses_xdg_then_dot_config(self):
        with patch.object(observed_token.sys, "platform", "linux"), patch.object(Path, "home", return_value=Path("/home/example")):
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg"}):
                self.assertEqual(default_config_dir(), Path("/xdg/kt-agent-dashboard"))
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}):
                self.assertEqual(default_config_dir(), Path("/home/example/.config/kt-agent-dashboard"))
            env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(default_config_dir(), Path("/home/example/.config/kt-agent-dashboard"))
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
                self.assertEqual(default_config_dir(), Path("/home/example/.config/kt-agent-dashboard"))


if __name__ == "__main__":
    unittest.main()

"""Sync guard: generated Codex and Claude role files match team_source, and drift is reported."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_roles.py"
BASELINE = ROOT / "tests" / "fixtures" / "codex_roles_baseline.json"
BASELINE_KEYS = ("name", "description", "model", "model_reasoning_effort", "developer_instructions")

spec = importlib.util.spec_from_file_location("sync_roles", SCRIPT)
sync_roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_roles)
sync = sync_roles.sync


def make_skeleton(directory):
    """Copy the role sources and model policy into a temp repo skeleton."""
    root = Path(directory)
    (root / "team_source").mkdir()
    shutil.copytree(ROOT / "team_source" / "roles", root / "team_source" / "roles")
    shutil.copy(ROOT / "team_source" / "models.toml", root / "team_source" / "models.toml")
    return root


def role_ids(root):
    return sorted(path.stem for path in (root / "team_source" / "roles").glob("*.md"))


def snapshot(root):
    """Every path under root mapped to its bytes (None for directories) and mtime."""
    return {
        str(path.relative_to(root)): (
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
    }


def run_cli(*args, cwd):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True
    )


class SyncRolesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_skeleton(self.tmp.name)

    def test_sync_writes_all_28_files(self):
        self.assertEqual(sync(self.root, check=False), [])
        ids = role_ids(self.root)
        self.assertEqual(len(ids), 14)
        codex = sorted(path.name for path in (self.root / ".codex" / "agents").iterdir())
        claude = sorted(path.name for path in (self.root / ".claude" / "agents").iterdir())
        self.assertEqual(codex, [f"{role_id}.toml" for role_id in ids])
        self.assertEqual(claude, [f"{role_id}.md" for role_id in ids])

    def test_check_passes_after_sync(self):
        sync(self.root, check=False)
        self.assertEqual(sync(self.root, check=True), [])

    def test_check_fails_naming_the_edited_file(self):
        sync(self.root, check=False)
        edited = self.root / ".claude" / "agents" / "backend_developer.md"
        edited.write_bytes(edited.read_bytes() + b"hand edit\n")
        problems = sync(self.root, check=True)
        self.assertEqual(len(problems), 1)
        self.assertIn(".claude/agents/backend_developer.md", problems[0])
        self.assertIn("stale", problems[0])

    def test_check_reports_missing_file(self):
        sync(self.root, check=False)
        missing = self.root / ".codex" / "agents" / "qa_engineer.toml"
        missing.unlink()
        problems = sync(self.root, check=True)
        self.assertEqual(len(problems), 1)
        self.assertIn(".codex/agents/qa_engineer.toml", problems[0])
        self.assertIn("missing", problems[0])
        self.assertFalse(missing.exists())

    def test_check_reports_extra_agent_file_in_both_directories(self):
        sync(self.root, check=False)
        extra_md = self.root / ".claude" / "agents" / "extra_role.md"
        extra_toml = self.root / ".codex" / "agents" / "extra_role.toml"
        extra_md.write_text("extra\n", encoding="utf-8")
        extra_toml.write_text("extra = 1\n", encoding="utf-8")
        for check in (True, False):
            with self.subTest(check=check):
                problems = sync(self.root, check=check)
                self.assertEqual(len(problems), 2)
                self.assertTrue(
                    any(".claude/agents/extra_role.md" in p and "unexpected" in p for p in problems)
                )
                self.assertTrue(
                    any(".codex/agents/extra_role.toml" in p and "unexpected" in p for p in problems)
                )
                self.assertTrue(extra_md.exists())
                self.assertTrue(extra_toml.exists())

    def test_unrelated_plain_files_in_agent_folders_are_ignored(self):
        sync(self.root, check=False)
        for directory in (".codex/agents", ".claude/agents"):
            (self.root / directory / ".DS_Store").write_bytes(b"\x00\x01")
            (self.root / directory / "notes.txt").write_text("scratch\n", encoding="utf-8")
        before = snapshot(self.root)
        for check in (True, False):
            with self.subTest(check=check):
                self.assertEqual(sync(self.root, check=check), [])
        self.assertEqual(snapshot(self.root), before)
        with tempfile.TemporaryDirectory() as elsewhere:
            for args in (("--check",), ()):
                result = run_cli("--root", str(self.root), *args, cwd=elsewhere)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_extra_subdirectory_in_agent_folders_is_reported_and_kept(self):
        sync(self.root, check=False)
        extras = [self.root / ".codex" / "agents" / "old", self.root / ".claude" / "agents" / "old"]
        for extra in extras:
            extra.mkdir()
        for check in (True, False):
            with self.subTest(check=check):
                problems = sync(self.root, check=check)
                self.assertEqual(len(problems), 2)
                self.assertTrue(any(".codex/agents/old" in p and "unexpected" in p for p in problems))
                self.assertTrue(any(".claude/agents/old" in p and "unexpected" in p for p in problems))
                self.assertTrue(all(extra.is_dir() for extra in extras))

    def test_wrong_suffix_is_not_reported_in_the_other_folder(self):
        sync(self.root, check=False)
        (self.root / ".claude" / "agents" / "extra.toml").write_text("x = 1\n", encoding="utf-8")
        (self.root / ".codex" / "agents" / "extra.md").write_text("x\n", encoding="utf-8")
        self.assertEqual(sync(self.root, check=True), [])

    def test_source_edit_without_sync_is_flagged_stale_in_both_harnesses(self):
        sync(self.root, check=False)
        source = self.root / "team_source" / "roles" / "qa_engineer.md"
        source.write_text(source.read_text(encoding="utf-8") + "A new shared line.\n", encoding="utf-8")
        problems = sync(self.root, check=True)
        self.assertEqual(len(problems), 2)
        self.assertTrue(
            all("stale" in problem for problem in problems), problems
        )
        self.assertTrue(any(".codex/agents/qa_engineer.toml" in p for p in problems))
        self.assertTrue(any(".claude/agents/qa_engineer.md" in p for p in problems))

    def test_check_writes_nothing(self):
        before = snapshot(self.root)
        problems = sync(self.root, check=True)
        self.assertEqual(len(problems), 28)
        self.assertTrue(all("missing" in problem for problem in problems))
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".codex").exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_sync_is_idempotent(self):
        sync(self.root, check=False)
        before = snapshot(self.root)
        self.assertEqual(sync(self.root, check=False), [])
        self.assertEqual(snapshot(self.root), before)

    def test_bad_role_writes_nothing(self):
        path = self.root / "team_source" / "roles" / "qa_engineer.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n<!-- codex-only -->\nunclosed\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            sync(self.root, check=False)
        self.assertFalse((self.root / ".codex").exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_works_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            result = run_cli("--check", cwd=elsewhere)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repository_roles_are_in_sync(self):
        self.assertEqual(sync(ROOT, check=True), [])

    def test_dashboard_load_roles_equals_baseline_after_sync(self):
        sync(self.root, check=False)
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        loaded = {}
        for path in sorted((self.root / ".codex" / "agents").glob("*.toml")):
            role = tomllib.loads(path.read_text())
            loaded[path.stem] = {
                "name": role["name"],
                "model": role["model"],
                "model_reasoning_effort": role["model_reasoning_effort"],
                "developer_instructions": role["developer_instructions"],
                "description": role.get("description", ""),
            }
        self.assertEqual(sorted(loaded), sorted(baseline))
        self.assertEqual(len(loaded), 14)
        for role_id, expected in baseline.items():
            with self.subTest(role=role_id):
                self.assertEqual(sorted(expected), sorted(BASELINE_KEYS))
                self.assertEqual(loaded[role_id], {key: expected[key] for key in BASELINE_KEYS})

    def test_extension_rule_is_case_insensitive(self):
        sync(self.root, check=False)
        extra = self.root / ".claude" / "agents" / "Extra.MD"
        extra.write_text("---\nname: extra\n---\n", encoding="utf-8")
        for check in (True, False):
            with self.subTest(check=check):
                problems = sync(self.root, check=check)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(".claude/agents/Extra.MD", problems[0])
                self.assertIn("unexpected", problems[0])
                self.assertTrue(extra.exists())

    def test_ds_store_is_still_ignored_next_to_an_upper_case_name(self):
        sync(self.root, check=False)
        (self.root / ".claude" / "agents" / ".DS_Store").write_bytes(b"\x00\x01")
        (self.root / ".codex" / "agents" / ".DS_Store").write_bytes(b"\x00\x01")
        (self.root / ".claude" / "agents" / "README.TXT").write_text("x\n", encoding="utf-8")
        self.assertEqual(sync(self.root, check=True), [])

    def test_cli_reports_drift_exit_code(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            written = run_cli("--root", str(self.root), cwd=elsewhere)
            self.assertEqual(written.returncode, 0, written.stderr)
            clean = run_cli("--root", str(self.root), "--check", cwd=elsewhere)
            self.assertEqual(clean.returncode, 0, clean.stderr)
            edited = self.root / ".codex" / "agents" / "product_manager.toml"
            edited.write_bytes(edited.read_bytes() + b"# edit\n")
            stale = run_cli("--root", str(self.root), "--check", cwd=elsewhere)
        self.assertEqual(stale.returncode, 1)
        self.assertIn("product_manager.toml", stale.stderr)
        self.assertIn("stale", stale.stderr)


class UnsafeOutputPathTests(unittest.TestCase):
    """F1/F10: symlinks or non-regular files at output locations stop the sync before any write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "root").mkdir()
        self.root = make_skeleton(self.base / "root")
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def assert_unsafe_in_both_modes(self, name):
        for check in (True, False):
            with self.subTest(check=check):
                problems = sync(self.root, check=check)
                self.assertTrue(
                    any(name in p and "unsafe" in p for p in problems), problems
                )

    def test_symlinked_output_file_is_refused_and_target_untouched(self):
        sync(self.root, check=False)
        target = self.outside / "target.sh"
        target.write_bytes(b"#!/bin/sh\necho original\n")
        mtime = target.stat().st_mtime_ns
        link = self.root / ".claude" / "agents" / "qa_engineer.md"
        link.unlink()
        link.symlink_to(target)
        before = snapshot(self.root)
        self.assert_unsafe_in_both_modes(".claude/agents/qa_engineer.md")
        self.assertEqual(target.read_bytes(), b"#!/bin/sh\necho original\n")
        self.assertEqual(target.stat().st_mtime_ns, mtime)
        self.assertTrue(link.is_symlink())
        self.assertEqual(snapshot(self.root), before)

    def test_symlinked_agents_directory_is_refused_and_nothing_written_outside(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "agents").symlink_to(self.outside, target_is_directory=True)
        self.assert_unsafe_in_both_modes(".claude/agents")
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertFalse((self.root / ".codex").exists())

    def test_symlinked_top_level_directory_is_refused(self):
        (self.root / ".codex").symlink_to(self.outside, target_is_directory=True)
        self.assert_unsafe_in_both_modes(".codex")
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertFalse((self.root / ".claude").exists())

    def test_directory_at_an_output_file_name_aborts_before_any_write(self):
        (self.root / ".claude" / "agents" / "qa_engineer.md").mkdir(parents=True)
        before = snapshot(self.root)
        self.assert_unsafe_in_both_modes(".claude/agents/qa_engineer.md")
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".codex").exists())
        self.assertEqual(
            [p.name for p in (self.root / ".claude" / "agents").iterdir()], ["qa_engineer.md"]
        )

    def test_directory_at_an_output_name_after_a_sync_changes_no_other_file(self):
        sync(self.root, check=False)
        source = self.root / "team_source" / "roles" / "backend_developer.md"
        source.write_text(source.read_text(encoding="utf-8") + "New line.\n", encoding="utf-8")
        blocker = self.root / ".codex" / "agents" / "qa_engineer.toml"
        blocker.unlink()
        blocker.mkdir()
        before = snapshot(self.root)
        self.assert_unsafe_in_both_modes(".codex/agents/qa_engineer.toml")
        self.assertEqual(snapshot(self.root), before)

    def test_interrupted_write_leaves_no_temp_file_and_no_partial_file(self):
        real_replace = os.replace
        calls = []

        def failing_replace(src, dst):
            calls.append(dst)
            if len(calls) == 5:
                raise OSError("synthetic disk full")
            return real_replace(src, dst)

        expected = {
            name: text.encode("utf-8") for name, text in sync_roles.render_all(self.root).items()
        }
        with mock.patch.object(sync_roles.os, "replace", failing_replace):
            with self.assertRaises(OSError):
                sync(self.root, check=False)
        self.assertEqual(len(calls), 5)
        written = 0
        for directory in (".codex/agents", ".claude/agents"):
            for entry in (self.root / directory).iterdir():
                name = f"{directory}/{entry.name}"
                self.assertIn(name, expected, f"stray entry left behind: {name}")
                self.assertEqual(entry.read_bytes(), expected[name], name)
                written += 1
        self.assertEqual(written, 4)
        self.assertEqual(sync(self.root, check=False), [])
        self.assertEqual(sync(self.root, check=True), [])

    def test_written_files_get_the_same_permissions_as_a_plain_write(self):
        sync(self.root, check=False)
        reference = self.base / "reference.txt"
        reference.write_text("x\n", encoding="utf-8")
        expected = reference.stat().st_mode & 0o777
        for name in (".claude/agents/qa_engineer.md", ".codex/agents/qa_engineer.toml"):
            mode = (self.root / name).stat().st_mode & 0o777
            self.assertEqual(oct(mode), oct(expected), name)

    def test_cli_prints_the_unsafe_problem_and_exits_1(self):
        sync(self.root, check=False)
        link = self.root / ".codex" / "agents" / "product_manager.toml"
        link.unlink()
        link.symlink_to(self.outside / "missing-target.toml")
        with tempfile.TemporaryDirectory() as elsewhere:
            for args in (("--check",), ()):
                with self.subTest(args=args):
                    result = run_cli("--root", str(self.root), *args, cwd=elsewhere)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(".codex/agents/product_manager.toml: unsafe", result.stderr)
        self.assertFalse((self.outside / "missing-target.toml").exists())


if __name__ == "__main__":
    unittest.main()

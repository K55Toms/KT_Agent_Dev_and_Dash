"""Sync guard: generated Codex and Claude role files match team_source, and drift is reported."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

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


if __name__ == "__main__":
    unittest.main()

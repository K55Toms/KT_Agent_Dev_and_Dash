"""CI guard: the workflow runs the project checks, stays least-privilege and pinned (finding F2)."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
OWNER = "@K55Toms"
OWNED_PATHS = (
    ".github/",
    "AGENTS.md",
    "CLAUDE.md",
    "SECURITY.md",
    "scripts/",
    ".githooks/",
    ".gitleaks.toml",
    "team_source/",
    ".codex/",
    ".claude/",
)
REQUIRED_COMMANDS = (
    "python3 -I scripts/sync_roles.py --check",
    "python3 -m unittest discover -s tests",
    "node --test tests/*.js",
    "python3 -I scripts/security_check.py history",
)
GITLEAKS_VERSION = "8.30.1"


def workflow_text():
    return WORKFLOW.read_text(encoding="utf-8")


class WorkflowTests(unittest.TestCase):
    def test_workflow_exists(self):
        self.assertTrue(WORKFLOW.is_file(), "missing .github/workflows/ci.yml")

    def test_runs_on_pull_requests_and_main_pushes(self):
        text = workflow_text()
        self.assertRegex(text, r"(?m)^on:\n(?:  .*\n)*?  pull_request:")
        self.assertRegex(text, r"(?m)^  push:\n    branches: \[main\]")

    def test_never_uses_pull_request_target_or_secrets(self):
        text = workflow_text()
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("secrets.", text)

    def test_top_level_permissions_are_read_only(self):
        text = workflow_text()
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read\n")
        self.assertNotRegex(text, r"(?m)^\s+(?:contents|pull-requests|id-token): write")

    def test_every_action_is_pinned_to_a_full_commit_sha(self):
        uses = re.findall(r"(?m)^\s*-?\s*uses:\s*(\S+)", workflow_text())
        self.assertTrue(uses, "expected at least one action")
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$", ref)

    def test_checkout_does_not_persist_credentials(self):
        text = workflow_text()
        self.assertEqual(text.count("actions/checkout@"), text.count("persist-credentials: false"))

    def test_runs_every_required_command(self):
        text = workflow_text()
        for command in REQUIRED_COMMANDS:
            self.assertIn(command, text)

    def test_python_tests_use_an_empty_config_home(self):
        self.assertIn("XDG_CONFIG_HOME", workflow_text())

    def test_python_tests_ignore_system_and_global_git_config(self):
        # The runner image configures git-lfs filters system-wide, which the dashboard refuses.
        text = workflow_text()
        self.assertIn('GIT_CONFIG_NOSYSTEM: "1"', text)
        self.assertIn("GIT_CONFIG_GLOBAL: /dev/null", text)

    def test_security_job_scans_full_history(self):
        self.assertRegex(workflow_text(), r"fetch-depth: 0")

    def test_gitleaks_is_the_reviewed_version_and_checksum_verified(self):
        text = workflow_text()
        self.assertIn(f"v{GITLEAKS_VERSION}", text)
        self.assertRegex(text, r"[0-9a-f]{64}\s+gitleaks_" + re.escape(GITLEAKS_VERSION))
        self.assertIn("sha256sum -c", text)

    def test_tests_job_runs_on_macos_with_the_reviewed_gitleaks(self):
        # The suite assumes macOS (/private/tmp) and the reviewed Gitleaks on PATH.
        text = workflow_text()
        self.assertRegex(text, r"(?m)^  tests:\n    name: tests\n    runs-on: macos-\d+(?: #.*)?\n")
        self.assertRegex(text, r"[0-9a-f]{64}\s+gitleaks_" + re.escape(GITLEAKS_VERSION) + r"_darwin_arm64")
        self.assertIn("shasum -a 256 -c", text)

    def test_job_names_are_stable_for_branch_protection(self):
        text = workflow_text()
        for job in ("tests", "security"):
            self.assertRegex(text, rf"(?m)^  {job}:\n    name: {job}\n")


class CodeownersTests(unittest.TestCase):
    def test_codeowners_exists(self):
        self.assertTrue(CODEOWNERS.is_file(), "missing .github/CODEOWNERS")

    def test_every_protected_path_has_the_owner(self):
        entries = {}
        for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                path, *owners = line.split()
                entries[path] = owners
        for path in OWNED_PATHS:
            self.assertEqual(entries.get("/" + path), [OWNER], path)


if __name__ == "__main__":
    unittest.main()

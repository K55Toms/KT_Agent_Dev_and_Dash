"""Documentation guard: the Claude Code entry point and setup guide exist and stay honest."""

from pathlib import Path
import re
import unittest

from dashboard.project_files import FileAccessError, scan_preview

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = ROOT / "CLAUDE.md"
SETUP = ROOT / "docs" / "claude-code-setup.md"
README = ROOT / "README.md"
TEAM = ROOT / "docs" / "team.md"
SYNC = "python3 scripts/sync_roles.py"
DIFFERENCES = "## Claude Code differences"
POINTER = "## Claude Code"
INSTALL_PREFIXES = ("claude plugin", "npx", "npm install", "pip install", "/plugin")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def read(path):
    return path.read_text(encoding="utf-8")


def section(text, heading):
    """Return the body of a level-2 section, from its heading to the next level-2 heading."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1 : end])


class ClaudeDocsTests(unittest.TestCase):
    def test_claude_md_imports_agents_md(self):
        lines = [line for line in read(CLAUDE_MD).splitlines() if line.strip()]
        self.assertEqual(lines[0], "@AGENTS.md")

    def test_claude_md_differences_section_says_ponytail_and_ui_skills_not_used(self):
        body = section(read(CLAUDE_MD), DIFFERENCES)
        self.assertIsNotNone(body, "missing section: " + DIFFERENCES)
        self.assertIn("Ponytail", body)
        self.assertIn("ui-skills", body)
        self.assertRegex(body, r"(?i)do(es)? not apply|not used")

    def test_claude_md_says_roles_are_generated_and_names_the_sync_command(self):
        text = read(CLAUDE_MD)
        self.assertIn("team_source/", text)
        self.assertIn(SYNC, text)

    def test_claude_md_names_reviewer_tools_and_model_policy_scope(self):
        text = read(CLAUDE_MD)
        self.assertIn("Read, Grep, Glob", text)
        self.assertIn("docs/model-policy.md", text)
        self.assertRegex(text, r"docs/model-policy\.md[^\n]*Codex")

    def test_setup_doc_mentions_sync_command_superpowers_and_not_supported_yet(self):
        text = read(SETUP)
        self.assertTrue(text.startswith("# Claude Code setup"))
        self.assertIn(SYNC, text)
        self.assertIn("superpowers", text)
        self.assertIn("6.4.2", text)
        self.assertIsNotNone(section(text, "## What is not supported yet"))
        self.assertIsNotNone(section(text, "## Verification status"))

    def test_setup_doc_does_not_invent_install_commands(self):
        for number, line in enumerate(read(SETUP).splitlines(), 1):
            stripped = line.strip().lstrip("$ ").lstrip()
            self.assertFalse(
                stripped.startswith(INSTALL_PREFIXES), f"line {number} looks like an install command"
            )

    def test_pointer_sections_exist_in_readme_and_team_doc(self):
        for path in (README, TEAM):
            body = section(read(path), POINTER)
            self.assertIsNotNone(body, f"{path.name} lacks {POINTER}")
            self.assertIn("claude-code-setup.md", body, path.name)

    def test_relative_links_resolve(self):
        sources = [
            (CLAUDE_MD, read(CLAUDE_MD)),
            (SETUP, read(SETUP)),
            (README, section(read(README), POINTER) or ""),
            (TEAM, section(read(TEAM), POINTER) or ""),
        ]
        checked = 0
        for path, text in sources:
            for target in LINK.findall(text):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                relative = target.split("#", 1)[0]
                checked += 1
                self.assertTrue(
                    (path.parent / relative).exists(), f"{path.name}: broken link {target}"
                )
        self.assertGreater(checked, 0)

    def test_new_docs_contain_no_secret_shaped_text(self):
        for path in (CLAUDE_MD, SETUP):
            try:
                scan_preview(path.read_bytes())
            except FileAccessError as error:
                self.fail(f"{path.name}: scanner reported a finding or was unavailable: {error}")

    def test_no_machine_specific_paths(self):
        for path in (CLAUDE_MD, SETUP):
            text = read(path)
            self.assertNotIn("/Users/", text, path.name)
            self.assertNotIn("/private/tmp", text, path.name)


if __name__ == "__main__":
    unittest.main()

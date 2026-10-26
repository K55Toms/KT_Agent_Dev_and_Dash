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
EVIDENCE = "superpowers/evidence/2026-10-26-phase-1-live.md"
INSTALL_PREFIXES = ("claude plugin", "npx", "npm install", "pip install", "/plugin")
QUICK_START = "## Quick start"
CODEX_USERS = "## Changes for existing Codex users"
RUNBOOK = (
    "## Add a role",
    "## Change a model or effort",
    "## When --check fails",
    "## Run the checks",
)
TIME_WORDS = re.compile(r"(?i)\b(now|currently)\b")
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
        # The exclusion is scoped to one paragraph, not the whole last heading of AGENTS.md.
        flat = " ".join(body.split())
        self.assertIn("first paragraph under `### Ponytail pilot`", flat)
        self.assertIn("Backend and Frontend default to Ponytail Full", flat)
        self.assertIn("Everything after it in that file", flat)
        self.assertIn("still applies", flat)

    def test_agents_md_ponytail_anchor_has_not_drifted(self):
        agents = read(ROOT / "AGENTS.md")
        self.assertIn("### Ponytail pilot", agents)
        self.assertIn("Backend and Frontend default to Ponytail Full", agents)
        self.assertIn("no savings are assumed", agents)
        self.assertIn("read its TOML", agents)

    def test_claude_md_bash_wording_and_markdown_role_files(self):
        text = read(CLAUDE_MD)
        self.assertIn("write route once Bash is approved", text)
        self.assertNotIn("lists Bash can write", text)
        self.assertRegex(text, r"(?s)TOML.*Markdown")
        self.assertIn("write route once", read(SETUP))
        self.assertRegex(read(SETUP), r"(?s)TOML.*Markdown|Markdown.*TOML")

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

    def test_setup_doc_links_live_evidence_and_it_exists(self):
        text = read(SETUP)
        self.assertIn("](" + EVIDENCE + ")", text)
        self.assertTrue((SETUP.parent / EVIDENCE).exists())
        self.assertIn("](docs/" + EVIDENCE + ")", read(CLAUDE_MD))

    def test_setup_doc_marks_live_checks_observed_with_their_limits(self):
        flat = " ".join(read(SETUP).split())
        self.assertNotIn("have not been run against the live API", flat)
        rows = {
            line.split("|")[1].strip(): line
            for line in read(SETUP).splitlines()
            if line.startswith("| ") and line.count("|") >= 4
        }
        for key in ("opus/medium", "sonnet/high", "sonnet/medium", "opus/low", "disallowedTools", "differences section"):
            matching = [row for name, row in rows.items() if key in name]
            self.assertTrue(matching, "no verification row mentions " + key)
            for row in matching:
                self.assertIn("Observed", row, key)
                self.assertNotIn("Not verified", row, key)
        self.assertIn("one run per condition", flat)
        self.assertIn("2.1.310", flat)
        self.assertIn("claude-opus-5-5", flat)
        self.assertIn("claude-sonnet-5-5", flat)

    def test_setup_doc_keeps_the_honest_limits(self):
        flat = " ".join(read(SETUP).split())
        self.assertRegex(flat, r"\| `fable` as a working model \| Not verified")
        self.assertRegex(flat, r"removes only the `Agent` tool")
        self.assertIn("not blocked", flat)
        for limit in ("Effort values other than", "Interactive mode", "AskUserQuestion", "CLAUDE_EFFORT"):
            self.assertIn(limit, flat)
        self.assertIn("| Auto-mode behaviour | Not verified |", flat)
        self.assertIn("| Interactive mode | Not verified |", flat)
        self.assertIn("| `AskUserQuestion` not being available in subagents | Not verified |", flat)
        self.assertRegex(flat, r"CLAUDE_EFFORT` variable affects anything \| Not verified \|[^|]*matched the role files")
        self.assertRegex(flat, r"(?i)advisor[^.]*docs-sourced|docs-sourced[^.]*advisor")

    def test_docs_say_subagents_receive_claude_md_and_agents_md(self):
        for path in (CLAUDE_MD, SETUP):
            flat = " ".join(read(path).split())
            self.assertRegex(flat, r"(?i)subagents receive[^.]*CLAUDE\.md[^.]*AGENTS\.md", path.name)
            self.assertRegex(flat, r"(?i)switched off[^.]*not removed|not removed", path.name)
            self.assertIn("Roles observed (including `security_reviewer`", flat, path.name)

    def test_claude_md_no_longer_claims_untested_status(self):
        flat = " ".join(read(CLAUDE_MD).split())
        self.assertNotIn("not yet been exercised", flat)
        self.assertNotIn("has not been tested in a live run", flat)
        self.assertRegex(flat, r"(?i)observed")
        self.assertRegex(flat, r"removes only the `Agent` tool")

    def test_docs_say_codex_files_carry_a_generated_header_and_hand_edits_are_flagged(self):
        readme = " ".join((section(read(README), POINTER) or "").split())
        self.assertIn("Each `.codex/agents/*.toml` file starts with a generated-file header", readme)
        self.assertNotRegex(readme, TIME_WORDS)
        self.assertIn("hand edits are reverted by the next sync and flagged by `--check`", readme)
        codex_users = " ".join((section(read(SETUP), CODEX_USERS) or "").split())
        self.assertIn("two-line generated-file header", codex_users)
        self.assertIn("hand edits are reverted by the next sync and flagged by `--check`", codex_users)

    def test_no_machine_specific_paths(self):
        for path in (CLAUDE_MD, SETUP):
            text = read(path)
            self.assertNotIn("/Users/", text, path.name)
            self.assertNotIn("/private/tmp", text, path.name)

    def test_quick_start_precedes_generating_and_gives_the_check_and_a_marked_example(self):
        text = read(SETUP)
        body = section(text, QUICK_START)
        self.assertIsNotNone(body, "missing section: " + QUICK_START)
        self.assertLess(text.index(QUICK_START), text.index("## Generating the roles"))
        flat = " ".join(body.split())
        for needle in ("signed in", "Python 3", "repository root", "CLAUDE.md", "superpowers",
                       "python3 scripts/sync_roles.py --check", "role files are in sync",
                       "Act as Chief of Staff"):
            self.assertIn(needle, flat)
        self.assertRegex(flat, r"(?i)example, not verified behaviou?r")

    def test_setup_doc_states_the_observation_conditions_once_near_the_top(self):
        text = read(SETUP)
        top = text[: text.index("## ")]
        flat = " ".join(top.split())
        self.assertIn("headless `-p` mode on Claude Code 2.1.310, one run per condition", flat)
        self.assertEqual(" ".join(text.split()).count("headless `-p` mode on Claude Code 2.1.310, one run per condition"), 1)

    def test_codex_user_section_has_four_bullets_and_the_description_change(self):
        body = section(read(SETUP), CODEX_USERS)
        self.assertIsNotNone(body, "missing section: " + CODEX_USERS)
        bullets = [line for line in body.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), 4)
        flat = " ".join(body.split())
        self.assertIn("On-demand escalation specialist", flat)
        self.assertIn("`gpt-6-astra`", flat)
        self.assertIn(SYNC + " --check", flat)

    def test_runbook_sections_exist_and_cover_the_checked_procedures(self):
        text = read(SETUP)
        bodies = {heading: section(text, heading) for heading in RUNBOOK}
        for heading, body in bodies.items():
            self.assertIsNotNone(body, "missing section: " + heading)
        add = " ".join(bodies["## Add a role"].split())
        for needle in ("team_source/roles/<id>.md", '"editor"', '"reviewer"', "file stem",
                       "[<id>.codex]", "[<id>.claude]", "PROFILES", "dashboard/team.py",
                       "does not check this", "tests/test_team_source_migration.py", "14 roles"):
            self.assertIn(needle, add)
        change = " ".join(bodies["## Change a model or effort"].split())
        for needle in ("team_source/models.toml", "gpt-6.1-sol", "xhigh", "haiku", "max",
                       "low, medium and high", "silently ignores", "guard"):
            self.assertIn(needle, change)
        failing = " ".join(bodies["## When --check fails"].split())
        for needle in ("missing", "stale", "unexpected", "never deletes", "exits 1",
                       ".DS_Store", "RoleSourceError", "PolicyError", "writes nothing"):
            self.assertIn(needle, failing)
        checks = " ".join(bodies["## Run the checks"].split())
        for needle in (SYNC + " --check", "python3 -m unittest discover -s tests",
                       "node --test tests/*.js", "zero tests", "Node 26", "tests/test_git_service.py",
                       "`.env`", "scripts/security_check.py staged", "scripts/security_check.py history",
                       "XDG_CONFIG_HOME"):
            self.assertIn(needle, checks)

    def test_new_sections_avoid_time_relative_words(self):
        text = read(SETUP)
        for heading in (QUICK_START, CODEX_USERS) + RUNBOOK:
            body = section(text, heading) or ""
            self.assertIsNone(TIME_WORDS.search(body), heading)

    def test_setup_doc_wording_fixes(self):
        flat = " ".join(read(SETUP).split())
        self.assertIn("come from `team_source/models.toml`", flat)
        self.assertIn("`profile`", flat)
        self.assertIn("`code_quality_reviewer`", flat)
        self.assertRegex(flat, r"(?i)coordinator or `qa_engineer` runs")
        self.assertIn("opus/high", flat)
        self.assertRegex(flat, r"R2, R3, R8, R9 and S5")
        self.assertIn("never run", flat)
        self.assertIn("replaces no role", flat)
        self.assertRegex(flat, r"Open question[^.]*\.claude/agents/\*\.md[^.]*running session")

    def test_docs_say_agents_md_ponytail_and_codex_text_is_visible_to_subagents(self):
        for path in (CLAUDE_MD, SETUP):
            flat = " ".join(read(path).split())
            self.assertIn("Ponytail paragraph and the Codex references in `AGENTS.md` are visible", flat, path.name)
            self.assertIn("`ui-skills` only to exclude it", flat, path.name)
            self.assertNotIn("AGENTS.md contains", flat, path.name)

    def test_claude_md_closing_links_to_setup_instead_of_evidence_narrative(self):
        text = read(CLAUDE_MD)
        self.assertNotIn("2.1.310", text)
        self.assertNotIn("R1 in", text)
        self.assertIn("in context and understood, not that every part is obeyed", " ".join(text.split()))
        self.assertIn("](docs/claude-code-setup.md)", text)

    def test_claude_md_bullets_are_not_wrapped_mid_sentence_awkwardly(self):
        text = read(CLAUDE_MD)
        for fragment in ("Evaluation recording pilot outcomes. Everything\n",
                         "removed. Roles observed (including `security_reviewer`,\n"):
            self.assertNotIn(fragment, text)


if __name__ == "__main__":
    unittest.main()

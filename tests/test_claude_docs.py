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


def section_from(text, start, end):
    """Text from the first ``start`` to the next ``end`` (or the end of the text); empty when ``start`` is missing."""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


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
        self.assertIn("Python 3.11 or newer", flat)
        for needle in ("signed in", "Python 3", "repository root", "CLAUDE.md", "superpowers",
                       "python3 scripts/sync_roles.py --check", "role files are in sync",
                       "Act as Chief of Staff"):
            self.assertIn(needle, flat)
        self.assertRegex(flat, r"(?i)example, not verified behaviou?r")

    def test_setup_doc_states_the_observation_conditions_once_near_the_top(self):
        text = read(SETUP)
        top = " ".join(text[: text.index("## ")].split())
        live = "The live runs (R1 to R10) were headless `-p` on Claude Code 2.1.310, one run per condition"
        self.assertIn(live, top)
        self.assertEqual(" ".join(text.split()).count(live), 1)
        self.assertIn("spikes S1, S2 and S4 ran on 2.1.296", top)
        self.assertIn("S2 also has owner-run interactive checks (one observation per condition)", top)
        self.assertNotIn("All Claude behaviour", " ".join(text.split()))
        self.assertNotIn("All Claude behaviour", read(CLAUDE_MD))

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
        for needle in ("(display name, description)", "tests/test_team.py", "role files written (28 files)",
                       "docs/team.md", "docs/model-policy.md"):
            self.assertIn(needle, add)
        for needle in ("team_source/roles/<id>.md", '"editor"', '"reviewer"', "file stem",
                       "[<id>.codex]", "[<id>.claude]", "PROFILES", "dashboard/team.py",
                       "does not check this", "tests/test_team_source_migration.py", "14 roles"):
            self.assertIn(needle, add)
        change = " ".join(bodies["## Change a model or effort"].split())
        for needle in ("team_source/models.toml", "gpt-6.1-sol", "xhigh", "haiku", "max",
                       "low, medium and high", "silently ignores", "guard"):
            self.assertIn(needle, change)
        failing = " ".join(bodies["## When --check fails"].split())
        for needle in ("missing", "stale", "unexpected", "never deletes",
                       "prints one problem per line to standard error and exits 1",
                       "plain sync also exits 1", ".DS_Store", "RoleSourceError", "PolicyError",
                       "tomllib.TOMLDecodeError", "writes nothing",
                       "flags only its own extension", "`.toml` in `.codex/agents/`",
                       "`.md` in `.claude/agents/`", "any directory"):
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
        self.assertIn("(`backend_developer` in R2, R8 and R9, `security_reviewer` in R3)", flat)
        self.assertIn("(`qa_engineer` in R4, `chief_of_staff` in R10)", flat)
        self.assertNotIn("the others once each", flat)
        self.assertIn("also ran as the S5 probe role, a scratch role", flat)
        self.assertIn("never run with a team role", flat)
        self.assertIn("main session of the live runs and of spikes S1, S3, S4 and S5", flat)
        self.assertIn("a probe role in S3 and S4", flat)
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

    def test_readme_claude_section_says_ponytail_is_codex_only_and_merges_the_sync_advice(self):
        body = section(read(README), POINTER) or ""
        flat = " ".join(body.split())
        self.assertIn(
            "Ponytail Full and `ui-skills-root` apply to Codex only; Claude Code roles do not use them"
            " (see [CLAUDE.md](CLAUDE.md))",
            flat,
        )
        self.assertEqual(flat.count("run `python3 scripts/sync_roles.py`"), 1)
        team = " ".join((section(read(TEAM), "## Ponytail implementation pilot") or "").split())
        self.assertIn("Ponytail Full and `ui-skills-root` apply to Codex only", team)

    def test_claude_md_says_superpowers_replaces_no_role(self):
        self.assertIn("replaces no role", " ".join(read(CLAUDE_MD).split()))

    def test_claude_md_never_relaxes_agents_md_security_rules(self):
        flat = " ".join(read(CLAUDE_MD).split())
        self.assertIn("This file never relaxes the security rules in AGENTS.md or SECURITY.md.", flat)
        self.assertNotIn("except where this file says otherwise", flat)
        body = " ".join((section(read(CLAUDE_MD), DIFFERENCES) or "").split())
        self.assertLess(body.index("never relaxes the security rules"), body.index("Ponytail pilot"))

    def test_claude_md_keeps_the_security_mandatory_sentence_of_the_ponytail_paragraph(self):
        sentence = ("Security, accessibility, required checks, documentation, independent reviews"
                    " and human approval boundaries remain mandatory")
        agents = " ".join(read(ROOT / "AGENTS.md").split())
        self.assertIn(sentence, agents)
        start = agents.index("Backend and Frontend default to Ponytail Full")
        end = agents.index("no savings are assumed")
        self.assertLess(start, agents.index(sentence))
        self.assertLess(agents.index(sentence), end)
        body = " ".join((section(read(CLAUDE_MD), DIFFERENCES) or "").split())
        self.assertIn('The one exception within the paragraph is its sentence that begins "'
                      + sentence + '"', body)
        self.assertIn("that sentence still applies on Claude Code", body)

    def test_claude_md_says_skills_never_override_or_authorize_publication(self):
        process = " ".join((section(read(CLAUDE_MD), "## Process") or "").split())
        self.assertIn(
            "Skill instructions (superpowers or any other) never override AGENTS.md or SECURITY.md"
            " and never authorize pushing, publishing or merging; those need the owner's authorization.",
            process,
        )

    def test_setup_doc_has_an_untrusted_checkouts_section(self):
        text = read(SETUP)
        body = section(text, "## Untrusted checkouts")
        self.assertIsNotNone(body, "missing section: ## Untrusted checkouts")
        self.assertLess(text.index("## Untrusted checkouts"), text.index("## Generating the roles"))
        flat = " ".join(body.split())
        for needle in ("`CLAUDE.md`", "`AGENTS.md`", "`.claude/agents/*.md`", "load as instructions",
                       "`.claude/settings.json`", "`.mcp.json`",
                       "](superpowers/spikes/S1-auth-launch-mode.md)",
                       "`SessionStart` hook ran in headless `-p` mode with no trust dialog (one run)",
                       "MCP servers", "docs-sourced, not tested",
                       "`--setting-sources user`", "`--safe-mode`", "`--restricted`",
                       "help text and one hook marker", "review the diff",
                       "someone else's branch",
                       "This repository ships no `.claude/settings.json`"):
            self.assertIn(needle, flat)
        self.assertNotRegex(flat, TIME_WORDS)
        top = " ".join(text[: text.index("## Quick start")].split())
        self.assertIn("[Untrusted checkouts](#untrusted-checkouts)", top)

    def test_setup_doc_records_superpowers_as_an_unreviewed_unpinned_dependency(self):
        body = " ".join((section(read(SETUP), "## The superpowers plugin") or "").split())
        self.assertIn("unpinned third-party dependency", body)
        self.assertIn("have not been security-reviewed by this project", body)
        self.assertIn("Review each plugin update", body)
        self.assertIn("never override AGENTS.md or SECURITY.md", body)

    def test_setup_doc_states_the_unsafe_kind_case_rule_and_write_atomicity(self):
        failing = " ".join((section(read(SETUP), "## When --check fails") or "").split())
        self.assertIn("There are four kinds", failing)
        self.assertIn("`<path>: unsafe, symlink or not a regular file`", failing)
        self.assertIn("`<path>: unsafe, symlink or not a directory`", failing)
        self.assertIn("in either letter case", failing)
        self.assertIn("`Extra.MD`", failing)
        self.assertIn("every file is rendered and every output path validated before any is written", failing)
        self.assertIn("each file is replaced atomically", failing)
        self.assertIn("can leave a partial set", failing)
        self.assertNotIn("In each case the sync writes nothing, because every file is rendered before any is written", failing)

    def test_design_spec_labels_the_mcp_claim_docs_sourced(self):
        spec = read(ROOT / "docs" / "superpowers" / "specs" / "2026-10-26-claude-code-adaptation-design.md")
        row = next(line for line in spec.splitlines() if line.startswith("| Project hooks |"))
        self.assertIn("MCP servers", row)
        self.assertIn("docs-sourced", row)
        self.assertIn("S1 tested only a `SessionStart` hook", row)

    def test_models_toml_comment_lists_the_verified_pairings_including_opus_high(self):
        comments = " ".join(
            line.lstrip("# ") for line in (ROOT / "team_source" / "models.toml").read_text().splitlines()
            if line.startswith("#")
        )
        self.assertIn("opus/high", comments)

    def test_not_available_for_claude_lists_no_longer_name_the_slice_2b_features(self):
        """Plan 5 Task 8: conversation, team view, outputs and delivery readiness work for Claude runs."""
        for path in (ROOT / "docs" / "dashboard-operations.md", SETUP):
            flat = " ".join(read(path).split())
            self.assertNotIn("Delivery checks are not available", flat, path.name)
            found = list(re.finditer(r"Not available for Claude runs:[^.]*\.", flat))
            self.assertTrue(found, path.name)
            for match in found:
                for feature in ("conversation view", "team view", "outputs", "delivery"):
                    self.assertNotIn(feature, match.group(0), path.name)
                self.assertIn("plan steps", match.group(0), path.name)

    def test_claude_delivery_docs_say_ponytail_is_not_applicable_and_fake_binary_only(self):
        api = " ".join(read(ROOT / "docs" / "dashboard-api.md").split())
        for needle in ('"ponytail":"not_applicable"', "policy_binding_changed", "replies_dropped",
                       "replies_withheld", "foreground", "Fake-binary evidence only"):
            self.assertIn(needle, api)
        self.assertIn("Ponytail is still not used", " ".join(read(README).split()))


    def test_claude_docs_separate_dropped_and_withheld_review_replies(self):
        api = " ".join(read(ROOT / "docs" / "dashboard-api.md").split())
        self.assertIn("A dropped reply leaves the status `unverified` with reason code `complete_review_messages_required`", api)
        self.assertIn("`changes_requested` with reason code `independent_review_required`", api)
        ops = " ".join(read(ROOT / "docs" / "dashboard-operations.md").split())
        self.assertIn("Delivery not verified: what to do", ops)


    # --- observed sessions (Terminal sessions) -------------------------------------------------------------

    def test_observed_sessions_documented(self):
        docs = ROOT / "docs"
        flat = lambda path: " ".join(read(path).split())
        ops = section_from(flat(docs / "dashboard-operations.md"), "### Terminal sessions (observed Claude Code sessions)",
                           "## Review files and publish commits")
        api = section_from(flat(docs / "dashboard-api.md"), "## Observed sessions (Claude deployments only)",
                           "## Ponytail policy and delivery readiness").replace("`", "")
        setup = flat(SETUP)
        decisions = section_from(flat(docs / "decisions.md"), "## 2026-11-06", "## 2026-11-01")
        board = flat(docs / "task-board.md")
        for name, text in (("ops", ops), ("api", api), ("decisions", decisions)):
            self.assertTrue(text, name + " section missing")
        for needle in (
            # setup, port, token
            "fixed default port **47615**",
            "~/Library/Application Support/KT Agent Dashboard",
            "`$XDG_CONFIG_HOME` or `~/.config` followed by `kt-agent-dashboard`",
            "mode 0600 in a folder of mode 0700",
            "never written to the logs, the database, the dashboard's own settings or the page",
            "**Rotate token** makes the old token stop working for new requests; requests already waiting finish",
            "**no other port is tried**",
            "has no screen in Settings",
            "`claude_approval_wait_seconds`",
            "the approval wait plus 60 seconds",
            # reading before setup, placement, hygiene
            "**Read before setup.** While the dashboard is not running, another program on this Mac could take port 47615 "
            "and receive the hook data (commands, file contents, the token) and could answer \"allow\". Remove the hook block "
            "from your settings when you stop using the dashboard, and put it back when you start.",
            "delete the `hooks` block you pasted",
            "**only into `.claude/settings.local.json` of the project you use.**",
            "never put the block in a committed or shared file: not `.claude/settings.json`, and not your user-level settings",
            "Never commit the snippet. If it was ever committed or pushed, rotate the token",
            "documentation-sourced and **not verified here**",
            "S11 case D5",
            "merge the seven entries into it rather than adding a second `hooks` key",
            "Start a **new** Claude Code session",
            "Hooks apply only to the projects where you pasted them",
            "`--setting-sources user`",
            "how Claude Code combines the two hooks' replies is not yet verified (S11 D3)",
            "stray quiet row",
            "fails closed",
            "the owner's own events",
            "gets a bare 404 and **the page shows nothing, with no error**",
            "**What the page cannot show.** No transcripts, no prompts, no tool results",
            # what the page shows, never blocks, limits
            "`active`: an event arrived in the last 30 minutes",
            "seven events",
            "Your terminal session",
            "subagent activity seen",
            "Limits: 256 sessions, 32 pending approvals, 64 finished cards and a 256 KiB request body",
            "the 32-pending cap",
            "the cap of 64 connections not yet holding a request, and a 10 second read deadline",
            # unverified claims
            "**`{}` verified live once (S11 case A1).**",
            "**Dashboard down: verified live once (S11 case D4, owner-reported).**",
            "S11 case D4",
            "verified live once for an Allow or Deny from the page",
            "(S11 cases C1, C2) and two answers at the same moment (C4) were not run",
            "Codex deployments have no Terminal sessions page",
            "**Live (2026-11-11):**",
            "**Owner-reported:** the terminal text for each case",
            "by the AI controller, not by the owner",
            "`1e9ac7b`",
            "**before the last fix wave**",
            "covered by unit and journey tests only, not by a browser",
            # inference
            "Inferred from later events, not a receipt",
            "**no run seen**",
            "A `PostToolUse` for a **different** call never closes a card",
            "ran although denied here",
            "the connection ends with `{}` at once",
            "opaque `~` followed by 12 hex digits",
            # security limit
            "**Security limit (an owner decision, recorded in [decisions](decisions.md) and still open):**",
            "while the dashboard is not running, another local program could bind the port",
            "remove or disable the hooks when you are not using the dashboard",
            "A wrapper command hook that checks who is listening is out of scope",
            "**If something does not work.**",
            "Stop that program, or change `observed_port` (advanced: edit `dashboard/config.toml` and restart the dashboard), "
            "then rotate the token and paste the snippet again",
        ):
            self.assertIn(needle, ops, needle)
        self.assertNotIn("so nothing breaks", ops)
        self.assertNotIn("PROJECT or LOCAL", ops)
        for needle in (
            "GET /api/observed", "GET /api/observed/hook-config", "POST /api/observed/rotate-token",
            "POST /api/observed/approvals/<id>/allow", "/deny",
            "Cache-Control: no-store", "not available for this provider", "Codex or none deployment",
            "{enabled, reason, port, sessions, approvals, refused, limits}",
            "{max_sessions: 256, max_pending: 32, quiet_seconds: 1800}",
            "200 {result: \"ok\"}", "409 {result: \"closed\"}", "404 {result: \"unknown\"}",
            "200 {rotated: true}",
            "/hook/observed/<REDACTED>", "plus 60",
            "not run (shown on the page as \"no run seen\"",
            "should not occur in practice",
            "Not every ending replies",
            "the 64-unheld-connection cap and the 10 second read deadline drop the connection without a reply",
            "live-tested once (S11 A1)",
            "fails closed", "stray quiet observed row",
            "after the usual content-type and size checks",
            "0600 file in a 0700 folder",
        ):
            self.assertIn(needle, api, needle)
        provider = " ".join(section_from(read(docs / "dashboard-api.md"), "## Provider-specific answers",
                                         "## Claude tool-call approvals").split())
        self.assertIn("The observed routes are the reverse", provider)
        self.assertIn("answer 409", provider)
        for needle in ("fixed default port 47615", "S11", "partly run",
                       "`.claude/settings.local.json`", "never into a committed or shared file", "owner-attended live run",
                       "S11 case D5", "D4"):
            self.assertIn(needle, setup, needle)
        self.assertIn("| Terminal sessions: the `{}` no-decision reply", setup)
        self.assertNotIn("PROJECT or LOCAL", setup)
        for needle in ("## 2026-11-06", "**Owner decision (answered 2026-11-09, recorded 2026-11-12): fixed-port exposure while the dashboard is down: accepted with warnings; no wrapper.**",
                       "Fixed port 47615", "`empty_object`", "not live-tested", "command` hook", "Fail-closed managed check",
                       "no run seen", "Release note (upgrade and rollback)", "refuses a `config.toml` that contains `observed_port`",
                       "D4", "D5", "`.claude/settings.local.json`"):
            self.assertIn(needle, decisions, needle)
        for needle in ("observed-sessions", "Plan 6", "merged by pull request 11 on 2026-11-09", "S11"):
            self.assertIn(needle, board, needle)
        self.assertIn("Terminal sessions", " ".join(read(README).split()))
        self.assertIn("docs/dashboard-operations.md#terminal-sessions-observed-claude-code-sessions", read(README))

    def test_observed_docs_match_the_code(self):
        from dashboard import server as server_module
        from dashboard.observed_receiver import NO_DECISION_MODE
        from dashboard.settings import DEFAULTS

        docs = ROOT / "docs"
        ops = " ".join(read(docs / "dashboard-operations.md").split())
        api = " ".join(read(docs / "dashboard-api.md").split())
        setup = " ".join(read(SETUP).split())
        for event in server_module.OBSERVED_EVENTS:
            self.assertIn("`" + event + "`", ops, event)
            self.assertIn(event, api.replace("`", ""), event)
        self.assertEqual(7, len(server_module.OBSERVED_EVENTS))
        port = str(DEFAULTS["observed_port"])
        for name, text in (("ops", ops), ("api", api), ("setup", setup)):
            self.assertIn(port, text, name)
        self.assertEqual("empty_object", NO_DECISION_MODE)
        self.assertIn("`{}`", ops)
        self.assertIn("empty_object", read(docs / "decisions.md"))
        source = read(ROOT / "dashboard" / "server.py")
        for reason in ("port_in_use", "token_unreadable", "token_permissions", "listener_error",
                       "settings_unavailable", "settings_invalid"):
            self.assertIn('"%s"' % reason, source, reason)
            self.assertIn(reason, api, reason)
        self.assertIn("47615", server_module.OBSERVED_NOTE + read(docs / "decisions.md"))
        # the fixed note the page and the API share is the one the docs describe
        note = server_module.OBSERVED_SNIPPET_NOTE
        self.assertIn(".claude/settings.local.json", note)
        self.assertIn(".claude/settings.local.json", ops)

    def test_no_stale_planned_wording(self):
        # Scoped: design specs legitimately record Phase 3 as planned. The two user-facing docs are checked whole;
        # README, the API doc and the task board only on sentences about observed or terminal sessions.
        stale = re.compile(
            r"(?is)observed sessions?[^.]{0,120}\b(are|is) (planned|not built|not yet built)\b"
            r"|\b(planned|not built)\b[^.]{0,80}observed sessions?"
            r"|not done: observed sessions"
        )
        for path in (SETUP, ROOT / "docs" / "dashboard-operations.md"):
            flat = " ".join(read(path).split())
            self.assertNotRegex(flat, stale, path.name)
            self.assertNotIn("Observation of your own Claude Code sessions.", flat, path.name)
        words = re.compile(r"(?i)\b(planned|not built|not yet built|will be built|to be built)\b")
        for path in (README, ROOT / "docs" / "dashboard-api.md", ROOT / "docs" / "task-board.md"):
            flat = " ".join(read(path).split())
            for sentence in re.split(r"(?<=[.!?])\s+", flat):
                if re.search(r"(?i)observed sessions?|terminal sessions?", sentence):
                    self.assertIsNone(words.search(sentence), f"{path.name}: {sentence[:120]}")

    def test_token_never_in_docs_examples(self):
        docs = ROOT / "docs"
        paths = [README] + sorted(docs.glob("*.md")) + sorted((docs / "superpowers").rglob("*.md"))
        self.assertGreater(len(paths), 20)
        for path in paths:
            for match in re.finditer(r"/hook/observed/([^\s\"'`)<>]*)", read(path)):
                self.assertFalse(re.fullmatch(r"[A-Za-z0-9_-]{40,}", match.group(1)),
                                 f"{path.name}: token-shaped value after /hook/observed/")
        for name in ("dashboard-operations.md", "dashboard-api.md"):
            self.assertIn("/hook/observed/<REDACTED>", read(docs / name), name)


class Plan5LeftoversDocs(unittest.TestCase):
    def test_leftovers_are_documented_where_users_and_integrators_look(self):
        docs = ROOT / "docs"
        ops = " ".join(read(docs / "dashboard-operations.md").split())
        api = " ".join(read(docs / "dashboard-api.md").split())
        decisions = " ".join(read(docs / "decisions.md").split())
        for needle in ("Files this run wrote or edited", "chosen by the model, not by you", "**Use this path** only copies the path",
                       "owner decision 2026-11-11: warning only"):
            self.assertIn(needle, ops, needle)
        for needle in ("`output_suggestions`", "at most 8 `{path, tool}` rows", "string logic only", "--disallowedTools Write,Edit,NotebookEdit",
                       "no count, no error text"):
            self.assertIn(needle, api, needle)
        for needle in ("2026-11-11 Plan 5 leftovers", "warning only", "Task 0 security review"):
            self.assertIn(needle, decisions, needle)
        self.assertNotIn("no suggestion of files the run wrote", api)
        self.assertNotIn("is a possible later hardening", api)


if __name__ == "__main__":
    unittest.main()

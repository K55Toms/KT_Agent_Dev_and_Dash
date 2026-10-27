@AGENTS.md

## Claude Code differences

The rules above are the same on both harnesses. This file never relaxes the security rules in
AGENTS.md or SECURITY.md. On Claude Code:

- The primary Claude Code session acts as the Chief of Staff. Its model is whatever the session
  runs; this file does not pin it.
- `.claude/agents/` replaces every `.codex/agents/` mention in AGENTS.md. Where AGENTS.md says to
  read a role's TOML instructions, read the role's Markdown file in `.claude/agents/` instead.
- The first paragraph under `### Ponytail pilot` in AGENTS.md does not apply on Claude Code, with
  one exception. It starts "Backend and Frontend default to Ponytail Full" and ends "no savings
  are assumed", and that includes its sentences about Code Quality Review checking Ponytail
  simplicity and Agent Evaluation recording pilot outcomes. Everything after it in that file,
  from "The primary agent acts as Chief of Staff" to the end, still applies, read with the
  substitutions listed in this section. The one exception within the paragraph is its sentence
  that begins "Security, accessibility, required checks, documentation, independent reviews and
  human approval boundaries remain mandatory": that sentence still applies on Claude Code.
  `ui-skills-root` and `npx ui-skills` do not apply either. Ponytail is not used on the Claude
  side.
- `docs/model-policy.md` and the GPT-6 model names in the docs describe Codex routing only. The
  Claude models and effort levels are in `team_source/models.toml`.
- Roles are generated. The only place to edit a role is `team_source/`, followed by
  `python3 scripts/sync_roles.py`. Never hand-edit `.codex/agents/*.toml` or
  `.claude/agents/*.md`. `python3 scripts/sync_roles.py --check` reports drift.
- `security_reviewer` and `code_quality_reviewer` have only read tools (`Read, Grep, Glob`, no
  Bash), because a role that lists Bash gains a write route once Bash is approved (spike S4: gated
  only by the session's permission rules). The coordinator or `qa_engineer` runs checks for them.
- Every role except `chief_of_staff` has `disallowedTools: Agent` to avoid recursive delegation.
  Observed live (one run per condition): `backend_developer` was not offered the `Agent` tool,
  `chief_of_staff` was and used it. The setting removes only the `Agent` tool; other routes (`Bash`
  once approved, `SendMessage`, MCP-based session tools) were not tested and are not blocked by it.
- Subagents receive the full `CLAUDE.md` and `AGENTS.md` as injected context. The Ponytail
  paragraph and the Codex references in `AGENTS.md` are visible to them and are switched off by
  this file, not removed; this file mentions `ui-skills` only to exclude it. Roles observed
  (including `security_reviewer`, `backend_developer` and `chief_of_staff`) were also offered
  `advisor`, a server tool run by the API per Claude Code's tools reference (docs-sourced, not
  called, not tested).
- Per Claude Code's sub-agents documentation (cited in the Claude Code adaptation design, section 3),
  `AskUserQuestion` is not available inside subagents, so specialists report questions back to
  the coordinator.

This file imports AGENTS.md with `@AGENTS.md`. The live runs showed the text was in context and
understood, not that every part is obeyed. The evidence, its limits and the unverified items
(interactive mode, Auto mode, `fable`) are in [Claude Code setup](docs/claude-code-setup.md) and its
[live evidence](docs/superpowers/evidence/2026-10-26-phase-1-live.md).

## Process

On Claude Code, use the superpowers skills for design, planning and completion:
brainstorming before design work, writing-plans, test-driven-development,
requesting-code-review and verification-before-completion. The 14 roles and the rules in
AGENTS.md stay as they are. Superpowers adds discipline and replaces no role. Skill instructions
(superpowers or any other) never override AGENTS.md or SECURITY.md and never authorize pushing,
publishing or merging; those need the owner's authorization.

Setup and status: [Claude Code setup](docs/claude-code-setup.md).

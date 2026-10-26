@AGENTS.md

## Claude Code differences

The rules above are the same on both harnesses. On Claude Code:

- The primary Claude Code session acts as the Chief of Staff. Its model is whatever the session
  runs; this file does not pin it.
- `.claude/agents/` replaces every `.codex/agents/` mention in AGENTS.md. Where AGENTS.md says to
  read a role's TOML instructions, read the role's Markdown file in `.claude/agents/` instead.
- The first paragraph under `### Ponytail pilot` in AGENTS.md (it starts "Backend and Frontend
  default to Ponytail Full" and ends "no savings are assumed") does not apply on Claude Code,
  including its sentences about Code Quality Review checking Ponytail simplicity and Agent
  Evaluation recording pilot outcomes. Everything
  after it in that file, from "The primary agent acts as Chief of Staff" to the end, still applies,
  except where this file says otherwise. `ui-skills-root` and `npx ui-skills` do not apply either.
  Ponytail is not used on the Claude side.
- `docs/model-policy.md` and the GPT-6 model names in the docs describe Codex routing only. The
  Claude models and effort levels are in `team_source/models.toml`.
- Roles are generated. The only place to edit a role is `team_source/`, followed by
  `python3 scripts/sync_roles.py`. Never hand-edit `.codex/agents/*.toml` or
  `.claude/agents/*.md`. `python3 scripts/sync_roles.py --check` reports drift.
- `security_reviewer` and `code_quality_reviewer` have only read tools (`Read, Grep, Glob`, no
  Bash), because a role that lists Bash gains a write route once Bash is approved (spike S4: gated
  only by the session's permission rules). The coordinator or `qa_engineer` runs checks for them.
- Every role except `chief_of_staff` has `disallowedTools: Agent` to avoid recursive delegation.
  This setting has not yet been exercised in a live run.
- Per Claude Code's sub-agents documentation (cited in the Claude Code adaptation design, section 3),
  `AskUserQuestion` is not available inside subagents, so specialists report questions back to
  the coordinator.

This file imports AGENTS.md with `@AGENTS.md`; spike S4 (a) verified that import with a one-line
CLAUDE.md in `-p` mode. A CLAUDE.md that also has this differences section has not been tested in
a live run yet.

## Process

On Claude Code, use the superpowers skills for design, planning and completion:
brainstorming before design work, writing-plans, test-driven-development,
requesting-code-review and verification-before-completion. The 14 roles and the rules in
AGENTS.md stay as they are. Superpowers adds discipline and replaces no role.

Setup and status: [Claude Code setup](docs/claude-code-setup.md).

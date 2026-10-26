# Claude Code setup

This project was built on Codex and now also targets Claude Code. This page covers what a clone
gives you for Claude Code, what it does not, and how much of that has been checked.

## What this repository provides

- [`CLAUDE.md`](../CLAUDE.md) at the repository root. It imports `AGENTS.md` and lists the
  differences on Claude Code.
- 14 generated role files in `.claude/agents/*.md`, one per role, with model, effort and tools
  set from the shared policy. They are Markdown, not TOML: where AGENTS.md says to read a role's
  TOML instructions, read the role's `.md` file instead.
- `team_source/`, the single source those files (and the Codex ones) are generated from.

A clone does not install anything on your machine. It does not install the superpowers plugin or
Claude Code itself, and it does not sign you in. The dashboard does not manage Claude runs yet.

## The superpowers plugin

`CLAUDE.md` tells the Chief of Staff to use the superpowers skills for design, planning and
completion. The plugin is installed per machine. This repository does not install or pin it, in
the same way [Skill dependencies and setup](skill-setup.md) leaves Codex skills to each machine.

At the time of writing, the plugin's own manifest reports name `superpowers`, version 6.4.2 and
homepage <https://github.com/obra/superpowers>. Follow the installation instructions at that
homepage. This page does not give install commands, because they are the plugin's to define and
may change.

## Generating the roles

Edit roles only in `team_source/`, then regenerate:

```sh
python3 scripts/sync_roles.py
python3 scripts/sync_roles.py --check
```

The first command writes the generated files: 14 `.codex/agents/*.toml` and 14
`.claude/agents/*.md`. `--check` writes nothing and reports drift between the source and the
generated files. Do not hand-edit generated files. The `.codex/agents/*.toml` files now start with a
generated-file header: edit `team_source/` and run the sync (hand edits are reverted by the next sync and
flagged by `--check`).

- `team_source/roles/*.md` is the single source for each role's instructions. Text meant for one
  harness only sits in whole-line blocks marked `<!-- codex-only -->` or `<!-- claude-only -->`.
- `team_source/models.toml` holds one Codex column and one Claude column (model and effort) per
  role. The owner chose the Claude column on 2026-10-26.
- `expert_escalation` uses `opus` / `low` on Claude, because the `fable` alias is credit-gated
  off at the owner's organisation (spike S5). The owner may switch it to `fable` once credits are
  enabled and the pairing is re-tested.
- The pairings opus/medium, sonnet/high, sonnet/medium and opus/low were each run once against the
  live API and the recorded model and effort matched this file (see
  [Verification status](#verification-status) and the
  [live evidence](superpowers/evidence/2026-10-26-phase-1-live.md)). `fable` is the one pairing
  not verified.

## Sign-in

Claude Code uses your own sign-in. No credentials belong in this repository, as AGENTS.md and
SECURITY.md already require.

## What is not supported yet

- Dashboard-managed Claude runs (starting and owning a run from the dashboard).
- Approvals for Claude runs.
- Observation of your own Claude Code sessions.

These are later phases (Phase 2 and Phase 3 in the
[design](superpowers/specs/2026-10-26-claude-code-adaptation-design.md)). The dashboard is still
Codex-only.

Approvals through a `PermissionRequest` hook are not part of this phase (Phase 3). In Auto
permission mode, routine tool calls are approved without a prompt, so such a hook is not reached
for them ([S2](superpowers/spikes/S2-approvals.md)).

## Verification status

Spike reports are in `docs/superpowers/spikes/`; the summary is the
[Phase 0 findings](superpowers/spikes/2026-10-26-phase-0-findings.md). The rows marked
"Observed, one run" come from 10 short live runs in headless `-p` mode on Claude Code 2.1.310, one
run per condition, recorded in the
[live evidence](superpowers/evidence/2026-10-26-phase-1-live.md). The model IDs seen were `opus`
= `claude-opus-5-5` and `sonnet` = `claude-sonnet-5-5`. One run each shows the behaviour occurred;
it does not show it is stable.

| What | Status | Source |
| --- | --- | --- |
| `@AGENTS.md` import from a one-line `CLAUDE.md`, in `-p` mode | Observed | [S4](superpowers/spikes/S4-team-loading.md) (a) |
| A role with `tools: Read, Grep, Glob` could not write; a role that also lists `Bash` gained a write route once Bash was approved | Observed | [S4](superpowers/spikes/S4-team-loading.md) (b) |
| A role's `model` is honoured (haiku and sonnet roles under other main models) | Observed | [S4](superpowers/spikes/S4-team-loading.md) (c) |
| `opus` alias resolves to `claude-opus-5-5` with effort `high` | Observed | [S5](superpowers/spikes/S5-model-alias-precheck.md) |
| `fable` is refused at the usage-credits gate for this organisation | Observed | [S5](superpowers/spikes/S5-model-alias-precheck.md) |
| `CLAUDE.md` with its differences section loads, imports `AGENTS.md` and is read (headless `-p`) | Observed, one run | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R1 |
| Pairings opus/medium (`qa_engineer`), sonnet/high (`technical_writer`), sonnet/medium (`user_documentation_writer`), opus/low (`expert_escalation`): model and effort recorded in the subagent transcripts matched `team_source/models.toml` | Observed, one run each | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R4 to R7 |
| `security_reviewer` called only `Glob`; the tools it was offered were `Read`, `Grep`, `Glob` and `advisor` | Observed, one run | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R3 |
| `backend_developer` receives its role body | Observed. R2 failed as specified because of prompt wording; the re-run passed | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R2, R9 |
| `disallowedTools: Agent` removes the `Agent` tool from a role (limited: see below) | Observed, one run per condition | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R8, R10 |
| `fable` as a working model | Not verified | Blocked until credits are enabled |
| Effort values other than `low`, `medium` and `high` | Not verified | |
| Interactive mode | Not verified | The live runs were headless |
| Auto-mode behaviour | Not verified | The live runs used permission mode `default` |
| `AskUserQuestion` not being available in subagents | Not verified | Docs only |
| Whether the `CLAUDE_EFFORT` variable affects anything | Not verified | Name only; recorded efforts matched the role files in every run, so no override showed. The variable was observed set when checked at run R9; it is assumed, not shown, for the first eight runs (same shell) |

### Limits of the `disallowedTools: Agent` result

In R8 `backend_developer` (which has the setting) was not offered the `Agent` tool; in R10
`chief_of_staff` (which lacks it) was offered `Agent` and used it once, so the nested subagent ran
at depth 2. The setting removes only the `Agent` tool. Other routes (`Bash` once approved,
`SendMessage`, MCP-based session tools) were not tested and are not blocked by it, so the result
supports "no recursive `Agent` delegation", not "cannot delegate".

### What subagents see

Subagents receive the full `CLAUDE.md` and `AGENTS.md` as injected context (R2, R3 and R9), so the
Ponytail paragraph, the `ui-skills` text and the Codex references are visible to them. The
`CLAUDE.md` differences section switches them off; they are not removed. Whether subagents follow
that exclusion in real work was not tested. Roles observed (including `security_reviewer`, `backend_developer` and `chief_of_staff`; R3, R8,
R10) were also offered `advisor`, which Claude Code's tools reference describes as a server tool
run by the API (docs-sourced, not called, not tested).

Other spikes: [S1](superpowers/spikes/S1-auth-launch-mode.md) (sign-in and launch mode),
[S2](superpowers/spikes/S2-approvals.md) (approvals) and
[S3](superpowers/spikes/S3-event-stream.md) (event stream).

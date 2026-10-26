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
generated files. Do not hand-edit generated files.

- `team_source/roles/*.md` is the single source for each role's instructions. Text meant for one
  harness only sits in whole-line blocks marked `<!-- codex-only -->` or `<!-- claude-only -->`.
- `team_source/models.toml` holds one Codex column and one Claude column (model and effort) per
  role. The owner chose the Claude column on 2026-10-26.
- `expert_escalation` uses `opus` / `low` on Claude, because the `fable` alias is credit-gated
  off at the owner's organisation (spike S5). The owner may switch it to `fable` once credits are
  enabled and the pairing is re-tested.
- The pairings opus/medium, sonnet/high and sonnet/medium have not been run against the live API
  yet.

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
[Phase 0 findings](superpowers/spikes/2026-10-26-phase-0-findings.md).

| What | Status | Source |
| --- | --- | --- |
| `@AGENTS.md` import from a one-line `CLAUDE.md`, in `-p` mode | Observed | [S4](superpowers/spikes/S4-team-loading.md) (a) |
| A role with `tools: Read, Grep, Glob` could not write; a role that also lists `Bash` gained a write route once Bash was approved | Observed | [S4](superpowers/spikes/S4-team-loading.md) (b) |
| A role's `model` is honoured (haiku and sonnet roles under other main models) | Observed | [S4](superpowers/spikes/S4-team-loading.md) (c) |
| `opus` alias resolves to `claude-opus-5-5` with effort `high` | Observed | [S5](superpowers/spikes/S5-model-alias-precheck.md) |
| `fable` is refused at the usage-credits gate for this organisation | Observed | [S5](superpowers/spikes/S5-model-alias-precheck.md) |
| `CLAUDE.md` with a differences section, in a live run | Not verified | Planned check |
| `disallowedTools: Agent` stopping delegation | Not verified | |
| opus/medium, sonnet/high, sonnet/medium | Not verified | |
| `fable` as a working model | Not verified | Blocked until credits are enabled |

Other spikes: [S1](superpowers/spikes/S1-auth-launch-mode.md) (sign-in and launch mode),
[S2](superpowers/spikes/S2-approvals.md) (approvals) and
[S3](superpowers/spikes/S3-event-stream.md) (event stream).

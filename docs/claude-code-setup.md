# Claude Code setup

This project was built on Codex and also targets Claude Code. This page covers what a clone gives
you for Claude Code, what it does not, and how much of that has been checked.

All Claude behaviour described here was observed in headless `-p` mode on Claude Code 2.1.310, one
run per condition. Interactive mode, Auto mode and the `fable` model are not verified (see
[Verification status](#verification-status)).

## What this repository provides

- [`CLAUDE.md`](../CLAUDE.md) at the repository root. It imports `AGENTS.md` and lists the
  differences on Claude Code.
- 14 generated role files in `.claude/agents/*.md`, one per role. Model and effort come from
  `team_source/models.toml`; the tool restrictions come from each role's `profile` (reviewer =
  `Read, Grep, Glob`) and `disallowedTools: Agent` on every role except `chief_of_staff`. They are
  Markdown, not TOML: where AGENTS.md says to read a role's TOML instructions, read the role's `.md`
  file instead.
- `team_source/`, the single source those files (and the Codex ones) are generated from.

A clone does not install anything on your machine. It does not install the superpowers plugin or
Claude Code itself, and it does not sign you in. The dashboard does not manage Claude runs yet.

## Quick start

1. Prerequisites: Claude Code is installed and you are signed in (a clone does neither), and Python
   3.11 or newer is available for the scripts, because `team_source/` reads TOML with the standard
   library.
2. Install the superpowers plugin as its own instructions say (see
   [The superpowers plugin](#the-superpowers-plugin)).
3. Launch Claude Code from the repository root, so that `CLAUDE.md` (and the `AGENTS.md` it
   imports) loads.
4. Check that the generated role files match their source:

   ```sh
   python3 scripts/sync_roles.py --check
   ```

   The expected output is `role files are in sync`.
5. Make a first request. This is an example, not verified behaviour (the live runs used trivial
   jobs, not this request):

   > Act as Chief of Staff. Have the Product Manager help me define our first product.
   > Ask about users, their problem, constraints, and success criteria before choosing a stack.
   > Record the agreed brief and delegate specialist work when it is ready.

## The superpowers plugin

`CLAUDE.md` tells the Chief of Staff to use the superpowers skills for design, planning and
completion. Superpowers adds process discipline (brainstorming, planning, test-driven development,
review, verification) and replaces no role: the 14 roles and the rules in AGENTS.md stay as they
are. The plugin is installed per machine. This repository does not install or pin it, in the same
way [Skill dependencies and setup](skill-setup.md) leaves Codex skills to each machine.

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
generated files. Do not hand-edit generated files. Hand edits are reverted by the next sync and
flagged by `--check`.

- `team_source/roles/*.md` is the single source for each role's instructions. Text meant for one
  harness only sits in whole-line blocks marked `<!-- codex-only -->` or `<!-- claude-only -->`.
- `team_source/models.toml` holds one Codex column and one Claude column (model and effort) per
  role. The owner chose the Claude column on 2026-10-26.
- `expert_escalation` uses `opus` / `low` on Claude, because the `fable` alias is credit-gated
  off at the owner's organisation (spike S5). The owner may switch it to `fable` once credits are
  enabled and the pairing is re-tested.
- The pairings opus/high, opus/medium, sonnet/high, sonnet/medium and opus/low were each run
  against the live API and the recorded model and effort matched this file (opus/high in R2, R3,
  R8, R9 and S5; the others once each; see [Verification status](#verification-status) and the
  [live evidence](superpowers/evidence/2026-10-26-phase-1-live.md)). `fable` is the one pairing
  not verified. The model `haiku` and the efforts `xhigh` and `max` are allowed by the policy but
  were never run with a team role (`haiku` ran only as a spike probe role and as the main session
  of the live runs).

## Changes for existing Codex users

- Each `.codex/agents/*.toml` file starts with a two-line generated-file header (comment lines that
  name `team_source/` and `scripts/sync_roles.py`).
- The generated files are not for hand editing: hand edits are reverted by the next sync and
  flagged by `--check`, so edit `team_source/` instead.
- The `expert_escalation` description reads "On-demand escalation specialist for consequential
  ambiguity, difficult defects or sensitive reviews." (it said "Astra specialist" before the
  migration). Its Codex model `gpt-6-astra` and effort `low` are unchanged, and the parsed model,
  effort and instructions of the other 13 files equal the pre-migration files (checked by script
  against the earlier files and by `tests/test_team_source_migration.py`). A native Codex session
  loading the regenerated files was not run.
- Role edits use two commands: `python3 scripts/sync_roles.py` writes the files and
  `python3 scripts/sync_roles.py --check` reports drift without writing.

## Add a role

1. Create `team_source/roles/<id>.md`. Its front matter has the keys `id`, `description` and
   `profile`, each a JSON string in double quotes. `profile` is `"editor"` or `"reviewer"`
   (reviewers get `tools: Read, Grep, Glob`), and `id` must equal the file stem. Role text for one
   harness only goes in whole-line `codex-only` / `claude-only` blocks.
2. In `team_source/models.toml`, add the tables `[<id>.codex]` and `[<id>.claude]`, each with
   `model` and `effort`. A missing table or key raises a `PolicyError`.
3. Add the role to `PROFILES` in `dashboard/team.py`. The sync does not check this (it passes the
   role ids as the profiles); `tests/test_team_source_migration.py` does, and the dashboard
   requires the same set of roles.
4. Update the tests and docs that pin 14 roles (for example `tests/test_sync_roles.py`,
   `tests/test_team_source_policy.py`, `tests/test_team_source_migration.py` and its Codex baseline
   fixture) and the "14 roles" and "thirteen core" statements in the docs.
5. Run `python3 scripts/sync_roles.py`, then `python3 scripts/sync_roles.py --check`, then the tests
   (see [Run the checks](#run-the-checks)).

## Change a model or effort

Edit the role's row in `team_source/models.toml`, then run `python3 scripts/sync_roles.py`. The
allowed values are in `team_source/policy.py`:

- Codex models `gpt-6.1-sol`, `gpt-6-luna` and `gpt-6-astra`; efforts `low`, `medium`, `high` and
  `xhigh`.
- Claude models `opus`, `sonnet`, `haiku` and `fable`; efforts `low`, `medium`, `high`, `xhigh` and
  `max`.

Only the efforts low, medium and high have been observed live. The sync rejects any other value
with a `PolicyError` that names the role and column. This matters because Claude Code silently
ignores an effort it does not recognise (spike [S4](superpowers/spikes/S4-team-loading.md) (d)),
so the sync is the guard. Re-test any new
model and effort pairing before relying on it.

## When --check fails

`--check` writes nothing. It prints one problem per line to standard error and exits 1. There are
three kinds:

- `<path>: missing`: a generated file does not exist. Run `python3 scripts/sync_roles.py`.
- `<path>: stale`: a generated file differs from what the source renders, because it was hand
  edited or the source changed without a sync. Run `python3 scripts/sync_roles.py` and review
  `git diff`. The sync overwrites a hand edit, so move the change into `team_source/` first.
- `<path>: unexpected, not generated from team_source`: a `.md` or `.toml` file, or a directory,
  sits in `.codex/agents/` or `.claude/agents/` with no source role. The sync never deletes, so
  remove it by hand or add a source role. A plain `.DS_Store` and other files that are not role
  files are ignored.

The plain sync also exits 1 when it finds unexpected entries, after it has written the other
files. A malformed role source or policy is not reported as a problem line: the command ends with a
Python traceback whose last line names `RoleSourceError` or `PolicyError`, and it writes nothing,
because every file is rendered before any is written.

## Run the checks

```sh
python3 scripts/sync_roles.py --check
python3 -m unittest discover -s tests -v
XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests
node --test tests/*.js
python3 scripts/security_check.py staged
python3 scripts/security_check.py history
```

- Use `node --test tests/*.js`: `node --test tests/` ran zero tests on Node 26.
- The unit tests include the drift guard (`tests/test_sync_roles.py`) and the documentation guard
  (`tests/test_claude_docs.py`).
- Two tests in `tests/test_git_service.py` fail on a machine whose global git ignore file ignores
  `.env`. They are environment failures, unrelated to the roles. The second command above, which
  points `XDG_CONFIG_HOME` at an empty directory, avoids that.

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

Approvals through a `PermissionRequest` hook are not part of this phase (Phase 3). Spike S2
observed that in Auto permission mode routine tool calls are approved without a prompt, so such a
hook is not reached for them ([S2](superpowers/spikes/S2-approvals.md)).

## Verification status

Spike reports are in `docs/superpowers/spikes/`; the summary is the
[Phase 0 findings](superpowers/spikes/2026-10-26-phase-0-findings.md). The rows marked
"Observed, one run" come from 10 short live runs under the conditions stated at the top of this
page, recorded in the
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
| `CLAUDE.md` with its differences section loads, imports `AGENTS.md` and is read (headless `-p`). This shows the text was in context and understood, not that every part is obeyed | Observed, one run | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R1 |
| Pairings opus/medium (`qa_engineer`), sonnet/high (`technical_writer`), sonnet/medium (`user_documentation_writer`), opus/low (`expert_escalation`): model and effort recorded in the subagent transcripts matched `team_source/models.toml` | Observed, one run each | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R4 to R7 |
| Pairing opus/high (`backend_developer`, `security_reviewer`): model and effort recorded matched `team_source/models.toml` | Observed, in R2, R3, R8, R9 and S5 | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R2, R3, R8, R9; [S5](superpowers/spikes/S5-model-alias-precheck.md) |
| `security_reviewer` called only `Glob`; the tools it was offered were `Read`, `Grep`, `Glob` and `advisor` | Observed, one run | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R3 |
| `backend_developer` receives its role body | Observed. R2 failed as specified because of prompt wording; the re-run passed | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R2, R9 |
| `disallowedTools: Agent` removes the `Agent` tool from a role (limited: see below) | Observed, one run per condition | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R8, R10 |
| `fable` as a working model | Not verified | Blocked until credits are enabled |
| Effort values other than `low`, `medium` and `high`; `haiku` as a team role's model | Not verified | Allowed by `team_source/policy.py`, never run with a team role |
| Interactive mode | Not verified | The live runs were headless |
| Auto-mode behaviour | Not verified | The live runs used permission mode `default` |
| `AskUserQuestion` not being available in subagents | Not verified | Docs only |
| Whether the `CLAUDE_EFFORT` variable affects anything | Not verified | Name only; recorded efforts matched the role files in every run, so no override showed. The variable was observed set when checked at run R9; it is assumed, not shown, for the first eight runs (same shell) |
| A native Codex session loading the regenerated `.codex/agents/*.toml` files | Not verified | Parse-level and test evidence only |

Open question: whether a changed `.claude/agents/*.md` takes effect in a running session is not
verified. `docs/team.md` states the Codex behaviour (an already-running invocation keeps the
instructions it was given); no Claude Code check was run.

### Limits of the `disallowedTools: Agent` result

In R8 `backend_developer` (which has the setting) was not offered the `Agent` tool; in R10
`chief_of_staff` (which lacks it) was offered `Agent` and used it once, so the nested subagent ran
at depth 2. The setting removes only the `Agent` tool. Other routes (`Bash` once approved,
`SendMessage`, MCP-based session tools) were not tested and are not blocked by it, so the result
supports "no recursive `Agent` delegation", not "cannot delegate".

### Read-only reviewers

`security_reviewer` and `code_quality_reviewer` have only `Read`, `Grep` and `Glob`, with no
`Bash`: a role that lists `Bash` gains a write route once Bash is approved (spike S4). The
coordinator or `qa_engineer` runs any command a reviewer needs.

### What subagents see

Subagents receive the full `CLAUDE.md` and `AGENTS.md` as injected context (R2, R3 and R9), so the
Ponytail paragraph and the Codex references in `AGENTS.md` are visible to them. `AGENTS.md` has no
`ui-skills` text; `CLAUDE.md` mentions `ui-skills` only to exclude it. The `CLAUDE.md` differences
section switches the Ponytail paragraph off; it is not removed. Whether subagents follow that
exclusion in real work was not tested. Roles observed (including `security_reviewer`,
`backend_developer` and `chief_of_staff`; R3, R8, R10) were also offered `advisor`, which Claude
Code's tools reference describes as a server tool run by the API (docs-sourced, not called, not
tested).

Other spikes: [S1](superpowers/spikes/S1-auth-launch-mode.md) (sign-in and launch mode),
[S2](superpowers/spikes/S2-approvals.md) (approvals) and
[S3](superpowers/spikes/S3-event-stream.md) (event stream).

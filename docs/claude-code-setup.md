# Claude Code setup

This project was built on Codex and also targets Claude Code. This page covers what a clone gives
you for Claude Code, what it does not, and how much of that has been checked.

The live runs (R1 to R10) were headless `-p` on Claude Code 2.1.310, one run per condition; spikes
S1, S2 and S4 ran on 2.1.296 (S3 and S5 on 2.1.310), and S2 also has owner-run interactive checks
(one observation per condition). Apart from those S2 approval-hook checks, interactive mode and
Auto mode are not verified, and neither is the `fable` model (see
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
Claude Code itself, and it does not sign you in. The dashboard can start and stop Claude runs (tested with a fake `claude` only; see [The dashboard with Claude](#the-dashboard-with-claude)).
Launching Claude Code in a checkout does load that checkout's instruction files: see
[Untrusted checkouts](#untrusted-checkouts) before launching on someone else's branch.

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

## The dashboard with Claude

The local dashboard serves one provider per deployment, chosen when you start it. With `claude`
it starts managed `claude -p` runs, shows their status, usage and an estimated cost, stops them, and
continues them with a follow-up. A tool call that needs permission is shown as an approval for you to
approve once or decline.

Start it with:

```sh
sh scripts/run_dashboard.sh claude
```

This needs `python3` and `claude` on PATH, but not the `codex` CLI; without `claude` the launcher
prints "Claude Code CLI is required on PATH." and exits 1. Open `http://127.0.0.1:8765/`. What you
see (checked against the source, unit and Node tests, and a fake-binary journey test that replays
recorded stream fixtures over HTTP; not by a browser and not with a live dashboard run):

- At start the dashboard runs `claude --version` once. No Codex process is started. A version shows
  "Claude connected" with "Claude Code <version> (login not verified)"; the login is not checked.
  A missing `claude` or no version disables **Start run** with that fixed reason; restart to probe again.
- **Start run** launches `claude -p` in the project directory with the role as the main session
  (`--agents` plus `--agent`), `--setting-sources user`, and the dashboard's security baseline plus the
  project's `CLAUDE.md` (its `@AGENTS.md` import expanded by the dashboard) passed through
  `--append-system-prompt`. The child gets only an allow-listed environment (`PATH`, `HOME`, `USER`,
  `LANG`, `TMPDIR`, `SHELL`, `TERM`, `LC_*`).
- Usage shows five token counters; cost is "Estimated USD (list price)" from Claude Code, never a
  billed amount.
- A tool call that needs permission is sent to the dashboard as an approval (Approvals page). Choose
  **Review request** to see the tool name and the complete input, then **Accept** (this one call) or
  **Decline**. A call you do not approve, or that is not answered within the configured wait, is denied;
  nothing is ever allowed by a timeout, a crash, a stop or a restart. A dashboard-started run is headless,
  so the request cannot be answered in Claude Code itself. The wait is the Settings field "Claude approval
  wait" (default 900 seconds, range 60 to 3600; unverified above 120 seconds). The task shows the count
  and tool names of denied calls. A Claude project can be switched to Automatic mode in Settings: then
  `Bash`, `Write`, `Edit` and `NotebookEdit` requests without secret-shaped input are accepted one call at
  a time, and every other tool still waits for you. Details:
  [Claude tool-call approvals](dashboard-operations.md#claude-tool-call-approvals). Runs use
  `--setting-sources user`, so your own user-level allow rules and hooks apply (accepted design decision,
  [decisions](decisions.md); not tested): a call such a rule covers can run without reaching the dashboard.
- Instructions and follow-ups are passed to Claude Code as a command-line argument and can be seen by
  other users of this Mac with `ps` while a run lasts; do not put secrets in instructions.
- Readiness does not check the login; a run can fail after start with `claude_not_logged_in`: sign in
  through the Claude Code CLI. Deleting a run removes only the dashboard record; Claude Code keeps its own
  local session history.
- **Stop** sends SIGINT and escalates. A follow-up message resumes the session with `--resume` (limits: 50
  invocations and 200 turns per run, prompts up to 16000 characters; not for a run stopped for its permission
  mode).
- After a dashboard restart an active run is `unknown`, keeps its session and can be continued.
- Not available for Claude runs: the agent-message conversation view (the panel shows your own
  messages and is where a follow-up is sent), team view, outputs, delivery
  readiness and plan steps. Recovery and approval-alternative routes answer 409 "not available for
  this provider".
- Runs recorded earlier under Codex stay in the database. Acting on them answers 409 "recorded under
  a different provider". Projects stay visible in either deployment. Switch back with
  `sh scripts/run_dashboard.sh codex`.

Without an argument, or with anything but exactly `codex` or `claude`, the launcher prints its
usage and exits with status 2. See [Local dashboard operations](dashboard-operations.md) and the
[API contract](dashboard-api.md#provider-specific-answers).

What is done and what is not:

- Done (Plan 2, provider seam): the provider-neutral backend interface, the start-up setting that
  fails closed, the provider recorded on projects and runs, the provider label and the 409 answers.
- Done (Plan 3, managed run loop; fake-binary and unit tests, plus the live spikes below): launch
  builder, stream parser, process runner, lifecycle, stop, follow-up, restart handling, usage and
  cost estimate, UI wording. Evidence and what was not tested:
  [evidence](superpowers/evidence/2026-10-28-managed-run-loop.md).
- Spike S8 (project instructions): `--append-system-prompt` carries the appended text; `--add-dir`
  alone did not make `CLAUDE.md` visible. One live spike, four `haiku` runs (three reached the
  model), one run per condition, under `--setting-sources user`. It shows the appended text reaches
  the model, not that Claude Code resolves `@AGENTS.md` itself. Evidence:
  [S8](superpowers/spikes/S8-project-instructions.md).
- Spike S9 (role and environment): with `--agents` plus `--agent` the role became the main session
  (its prompt and tool list applied); a run with the environment allow-list logged in; `--effort`
  was accepted but its effect was not observable; the agent and appended texts both reached the
  model. Qualifiers: four `haiku` runs on Claude Code 2.1.312, one per condition, trivial prompt,
  total about 0.004 USD at list price. Evidence: [S9](superpowers/spikes/S9-role-and-environment.md).
- Done (Plan 4, managed approvals; unit and fake-binary tests, plus the S10 live spike of the hook itself):
  per-run hook settings file, loopback receiver, `tool_call` approvals with review and accept-once,
  configurable wait, optional Automatic mode, cleanup on stop, close and restart. Evidence and what was
  not verified: [evidence](superpowers/evidence/2026-11-01-managed-approvals.md); spike
  [S10](superpowers/spikes/S10-managed-approvals.md) (eight `haiku` runs, about 0.036 USD at list price).
  Live acceptance through the dashboard is pending the owner's approval.
- Not done: conversations, team view, outputs, deletion changes and delivery readiness for Claude
  runs (slice 2b, Plan 5), observed sessions (Phase 3, Plan 6). No Claude run has been started through
  the dashboard with the real `claude`; the optional live smoke test needs the owner's approval and has
  not been run.
- Design decisions that already apply: managed Claude runs are manual by default, with an optional
  per-project Automatic mode for approvals (owner, 2026-11-01, replacing the manual-only decision;
  [decisions](decisions.md)); Claude's own Auto mode is never used. They inherit the owner's user-level
  Claude configuration, including later additions.

Sources: [design](superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md),
[Plan 2](superpowers/plans/2026-10-28-claude-dashboard-provider-seam.md) and its
[evidence](superpowers/evidence/2026-10-28-provider-seam.md).

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

The plugin is an unpinned third-party dependency. Its own hooks, skills and commands have not been
security-reviewed by this project. Review each plugin update, including any hooks it adds, before
relying on it. Skill instructions never override AGENTS.md or SECURITY.md and never authorize
pushing, publishing or merging (see [`CLAUDE.md`](../CLAUDE.md)).

## Untrusted checkouts

When Claude Code starts in a checkout, `CLAUDE.md`, the `AGENTS.md` it imports and the
`.claude/agents/*.md` role files load as instructions. A change to any of them changes what the
agents are told. Other project files would also take effect:

- A project `.claude/settings.json` with hooks. Spike [S1](superpowers/spikes/S1-auth-launch-mode.md)
  showed that a project `SessionStart` hook ran in headless `-p` mode with no trust dialog (one run).
  Its permission rules would apply too.
- Project MCP servers in `.mcp.json`, which can launch commands. That they start the same way is
  docs-sourced, not tested.

This repository ships no `.claude/settings.json` and no `.mcp.json`. A branch could add them.

S1 observed three launch options that stopped the project hook: `--setting-sources user`,
`--safe-mode` and `--restricted`. The evidence is their help text and one hook marker, one run
each; nothing beyond the marker was tested. Per the help text, `--safe-mode` also turns off
`CLAUDE.md`, the role files and skills, and `--restricted` removes Bash and the other code-running
tools. S1 did not test whether `--setting-sources user` still loads the project's `CLAUDE.md`, role
files and `.mcp.json`. Later, spike [S6](superpowers/spikes/S6-managed-hook.md) found the project
`CLAUDE.md` was not visible under `--setting-sources user` and was visible under `user,project` (one
run each); role files and `.mcp.json` remain untested.

Before launching Claude Code on a checkout of someone else's branch or pull request, review the diff
of `CLAUDE.md`, `AGENTS.md`, `team_source/`, `.claude/` and `.mcp.json` against a version you trust.

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
- The pairings opus/high (`backend_developer` in R2, R8 and R9, `security_reviewer` in R3),
  opus/medium (`qa_engineer` in R4, `chief_of_staff` in R10), sonnet/high (R5), sonnet/medium (R6)
  and opus/low (R7) were each run against the live API, and the model and effort recorded in the
  transcripts matched this file (see [Verification status](#verification-status) and the
  [live evidence](superpowers/evidence/2026-10-26-phase-1-live.md)). opus/high also ran as the S5
  probe role, a scratch role outside the team roles that was not checked against `models.toml`.
  `fable` is the one pairing not verified. The model `haiku` and the efforts `xhigh` and `max` are
  allowed by the policy but were never run with a team role (`haiku` ran as the main session of the
  live runs and of spikes S1, S3, S4 and S5, and as a probe role in S3 and S4).

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
3. Add the role to `PROFILES` in `dashboard/team.py`; an entry is a (display name, description)
   tuple. The sync does not check this (it passes the
   role ids as the profiles); `tests/test_team_source_migration.py` does, and the dashboard
   requires the same set of roles.
4. Update the tests and docs that mention the role count. Examples (not a complete list; search for
   `14` and `28`): `tests/test_team.py` (pins 14 members), `tests/test_sync_roles.py` (28 files),
   `tests/test_team_source_policy.py`, `tests/test_team_source_migration.py` and its Codex baseline
   fixture, the role tables in `docs/team.md` and `docs/model-policy.md`, the "14 roles" and
   "thirteen core" statements in the docs, and the `role files written (28 files)` message in
   `scripts/sync_roles.py`.
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
four kinds:

- `<path>: missing`: a generated file does not exist. Run `python3 scripts/sync_roles.py`.
- `<path>: stale`: a generated file differs from what the source renders, because it was hand
  edited or the source changed without a sync. Run `python3 scripts/sync_roles.py` and review
  `git diff`. The sync overwrites a hand edit, so move the change into `team_source/` first.
- `<path>: unexpected, not generated from team_source`: a file with no source role, or a directory,
  sits in an agent folder. Each folder flags only its own extension (`.toml` in `.codex/agents/`,
  `.md` in `.claude/agents/`), in either letter case (so `Extra.MD` is flagged), and any
  directory; a stray file of the other extension, `.DS_Store` and other non-role files are
  ignored. The sync never deletes, so remove the entry by hand or add a source role.
- `<path>: unsafe, symlink or not a regular file` or `<path>: unsafe, symlink or not a directory`:
  an output file is a symlink, a directory or another non-regular file, or one of `.codex`,
  `.codex/agents`, `.claude` and `.claude/agents` is a symlink or not a directory. Writing through
  it could change a file outside the agent folders, so the plain sync also reports it, exits 1 and
  writes nothing at all. Inspect the entry and replace it with a plain file or folder.

The plain sync also exits 1 when it finds unexpected entries, after it has written the other
files. A malformed role source or invalid policy values are not reported as problem lines: the
command ends with a Python traceback whose last line names `RoleSourceError` or `PolicyError`. A
TOML syntax error in `team_source/models.toml` ends in `tomllib.TOMLDecodeError` instead. In these
cases, and for an unsafe path, the sync writes nothing, because every file is rendered and every
output path validated before any is written. After that, each file is replaced atomically (written
to a hidden temporary file in the same folder, then renamed over the old one), but a write error
part-way through the set, for example a full disk, can leave a partial set: some files new, the
rest old. Run the sync again once the cause is fixed.

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
- `.github/workflows/ci.yml` runs the drift check, the Python and Node tests and the history
  security check on every pull request. `.github/CODEOWNERS` names the owner for the rule,
  security and role files. Neither blocks a merge until branch protection is turned on.
- The git hooks run `python3 -I scripts/security_check.py ...`, so a stand-in module such as
  `scripts/shutil.py` cannot fake a pass. The commands above run without `-I` and would import such
  a stand-in from `scripts/`. On an untrusted checkout use `python3 -I scripts/sync_roles.py --check`
  and `python3 -I scripts/security_check.py staged` (both checked to work under `-I`).
- The unit tests include the drift guard (`tests/test_sync_roles.py`) and the documentation guard
  (`tests/test_claude_docs.py`).
- Two tests in `tests/test_git_service.py` fail on a machine whose global git ignore file ignores
  `.env`. They are environment failures, unrelated to the roles. The second command above, which
  points `XDG_CONFIG_HOME` at an empty directory, avoids that.

## Sign-in

Claude Code uses your own sign-in. No credentials belong in this repository, as AGENTS.md and
SECURITY.md already require.

## What is not supported yet

- Dashboard-managed Claude runs against the real CLI are untested (fake-binary tests only).
- Observation of your own Claude Code sessions.

Observed sessions are planned (Phase 3 in the
[design](superpowers/specs/2026-10-26-claude-code-adaptation-design.md)) and are not built. Approvals for
dashboard-started runs exist (see [The dashboard with Claude](#the-dashboard-with-claude)); they cover
managed runs only, not your own Claude Code sessions. Spike S2 observed that in Auto permission mode
routine tool calls are approved without a prompt, so the hook is not reached for them
([S2](superpowers/spikes/S2-approvals.md)); the dashboard stops a run that is not in the `default`
permission mode.

## Verification status

Spike reports are in `docs/superpowers/spikes/`; the summary is the
[Phase 0 findings](superpowers/spikes/2026-10-26-phase-0-findings.md). The rows marked
"Observed, one run" come from the 10 short live runs described at the top of this page, recorded in the
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
| Pairings opus/medium (`qa_engineer`; also `chief_of_staff` in R10), sonnet/high (`technical_writer`), sonnet/medium (`user_documentation_writer`), opus/low (`expert_escalation`): model and effort recorded in the subagent transcripts matched `team_source/models.toml` | Observed, one run per role | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R4 to R7, R10 |
| Pairing opus/high (`backend_developer`, `security_reviewer`): model and effort recorded matched `team_source/models.toml` | Observed, in R2, R3, R8 and R9 (also in the S5 scratch probe role) | [Live evidence](superpowers/evidence/2026-10-26-phase-1-live.md) R2, R3, R8, R9; [S5](superpowers/spikes/S5-model-alias-precheck.md) |
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

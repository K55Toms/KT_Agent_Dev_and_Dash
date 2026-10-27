# Claude Code Adaptation, Phases 0 and 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the unknowns about running this project on Claude Code (Phase 0), then make the 14-role agent team run on Claude Code from one shared role source while Codex keeps working unchanged (Phase 1).

**Architecture:** Role intent lives once in `team_source/` (one Markdown file per role plus a model policy file with a column per harness). A stdlib-only generator writes `.codex/agents/*.toml` (which `dashboard/server.py:load_roles` already reads) and `.claude/agents/*.md`. A drift test keeps generated files in sync with the source. Phase 0 spikes are throwaway experiments whose output is a findings report.

**Tech Stack:** Python 3.11+ stdlib only (`unittest`, `tomllib`), Node `node:test` (existing suite), Claude Code CLI.

**Spec:** `docs/superpowers/specs/2026-10-26-claude-code-adaptation-design.md`

## Global Constraints

- Codex must not regress: the existing suite (584 Python tests, 126 Node tests at the last recorded count) keeps passing. Task 6 records the actual baseline.
- `AGENTS.md`, `SECURITY.md`, gitleaks configuration and the git hooks are unchanged. Do not edit them.
- No new third-party dependencies in the repo. New repo code uses the Python standard library only. (Spike S2 installs the Agent SDK in a scratch virtualenv outside the repo.)
- Ponytail is not used on the Claude side. No Claude role text mentions it.
- Roles are one source of truth: never hand-edit `.codex/agents/*.toml` or `.claude/agents/*.md` after Task 11; edit `team_source/` and regenerate.
- No secrets in any file, log, report or commit. Use variable names and `<REDACTED>` only.
- Every real Claude Code run (all of Phase 0, and Task 15) consumes the owner's subscription usage. The owner must say yes in chat before each one.
- Nothing is pushed, published or deployed. Commits stay on the work branch.
- Work happens on a branch cut from the owner's synced state, not from the stale GitHub copy this plan was prepared from.
- The dashboard UI never labels the Claude backend "Claude Code" (applies from Phase 2; no UI work here).

## Decisions made in this plan (the owner may veto at review)

1. **Reviewer tools.** `security_reviewer` and `code_quality_reviewer` get the tool allowlist `Read, Grep, Glob` only. Docs say allowing `Bash` does not make a role read-only. The cost: these two roles cannot run checks themselves; the coordinator or `qa_engineer` runs them. Spike S4 re-tests this; a hook-guarded Bash variant is a later option, not built here.
2. **No recursive delegation.** Every role except `chief_of_staff` gets `disallowedTools: Agent`, matching AGENTS.md ("avoid recursive coordinators").
3. **Codex-only passages.** Text about Ponytail, `ui-skills-root`/`npx ui-skills`, and Codex spawn-override behaviour is wrapped in `codex-only` blocks. The `ui-skills-root` removal is the plan's call, not the owner's: it is a Codex skill, and nothing in the owner's answers covers it.
4. **`AGENTS.md` is not split.** Because it must stay unchanged, `CLAUDE.md` imports it and adds a "Claude Code differences" section that overrides the Codex- and Ponytail-specific parts.
5. **Proposed Claude models** (owner confirms or edits in `team_source/models.toml` at Task 9; the generator refuses to run until every cell is a valid value):

| Roles | Codex today | Proposed Claude |
| --- | --- | --- |
| chief_of_staff, product_manager, ui_designer, frontend_developer, qa_engineer | gpt-6.1-sol, medium | opus, medium |
| technical_architect, backend_developer, platform_reliability_engineer, security_reviewer, code_quality_reviewer, agent_evaluation_engineer | gpt-6.1-sol, high | opus, high |
| technical_writer | gpt-6-luna, high | sonnet, high |
| user_documentation_writer | gpt-6-luna, medium | sonnet, medium |
| expert_escalation | gpt-6-astra, low | fable, low |

## Review Focus

- A role body containing `"""` or a backslash would corrupt generated TOML: the generator must raise, not emit broken TOML (Task 8).
- A role source edited but outputs not regenerated: the drift test must fail and name the stale file (Task 11).
- An unbalanced or nested `codex-only` marker silently swallowing text: parsing must raise with the role id and line (Task 7).
- A role added to the source but missing from `models.toml` or from `dashboard/team.py:PROFILES`: validation must fail with a clear message (Task 9).
- Claude output leaking Codex-only terms (`ponytail`, `ui-skills`, `codex`, `gpt-`): a test scans every rendered Claude file (Task 10).
- Extra, unexpected files in `.claude/agents/`: `--check` must report them rather than ignore them (Task 11).

---

# Phase 0: spikes

Spikes are throwaway. Scratch projects live in the session scratchpad, never in the repo. Nothing from a spike is kept except its entry in the findings report (Task 5). Each spike records: exact command, observed output (redacted), and pass/fail against the stated criterion. Every Claude run is announced to the owner first.

### Task 1: S4 Team loading

**Files:**
- Create (scratch only): `<scratchpad>/s4/CLAUDE.md`, `<scratchpad>/s4/AGENTS.md`, `<scratchpad>/s4/.claude/agents/reader.md`, `<scratchpad>/s4/.claude/agents/writer.md`
- Create: `docs/superpowers/spikes/S4-team-loading.md`

**Interfaces:**
- Produces: S4 findings that Tasks 7 to 10 depend on: (a) does `@AGENTS.md` import work, (b) can a `tools: Read, Grep, Glob` role write via any route, (c) which model each role actually used, (d) accepted `effort` values.

- [ ] **Step 1: Build the scratch project.** `CLAUDE.md` is one line, `@AGENTS.md`. `AGENTS.md` contains a rule with a unique marker string `S4-MARKER-7731`. `reader.md` has frontmatter `name: reader`, `description: reads files`, `tools: Read, Grep, Glob`, `model: haiku`, `effort: low`. `writer.md` has `name: writer`, `description: writes files`, `model: sonnet`, no `tools`.
- [ ] **Step 2: Get the owner's yes, then run import check.** Run `claude -p "What is the S4 marker string in your project instructions?" --output-format json` in the scratch dir. Pass: the answer contains `S4-MARKER-7731`.
- [ ] **Step 3: Read-only check.** Run `claude -p "Use the reader agent to create a file named s4-out.txt containing hello" --output-format stream-json --verbose`. Pass: `s4-out.txt` does not exist afterwards. Record whether the reader attempted any other route (for example a shell tool) and what happened.
- [ ] **Step 4: Model check.** From the same stream, extract the `message.model` of messages whose `parent_tool_use_id` is non-null for each of `reader` and `writer` (run the writer once with "Use the writer agent to say hi"). Pass: the recorded model for each differs as the aliases imply. Record the exact model IDs seen.
- [ ] **Step 5: Effort check.** Run the reader once with `effort: bogus-value` in frontmatter. Record whether Claude Code warns, ignores or errors. Record the accepted value set found in current docs (`https://code.claude.com/docs/en/sub-agents`).
- [ ] **Step 6: Write `docs/superpowers/spikes/S4-team-loading.md`** with the four answers, each stated as pass, fail or inconclusive, plus the exact commands. Commit: `git add docs/superpowers/spikes/S4-team-loading.md && git commit -m "docs: record S4 team-loading spike findings"`.

### Task 2: S1 Authentication and launch mode

**Files:**
- Create (scratch only): `<scratchpad>/s1/.claude/settings.json`
- Create: `docs/superpowers/spikes/S1-auth-launch-mode.md`

**Interfaces:**
- Produces: the launch mode Phase 2 will use for managed runs, or a recorded "none found", and the owner's recorded decision on subscription versus API key.

- [ ] **Step 1: Login check.** With the owner's yes, run `claude -p "Reply with OK" --output-format json` in an empty scratch dir without `--bare`. Pass: exit 0 and a result. Record from the output which credential source is reported, if the output exposes one. Record `total_cost_usd` as an estimate, not a charge.
- [ ] **Step 2: Hook-execution check.** In `<scratchpad>/s1/.claude/settings.json` add a `SessionStart` command hook that runs `touch <scratchpad>/s1/hook-ran`. Run the same `claude -p` command there without `--bare`. Pass criterion for this step is only to record whether `hook-ran` exists (the docs say it should).
- [ ] **Step 3: Candidate mitigations.** Run `claude --help` and list flags that control which settings sources load. For each candidate flag found (for example a setting-sources option), delete `hook-ran`, rerun with the flag, and record whether login still works and whether `hook-ran` appears. Also run once with `--bare` and record that it does not use the subscription login. Do not use a flag that `claude --help` does not list.
- [ ] **Step 4: Owner decision.** Present the owner with Step 3's table and the SDK docs' statement on third-party claude.ai login (cite the page, do not quote it at length). Record the owner's choice verbatim: subscription, API key (environment variable name only), or undecided.
- [ ] **Step 5: Write `S1-auth-launch-mode.md`** with the table, the recommended Phase 2 launch mode (or "none found: API key or trusted projects only"), and the owner's decision. Commit: `git add docs/superpowers/spikes/S1-auth-launch-mode.md && git commit -m "docs: record S1 auth and launch-mode findings"`.

### Task 3: S2 Approval round trip

**Files:**
- Create (scratch only): `<scratchpad>/s2/stub_dashboard.py` (stub HTTP server on 127.0.0.1, random port, requires `Authorization: Bearer <token from env var S2_TOKEN>`), `<scratchpad>/s2/managed.py` (Agent SDK script), `<scratchpad>/s2/.claude/settings.json`
- Create: `docs/superpowers/spikes/S2-approvals.md`

**Interfaces:**
- Produces: observed answers to: allow scope (once or wider), maximum wait, behaviour when the dashboard is down, payload fields received, and whether the managed callback and the hook can both be used.

- [ ] **Step 1: Managed path.** In a scratch virtualenv (not the repo's), install `claude-agent-sdk`. Write `managed.py` with a `can_use_tool` callback that logs tool name and input, sleeps 5 seconds, and allows `Bash` commands starting with `echo` once; a second identical request must trigger the callback again. Ask Claude to run `echo one` twice. Pass: the callback fires for both calls. Then deny a third call with a message and record that Claude receives and repeats that message.
- [ ] **Step 2: Hook payload.** Write `stub_dashboard.py` so it logs each request body (tool name and input only, no headers) and answers `PermissionRequest` with `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}` after a configurable delay. Configure an `http` `PermissionRequest` hook in `<scratchpad>/s2/.claude/settings.json` with `timeout: 20` and the token via `allowedEnvVars`. Run a `claude -p` that needs a Bash permission. Record the exact payload field names received.
- [ ] **Step 3: Timeout and down behaviour.** Set the stub delay to 30 seconds and record what Claude Code does at 20 seconds. Then stop the stub and rerun; record what happens (expected from docs: normal permission flow continues). Fail-closed requirement from the spec: record whether a managed `-p` run denies when nothing answers.
- [ ] **Step 4: Interactive session (owner performs).** Give the owner the exact checklist: start `claude` in `<scratchpad>/s2` with the stub running, ask it to run `echo from-interactive`, watch the stub log, and report whether the stub saw the request and whether the answer was applied. The owner reports back; record their statement.
- [ ] **Step 5: Write `S2-approvals.md`** with the observed answers and a verdict for each spec claim (allow-once, long wait, interactive sessions, fail-closed). Commit: `git add docs/superpowers/spikes/S2-approvals.md && git commit -m "docs: record S2 approval round-trip findings"`.

### Task 4: S3 Event stream mapping

**Files:**
- Create (scratch only): `<scratchpad>/s3/summarize_stream.py`
- Create: `docs/superpowers/spikes/S3-event-stream.md`

**Interfaces:**
- Produces: a table mapping each dashboard projection (status, plan or progress, visible messages, token usage, delegation lineage, completion and failure) to the stream-json event that carries it, or "no equivalent".

- [ ] **Step 1: Capture.** With the owner's yes, in a scratch project with one subagent definition, run a `claude -p` prompt that delegates once and runs one `Bash` command, with `--output-format stream-json --verbose --include-partial-messages` and `--forward-subagent-text`. Save the output to `<scratchpad>/s3/stream.ndjson`. Also capture one run that fails (for example an impossible tool request) and one interrupted with SIGINT.
- [ ] **Step 2: Summarize.** `summarize_stream.py` reads an NDJSON file and prints each distinct `(type, subtype)` with a count, whether `usage` appears and where, `parent_tool_use_id` values, `session_id`, and the final `result` message's cost and denial fields. No message text is printed.
- [ ] **Step 3: Write `S3-event-stream.md`** with the mapping table, the failure and interrupt shapes, and a list of dashboard projections with no Claude equivalent (candidates: Codex "plan" updates versus Claude's task-list tool). Commit: `git add docs/superpowers/spikes/S3-event-stream.md && git commit -m "docs: record S3 event-stream mapping"`.

### Task 5: Phase 0 findings report and owner gate

**Files:**
- Create: `docs/superpowers/spikes/2026-10-26-phase-0-findings.md`

**Interfaces:**
- Consumes: the four spike files.
- Produces: go or no-go for Phase 1 choices (import vs reference, reviewer profile, effort values, launch mode) and a list of spec amendments.

- [ ] **Step 1: Consolidate** each spike into one verdict line (pass, fail, inconclusive), then list: the `CLAUDE.md` form to use in Task 12 (`@AGENTS.md` import, or a prose reference); whether the reviewer allowlist held; the valid `effort` values for Task 9's validator; the Phase 2 launch mode; and any spec sections that need amending, with the proposed new wording.
- [ ] **Step 2: Owner gate.** Ask the owner to review the report and the spec amendments. Apply amendments to the spec only on their yes. Commit: `git add docs/superpowers && git commit -m "docs: Phase 0 findings and spec amendments"`.
- [ ] **Step 3:** Phase 1 does not start until the owner accepts this report.

---

# Phase 1: the team

### Task 6: Branch and baseline

**Files:**
- Create: `docs/superpowers/plans/phase-1-baseline.md`

**Interfaces:**
- Produces: the recorded test counts every later task compares against.

- [ ] **Step 1: Confirm the starting point.** Verify the owner has synced their local work: `git status` is clean and `git log origin/main..HEAD` is empty on the checkout used. If not, stop and tell the owner.
- [ ] **Step 2: Create the branch** (use superpowers:using-git-worktrees): `git switch -c claude-code-adaptation`.
- [ ] **Step 3: Run the baseline.** Run `sh scripts/bootstrap.sh`, then `python3 -m unittest discover -s tests -v 2>&1 | tail -5` and `node --test tests/`. Record passed, failed and skipped counts for each in `phase-1-baseline.md`, with the date and git commit hash. If any test fails before changes, record it and tell the owner; do not proceed to Task 7 until they decide.
- [ ] **Step 4: Commit:** `git add docs/superpowers/plans/phase-1-baseline.md && git commit -m "docs: record Phase 1 test baseline"`.

### Task 7: Role source format and parser

**Files:**
- Create: `team_source/__init__.py`, `team_source/roles.py`
- Test: `tests/test_team_source_roles.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Role: id: str; description: str; profile: str; body: str` where `profile` is `"editor"` or `"reviewer"` and `body` keeps both `codex-only` and `claude-only` blocks unresolved.
  - `parse_role(text: str, source: str) -> Role` raising `RoleSourceError(ValueError)`.
  - `resolve(body: str, harness: str) -> str` for `harness` in `{"codex", "claude"}`: removes the marker lines, keeps blocks for the matching harness, drops the others.
  - `load_roles_dir(directory: Path) -> dict[str, Role]`: parses every `*.md` file, requires each front-matter `id` to equal the file's stem, and returns roles keyed by id.
- Source file format: first line `---`; then lines `key: <JSON string>` for `id`, `description`, `profile`; then `---`; then the body. Block markers are whole lines `<!-- codex-only -->`, `<!-- /codex-only -->`, `<!-- claude-only -->`, `<!-- /claude-only -->`.

- [ ] **Step 1: Write failing tests** in `tests/test_team_source_roles.py`: `test_parse_reads_front_matter_and_body`, `test_resolve_keeps_matching_harness_block_and_drops_other`, `test_resolve_removes_marker_lines_exactly` (no blank-line residue: input `a\n<!-- codex-only -->\nb\n<!-- /codex-only -->\nc\n` resolves to `a\nb\nc\n` for codex and `a\nc\n` for claude), `test_unbalanced_marker_raises_with_role_id_and_line`, `test_nested_marker_raises`, `test_unknown_profile_raises`, `test_missing_key_raises`, `test_error_text_includes_source`, `test_load_roles_dir_rejects_id_that_differs_from_filename_stem`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_team_source_roles -v`. Expected: ImportError/failures.
- [ ] **Step 3: Implement** `team_source/roles.py` per the interfaces. Use a line-based state machine for blocks; front matter values via `json.loads`.
- [ ] **Step 4: Run** the same command. Expected: all pass.
- [ ] **Step 5: Commit:** `git add team_source tests/test_team_source_roles.py && git commit -m "feat: add role source parser with harness blocks"`.

### Task 8: Renderers

**Files:**
- Modify: `team_source/roles.py`
- Test: `tests/test_team_source_render.py`

**Interfaces:**
- Consumes: `Role`, `resolve` from Task 7.
- Produces:
  - `render_codex(role: Role, model: str, effort: str) -> str` returning TOML text with keys in the order `name`, `model`, `model_reasoning_effort`, `description`, `developer_instructions`, where `developer_instructions` is a multi-line `"""` string equal to `"\n" + resolve(role.body, "codex")`.
  - `render_claude(role: Role, model: str, effort: str, *, coordinator: bool) -> str` returning Markdown with front matter keys in the order `name`, `description` (JSON-quoted), `model`, `effort`, then `tools: Read, Grep, Glob` when `role.profile == "reviewer"`, then `disallowedTools: Agent` when `coordinator` is false; body is `resolve(role.body, "claude")`.

- [ ] **Step 1: Write failing tests:** `test_render_codex_parses_back_to_same_values` (render, `tomllib.loads`, compare each field), `test_render_codex_rejects_triple_quote_and_backslash` (expects `RoleSourceError`), `test_render_claude_reviewer_has_read_only_tools_and_no_agent_tool`, `test_render_claude_editor_has_no_tools_line`, `test_render_claude_coordinator_keeps_agent_tool` (no `disallowedTools` line), `test_render_claude_description_survives_quotes` (description with a double quote round-trips through `json.loads` of the value).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_team_source_render -v`. Expected: failures.
- [ ] **Step 3: Implement** both renderers. After rendering Codex TOML, parse it with `tomllib` and raise `RoleSourceError` if any field differs from the input; that is also what rejects `"""` and backslashes.
- [ ] **Step 4: Run** the same command. Expected: pass.
- [ ] **Step 5: Commit:** `git add team_source tests/test_team_source_render.py && git commit -m "feat: render Codex TOML and Claude Markdown from role source"`.

### Task 9: Model policy file and cross-checks

**Files:**
- Create: `team_source/models.toml`, `team_source/policy.py`
- Test: `tests/test_team_source_policy.py`

**Interfaces:**
- Consumes: `Role` from Task 7.
- Produces:
  - `models.toml` shape: `[<role_id>.codex]` and `[<role_id>.claude]` tables, each with `model` and `effort`.
  - `@dataclass(frozen=True) class Assignment: model: str; effort: str`
  - `load_policy(path: Path) -> dict[str, dict[str, Assignment]]` (outer key role id, inner key `"codex"` or `"claude"`).
  - `validate(roles: dict[str, Role], policy, profiles: Iterable[str]) -> None` raising `PolicyError(ValueError)`.
  - Allowed values: Codex model in `{"gpt-6.1-sol","gpt-6-luna","gpt-6-astra"}` and effort in `{"low","medium","high","xhigh"}` (the sets `dashboard/native_roles.py` enforces); Claude model in `{"opus","sonnet","haiku","fable"}` and effort in the set recorded in the Task 5 report.

- [ ] **Step 1: Fill `models.toml`.** Codex column: copy every role's current `model` and `model_reasoning_effort` from `.codex/agents/*.toml`. Claude column: the proposed table above, edited by the owner if they chose to. Show the owner the finished file and get their yes before Step 2.
- [ ] **Step 2: Write failing tests:** `test_loads_every_role_with_both_columns`, `test_missing_role_in_policy_raises`, `test_extra_role_in_policy_raises`, `test_unknown_claude_model_raises`, `test_unknown_codex_effort_raises`, `test_role_ids_must_equal_dashboard_profiles` (pass `dashboard.team.PROFILES` keys), `test_codex_column_matches_current_agents_files` (parses `.codex/agents/*.toml` and compares; this guards the transcription).
- [ ] **Step 3: Run** `python3 -m unittest tests.test_team_source_policy -v`. Expected: failures.
- [ ] **Step 4: Implement** `team_source/policy.py`.
- [ ] **Step 5: Run** the same command. Expected: pass.
- [ ] **Step 6: Commit:** `git add team_source tests/test_team_source_policy.py && git commit -m "feat: add shared model policy with per-harness columns"`.

### Task 10: Extract the 14 roles into the source

**Files:**
- Create: `team_source/roles/<role_id>.md` (14 files), `tests/fixtures/codex_roles_baseline.json`
- Test: `tests/test_team_source_migration.py`

**Interfaces:**
- Consumes: `parse_role`, `render_codex`, `load_policy` from Tasks 7 to 9.
- Produces: the committed role source, and a migration guard asserting Codex output is unchanged.

- [ ] **Step 1: Capture the baseline** *before touching any role file*: write `tests/fixtures/codex_roles_baseline.json` containing, for each `.codex/agents/*.toml`, the parsed fields (`name`, `description`, `model`, `model_reasoning_effort`, `developer_instructions`). Commit it on its own: `git commit -m "test: capture Codex role baseline before migration"`.
- [ ] **Step 2: Write the failing tests:** `test_codex_render_of_source_equals_baseline_for_all_14_roles` (render each source role with its Codex assignment, `tomllib.loads`, compare to the baseline JSON), `test_claude_render_contains_no_codex_only_terms` (case-insensitive scan of every rendered Claude file for `ponytail`, `ui-skills`, `codex`, `gpt-`; `AGENTS.md` references are allowed).
- [ ] **Step 3: Run** them. Expected: failures (no source yet).
- [ ] **Step 4: Create the 14 source files** by transcribing each TOML's `developer_instructions` into the body and its `description` into the front matter. `profile` is `reviewer` for `security_reviewer` and `code_quality_reviewer`, `editor` for the rest. Wrap exactly these passages in `codex-only` blocks (found by `grep -n -iE "ponytail|ui-skills|skill|spawn" .codex/agents/*.toml`): the Ponytail paragraph in `backend_developer` and `frontend_developer`; the `ui-skills-root` paragraph in `frontend_developer` and `ui_designer`; the Ponytail lines in `code_quality_reviewer`, `agent_evaluation_engineer` and `chief_of_staff`; and chief_of_staff's "Custom role model settings take precedence; do not assume a spawn override changes that role." In that last place add a `claude-only` replacement sentence: "A role's configured model applies unless an invocation overrides it; do not override a role's model without the owner's approval."
- [ ] **Step 5: Run** the tests from Step 2. Expected: pass. If a Codex-only term remains in Claude output, wrap that sentence and repeat.
- [ ] **Step 6: Owner review.** Show the owner the diff between each role's Codex and Claude rendering for the 6 files with `codex-only` blocks. Revise on their feedback.
- [ ] **Step 7: Commit:** `git add team_source tests && git commit -m "feat: migrate 14 roles into shared source"`.

### Task 11: Sync command and drift check

**Files:**
- Create: `scripts/sync_roles.py`
- Modify: `.gitignore`
- Test: `tests/test_sync_roles.py`

**Interfaces:**
- Consumes: Tasks 7 to 10.
- Produces: `sync(root: Path, *, check: bool) -> list[str]` returning problem descriptions (empty means clean); CLI `python3 scripts/sync_roles.py [--check]` exiting 0 if clean or written, 1 if `--check` finds drift.
- Behaviour: writes `.codex/agents/<id>.toml` and `.claude/agents/<id>.md` for all 14 roles; `--check` writes nothing and reports each file that differs, is missing, or is an unexpected extra `.md` in `.claude/agents/` or `.toml` in `.codex/agents/`.

- [ ] **Step 1: Write failing tests** against a temp copy of the repo skeleton: `test_sync_writes_all_28_files`, `test_check_passes_after_sync`, `test_check_fails_naming_the_edited_file`, `test_check_reports_extra_agent_file`, `test_check_writes_nothing`, `test_sync_is_idempotent` (second run changes no bytes), `test_works_from_another_working_directory`, `test_repository_roles_are_in_sync` (runs `sync(ROOT, check=True)` against the real repo and asserts no problems: this is the standing drift guard), `test_dashboard_load_roles_equals_baseline_after_sync` (after syncing into a temp copy, `dashboard.server.load_roles()`-style parsing of its `.codex/agents` equals `tests/fixtures/codex_roles_baseline.json`).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_sync_roles -v`. Expected: failures.
- [ ] **Step 3: Implement** `scripts/sync_roles.py` with the repo root derived from the file location, never the working directory. `coordinator` is `role.id == "chief_of_staff"`.
- [ ] **Step 4: Update `.gitignore`** to track only generated agent definitions, mirroring the `.codex` rules: ignore `.claude/*`, then `!.claude/agents/` and `!.claude/agents/*.md`.
- [ ] **Step 5: Run** `python3 scripts/sync_roles.py`, then `python3 scripts/sync_roles.py --check` (expected exit 0), then the Step 1 tests (expected pass).
- [ ] **Step 6: Run the Task 10 tests** and the Python suite's `tests.test_team tests.test_team_prompt tests.test_native_roles` (expected pass: `load_roles()` still reads the regenerated TOML).
- [ ] **Step 7: Expect a cosmetic diff.** Some current TOML files order their keys differently; regeneration normalizes them to the Task 8 order. Confirm with the baseline test that parsed values are identical, then commit generated files with the generator: `git add scripts/sync_roles.py .gitignore .codex/agents .claude/agents tests && git commit -m "feat: generate Codex and Claude role files from team_source"`.

### Task 12: CLAUDE.md and setup documentation

**Files:**
- Create: `CLAUDE.md`, `docs/claude-code-setup.md`
- Modify: `docs/team.md` (add a short section), `README.md` (one short section)
- Test: `tests/test_claude_docs.py`

**Interfaces:**
- Consumes: the `CLAUDE.md` form decided in Task 5 (`@AGENTS.md` import or prose reference).
- Produces: the Claude Code entry point.

- [ ] **Step 1: Write failing tests:** `test_claude_md_references_agents_md`, `test_claude_md_has_differences_section_naming_ponytail_not_used`, `test_setup_doc_mentions_sync_command_and_superpowers`, `test_docs_contain_no_secret_shaped_text` (reuse `dashboard.project_files.scan_preview` on each new file; it raises `FileAccessError` on findings).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_claude_docs -v`. Expected: failures.
- [ ] **Step 3: Write `CLAUDE.md`:** the AGENTS.md reference; a **Claude Code differences** section stating that the primary session acts as Chief of Staff, `.claude/agents/` replaces every `.codex/agents/` mention, Ponytail and `ui-skills-root` do not apply, subagents cannot ask the owner questions or (except `chief_of_staff`) delegate, reviewers have read-only tools and the coordinator or QA runs checks for them, and `team_source/` is the only place to edit roles; a **Process** section saying to use the superpowers skills (brainstorming, writing-plans, test-driven-development, verification-before-completion, requesting-code-review) for design, planning and completion on this side, with the 14 roles unchanged.
- [ ] **Step 4: Write `docs/claude-code-setup.md`:** installing the superpowers plugin per machine (state that this repo does not install it, as `docs/skill-setup.md` does for Codex skills), running `python3 scripts/sync_roles.py`, the model policy file, and what is not yet supported (dashboard runs, approvals, observed sessions: Phases 2 and 3). Add the short pointers to `docs/team.md` and `README.md`.
- [ ] **Step 5: Run** the Step 1 tests. Expected: pass.
- [ ] **Step 6: Commit:** `git add CLAUDE.md docs tests/test_claude_docs.py README.md && git commit -m "docs: add Claude Code entry point and setup guide"`.

### Task 13: Full regression

**Files:** none changed.

- [ ] **Step 1:** Run `python3 -m unittest discover -s tests -v 2>&1 | tail -5` and `node --test tests/`. Expected: failures zero; passed and skipped counts equal the Task 6 baseline plus only the new tests from Tasks 7 to 12.
- [ ] **Step 2:** Run `python3 scripts/sync_roles.py --check` (exit 0), `python3 scripts/security_check.py staged` and `python3 scripts/security_check.py history` (both pass). Record outputs as evidence, not summaries.
- [ ] **Step 3:** If any count differs from expectation, stop and use superpowers:systematic-debugging; do not adjust the baseline.

### Task 14: Project records

**Files:**
- Modify: `docs/task-board.md`, `docs/decisions.md`

- [ ] **Step 1:** Add one dated entry to each, following the existing entries' style: what was delivered (shared role source, generator, `CLAUDE.md`), the decisions listed under "Decisions made in this plan" with the owner's rulings, the executed checks with exact counts from Task 13, and the open items (live Claude evidence in Task 15, Phases 2 and 3). Note the documentation impact and that no-documentation-change is not claimed.
- [ ] **Step 2: Commit:** `git add docs/task-board.md docs/decisions.md && git commit -m "docs: record Phase 1 outcome and decisions"`.

### Task 15: Live Claude Code evidence

**Files:**
- Create: `docs/superpowers/evidence/2026-10-26-phase-1-live.md`

**Interfaces:**
- Produces: the Phase 1 "done" evidence: a specialist run showing the intended instructions, tools and model, from tool output rather than the agent's claim.

- [ ] **Step 1: Get the owner's yes**, stating that this spends subscription usage (three short runs).
- [ ] **Step 2: Instructions.** In the repo root run `claude -p "Use the backend_developer agent. Quote the first sentence of its instructions and nothing else." --output-format stream-json --verbose`. Pass: the quoted sentence equals the first sentence of `team_source/roles/backend_developer.md`'s body, and no mention of Ponytail appears.
- [ ] **Step 3: Read-only.** Run `claude -p "Use the security_reviewer agent to create a file named evidence-out.txt"`. Pass: the file does not exist afterwards (delete it if it does and record a fail).
- [ ] **Step 4: Model.** From Step 2's and Step 3's streams, record the `message.model` for each subagent message. Pass: it matches the `models.toml` Claude column's alias for that role.
- [ ] **Step 5: Write the evidence file** with the three results, labelled as native Claude Code evidence (not mocks), with commands and redacted excerpts. Commit: `git add docs/superpowers/evidence && git commit -m "docs: record live Claude Code evidence for Phase 1"`.

### Task 16: Branch review and handoff

- [ ] **Step 1:** Request a review of the whole branch (superpowers:requesting-code-review) and address findings.
- [ ] **Step 2:** Use superpowers:verification-before-completion: rerun Task 13's commands fresh and report their output.
- [ ] **Step 3:** Hand the branch to the owner via superpowers:finishing-a-development-branch. Do not push or open a pull request unless the owner asks.

## Not in this plan

Phase 2 (backend interface, Claude managed backend, approvals, UI) and Phase 3 (observed sessions) each get their own plan after this one's findings are in. No file under `dashboard/` is modified here.

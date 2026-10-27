# Claude dashboard: baseline, characterization and spikes (Plan 1 of 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin current Codex dashboard behaviour with characterization tests, then run the two feasibility spikes (S6 managed hook, S7 interactive hooks) that decide whether the rest of the Claude dashboard can proceed as designed.

**Architecture:** No product code changes. Tasks 1 to 4 add a baseline record and golden-file tests that drive `Dashboard` with a scripted fake client and compare a normalized state projection to committed goldens. Tasks 5 to 8 are throwaway spikes outside the repo that write evidence documents into the repo.

**Tech Stack:** Python 3 `unittest` (stdlib only), the existing `Dashboard` and `FakeClient` test pattern from `tests/test_dashboard_backend.py`, the system `claude` CLI for the spikes.

**Spec:** `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (approved by the owner 2026-10-27).

## Plan set

The spec is too large and too dependent on spike results for one plan. Plan 1 (this file) ends in a go/no-go gate. Plans 2 to 4 are written after it, each from the evidence it produces:

1. This plan: baseline, characterization tests, spikes S6 and S7.
2. Slice 2a: neutral interface, Codex translator, provider setting and migration, Claude backend, approvals.
3. Slice 2b: carried-over features.
4. Phase 3: hook receiver and observed sessions.

## Global Constraints

- Codex behaviour must not change. Tasks 1 to 4 change no file under `dashboard/`.
- `AGENTS.md`, `SECURITY.md`, `.gitleaks.toml` and `.githooks/` are unchanged.
- Run `python3 -I scripts/security_check.py staged` before every commit and `... history` before any push. Never print environment variables, tokens or credentials. Use `<REDACTED>` in evidence.
- Commit identity `K55Toms <K55Toms@users.noreply.github.com>`; commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nothing is pushed without the owner's authorization.
- Live Claude runs (Tasks 6 and 7) happen only after the owner approves the run list and the estimated list-price cost. Model alias `haiku`, input from `/dev/null`, launch mode `--setting-sources user`. Record `claude --version` with every run.
- Clean-environment test command (the dashboard strips `GIT_*` variables, so isolate `HOME`): `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests`. Node: `node --test tests/*.js`.
- Golden files contain only synthetic values (`SYNTHETIC_*`), never real paths, ids or timestamps.

## Review Focus

- A golden that cannot fail: each characterization test must be shown to fail when the behaviour it pins is mutated.
- Volatile data in goldens (uuids, timestamps, temp paths) making them flaky or machine-specific.
- Spike runs that leak credentials, print environment variables, or auto-allow something when nobody answered.
- Spike claims stronger than the evidence (one run is one run; say so).
- A regenerated golden hiding a regression: regeneration must be explicit and named in the commit message.

---

### Task 1: Baseline record

**Files:**
- Create: `docs/superpowers/evidence/2026-10-27-phase-2-baseline.md`

**Interfaces:**
- Produces: the baseline test counts and the baseline commit hash that Plans 2 to 4 compare against.

- [ ] **Step 1: Run the clean-environment Python suite and the Node suite on `main`** with the commands in Global Constraints. Expected: 0 failures; record tests run, skipped, and seconds. (CI on `main` is the second source: the latest `ci.yml` run on `main`, 738 Python tests with none skipped at the last record.)
- [ ] **Step 2: Write the evidence file**: `git rev-parse HEAD`, `python3 --version`, `node --version`, the counts from Step 1, the two commands, and one line stating that skips differ between this machine (PyJWT absent) and CI (PyJWT installed).
- [ ] **Step 3: Run `python3 -I scripts/security_check.py staged`, then commit** ("docs: record the Phase 2 baseline").

### Task 2: Characterization harness and run-lifecycle goldens

**Files:**
- Create: `tests/characterization.py` (helpers), `tests/test_characterization_runs.py`, `tests/fixtures/characterization/runs.json`

**Interfaces:**
- Produces in `tests/characterization.py`:
  - `normalize(snapshot: dict) -> dict`: returns the snapshot with every uuid-like id replaced by a stable ordinal (`task-1`, `approval-1`), timestamps and absolute paths removed, key order sorted. Raises `AssertionError` if any string matches a secret-looking pattern from `dashboard.project_files.scan_preview`.
  - `check_golden(testcase, name: str, actual: dict) -> None`: loads `tests/fixtures/characterization/<file>` entry `name`, asserts equality with a readable diff; when the environment variable `CHARACTERIZE=1` is set it writes the entry instead and the test then fails with "golden written, review and commit".
  - `ScriptedDashboard`: a `unittest.TestCase` mixin copying `DashboardTests.setUp`, `task()`, `event()` and `approval()` from `tests/test_dashboard_backend.py` (import `FakeClient` from there, do not copy it).
- Consumes: `Dashboard`, `FakeClient`, `Dashboard.snapshot()`, `Dashboard.on_message()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_characterization_runs.py`:
  - `test_start_to_completed_projection`: start a task, then `turn/started`, `turn/plan/updated` (two steps), `thread/tokenUsage/updated`, `turn/completed` with status `completed`; after each event assert `check_golden(self, "completed.<event>", normalize(self.app.snapshot()))`.
  - `test_failed_turn_projection` (status `failed` with an error), `test_interrupted_turn_projection` (via `app.interrupt` then `turn/completed` `interrupted`), `test_unknown_terminal_status_projection` (status `weird`).
  - `test_stale_turn_event_is_ignored`: an event with a different `turnId` leaves the projection equal to the previous golden.
- [ ] **Step 2: Run them; expected FAIL** (helpers and goldens missing).
- [ ] **Step 3: Implement the helpers**, then generate goldens once with `CHARACTERIZE=1` on the unmodified baseline commit.
- [ ] **Step 4: Run without the flag; expected PASS.** Inspect `runs.json` by eye for volatile or sensitive data; none allowed.
- [ ] **Step 5: Mutation check** on a scratch copy: (a) change the `turn/completed` status mapping in `dashboard/server.py` so `failed` maps to `completed`; (b) drop the `turn/plan/updated` branch; (c) ignore the stale-turn guard. Each must fail at least one test here. Record the three results in the baseline evidence file.
- [ ] **Step 6: Commit** ("test: characterize the Codex run lifecycle projection").

### Task 3: Approval goldens

**Files:**
- Create: `tests/test_characterization_approvals.py`, `tests/fixtures/characterization/approvals.json`

**Interfaces:**
- Consumes: Task 2's helpers; `Dashboard.respond_approval(approval_id, data)`, `Dashboard.snapshot()`, `FakeClient.responses`, `FakeClient.rejections`.

- [ ] **Step 1: Write the failing tests**:
  - `test_command_approval_pending_then_accepted`: golden after the request, golden after `respond_approval(..., {"decision": ...})` for accept; assert `fake.responses` equals the recorded reply list.
  - `test_command_approval_declined`, `test_file_change_approval_pending_then_resolved_by_server_request_resolved`.
  - `test_pending_approval_finished_when_turn_completes` (stale outcome distinct from declined).
  - `test_approval_for_unknown_thread_is_rejected` (assert `fake.rejections`).
  - `test_snapshot_never_contains_command_text`: the synthetic command and reason strings must not appear anywhere in `json.dumps(snapshot)`.
- [ ] **Step 2 to 4:** run to FAIL, generate goldens with `CHARACTERIZE=1`, run to PASS (same procedure as Task 2).
- [ ] **Step 5: Mutation check**: (a) make `respond_approval` reply `decline` for accept; (b) stop clearing pending approvals on `turn/completed`; (c) remove the unknown-thread rejection. Each must fail a test here. Record results.
- [ ] **Step 6: Commit** ("test: characterize Codex approval flows").

### Task 4: Conversation and question goldens

**Files:**
- Create: `tests/test_characterization_conversation.py`, `tests/fixtures/characterization/conversation.json`

**Interfaces:**
- Consumes: Task 2's helpers; the `item/completed`, `item/tool/requestUserInput` message shapes already used in `tests/test_conversation.py` (read it first and reuse its message builders by import).

- [ ] **Step 1: Write the failing tests**: `test_agent_message_item_projection`, `test_requestuserinput_question_pending_then_answered`, `test_question_expires_on_turn_completed`, `test_unsupported_tool_call_is_rejected`. Each compares a normalized snapshot (and the conversation view the existing tests read) to a golden.
- [ ] **Step 2 to 4:** FAIL, generate, PASS as in Task 2.
- [ ] **Step 5: Mutation check**: (a) mark a question answered when it expires; (b) accept `item/tool/call` instead of rejecting; (c) drop the scanner on stored conversation text. Each must fail here or in the existing suite; record which.
- [ ] **Step 6: Run the full clean-environment Python suite and Node suite; expected same counts as Task 1 plus the new tests, 0 failures.** Update the baseline evidence file with the new counts. Commit ("test: characterize Codex conversation and question flows").

### Task 5: Spike S6 harness (no live run yet)

**Files:**
- Create outside the repo, under the scratchpad folder `s6/`: `stub_receiver.py`, `run.sh`, a scratch project folder `s6/project/` with a plain `README.md` and a `CLAUDE.md` containing one distinctive harmless sentence.

**Interfaces:**
- `stub_receiver.py`: loopback HTTP server on a port printed to stdout; logs each request's tool name, input and timing (no headers, no tokens) to `s6/receiver.log`; its answer mode is chosen by a file `s6/mode` containing `allow`, `deny`, `silent` (never answers) or is stopped to simulate unreachable.
- `run.sh <mode> <prompt-file>`: writes `s6/settings.json` containing one `PermissionRequest` hook pointing at the stub (the hook type S2 proved is `http`; the spec text says command; S6 records which works), then runs `claude -p --output-format stream-json --verbose --setting-sources user --settings s6/settings.json --model haiku --agents '<json for one read-only role>' < /dev/null` from `s6/project/`, saving the stream to `s6/out/<run>.jsonl`.

- [ ] **Step 1: Read** `docs/superpowers/spikes/S2-approvals.md` and `S3-event-stream.md` and reuse their working hook configuration and stream parsing; do not rediscover them.
- [ ] **Step 2: Write the scripts; dry-run the stub only** (no `claude`): start it, `curl` it in each mode, confirm the log has no header or token content.
- [ ] **Step 3: Write the run list** (R1 to R7, below) with the exact prompt for each and the estimated list-price cost (each run is a few turns on `haiku`), to present to the owner in Task 6.

### Task 6: Spike S6 live runs (needs owner approval)

**Files:**
- Create: `docs/superpowers/spikes/S6-managed-hook.md`

**Interfaces:**
- Consumes: Task 5's scripts.
- Produces: per-run evidence and a verdict table the Task 8 gate reads.

- [ ] **Step 1: Present the run list and estimated cost to the owner; wait for an explicit yes.** Runs:
  - R1 hook supplied by `--settings` loads under `--setting-sources user` and fires for a command that needs permission (a `Bash` command with `>>` redirect into a scratch file); stub `deny`: command did not run, run finished, denial recorded.
  - R2 stub `allow`: command ran once; a second identical request in the same run prompts again (allow is one call).
  - R3 stub `silent`: what the run does (denies, hangs, or times out) and after how long; nothing auto-allowed.
  - R4 stub stopped (connection refused): outcome, nothing auto-allowed.
  - R5 `--agents` role is available (name appears in the `init` event) and the project `CLAUDE.md` sentence is visible to the model under `--setting-sources user`.
  - R6 `--resume <session id>` continues the earlier conversation (follow-up turn sees prior context).
  - R7 interrupt: send SIGINT to the `claude` process mid-run; record exit code, final events, and that no child process remains.
- [ ] **Step 2: Run R1 to R7, one at a time.** After each, record the exact command (without secrets), `claude --version`, the observed outcome, and the stream lines that prove it. Stop and report on any surprise.
- [ ] **Step 3: Write `S6-managed-hook.md`**: a verdict table (PASS, FAIL, NOT TESTED with the reason) per run, what each run does not prove, and the hook type that worked.
- [ ] **Step 4: Security-check, commit** ("docs: record spike S6").

### Task 7: Spike S7 interactive hooks (owner at the keyboard)

**Files:**
- Create: `docs/superpowers/spikes/S7-observed-hooks.md`

**Interfaces:**
- Consumes: Task 5's stub receiver, extended with a mode that logs `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop` and `PermissionRequest` payload field names only (never values).
- Produces: evidence for section 4.3 of the spec.

- [ ] **Step 1: Write the exact hook configuration as a project-level `s6/project/.claude/settings.json`** in the scratch project, so the owner's own Claude settings are never edited. Give the owner the exact commands to start the stub and `claude` in the app's Terminal tabs.
- [ ] **Step 2: With the owner, run**: (a) a manual-mode session that triggers a permission prompt, stub `allow` and `deny`; (b) the stub silent until the hook times out; (c) answering in the terminal while the stub is also pending, and the reverse; (d) a subagent launch (event fields); (e) an Auto-mode session, noting which calls reach the stub. The owner reports what they saw; record it as owner-reported.
- [ ] **Step 3: Write `S7-observed-hooks.md`** with the same verdict-table format and an explicit "owner-reported" label where applicable.
- [ ] **Step 4: Security-check, commit** ("docs: record spike S7").

### Task 8: Findings and go/no-go gate

**Files:**
- Create: `docs/superpowers/spikes/2026-10-27-phase-2-spikes-findings.md`
- Modify: `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (status line; amendments only if a spike contradicts it), `docs/task-board.md`

**Interfaces:**
- Produces: a recommendation the owner decides on, and the facts Plan 2 is written from.

- [ ] **Step 1: Write the findings report**: per-claim verdicts from S6 and S7, what changes in the spec (a list; make the edits only after the owner agrees), the recommendation (proceed with `claude -p` and hook, or return to the Agent SDK, or stop), and the open items still untested.
- [ ] **Step 2: If S6 failed on R1, R2 or R4, state it first** and do not recommend proceeding; the owner decides.
- [ ] **Step 3: Update the task board** (Plan 1 status, spike results in one line each) and the spec status line.
- [ ] **Step 4: Run both suites in the clean environment; expected the Task 4 counts.** Commit ("docs: Phase 2 spike findings"). Ask the owner for the go/no-go; do not start Plan 2 without it.

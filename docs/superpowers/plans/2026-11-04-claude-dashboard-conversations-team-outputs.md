# Claude Dashboard Plan 5: Conversations, Team View, Outputs, Deletion and Delivery Readiness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a Claude deployment, every feature of slice 2b works for dashboard-started Claude runs: the conversation view, the team view, completed-task outputs, task deletion and delivery readiness (every gate except Ponytail, which reads "not applicable for Claude" and never counts as passed). Codex behaviour does not change.

**Architecture:** The features already read provider-neutral task records, so the work is to feed them from Claude's stream events (messages, subagent lineage, a model summary) and to replace the three places that are Codex-shaped for Claude: the delivery policy source, the delivery connection-generation check and the refusal of delivery operations in `_start_task`. Each task starts with a characterization test of what a Claude task does today, so work the code already does is recorded and not rewritten.

**Tech Stack:** Python 3.12+ standard library, the existing `unittest` and `node --test` suites, the fake `claude` executable (`tests/fake_claude.py`) and its sanitized fixtures (`tests/fixtures/claude/`), one optional live run.

**Spec:** `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (sections 1, 2 P1 and P3, 4.4 slice 2b, 4.5, 6, 7, 8 item 5). Parent design: `docs/superpowers/specs/2026-10-26-claude-code-adaptation-design.md`. Code facts below come from a read-only survey of `main` at 17d764a (2026-11-04); each task re-verifies the ones it depends on in its Step 1.

**Prerequisite:** Plans 1 to 4 are merged to `main`. Work on a branch cut from `main` (PR 8, the dashboard key, merges first or is rebased onto; the two touch different files except tests that use `tests/dashboard_key_harness.py`).

**Plan after this one (not written):** Plan 6 = Phase 3 (observed sessions; reuses the hook receiver with a second token class).

## Owner questions (answer or confirm before execution; defaults are proposals, not decisions)

1. **Subagent lineage (Task 3).** The stream parser drops every line with `parent_tool_use_id` or `agent_id` (`translate_stream_line`, `claude_stream.py:221`). Showing delegated rows in the team view and the delegation tree needs those lines. Default: parse them into child rows, from the sanitized fixtures only. Whether a subagent's hook request carries the parent's `session_id` is still unverified live (carry-list M1); this plan does not depend on it. Alternative: leave subagent activity out of the team view in this release.
2. **Outputs registration (Task 5).** Codex registers outputs through a model-called dynamic tool (`OUTPUT_TOOL`); Claude has no equivalent in `claude -p`. Default: Claude outputs are attached by the owner only (the existing human path, `source: "human"`). Alternative: give the model a way to name its output file, which is new design work and not in the spec.
3. **Rewards (Task 4).** `issue_award` needs a live native tool request from the Chief of Staff. Default: rewards stay Codex-only and the Claude team view shows no coins or Agent of the Week, labelled "not available for this provider". Alternative: design a Claude route.
4. **Ponytail for Claude (Task 7).** Spec section 1 assumes the gate "reads not applicable for Claude and never counts as passed". Default: delivery for a Claude run can reach `ready` when every other gate passes, with the Ponytail row shown as "Not applicable for Claude" and excluded from the pass count. Alternative: a Claude run is never `ready` while any gate is not applicable. The owner confirms this one.
5. **Live acceptance (Task 8).** Optional: one live `haiku` run to check the conversation view and an output on the real CLI. Needs the owner's separate approval (alias, count, list-price estimate) before it runs; without it Plan 5 completes as fake-binary and browser evidence only, and the docs say so.

## Global Constraints

- Codex behaviour must not change: `git diff --stat main..HEAD -- tests/fixtures/characterization/` stays empty and Codex tests are not edited to pass.
- After every task, in a clean environment: `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests` and `node --test tests/*.js` pass. The two `tests/test_git_service.py` failures from the owner's global git ignore are environmental and recorded; no test is removed or skipped to get green.
- Fail closed: a Claude record that is missing a field a feature needs makes the feature refuse, never guess. Unknown stays unknown.
- Secrets: none in tracked files, fixtures, logs or commit messages. All fixtures are synthetic. Message and output text passes `safe_text` / `scan_preview` as it does today.
- Evidence kinds stay labelled: fake-binary, live, browser and owner-reported are separate; a fake never establishes live behaviour.
- Lock discipline from Plan 3 holds: `run.stop()` and `run.close()` never under `self.lock`.
- Nothing is pushed, merged or published without the owner. Commit identity `K55Toms <K55Toms@users.noreply.github.com>`, every message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; run `python3 scripts/security_check.py staged` before each commit and `history` before a push.
- Documentation impact is recorded per task; `technical_writer` reviews Task 8, and `user_documentation_writer` reviews the user-facing text changes. Agent evaluation checkpoints: start (Task 1 Step 6) and completion (Task 8).

## Review Focus

Each line is pinned by a test in the task named in brackets.

1. A Claude task's conversation shows the owner's messages and the run's replies in order, and never a message from another task or another turn. [Task 2]
2. A follow-up after a completed Claude turn keeps earlier messages, and an output attached to the first turn is not shown as the latest turn's output (`output_metadata` filters by `turn_id`). [Task 2, Task 5]
3. A Claude subagent line with a malformed `agent_id`, a missing parent or an unknown role makes no child row and no crash; the row count is capped. [Task 3]
4. The team view never shows a Codex-only reward or recovery control in a Claude deployment, and a task from another provider is not listed. [Task 4]
5. An output path that escapes the project, is a secret-shaped file or is a symlink out is refused for a Claude task exactly as for a Codex task. [Task 5]
6. Deleting a Claude task with a held approval, a live process or a pending follow-up is refused or releases everything it held (hook request denied, project hold dropped, session registration removed). [Task 6]
7. Delivery readiness for Claude never reads Ponytail as passed, never reaches `ready` with a failing or missing gate, and a policy or code-snapshot change after review invalidates the review. [Task 7]
8. A delivery review or checks run for a Claude subject starts as a Claude run in the same project with the right role (`qa_engineer`, `code_quality_reviewer`) and is refused when the subject is not the latest completed turn. [Task 7]

---

### Task 1: Characterize what a Claude task does today, and close the gaps list

**Files:**
- Create: `tests/test_claude_slice2b_baseline.py`
- Modify: `docs/task-board.md` (Plan 5 line), `docs/model-evaluation.md` (start checkpoint)

**Interfaces:**
- Consumes: `Dashboard`, the Claude test harness used by `tests/test_claude_journey.py` (fake `claude`, `FAKE_CLAUDE_FIXTURE`).
- Produces: a baseline test class `Slice2bBaseline` whose passing tests pin today's behaviour and whose `expectedFailure` tests name each gap below; later tasks remove the marker when they fix the gap. Produces the confirmed gap list that Tasks 2 to 7 use.

- [ ] **Step 1: Write baseline tests, one per area, against a finished fake Claude run**
  - `test_conversation_view_for_claude_task`: `conversation(task_id)` returns the user's message and the send state; record what it returns for assistant text (expected gap: none).
  - `test_team_snapshot_lists_claude_task_as_direct_activity` and `test_team_last_summary_is_none_for_claude`.
  - `test_attach_output_on_completed_claude_task` and `test_output_hidden_after_followup_turn`.
  - `test_delete_completed_claude_task_releases_session_and_hold`.
  - `test_delivery_refused_for_claude_today` (409 `not available for this provider`).
- [ ] **Step 2: Run them; mark each failing gap `@unittest.expectedFailure` with a one-line reason; do not fix anything**
  - Run: `python3 -m unittest tests.test_claude_slice2b_baseline -v`; expected: all pass or are expected failures.
- [ ] **Step 3: Verify the uncertain survey items** by reading code: whether `_append_message` is called for Claude assistant text (`conversation.py:370`), whether `last_summary` is set anywhere for Claude (`grep -n last_summary dashboard/*.py`), whether `app.js` hides outputs/team/delivery for Claude (`grep -n providerOff dashboard/static/app.js`). Write the findings, with file and line, into the Task 1 report; adjust Tasks 2 to 7 in the ledger if a finding changes them.
- [ ] **Step 4: Record the Plan 5 start in `docs/task-board.md`** (branch, owner questions awaiting answer).
- [ ] **Step 5: Run the full suites; commit** `test: pin what a Claude task does for the slice 2b features`.
- [ ] **Step 6: Agent evaluation start checkpoint:** `agent_evaluation_engineer` records `EVAL-<date>-<n>` in `docs/model-evaluation.md`, including the open Plan 3 and Plan 4 findings still unresolved and whether routing was recorded this time. Commit separately.

### Task 2: Conversation view for Claude (replies in the conversation)

**Files:**
- Modify: `dashboard/conversation.py` (`conversation`, `_append_message`, `_claude_followup`), `dashboard/server.py` (`_claude_event_locked`, around line 1250), `dashboard/backends/claude_stream.py` (add a `message` neutral kind if Task 1 shows replies are not yet surfaced; `NEUTRAL_KEYS` and `EVENT_KINDS` in `backends/base.py` change together)
- Test: `tests/test_claude_conversation.py`

**Interfaces:**
- Consumes: Task 1's gap list; `_append_message(task_id, kind, text, turn_id, sender, receivers=(), status='complete', event_id=None)`.
- Produces: for each assistant text block in a Claude stream, one message with `kind="agent"`, `sender=<session id>`, `turn_id=<current turn>`, `event_id` unique per stream line so replay and resume never duplicate it. Task 7 relies on `sender == task.thread_id` and `turn_id` to match a review message.

- [ ] **Step 1: Write failing tests** (fixture `success`, and a two-turn run with a follow-up):
  - `test_assistant_text_appears_once_in_order_with_turn_id`
  - `test_followup_keeps_earlier_messages_and_new_turn_id`
  - `test_message_text_is_scanned_and_bounded` (a secret-shaped synthetic string is refused as in `safe_text`; text over the bound is truncated with a marker, never dropped silently)
  - `test_duplicate_stream_line_makes_one_message`
  - `test_other_task_messages_are_not_returned`
- [ ] **Step 2: Run to see them fail** (`python3 -m unittest tests.test_claude_conversation -v`).
- [ ] **Step 3: Implement** the neutral message event in `claude_stream.translate_stream_line` and the append in `_claude_event_locked`; reuse `safe_text` and the existing message cap. Remove the `expectedFailure` markers from Task 1 that this closes.
- [ ] **Step 4: Run the new tests, then the Claude and Codex conversation suites** (`tests/test_conversation*.py`, `tests/test_claude_*.py`); expected: all pass.
- [ ] **Step 5: Commit** `feat: show Claude replies in the conversation view`.

### Task 3: Subagent lineage and delegated activity (needs owner question 1)

**Files:**
- Modify: `dashboard/backends/claude_stream.py` (`translate_stream_line`, 221), `dashboard/conversation.py` (`_register_thread`, `_child_activity`, `_note_turn`), `dashboard/server.py` (`_claude_event_locked`)
- Test: `tests/test_claude_subagents.py`, fixture additions under `tests/fixtures/claude/` (sanitized, synthetic ids)

**Interfaces:**
- Consumes: `_register_thread(thread_id, task_id, parent=None)`, `observed_tasks` rows with `parent_task_id`, `parent_thread_id`, `role`, `status`.
- Produces: child rows keyed by `agent_id` with `parent_task_id = task id`, `role` from the stream's agent type when it is a registered role else `None`, at most 64 per task.

- [ ] **Step 1: Write failing tests:** `test_subagent_lines_make_one_child_row_with_lineage`, `test_child_row_ends_with_parent_run`, `test_malformed_agent_id_makes_no_row`, `test_child_rows_are_capped_at_64`, `test_unknown_agent_type_has_no_role`, `test_subagent_tool_call_still_denied_with_claude_hook_subagent_session` (Plan 4 behaviour unchanged).
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement.** If the owner answered "leave out", replace this task with a docs-only line saying the team view shows no subagents for Claude and skip Steps 1 to 4.
- [ ] **Step 4: Run Claude and Codex suites.**
- [ ] **Step 5: Commit** `feat: record Claude subagent lineage as delegated activity`.

### Task 4: Team view for Claude

**Files:**
- Modify: `dashboard/team.py` (`snapshot`), `dashboard/server.py` (set a Claude `last_summary`), `dashboard/static/app.js` (`loadTeam`, reward text), `dashboard/static/index.html`
- Test: `tests/test_team.py` additions (new class `ClaudeTeamTests`), `tests/test_claude_ui.js`

**Interfaces:**
- Consumes: `Team.snapshot(tasks)`, `team_tasks()` (`conversation.py:102`), Task 3's child rows, `self.roles` from `.claude/agents`.
- Produces: Claude tasks counted per role with direct and delegated activity; `last_task.last_summary` filled from the run's final result text with `last_summary_source == "model-reported"` (bounded, scanned); the reward area states "not available for this provider".

- [ ] **Step 1: Failing tests:** `test_snapshot_groups_claude_tasks_by_role`, `test_snapshot_ignores_other_provider_tasks`, `test_claude_last_summary_is_model_reported_and_bounded`, `test_no_awards_in_claude_deployment`, and a Node test that the team panel renders the reward notice for Claude.
- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement** the summary capture from the stream's final result and the UI notice (owner question 3 default).
- [ ] **Step 4: Run suites.** Browser check of the team panel on a scratch copy with the Claude provider and the dashboard key URL; label it browser evidence.
- [ ] **Step 5: Commit** `feat: team view for Claude deployments`.

### Task 5: Completed-task outputs for Claude

**Files:**
- Modify: `dashboard/task_outputs.py` (`can_attach_output`, `output_metadata`), `dashboard/static/app.js` (outputs section) as the Task 1 findings require
- Test: `tests/test_task_outputs.py` additions (class `ClaudeOutputTests`)

**Interfaces:**
- Consumes: `attach_task_output(task_id, data)` with `{path, expected_turn_id, confirmed: true}`, `can_attach_output(task)`.
- Produces: owner-attached outputs (`source: "human"`) for a completed Claude task on its latest turn; no native source.

- [ ] **Step 1: Failing tests:** `test_owner_can_attach_output_to_completed_claude_task`, `test_output_refused_after_followup_started`, `test_path_escape_symlink_and_secret_file_refused_for_claude` (Review Focus 5), `test_stale_expected_turn_refused`.
- [ ] **Step 2: Run to fail** (skip the ones Task 1 already showed passing; keep them as regression tests).
- [ ] **Step 3: Implement** only what fails. Update the UI text if outputs are currently labelled Codex-only.
- [ ] **Step 4: Run suites.**
- [ ] **Step 5: Commit** `feat: attach outputs to completed Claude tasks`.

### Task 6: Task deletion edge cases for Claude

**Files:**
- Modify: `dashboard/task_deletion.py` and `dashboard/server.py` (`delete_task`, `task_deletion_state`) only if a test fails
- Test: `tests/test_task_deletion.py` additions (class `ClaudeDeletionTests`)

**Interfaces:**
- Consumes: `task_deletion_state(task)`, `delete_task(task_id, data)`, DELETABLE statuses.
- Produces: confirmed behaviour for Claude tasks with a held hook request, a launching worker, a possibly-running old process and a registered session.

- [ ] **Step 1: Failing tests:** `test_delete_with_held_approval_denies_it_and_releases_everything`, `test_delete_refused_while_run_live_or_launching`, `test_delete_possibly_running_task_drops_hold_only_after_confirmation` (carry-list item (e): record the decision the test pins), `test_delete_removes_messages_child_rows_and_session_registration`, `test_deleted_task_session_cannot_be_followed_up`.
- [ ] **Step 2: Run; fix only failures** (Plan 3 and 4 code may already satisfy most).
- [ ] **Step 3: Run suites.**
- [ ] **Step 4: Commit** `test: pin Claude task deletion edge cases` (plus `fix:` commits for any defect found).

### Task 7: Delivery readiness without the Ponytail gate

**Files:**
- Modify: `dashboard/ponytail_policy.py` (a `NotApplicablePolicy` with the same `load()` shape), `dashboard/server.py` (`__init__` policy source per provider, `_start_task` refusal at 663, `_start_claude_task` policy stamp), `dashboard/delivery.py` (`_delivery_policy_digest`, `_delivery_operation_current` generation check, the review-message match around line 606, gate rows), `dashboard/static/app.js`, `dashboard/static/index.html`
- Test: `tests/test_claude_delivery.py`; keep `tests/test_provider_routes.py` Codex refusals passing unedited

**Interfaces:**
- Consumes: Task 2's messages (`sender`, `turn_id`), `delivery_available(task)`, `_delivery_evaluate`, `_start_task(data, delivery_operation=None)`, `_start_claude_task(project, role, title, instruction)`.
- Produces: `NotApplicablePolicy.load()` returning a bundle with `metadata == {"provider": "claude", "ponytail": "not_applicable"}`; delivery gate status for Ponytail `not_applicable`, never counted as passed; Claude delivery checks (`qa_engineer`) and review (`code_quality_reviewer`) runs started through the Claude launch path.

- [ ] **Step 1: Read `_delivery_evaluate` and the review path (`delivery.py:320-682`) in full** and write the exact gate list and the places that touch `self.client` or `_recovery_connection_generation` into the Task 7 report; adjust the steps below to match. Do not start Step 2 until the report names every Codex-only call in the delivery path.
- [ ] **Step 2: Failing tests:**
  - `test_not_applicable_policy_never_counts_as_passed`
  - `test_claude_task_ready_when_all_other_gates_pass` (or never ready, per owner question 4)
  - `test_claude_checks_run_starts_qa_engineer_run_in_project`
  - `test_claude_review_run_starts_code_quality_reviewer_and_matches_message_sender_and_turn`
  - `test_code_snapshot_change_after_review_invalidates_it`
  - `test_delivery_refused_when_subject_is_not_latest_completed_turn`
  - `test_codex_deployment_still_refuses_not_applicable_and_uses_ponytail` (Codex unchanged)
- [ ] **Step 3: Run to fail.**
- [ ] **Step 4: Implement** the per-provider policy source, the delivery start path for Claude and the connection-generation substitute for Claude (a constant tied to the Claude backend's readiness), and the UI wording "Not applicable for Claude".
- [ ] **Step 5: Run suites, then `python3 scripts/sync_roles.py --check`.**
- [ ] **Step 6: Commit** `feat: delivery readiness for Claude runs without the Ponytail gate`.

### Task 8: UI, documentation, journey check, evaluation and closeout

**Files:**
- Modify: `docs/dashboard-operations.md` (remove "Not available for Claude runs" for the five features), `docs/dashboard-api.md` (delivery refusal, deletion, outputs), `docs/product-brief.md`, `docs/task-board.md`, `docs/decisions.md`, `README.md` and `docs/team.md` Ponytail note, `docs/model-evaluation.md`
- Create: `docs/superpowers/evidence/2026-11-04-slice-2b.md`
- Test: `tests/test_claude_docs.py` (extend), `tests/test_claude_slice2b_journey.py`

- [ ] **Step 1: Journey test (fake binary):** start a Claude run, follow up, see replies in the conversation, attach an output, run delivery checks and review, read readiness, delete the task; assert each step's observable result and that Ponytail reads "not applicable".
- [ ] **Step 2: Browser check** on a scratch copy with the Claude provider: team panel, conversation, outputs, delivery panel, delete dialog; label as browser evidence; record what was not exercised.
- [ ] **Step 3: Optional live run** only with the owner's recorded approval (owner question 5); record `claude --version`; otherwise record "not run".
- [ ] **Step 4: Documentation closeout:** `technical_writer` and `user_documentation_writer` review; update the docs listed above; `python3 -m unittest tests.test_claude_docs`.
- [ ] **Step 5: Agent evaluation completion checkpoint:** record in `docs/model-evaluation.md` with findings routed to named owners.
- [ ] **Step 6: Security and whole-branch review:** `security_reviewer` (read-only) on the diff for message and output text handling and the delivery start path; `code_quality_reviewer` on the branch; findings fixed and re-reviewed.
- [ ] **Step 7: Full suites in a clean environment, `security_check.py staged` and `history`; commit.** Do not push or open a PR without the owner.

## Self-review notes

- Spec coverage: slice 2b lists conversations (Tasks 2, 3), team view (Task 4), outputs (Task 5), task deletion (Task 6), delivery readiness without Ponytail (Task 7); git and file review need no change (spec 4.4). Amendment P1 and P3 are covered by Tasks 6 and 7.
- Known unknowns, each owned by a Step 1 verification: whether Claude replies already reach `self.messages`; whether `app.js` hides the five features; the exact Codex-only calls in the delivery path.
- Not in scope: recovery and assessment (Codex only), Automatic approval changes, Phase 3.

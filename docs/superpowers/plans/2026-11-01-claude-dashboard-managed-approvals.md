# Claude Dashboard Plan 4: Managed-run Hook Receiver and Approvals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dashboard-started Claude run that needs permission shows an approval request in the dashboard; the owner reviews it and approves once (or declines); the same run then continues or is refused that one call. Nothing is ever allowed by a timeout, a crash, an unreachable dashboard or a stale answer.

**Architecture:** Each managed run gets a per-run settings file (private state folder, passed with `--settings`) holding one `PermissionRequest` `http` hook that points at a small loopback receiver owned by the dashboard. The receiver validates the request, hands it to the dashboard as a pending approval of a new kind `tool_call`, and holds the hook connection open until the owner answers, the run ends, the connection drops or the wait expires; every path except an explicit one-call accept replies deny. The existing review, secret-scan and receipt pipeline is reused; the Claude backend's `answer_approval` resolves the held request.

**Tech Stack:** Python 3.15 standard library (`http.server`, `threading`, `secrets`), the existing `unittest` and `node --test` suites, the `claude` CLI (Task 1 and Task 9 only, live).

**Spec:** `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (sections 4.2, 4.3 first bullet, 5, 7, 8). Evidence this plan relies on: `docs/superpowers/spikes/` (S2, S6, S7, S9), `docs/superpowers/evidence/2026-10-28-managed-run-loop.md`. Code map (git-ignored scratch, written by the controller before Task 2): `.superpowers/sdd/plan4-map.md`.

**Prerequisite:** Plan 3 (PR 6) is the base. Work on a branch cut from `managed-run-loop`; if PR 6 has merged by then, cut from `provider-seam`'s successor.

**Plans after this one (not written):** Plan 5 = slice 2b (conversations, team view, outputs, deletion, delivery readiness without the Ponytail gate). Plan 6 = Phase 3 (observed sessions; reuses the receiver with a second token class and "may already be answered elsewhere" states).

## Decisions made for this plan (proposed defaults; the owner confirms or changes them at plan review)

1. **A separate receiver**, not a route on the dashboard's own port: a `ThreadingHTTPServer` on `127.0.0.1` with an ephemeral port, started when the Claude provider is active, serving only `POST /hook/managed/<run token>`. The dashboard's API, UI and Host/Origin rules are untouched.
2. **Per-run token in the URL path**, 32 random bytes (`secrets.token_urlsafe(32)`), compared in constant time, valid only while the run is live. S6 proved the `http` hook with a plain URL; a `headers` plus `allowedEnvVars` form is adopted only if Task 1 proves it, because then the token would not sit in the settings file. **S10 result (2026-11-01, `docs/superpowers/spikes/S10-managed-approvals.md`):** R10b proved the header form works (the header arrived with the expected value, and a 401 reply was a deny), but it puts the token in the `claude` process environment, which tool subprocesses inherit by default (not tested whether Claude Code strips it). S10 therefore recommends keeping the token in the URL path, with the settings file at 0600 in a 0700 folder (decision 3); a `Read` outside the project reaches the hook (R10f). The owner or controller confirms this choice. Whichever placement is used, any non-2xx, malformed or closed reply is a deny (R10b, R10c, R10d, R10h).
3. **The settings file** lives in the dashboard's private state folder (not the project), mode 0600 in a 0700 folder, is written before spawn, deleted when the run ends and swept at start-up. It holds exactly one hook and nothing else.
4. **Waits are configurable (owner request 2026-11-01).** A dashboard setting `claude_approval_wait_seconds` (integer, default 900, allowed range 60 to 3600) sets how long the dashboard holds a request. The hook `timeout` written into a run's settings file is that value plus 60 s, fixed when the run launches, because Claude Code reads the file once. A change applies to runs launched afterwards; a running run keeps its own hook timeout, and its effective wait is the smaller of the current setting and its launch-time value. The setting lives in the existing dashboard settings (Settings page, same strict validation as the other keys); an out-of-range or non-integer value is refused, never clamped silently. **S10 evidence and ruling (controller, 2026-11-01):** the longest hold shown to work live is an answer at 75 s under a hook `timeout` of 120 s (R10a, one run); no ceiling is documented (schema: positive number, no maximum) but nothing above 120 s was run. S10 narrowed the defaults to 60 s; that would make approvals unusable for a human, so the numbers above stand and are marked **unverified above 120 s** in the docs and the Settings help text. This fails closed: if Claude Code ends the hook earlier than the dashboard's wait, the connection closes, the approval becomes unavailable (Review Focus 1) and Claude denies the call. One further live run (R10i, hook `timeout` 960, answer after 300 s) needs the owner's separate approval and is part of Task 9; if it fails, the default and upper bound drop to the proven value.
5. **Replies are exactly two shapes:** allow is `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}` (S2, S6; no `updatedInput`, no `updatedPermissions`); deny is the same with `"behavior":"deny"` and a fixed `message` ("Declined in the dashboard."). The owner's words, the request text and error detail never go into a reply. No `interrupt`.
6. **New approval kind `tool_call`** with decisions `accept` and `decline` only. Its reviewed context is `{tool_name, tool_input, agent_type?}` (bounded, secret-scanned like the Codex kinds). Accept means this one request; two identical requests are two approvals.
7. **Caps:** 16 pending requests per run, 64 across the dashboard, 256 KiB request body. Over any cap the receiver answers deny at once (nothing is queued).
8. **A request whose `permission_mode` is not `default`, whose `session_id` contradicts the run's known session, or whose token is unknown or finished is denied** and recorded by code only; the first of these for a live run also stops the run and marks it `failed` (`claude_permission_mode`).
9. **Automatic approval is an option for Claude runs (owner request 2026-11-01, replacing the 2026-10-27 manual-only decision for approvals).** The existing per-project approval mode (`manual` default, `automatic`, same confirmation checkbox as today) applies to Claude `tool_call` approvals. Automatic works exactly as for Codex: only after the dashboard has built and checked the complete context, only for non-sensitive requests, only for the tools `Bash`, `Write`, `Edit` and `NotebookEdit` (the Codex equivalents are command and file change); every other tool (web, MCP, agent launch, unknown names) stays manual. Each automatic accept is one call, recorded as `project_policy`, and shown in the UI as such. A project in `manual` mode behaves as in decision 6. This is not Claude's own Auto mode: a run whose `permission_mode` is anything but `default` is still stopped (decision 8), because Auto mode bypasses the hook entirely (S7 e).
10. **Live acceptance is part of this plan** (Task 9), within the owner's approval recorded in the ledger. If the owner declines it, Plan 4 completes as fake-binary only and the docs say so.

## Global Constraints

- Codex behaviour must not change: `git diff --stat b547e0b..HEAD -- tests/fixtures/characterization/` stays empty; Codex approval tests keep passing unedited.
- After every task, in a clean environment: `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests` (baseline at the start of this plan: 1100 OK, skipped=36) and `node --test tests/*.js` (151 pass). No test removed or skipped to get green.
- Fail closed everywhere (spec section 7): unknown means deny; no timeout, crash, disconnect, bad token or malformed reply path may allow a call.
- Secrets: none in tracked files, fixtures, logs or commit messages. Fixtures are synthetic. The token never appears in a log line, the snapshot, the store, a diagnostic or a test failure message; tool input never appears outside the reviewed approval context.
- Hook payloads are untrusted input: size-bounded, strictly parsed, field-allow-listed, validated and secret-scanned before display.
- Live Claude runs only in Task 1 and Task 9, each within the owner's recorded approval (alias, count, list-price estimate); `claude --version` recorded with each.
- Nothing is pushed, merged or published without the owner. Commit identity `K55Toms <K55Toms@users.noreply.github.com>`, every message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; run `python3 scripts/security_check.py staged` before each commit.
- Evidence kinds stay labelled: fake-binary, live and browser evidence are separate; a fake never establishes live behaviour.
- Lock discipline from Plan 3 holds: `run.stop()` and `run.close()` never under `self.lock`; the receiver thread never takes `self.lock` while blocked.

## Review Focus

Each line is pinned by a test in the task named in brackets.

1. The owner clicks accept after the hook connection has closed (hook timeout, run killed): the answer is refused as unavailable, the UI shows it expired, and nothing is sent or queued. [Task 3, Task 5]
2. Two near-simultaneous requests from parallel subagents become two approvals; accepting one never allows the other. [Task 5]
3. A `tool_input` containing a secret-shaped string reaches the owner only through the sensitive-review path, and appears in no log, snapshot, store row or diagnostic. [Task 5]
4. A token from run A cannot answer for run B; a finished run's token fails; wrong method, content type, oversize body, bad JSON and unknown fields are refused without reaching the dashboard. [Task 3]
5. Stop, restart or close with a request pending: the held connection is released with deny (or dropped), the approval becomes unavailable, no process is left, and the task ends `interrupted` or `unknown` as Plan 3 defines. [Task 6]
6. Automatic mode on a project: a plain `Bash`/`Write`/`Edit` request is accepted once without the owner; a secret-shaped input, an MCP or web tool, an unknown tool and any request in a `manual` project still wait for the owner; changing the mode mid-run affects only requests that arrive afterwards. [Task 5]
7. A wait setting changed while a run is live never lengthens that run's wait beyond its hook timeout, and a value outside 60 to 3600 is refused. [Task 4, Task 7]

---

### Task 1: Spike S10, hook behaviour that Plan 4 depends on (live), and evaluation checkpoint

**Files:**
- Create: `docs/superpowers/spikes/S10-managed-approvals.md`
- Modify: `docs/model-evaluation.md` (checkpoint entry)
- Scratch outside the repository (`<scratchpad>/s10`): a stub receiver that can answer late, answer with a non-2xx, send malformed JSON, and require a header token.

**Interfaces:**
- Produces: verdicts Tasks 2 to 6 build on: the longest wait that worked, whether `headers`/`allowedEnvVars` carry a token, how Claude treats a non-2xx or malformed reply, whether allow of one call leaves a differently worded call prompting, which tools and a subagent reach the hook, what SIGINT does while a hook is waiting, and whether two concurrent requests are both delivered.

- [ ] **Step 1: Ask the owner for approval** of the run list below (alias `haiku`, at most 8 runs, list-price estimate from S6/S9, about 0.01 USD in total) and record it in the ledger before any live run.
- [ ] **Step 2: Run, one run per condition, stdin `/dev/null`, `--setting-sources user`, scratch project, default permission mode:** R10a hook `timeout` 120, stub answers allow after 75 s (does the call run, does the run wait that long; also state whether any ceiling on `timeout` is documented, since the wait setting allows up to 3600 s and its upper bound must not exceed what is shown to work); R10b `headers` with an `allowedEnvVars` token (the stub rejects a missing or wrong header: is the header sent, and is a rejected request a deny); R10c stub replies 500 once, R10d stub replies 200 with malformed JSON (both: deny or hang?); R10e allow of `echo a >> f` then a differently worded call `printf b >> f`; R10f a `Write` and a `Read` outside the project reach the hook; R10g two Bash calls requested in one turn (concurrent delivery) and a subagent call (`agent_type` present); R10h SIGINT sent while the hook is waiting (exit time, `result`, descendants, does the stub see the connection close).
- [ ] **Step 3: Write the note** in the format of `docs/superpowers/spikes/S6-managed-hook.md`: header with the approval record, verdict table, commands, what each run does not prove, and a one-line recommendation for Tasks 2 to 6 (token placement, wait and timeout numbers).
- [ ] **Step 4: Update decisions 2 and 4 of this plan** (and the spec's 4.2 text if a spike result contradicts it) in the same commit as the note, saying which result changed which number.
- [ ] **Step 5: Evaluation checkpoint.** Invoke `agent_evaluation_engineer` for routing and handoff quality across Plan 3 (using `docs/model-evaluation.md` EVAL-2026-11-01-01 as input) and record a sanitized entry; route its findings to named owners on the task board.
- [ ] **Step 6: Commit** `docs: S10 managed approvals spike` after `python3 scripts/security_check.py staged`.

### Task 2: Hook protocol module (pure)

**Files:**
- Create: `dashboard/backends/claude_hook.py`, `tests/test_claude_hook.py`, `tests/fixtures/claude/hook_*.json` (synthetic payloads and sentinel strings)

**Interfaces:**
- Produces: `parse_request(body: bytes) -> HookRequest` (frozen dataclass: `session_id`, `permission_mode`, `tool_name`, `tool_input` (bounded deep copy), `agent_id`, `agent_type`, `prompt_id`, all optional fields typed or `None`); `class HookRejected(ValueError)` with a short `code` (`too_large`, `bad_json`, `bad_shape`, `bad_field`); `allow_reply() -> bytes`, `deny_reply() -> bytes` (the two exact shapes of decision 5); constants `MAX_BODY = 262144`, `DEFAULT_WAIT_SECONDS = 900`, `MIN_WAIT_SECONDS = 60`, `MAX_WAIT_SECONDS = 3600`, `HOOK_TIMEOUT_MARGIN = 60`, and `hook_timeout(wait: int) -> int` (wait plus margin, `ValueError` outside the range).

- [ ] **Step 1: Write failing tests** `test_parse_accepts_s7_payload_fields` (every field S7 lists: `cwd, effort, hook_event_name, permission_mode, permission_suggestions, prompt_id, scratchpad_dir, session_id, tool_input, tool_name, transcript_path`, plus `agent_id`, `agent_type`; unknown extra fields are dropped, never kept), `test_parse_rejects` (non-object, wrong `hook_event_name`, missing or non-string `tool_name`/`session_id`, `tool_input` not an object, nesting deeper than the existing review bound, bytes over `MAX_BODY`, invalid UTF-8, duplicate keys), `test_replies_are_exact` (byte-for-byte equality with decision 5, deny message fixed), `test_reply_never_contains_request_text` (sentinel in the request never appears in either reply).
- [ ] **Step 2: Run them to see them fail** (`python3 -m unittest tests.test_claude_hook`; expected: import error).
- [ ] **Step 3: Implement the module.** Reuse the bound and nesting helpers from `dashboard/approval_review.py` rather than copying them.
- [ ] **Step 4: Run the new tests and the full suite**; expected all pass.
- [ ] **Step 5: Commit** `feat: Claude hook request parsing and replies`.

### Task 3: Loopback receiver

**Files:**
- Create: `dashboard/hook_receiver.py`, `tests/test_hook_receiver.py`

**Interfaces:**
- Consumes: Task 2 (`parse_request`, `allow_reply`, `deny_reply`, `HookRejected`).
- Produces: `class HookReceiver(on_request: Callable[[str, HookRequest, HeldRequest], None])` with `start() -> int` (the bound port, 127.0.0.1 only), `stop()`, `register_run(task_id: str) -> str` (returns the run token), `unregister_run(task_id: str)`, and `url_for(token: str) -> str`. `HeldRequest` has `resolve(decision: str)` (`"allow"` or `"deny"`, first call wins, later calls are no-ops), `closed` (True once the client connection is gone), and `wait(seconds) -> str` used by the handler. The handler thread replies allow only if `resolve("allow")` happened first; every other end (timeout, closed connection, `stop()`, `unregister_run`, callback exception, parse failure, caps) replies deny or drops the connection.

- [ ] **Step 1: Write failing tests with real sockets** (`test_unknown_token_denied_without_callback`, `test_finished_run_token_denied`, `test_other_runs_token_cannot_resolve`, `test_wrong_method_content_type_oversize_and_bad_json_refused_before_callback`, `test_host_must_be_the_loopback_authority`, `test_allow_reply_only_after_resolve_allow`, `test_timeout_replies_deny`, `test_client_disconnect_marks_closed_and_frees_thread`, `test_stop_releases_all_held_requests`, `test_unregister_denies_pending_for_that_run`, `test_callback_exception_denies`, `test_caps_deny_immediately` (decision 7), `test_token_never_in_error_bodies_or_logs`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement the receiver.** Constant-time token lookup (`hmac.compare_digest` over the registered tokens); detect a closed client by polling the socket with `MSG_PEEK` once a second while waiting; handler logging off by default and never prints paths containing the token.
- [ ] **Step 4: Run the new tests, then the full suite** (both clean-environment commands).
- [ ] **Step 5: Commit** `feat: managed hook receiver`.

### Task 4: Per-run settings file, launch argv and the fake binary's hook mode

**Files:**
- Modify: `dashboard/settings.py`, `dashboard/backends/claude_launch.py`, `tests/fake_claude.py`, `tests/test_claude_launch.py`, the settings tests (additions only)
- Create: `tests/test_claude_settings_file.py`, `tests/fixtures/claude/permission_request_*.jsonl`

**Interfaces:**
- Consumes: `HookReceiver.url_for`, `HOOK_TIMEOUT_SECONDS`.
- Produces: `write_run_settings(state_dir: Path, url: str, timeout: int) -> Path` (0600 file in a 0700 `claude-runs` folder, deterministic JSON with exactly one `PermissionRequest` hook entry) and `remove_run_settings(path: Path) -> None`; `build_argv(..., settings_path: Optional[Path] = None)` adds `--settings <path>` after `--setting-sources user` and before `--model`, only when given. The fake `claude` reads the `--settings` file, and for scenarios `ask_allowed`, `ask_declined`, `ask_silent`, `ask_two` it POSTs a synthetic `PermissionRequest` payload to the hook URL, obeys the reply (allow: emit the tool result and go on; deny or no reply: emit a `permission_denied` event and finish), and honours SIGINT while waiting.

- [ ] **Step 0: Add the setting.** In `dashboard/settings.py` add `claude_approval_wait_seconds` (default 900) with strict validation (`type(value) is int`, 60 to 3600, otherwise the settings save is refused; existing settings files without the key load with the default). Tests: `test_default_wait_when_key_missing`, `test_out_of_range_bool_float_and_string_refused`, `test_existing_settings_round_trip_unchanged`. `launch` reads the value once per run and passes `hook_timeout(wait)` as the file's `timeout`; the run records its launch-time wait in memory so its effective wait is `min(current, launch)` (Review Focus 7).
- [ ] **Step 1: Write failing tests** (`test_settings_file_has_exactly_one_hook_and_no_other_keys`, `test_hook_timeout_in_file_is_wait_plus_margin_at_launch`, `test_changed_setting_does_not_lengthen_a_live_runs_wait`, `test_modes_0600_0700`, `test_remove_is_idempotent_and_refuses_paths_outside_state_dir`, `test_build_argv_places_settings_and_omits_when_none`, `test_existing_argv_golden_unchanged_without_settings`, `test_fake_claude_posts_and_obeys_allow_and_deny`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `write_run_settings` writes via a temp file in the same folder then renames; the URL is validated as `http://127.0.0.1:<port>/hook/managed/<token>` before writing.
- [ ] **Step 4: Run new tests, then the full suite.**
- [ ] **Step 5: Commit** `feat: per-run hook settings file and fake binary hook mode`.

### Task 5: Pending approvals for Claude runs (create, review, answer)

**Files:**
- Modify: `dashboard/server.py` (start-up wiring of the receiver, `_launch_claude_task` registers the run and writes the settings, new `_claude_hook_request`, `respond_approval` and `review_approval` accept kind `tool_call`), `dashboard/approval_review.py` (`context()` supports `tool_call`), the automatic-approval queue (`tool_call` with the tool allow-list), `dashboard/backends/claude.py` (`answer_approval` resolves the held request), `dashboard/diagnostics.py` if a new code is needed
- Create: `tests/test_claude_approvals.py`

**Interfaces:**
- Consumes: Tasks 2 to 4; the existing `ApprovalReviews`, `_scan_approval`, receipt and sensitive-review flow; `ApprovalRequest(kind, native_method, liveness_key, params, available_decisions, responder)` from `dashboard/backends/base.py`.
- Produces: on a hook request the dashboard creates an approval `{kind: "tool_call", native_method: "PermissionRequest", requester: "<role label> (or <agent_type>) via Claude Code", summary: "A tool call requires approval", available_decisions: ["decline"] until reviewed}`, sets the task to `waiting_approval`, and returns to `running` when the request resolves. `liveness_key = (session_id, turn_id, request_id)`. `answer_approval(request, "accept"|"decline")` calls the held request's `resolve("allow"|"deny")`.

- [ ] **Step 1: Write failing tests** (fake `claude`, real receiver): `test_request_creates_pending_tool_call_approval_and_waiting_status`, `test_review_then_accept_resumes_same_run_and_tool_runs_once` (the fake records that the tool ran once), `test_decline_denies_and_run_continues`, `test_accept_without_review_receipt_refused`, `test_accept_after_context_changed_refused`, `test_two_concurrent_requests_two_approvals_accept_one_denies_other_untouched` (Review Focus 2), `test_accept_after_connection_closed_is_request_unavailable` (Review Focus 1), `test_secret_in_tool_input_needs_sensitive_confirmation_and_is_absent_from_logs_snapshot_store` (Review Focus 3, sentinel scan across the store file, snapshot JSON and captured logs), `test_manual_project_never_auto_accepts_tool_call`, `test_automatic_project_accepts_plain_bash_write_edit_once_as_project_policy`, `test_automatic_project_leaves_sensitive_mcp_web_and_unknown_tools_for_owner`, `test_automatic_mode_change_applies_only_to_later_requests` (Review Focus 6, decision 9; the automatic path reuses `_queue_automatic_approval` and `respond_approval(..., _source='project_policy')`, with `tool_call` added to its eligible kinds and the tool allow-list applied there), `test_codex_kinds_unchanged` (existing Codex approval tests run unedited).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the kind in `approval_review.context()` (whole request, no excerpts, same bound as the other kinds), the dashboard callback and the backend's `answer_approval`. Provider guard: `respond_approval` on a Claude approval under a Codex deployment is already refused by `_require_active_provider_for_approval`; keep that and test it.
- [ ] **Step 4: Run new tests, the Codex approval tests and the full suite.**
- [ ] **Step 5: Commit** `feat: Claude tool-call approvals`.

### Task 6: Lifecycle: stop, exit, restart, expiry, invalid requests

**Files:**
- Modify: `dashboard/server.py` (`_claude_exit`, `_claude_interrupt`, `stop_all_runs`, `close`, restart sweep, `_finish_approvals`), `dashboard/hook_receiver.py` only if a test shows a gap
- Create: `tests/test_claude_approval_lifecycle.py`

**Interfaces:**
- Consumes: Tasks 3 and 5.
- Produces: guaranteed cleanup: every pending `tool_call` of a run becomes `unavailable` and its held request is released with deny on run exit, stop, delete, dashboard close and receiver stop; the run's token is unregistered and its settings file removed in the same places and at start-up (sweep of stale files); a hook request with `permission_mode != default` or a contradicting `session_id` is denied, and the first one for a live run stops it and marks it `failed` with `claude_permission_mode`.

- [ ] **Step 1: Write failing tests** (`test_stop_with_pending_releases_deny_and_marks_unavailable`, `test_run_exit_with_pending_cleans_up`, `test_close_with_pending_leaves_no_process_thread_or_settings_file`, `test_restart_sweep_removes_stale_settings_files_and_tokens_do_not_survive`, `test_expiry_after_approval_wait_denies_and_marks_expired`, `test_non_default_permission_mode_request_denied_and_run_failed`, `test_session_id_mismatch_denied_without_approval`, `test_deleting_task_with_pending_approval`, `test_cap_16_per_run_then_deny`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the cleanup paths. Release held requests outside `self.lock`; reuse Plan 3's ordering (`stop_all_runs` before `disconnected()`).
- [ ] **Step 4: Run new tests and the full suite**, then a manual check that no `fake_claude` process or `claude-runs` file remains after the suite.
- [ ] **Step 5: Commit** `feat: approval lifecycle cleanup for Claude runs`.

### Task 7: UI and diagnostics

**Files:**
- Modify: `dashboard/static/app.js`, `dashboard/server.py` (settings save route), `dashboard/diagnostics.py`, `tests/test_claude_ui.js`, `tests/test_claude_readiness_ui.js` as needed
- Create: `tests/test_claude_approvals_ui.js`

**Interfaces:**
- Consumes: Task 5's approval shape.
- Produces: `tool_call` is a reviewable kind; the card shows the tool name, the complete checked `tool_input` (command, path, text), the requester role or `agent_type`, "This one call only; the run stops waiting after <configured wait>", an Accept and a Decline button, and an "expired" state. The run dialog notice and the denied-calls line stop saying approvals arrive later when the provider is Claude, and say only that calls the owner did not approve were denied. Codex wording is byte-identical.

- [ ] **Step 0: Settings page.** Add a "Claude approval wait" number field (seconds, 60 to 3600, shown only when the provider is Claude) to Settings, extend the strict config validator in `app.js` and the settings save route to carry `claude_approval_wait_seconds`, and show the project Automatic-mode control for Claude with wording that names the covered tools and says every automatic accept is one call. Codex settings text is unchanged. Tests: `wait field hidden for Codex`, `out-of-range value shows an error and sends nothing`, `automatic confirmation required for Claude projects too`, `automatic accepts are labelled project policy`.
- [ ] **Step 1: Write failing tests** (`reviewableKinds includes tool_call`, `card shows complete input and requester`, `expired approval has no buttons`, `Codex strings unchanged`, `no innerHTML from request text`).
- [ ] **Step 2: Run them to see them fail** (`node --test tests/test_claude_approvals_ui.js`).
- [ ] **Step 3: Implement** with `textContent` and the existing helpers; no new markup from request text.
- [ ] **Step 4: Run all Node tests and the full Python suite.**
- [ ] **Step 5: Commit** `feat: dashboard UI for Claude tool-call approvals`.

### Task 8: Journey tests over HTTP (fake binary)

**Files:**
- Create: `tests/test_claude_approval_journey.py`

**Interfaces:**
- Consumes: everything above; patterned on `tests/test_claude_journey.py`.

- [ ] **Step 1: Write the journeys** from the original owner request, through the dashboard's HTTP API and the real receiver: `test_journey_start_ask_review_approve_work_resumes_and_completes` (start run, `/api/state` shows the approval, review, accept, task completes, file written once), `test_journey_decline_run_finishes_with_denial_recorded`, `test_journey_ignore_until_expiry_denied_and_expired_state`, `test_journey_stop_while_waiting`, `test_journey_restart_while_waiting`, `test_journey_codex_deployment_has_no_receiver_and_claude_routes_gated`.
- [ ] **Step 2: Run them; fix only real defects found** (each fix gets its own test in the owning task's file).
- [ ] **Step 3: Run the full suite twice** (clean environment) to catch ordering flakiness.
- [ ] **Step 4: Commit** `test: Claude approval journeys`.

### Task 9: Documentation, live acceptance, closeout

**Files:**
- Modify: `docs/dashboard-operations.md`, `dashboard-api.md`, `product-brief.md`, `claude-code-setup.md`, `decisions.md`, `task-board.md`, `README.md`, `model-evaluation.md`
- Create: `docs/superpowers/evidence/2026-11-01-managed-approvals.md`

**Interfaces:**
- Consumes: the finished branch.

- [ ] **Step 1: Documentation.** `technical_writer` and `user_documentation_writer` closeout: the approve-once journey, the configurable wait (default 15 minutes) and when a change takes effect, what happens on timeout, crash and stop, how Automatic mode applies to Claude runs and which tools it covers, that approving "in Claude" is not possible for a dashboard-started run, the receiver and per-run token model, the settings file location and clean-up, what the owner sees, and the limits (only calls that reach a prompt are sent; `updatedInput` and session grants are not offered).
- [ ] **Step 2: Live acceptance, only within the owner's recorded approval** (alias `haiku`, at most 3 runs through the real dashboard on a scratch project and scratch haiku role, estimated list price recorded first): L1 run asks, owner approves once, work resumes and the file exists once; L2 run asks, owner declines, the model reports the refusal; L3 optional, owner ignores until stop. Evidence recorded as live, with `claude --version`. If the owner declines, write "not run" in the evidence and the task board.
- [ ] **Step 3: Whole-branch review** by a fresh reviewer on the most capable model, then independent writer review, then fix commits.
- [ ] **Step 4: Final checks:** both suites, `python3 scripts/sync_roles.py --check`, `python3 scripts/security_check.py history`, goldens diff empty, no stray processes or `claude-runs` files.
- [ ] **Step 5: Evaluation checkpoint** entry in `docs/model-evaluation.md`; update the task board carry list.
- [ ] **Step 6: Commit** `docs: Plan 4 closeout and evidence`.

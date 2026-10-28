# Claude Dashboard Plan 2: Provider Seam and Project-Instructions Spike

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a provider-neutral backend interface between the dashboard and the Codex client, add a start-up provider setting that fails closed, record the provider on projects and runs, and settle how managed Claude runs get the project's instructions, without changing any Codex behaviour.

**Architecture:** New package `dashboard/backends/` (`base.py` neutral types and `Backend` protocol, `codex.py` a Codex adapter with a pure translator, `__init__.py` a resolver). The adapter wraps the raw `app.client` per call (never owns it), so `Dashboard.client`, `client_factory`, the Codex wire strings and the three characterization goldens stay as they are. Claude is a stub that reports "not implemented" until Plan 3. Only the run lifecycle, guidance, interrupt and approval answering move behind the seam; conversations, team view, outputs, deletion and delivery stay Codex-shaped until slice 2b.

**Tech Stack:** Python 3.15 standard library, SQLite (`records` table, JSON bodies), the existing `unittest` suite and `node --test`, a macOS runner, `claude` CLI (Task 1 only).

**Spec:** `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (sections 4.1, 4.2, 4.4, 5, 8). Code map the tasks rely on: `.superpowers/sdd/plan2-map.md` (git-ignored scratch; implementers re-read the code, not the map). Evidence: `docs/superpowers/spikes/2026-10-27-phase-2-spikes-findings.md`.

**Plans after this one (not written):** Plan 3 = Claude backend core run loop, per-run settings file, managed-run hook receiver and approvals. Plan 4 = slice 2b (conversations, team view, outputs, deletion, delivery readiness without the Ponytail gate). Plan 5 = Phase 3 (observed sessions). Each is written after the previous one is reviewed.

## Global Constraints

- **Codex behaviour must not change.** `git diff --stat -- tests/fixtures/characterization/` must be empty after every task. Existing tests are not edited, except `tests/characterization.py` and the two decorator swaps in Task 2. Every other task adds new test files only.
- After every task, in a clean environment: `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests` (baseline 758 tests, OK, 36 skipped locally) and `node --test tests/*.js` (126 pass). New tests add to the Python count; no test may be removed or skipped to get green.
- No new environment variable for the dashboard (`docs/dashboard-operations.md:44` says there are none). The provider is chosen with a start-up argument only, never from `config.toml` or `/api/state`.
- Fail closed: a missing, empty, differently cased or unknown provider starts no backend and no Codex process; `claude` never requires `codex` on PATH.
- `Dashboard.__init__` keeps its signature and defaults (`client_factory=CodexClient`); the new `backend` keyword defaults to the Codex adapter so about 30 construction sites in tests are unaffected.
- Secrets: none in tracked files, logs, fixtures or commit messages (`AGENTS.md`). Run `python3 scripts/security_check.py staged` before every commit. Nothing is pushed, merged or published without the owner.
- Commit identity `K55Toms <K55Toms@users.noreply.github.com>`; every commit message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Live Claude runs only in Task 1: at most 4 runs, alias `haiku`, subscription login, one run per condition, `claude --version` recorded with each. Owner pre-approval 2026-10-28 (estimate 0.35 to 0.55 USD at list price, not a billed amount).
- Evidence kinds stay labelled (`AGENTS.md`): unit tests, characterization goldens, live runs, owner-reported.

## Review Focus

Each line is pinned by a test in the task named in brackets.

1. No provider argument means no backend: the dashboard serves its page, shows "No provider configured", starts no Codex process and refuses to start runs. [Task 8]
2. Only the exact strings `codex` and `claude` resolve to a backend. `Codex`, `CLAUDE`, an empty string and `codex ` (trailing space) resolve to no backend in code, and the launch script exits with status 2 for them. [Task 8]
3. Existing databases hold projects and runs with no `provider` field; they load as `codex` and the Codex goldens stay identical. [Task 9]
4. A deployment switched from Codex to Claude still contains Codex-recorded runs; actions on a run recorded under another provider answer "recorded under a different provider" and change nothing. [Task 9]
5. A malformed or unknown notification never raises on the Codex reader thread; unknown methods pass through to the existing handlers untouched. [Task 4, Task 6]
6. A stale client's messages are still ignored after the call sites move behind the adapter. [Task 5, Task 6]
7. In a `claude` deployment the Codex-only routes (recovery, assessment, approval alternative) answer "not available for this provider" with status 409 and do nothing. [Task 10]
8. An unrecognised or missing decision still never answers a native request, and "consume before respond" is preserved when answering moves into the adapter. [Task 7]

---

### Task 1: Spike S8, project instructions in managed runs (live)

**Files:**
- Create: `docs/superpowers/spikes/S8-project-instructions.md`
- Scratch (outside the repository, reuse the S6 harness at `<scratchpad>/s6`: `run.sh`, `launch.py`, `summarize.py`, copied to `<scratchpad>/s8`)

**Interfaces:**
- Produces: a verdict on which mechanism makes the project's `CLAUDE.md` and its `@AGENTS.md` import visible to a run that uses `--setting-sources user`; Plan 3 builds the launch argv from it.

- [ ] **Step 1: Build the scratch project** `<scratchpad>/s8/project/` with `CLAUDE.md` ("Instruction one: the codeword is `amber-harbor-1111`.", then a line `@AGENTS.md`), `AGENTS.md` ("Instruction two: the codeword is `cedar-lantern-2222`."), and no `.claude/` folder. Compute the expanded text (CLAUDE.md with the `@AGENTS.md` line replaced by that file's content) into `expanded.txt`.
- [ ] **Step 2: Check the documented switches before spending a run.** Run `claude --help`, grep for `append-system-prompt`, `add-dir`, `system-prompt-file`; if the docs mention an environment variable that loads `CLAUDE.md` from `--add-dir` directories, note its exact name and source. Record what is documented and what is not.
- [ ] **Step 3: Run, in order, stopping when the budget of 4 runs is spent.** Prompt for every run: "List every codeword in your project instructions, quoted exactly; answer NONE if you see none. No tools." Each with `--setting-sources user --model haiku`, stdin `/dev/null`, stream-json, cwd `<scratchpad>/s8/empty` (an empty directory):
  - R8a: `--append-system-prompt "$(cat expanded.txt)"`.
  - R8b: only if Step 2 shows a file form exists: `--append-system-prompt-file expanded.txt`.
  - R8c: `--add-dir <scratchpad>/s8/project` with no other instruction flag.
  - R8d: only if Step 2 found a documented variable: R8c with that variable set.
- [ ] **Step 4: Write the note.** Same format as `docs/superpowers/spikes/S6-managed-hook.md`: header (version, model, flags), verdict table (run, mechanism, both codewords seen? yes/no, `@AGENTS.md` import resolved?), the commands used, what each run does not prove, the argv size of the real repository's `CLAUDE.md` + `AGENTS.md` expanded text against `getconf ARG_MAX`, and the resume caveat from `claude --help` (the system prompt is recorded once per conversation; not run). Recommendation: the single mechanism Plan 3 should use, or "none worked, owner decides".
- [ ] **Step 5: Commit** `docs: S8 project instructions spike` after `python3 scripts/security_check.py staged`.

### Task 2: Make characterization tests fail instead of skip in CI

**Files:**
- Modify: `tests/characterization.py` (add `require_scanner`), `tests/test_characterization_conversation.py:22`, `tests/test_characterization_approvals.py:33` (swap the skip decorator), module docstring of `tests/characterization.py` (record that goldens hold the synthetic policy's `sha256`, `pricing_date` and `source` values, an accepted exception to "synthetic values only")
- Create: `tests/test_characterization_guard.py`

**Interfaces:**
- Produces: `require_scanner() -> Callable[[type], type]`, a class decorator: when the scanner is available it returns the class unchanged; when it is missing and `os.environ.get("CI") == "true"` the decorated tests fail with the message "Gitleaks is required in CI"; when it is missing locally it skips as today.

- [ ] **Step 1: Write failing tests** in `tests/test_characterization_guard.py`: `test_decorator_skips_locally_without_scanner` (patch `scanner_available` to False, `CI` unset: the decorated test raises `unittest.SkipTest`), `test_decorator_fails_in_ci_without_scanner` (`CI=true`: the decorated test raises `AssertionError` containing "required in CI"), `test_decorator_passes_through_with_scanner`.
- [ ] **Step 2: Run them to see them fail** (`python3 -m unittest tests.test_characterization_guard`; expected: attribute error for `require_scanner`).
- [ ] **Step 3: Implement `require_scanner`** and swap the two existing skip sites. The goldens must not change.
- [ ] **Step 4: Run the full suites; expected the baseline counts plus 3 new tests, and an empty fixtures diff.**
- [ ] **Step 5: Commit** `test: fail characterization tests without scanner in CI`.

### Task 3: Neutral types and the `Backend` protocol

**Files:**
- Create: `dashboard/backends/__init__.py` (empty for now), `dashboard/backends/base.py`, `tests/test_backends_base.py`

**Interfaces:**
- Produces, in `dashboard/backends/base.py`:
  - `YES = "yes"`, `NO = "no"`, `UNCONFIRMED = "unconfirmed"`.
  - `@dataclass(frozen=True) class Capabilities` with string fields `provider`, `guidance_while_running`, `subagent_questions`, `plan`, `recovery`, `assessment`, `approval_alternative` (each of `YES`/`NO`/`UNCONFIRMED`, `provider` excepted) and `public(self) -> dict` returning all seven as a plain dict. Construction with a value outside the three raises `ValueError`.
  - `@dataclass(frozen=True) class NeutralEvent`: `kind: str`, `thread_id: Optional[str]`, `turn_id: Optional[str]`, `data: Mapping[str, Any]`. The kinds, as module constant `EVENT_KINDS`: `turn_started`, `turn_completed`, `plan_updated`, `usage_updated`, `run_error`, `model_changed`, `request_resolved`, `unrecognized`.
  - `@dataclass(frozen=True) class ApprovalRequest`: `kind: str`, `native_method: str`, `liveness_key: tuple`, `params: Mapping[str, Any]`, `available_decisions: tuple`, `responder: Any` (opaque to the dashboard).
  - `class Backend(Protocol)`: `capabilities: Capabilities`; `translate(self, message: Mapping) -> NeutralEvent`; `list_models(self) -> list`; `start_thread(self, params: Mapping, guard=None) -> Mapping`; `start_turn(self, params: Mapping, guard=None) -> Mapping`; `steer(self, params: Mapping) -> Mapping`; `interrupt(self, thread_id: str, turn_id: str) -> None`; `answer_approval(self, request: ApprovalRequest, decision: str) -> None`.
  - `class NoBackend`: a `Backend` whose `capabilities.provider` is `None`-equivalent: `provider == "none"`, every capability `NO`, and every method raising `ProviderUnavailable("No provider configured")`; `class ProviderUnavailable(Exception)`.
- Consumes: nothing from existing modules (this file imports nothing from `dashboard`).

- [ ] **Step 1: Write failing tests** in `tests/test_backends_base.py`: `test_capabilities_public_is_plain_dict`, `test_capabilities_reject_unknown_value`, `test_event_kinds_are_the_eight_named`, `test_neutral_event_is_frozen`, `test_no_backend_reports_provider_none_and_all_no`, `test_no_backend_methods_raise_provider_unavailable` (one assertion per method).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `base.py`** to those signatures. No logic beyond validation and the `NoBackend` raising.
- [ ] **Step 4: Run the full suites; expected baseline plus the new tests, empty fixtures diff.**
- [ ] **Step 5: Commit** `feat: neutral backend types`.

### Task 4: Codex translator (pure functions)

**Files:**
- Create: `dashboard/backends/codex.py`, `tests/test_backends_codex_translate.py`
- Read-only reference: `dashboard/server.py:750-870` (the existing `on_message` branches), `tests/characterization.py` (payload shapes via `ScriptedDashboard.event`)

**Interfaces:**
- Consumes: `NeutralEvent`, `Capabilities`, `YES`, `NO`, `UNCONFIRMED` from `base.py`.
- Produces: `translate_notification(message: Mapping) -> NeutralEvent` in `codex.py`, total (never raises: a non-mapping, a missing `method` or a malformed `params` yields `NeutralEvent("unrecognized", None, None, {"method": <str or None>})`). Mapping:
  - `turn/started` -> `turn_started`; ids from `params.threadId`, `params.turn.id`.
  - `turn/completed` -> `turn_completed`, `data = {"status": "completed"|"failed"|"interrupted"|"unknown", "error": params.turn.error or None}`; any other native status maps to `"unknown"` (this pins the behaviour the characterization mutation test already exercises).
  - `turn/plan/updated` -> `plan_updated`, `data = {"steps": [{"status": ...}]}` with the ordinal labels and statuses exactly as `server.py:821-827` keeps them.
  - `thread/tokenUsage/updated` -> `usage_updated`, `data = {"usage": {...the five USAGE_KEYS values...}}`.
  - `model/rerouted` and `thread/settings/updated` -> `model_changed`, `data = {"model": ..., "service_tier": ..., "rerouted": bool}`.
  - `error` -> `run_error`, `data = {"error": params.error, "will_retry": bool}`.
  - `serverRequest/resolved` -> `request_resolved`, `data = {"request_id": ...}`.
  - everything else -> `unrecognized` with `data = {"method": method}`.
  - `CODEX_CAPABILITIES`: provider `codex`, `guidance_while_running` YES, `subagent_questions` YES, `plan` YES, `recovery` YES, `assessment` YES, `approval_alternative` YES.

- [ ] **Step 1: Write failing tests**, one per row above plus `test_translate_never_raises_on_junk` (inputs: `None`, `42`, `{}`, `{"method": 7}`, `{"method": "turn/completed"}` with no params, `{"method": "turn/completed", "params": "x"}`), `test_unknown_terminal_status_maps_to_unknown`, `test_unrecognized_carries_method_only`. Payload shapes are copied from the characterization helpers, with synthetic ids.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement the functions** by reading the existing branches; they are pure and import nothing from `server.py`.
- [ ] **Step 4: Run the full suites; expected baseline plus new tests, empty fixtures diff.**
- [ ] **Step 5: Commit** `feat: Codex notification translator`.

### Task 5: `CodexBackend` for launch, guidance and interrupt

**Files:**
- Modify: `dashboard/backends/codex.py` (add `CodexBackend`), `dashboard/server.py` (`_launch_task`, `launch_request` around :546-714, `interrupt` around :1399-1434), `dashboard/conversation.py` (`send_message`, `_turn_options` neighbours, around :423-492)
- Create: `tests/test_backends_codex_backend.py`

**Interfaces:**
- Consumes: `Backend`, `CODEX_CAPABILITIES`, `translate_notification`.
- Produces: `class CodexBackend` with `__init__(self, get_client: Callable[[], Any])` (a callable returning the current `Dashboard.client`, so re-assignment in tests is followed; it never creates or closes a client), `capabilities = CODEX_CAPABILITIES`, `translate(message)` = `translate_notification`, and the methods that issue exactly today's requests: `list_models()` (the `model/list` loop of up to 10 pages, returning the collected list), `start_thread(params, guard=None)` (`thread/start`), `start_turn(params, guard=None)` (`turn/start`), `steer(params)` (`turn/steer`), `interrupt(thread_id, turn_id)` (`turn/interrupt`). With a `guard`, they use `request_guarded` when the client has it, exactly as `launch_request` does today; without one they use `request`.
- `Dashboard` gains `self.backend` (set in `__init__` to `CodexBackend(lambda: self.client)` unless a `backend` keyword is given; the keyword is added in Task 8).

- [ ] **Step 1: Write failing tests** in `tests/test_backends_codex_backend.py` using `FakeClient` (`tests/test_dashboard_backend.py:17`): `test_start_thread_sends_thread_start_with_same_params`, `test_start_turn_with_guard_uses_request_guarded`, `test_start_turn_without_guard_uses_request`, `test_steer_and_interrupt_send_native_methods`, `test_list_models_collects_pages_up_to_ten` (11 pages offered, 10 read), `test_backend_follows_client_reassignment` (assign a second FakeClient after construction; the second one receives the request), `test_backend_does_not_close_client`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement `CodexBackend`** and switch the three call sites to it, leaving error classification (`RequestRejected` vs `ProtocolError`, `turn_attempted`, `recovery_hold`) in `server.py` unchanged.
- [ ] **Step 4: Run the full suites; expected baseline plus new tests, empty fixtures diff.** Any existing-test failure means the call site changed behaviour: fix the code, not the test.
- [ ] **Step 5: Commit** `refactor: route Codex launch, guidance and interrupt through CodexBackend`.

### Task 6: Run lifecycle events through the translator

**Files:**
- Modify: `dashboard/server.py` (`on_message` at :750 and the branches at :796-862)
- Create: `tests/test_backends_lifecycle_parity.py`

**Interfaces:**
- Consumes: `self.backend.translate(message)` returning a `NeutralEvent`.
- Produces: `Dashboard.on_message(message)` unchanged in signature and entry (still accepts Codex dicts, still called by `_client_message`); internally it translates once and handles the lifecycle kinds (`turn_started`, `turn_completed`, `plan_updated`, `usage_updated`, `run_error`, `model_changed`, `request_resolved`) from the `NeutralEvent`, and still hands `unrecognized` messages and everything the other modules parse (`conversation`, `delivery`, `recovery`, `_approval_event`) the original message exactly as before.

- [ ] **Step 1: Write parity tests** in `tests/test_backends_lifecycle_parity.py` that drive `ScriptedDashboard` through each family and assert today's behaviour directly (the goldens cover whole snapshots; these pin each family on its own): `test_turn_completed_statuses` (completed, failed, interrupted, and an unknown status each set `task.status` as the goldens show), `test_plan_update_keeps_labels_and_statuses_only`, `test_usage_update_sets_usage_and_cost`, `test_model_reroute_marks_mixed`, `test_error_without_retry_fails_task_and_closes_approvals`, `test_server_request_resolved_removes_pending`, `test_unrecognized_message_does_not_raise`, `test_stale_client_message_ignored` (message via `_client_message` with a replaced client changes nothing).
- [ ] **Step 2: Run them against the current code; they must PASS before any change** (they pin today's behaviour; a failing one means the test is wrong).
- [ ] **Step 3: Refactor in two sub-steps, running the full suites after each:** (a) `turn_started`, `turn_completed`, `run_error`, `request_resolved`; (b) `plan_updated`, `usage_updated`, `model_changed`. Keep `_register_thread`, `_owned`, `owned_threads`, `starting_turn` and the recovery bookkeeping at :754-763 where they are.
- [ ] **Step 4: Run the full suites; expected: all previous tests and the three goldens unchanged.**
- [ ] **Step 5: Commit** `refactor: handle Codex run lifecycle through neutral events`.

### Task 7: Approval answering through the backend

**Files:**
- Modify: `dashboard/backends/codex.py` (add `codex_approval_result` and `CodexBackend.answer_approval`), `dashboard/server.py` (`respond_approval` response shaping at :1375-1387, `request_approval_alternative` response at :1112)
- Create: `tests/test_backends_codex_approval.py`

**Interfaces:**
- Consumes: `ApprovalRequest`.
- Produces: `codex_approval_result(kind: str, decision: str, params: Mapping) -> Mapping` returning exactly the dicts built at `server.py:1375-1386` (`{"decision": decision}`; `{"permissions": ..., "scope": "turn"}`; `{"action": ..., "content": ...}`; `{"answers": ...}`); `CodexBackend.answer_approval(request, decision)` writes `client.respond(rpc_id, result)` where `request.responder` is `(client, rpc_id)`. `Dashboard.pending[approval_id]` keeps today's keys (`rpc_id`, `client`, `binding`, `params`, ...). The `requester` text "via Codex App Server" and `native_method` are untouched.

- [ ] **Step 1: Write failing tests**: `test_result_shapes_for_each_kind_and_decision` (command, file_change, permissions, elicitation, approval_question; accept, decline, cancel), `test_answer_approval_writes_through_responder`, `test_unknown_decision_never_responds` (Review Focus 8), `test_answer_failure_propagates` (a client whose `respond` raises: the exception reaches the caller so `respond_approval` still closes the client).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement and switch the two call sites;** the order "consume authority, then respond" in `respond_approval` stays exactly as it is.
- [ ] **Step 4: Run the full suites; expected: previous tests and goldens unchanged (the approvals golden pins `requester` and `native_method`).**
- [ ] **Step 5: Commit** `refactor: answer Codex approvals through CodexBackend`.

### Task 8: Provider resolution and the start-up setting

**Files:**
- Modify: `dashboard/backends/__init__.py` (resolver), `dashboard/backends/base.py` (nothing new expected), `dashboard/server.py` (`Dashboard.__init__` `backend` keyword; `start()` skips `_connect_loop` for `NoBackend`; `main()` `--provider`; new `GET /api/provider`), `scripts/run_dashboard.sh`, `README.md` (Start section), `docs/dashboard-operations.md`
- Create: `dashboard/backends/claude.py` (stub), `tests/test_provider_setting.py`

**Interfaces:**
- Produces, in `dashboard/backends/__init__.py`: `resolve(name: Optional[str], get_client: Callable[[], Any]) -> Backend`: `"codex"` -> `CodexBackend(get_client)`, `"claude"` -> `ClaudeBackendStub()`, anything else including `None`, `""`, `"Codex"`, `"codex "` -> `NoBackend()`.
- `ClaudeBackendStub` (in `claude.py`): `capabilities` with provider `claude`, `guidance_while_running` `NO`, `subagent_questions` `NO`, `plan` `UNCONFIRMED`, `recovery` `NO`, `assessment` `NO`, `approval_alternative` `NO`; every method raises `ProviderUnavailable("Claude backend is not implemented yet")`.
- `GET /api/provider` returns `{"provider": "codex"|"claude"|"none", "configured": bool, "capabilities": {...public()...}}`.
- `main()` takes `--provider` (no `choices`, so a missing value reaches the resolver and yields `NoBackend`, which the UI shows as "No provider configured"); `Dashboard(..., backend=None)` uses `CodexBackend(lambda: self.client)` when `backend is None`; with a `NoBackend`, `start()` starts no connect loop, `connection.status` is `"disabled"` and `connection.detail` is "No provider configured."
- `scripts/run_dashboard.sh`: takes exactly one argument `codex` or `claude` (anything else, including none, prints usage and exits 2); requires `codex` on PATH only for `codex`; runs `exec "$dashboard_python" -m dashboard.server --port 8765 --provider "$1"`. README Start becomes `sh scripts/run_dashboard.sh codex`. This changes how existing Codex users start the dashboard; the release note says so.

- [ ] **Step 1: Write failing tests** in `tests/test_provider_setting.py`: `test_resolve_exact_names_only` (the values listed in Review Focus 2), `test_no_backend_dashboard_starts_no_connection` (a `Dashboard(backend=NoBackend())` with a `client_factory` that records calls: `start()` never calls it; status `disabled`), `test_no_backend_refuses_run_start` (the start-task method answers a clear error and sends no request), `test_api_provider_reports_codex_by_default`, `test_api_provider_reports_none_for_no_backend`, `test_claude_stub_start_run_answers_not_implemented_without_spawning` (no `codex` client created; no subprocess), `test_script_exit_codes` (run `sh scripts/run_dashboard.sh` with no argument, `claude2`, `Codex`: exit 2 and no server; do not start a server for valid arguments).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the resolver, stub, constructor keyword, `start()` branch, `--provider`, endpoint and script. `scripts/` is owner-reviewed (CODEOWNERS): keep the script change minimal and mention it in the commit message.
- [ ] **Step 4: Run the full suites; expected: previous tests and goldens unchanged.**
- [ ] **Step 5: Commit** `feat: start-up provider setting that fails closed`.

### Task 9: Record the provider on projects and runs

**Files:**
- Modify: `dashboard/server.py` (project creation :402, task creation :451, the load-time `setdefault` block, mutating handlers), `dashboard/recovery.py:79-92` (the existing `setdefault` block, add `provider`)
- Create: `tests/test_provider_records.py`

**Interfaces:**
- Produces: JSON field `provider` on `project` and `task` records, written as the active provider at creation, defaulting to `"codex"` on load for records without it. `snapshot()` omits `provider` for `codex` records (keeps the goldens) and includes it for any other value. `Dashboard._require_active_provider(task) -> None` raises the existing validation-error type with the message "recorded under a different provider" when `task["provider"] != self.backend.capabilities.provider`; it is called at the top of `send_message`, `interrupt`, `respond_approval`, `respond_question`, `request_approval_alternative`, `start_delivery_checks`, `start_delivery_review`. Read-only routes and `delete_task` are not guarded.

- [ ] **Step 1: Write failing tests**: `test_legacy_records_load_as_codex` (write `project` and `task` rows without `provider` through `Store`, reload), `test_new_records_carry_active_provider`, `test_snapshot_omits_provider_for_codex_and_shows_others`, `test_actions_on_other_provider_run_are_refused` (one assertion per guarded handler: refused, and `fake.requests` empty), `test_read_routes_and_delete_work_for_other_provider_run`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** No schema DDL; a `Store` row's JSON gains one key.
- [ ] **Step 4: Run the full suites; expected: previous tests and goldens unchanged.**
- [ ] **Step 5: Commit** `feat: record provider on projects and runs`.

### Task 10: Provider-aware routes and UI labels

**Files:**
- Modify: `dashboard/server.py` (`Handler.do_GET`/`do_POST` route table :1505-1760), `dashboard/static/app.js` (the strings at :190-195, :259, :344, :409-432 and the run-dialog title, plus a provider chip in `renderTasks` :207 and a "Provider" row in `renderDetail` :999), `dashboard/static/index.html` (:27, :31, :64, :65, :72, :79)
- Create: `tests/test_provider_routes.py`, `tests/test_provider_ui.js`

**Interfaces:**
- Consumes: `GET /api/provider`; `Capabilities.recovery`, `assessment`, `approval_alternative`.
- Produces: a table in `server.py` mapping the Codex-only routes (recovery and assessment paths, `/api/approvals/<id>/alternative`) to the capability that gates them; when the active capability is `NO`, the handler returns HTTP 409 `{"error": "not available for this provider"}` before touching state. The UI reads `/api/provider` once at load; if the request fails or the endpoint is absent it keeps today's wording ("Codex connected", "Codex App Server", "Start a Codex run"), so the existing JS tests (which never serve the endpoint) pass unchanged. With provider `claude` it shows "Claude", hides the recovery button and the approval-alternative control, and with `none` shows "No provider configured" and disables "Start run".

- [ ] **Step 1: Write failing tests**: `test_codex_only_routes_409_under_claude_stub` (every route in the table, GET and POST, asserts status 409 and unchanged records), `test_codex_routes_unchanged_under_codex`, JS `test_labels_follow_provider_endpoint` (provider `claude`: "Claude connected"-style text and no recovery button), `test_labels_default_to_codex_wording_without_endpoint`, `test_provider_chip_and_detail_row`, `test_none_provider_disables_start_run`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the gating table and the UI changes. Add nodes and functions; do not rename ids or restructure markup used by the seven existing JS test files.
- [ ] **Step 4: Run the full suites; expected: previous tests and goldens unchanged.**
- [ ] **Step 5: Commit** `feat: gate Codex-only routes and label the provider`.

### Task 11: Documentation closeout, evidence and verification

**Files:**
- Modify: `docs/dashboard-operations.md`, `docs/dashboard-api.md` (`GET /api/provider`, the 409 answer), `docs/product-brief.md` (one paragraph: one provider per deployment), `docs/decisions.md` if the provider-argument ruling is not yet recorded, `docs/task-board.md`, `docs/claude-code-setup.md` (how to start a Claude deployment, stub status)
- Create: `docs/superpowers/evidence/2026-10-28-provider-seam.md`

- [ ] **Step 1: Assign `technical_writer` (and `user_documentation_writer`, since the start command changed) per `AGENTS.md`;** they review the doc changes for accuracy against the code. Record the closeout or an explicit no-change rationale in the evidence file.
- [ ] **Step 2: Write the evidence file:** commits per task, the full-suite counts before and after, `git diff --stat 85c14bc.. -- tests/fixtures/characterization/` (expected empty), what is unit, golden, live (Task 1 only) and owner-reported, and what remains untested (no Claude run through the dashboard; the Codex native end-to-end path was not re-run live).
- [ ] **Step 3: Run both suites in the clean environment, `python3 scripts/sync_roles.py --check`, and `python3 scripts/security_check.py staged`;** record outputs.
- [ ] **Step 4: Commit** `docs: provider seam closeout`. Ask the owner for review; do not start Plan 3 without it.

# Claude observed sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner sees their own Claude Code terminal sessions in the dashboard and answers those sessions' permission prompts there (Phase 3).

**Architecture:** A second loopback listener on a fixed port (default 47615) accepts `/hook/observed/<install token>` only, with its own token table. Sessions and approvals live in a new `ObservedSessions` model (ids and status in SQLite, request payloads in memory). Shared HTTP/held-request code is split out of `dashboard/hook_receiver.py` without changing managed behaviour. Claude deployments only.

**Tech Stack:** Python 3 standard library (`http.server`, `sqlite3`, `unittest`), the existing vanilla JS dashboard (`dashboard/static/app.js`), `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-06-claude-observed-sessions-design.md` (parent: `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` section 4.3; hook evidence: `docs/superpowers/spikes/S7-observed-hooks.md`).

## Global Constraints

- One provider per deployment: a Codex deployment opens no listener, shows no observed page, and its observed routes return 409 `not available for this provider` (`NOT_AVAILABLE`).
- Listener binds `127.0.0.1` only; path exactly `/hook/observed/<token>` where token matches `[A-Za-z0-9_-]{1,128}`; managed path `/hook/managed/...` unchanged and never served by the observed listener (and the reverse).
- Install token: `secrets.token_urlsafe(32)`; file mode 0600 in a directory mode 0700 outside the repository; never in a log line, error body, exception text, snapshot, list or any API response except `GET /api/observed/hook-config`.
- Caps: 256 stored sessions, 32 pending approvals, quiet after 1800 s without events. Defaults changeable only in code constants and the `observed_port` setting.
- `observed_port` setting: integer 1024 to 65535, default 47615, optional on save (like `claude_approval_wait_seconds`).
- The observed listener never replies deny on its own and never blocks the terminal: expiry, closed connection, cap, stop, parse failure and dashboard error all reply HTTP 200 `{}` (no decision). Only the owner's Allow or Deny from the dashboard produces an allow or deny reply.
- Each approval card records `decided_by` (`dashboard`, `terminal (inferred)`, `timed out`, `unknown`), `decision`, `outcome` (`ran`, `not run`, `unknown`) and `decided_at`; terminal answers are inferred from later same-session, same-agent events and labelled as inferred.
- Observed approvals are never auto-approved in any approval mode, and a closed or expired card can never be answered.
- No real secrets in files, logs, tests or chat; tests use fake tokens. Run `python3 scripts/security_check.py staged` before each commit and `history` before a push. Add files by name; never `git add -A`.
- Python 3.12 is the CI version; run affected modules with `$(uv python find 3.12)` too.
- Live runs need an owner-approved alias, count and estimate immediately beforehand. Label evidence kinds: unit, fake-binary, browser, live, owner-reported.

## Review Focus

- A card is answered after the owner already answered in the terminal or after the hook timed out: the answer must not be sent and the API must say the card is closed.
- A hook request whose `cwd` or `tool_input` contains a credential-shaped string: nothing of it appears in any API response or the database.
- Hundreds of distinct `session_id`s from one client: caps hold, memory stays bounded, the oldest ended or quiet sessions go first.
- The fixed port is already in use at startup (or the token file is unreadable): the dashboard still starts, observed sessions report "off" with the reason, nothing else breaks.
- A managed run's token sent to the observed path, and the install token sent to the managed path: both refused with no state change.

---

### Task 1: Attended spike kit S11 (no-decision reply and the four untested terminal cases)

**Files:**
- Create: `scripts/spike_s11_stub.py` (stub listener, runs outside the dashboard), `docs/superpowers/spikes/S11-observed-replies.md` (method, kit instructions, results table left "pending owner run")
- Test: `tests/test_spike_s11_stub.py`

**Interfaces:**
- Produces: the decision for the constant `NO_DECISION_MODE` in `dashboard/observed_receiver.py` (Task 5), one of `"empty_object"` (200 with `{}`; the default, docs-sourced), `"status_204"`, `"close"` (drop the connection), `"hold"` (keep the connection open until the hook's own timeout; the only behaviour S7 verified, the fallback if `empty_object` is shown to disturb the terminal prompt). The spike also records the real `PostToolUse` and `Stop` payload fields (is `tool_input` present, is there a `tool_use_id`, what a terminal No produces) that the two-way record depends on.

- [ ] **Step 1: Write the failing test** in `tests/test_spike_s11_stub.py`: `test_stub_replies_per_mode` starts the stub on an ephemeral port for each mode in (`empty_object`, `status_204`, `close`, `hold`), posts a PermissionRequest-shaped JSON body, and asserts status/body per mode (`200 {}`, `204` empty, connection closed with no response, no response before a short client timeout); `test_stub_logs_no_body` asserts the stub's log file contains event names and field names only, never `tool_input` values.
- [ ] **Step 2: Run it to see it fail:** `python3 -m unittest tests.test_spike_s11_stub -v` expects an import error.
- [ ] **Step 3: Implement** `scripts/spike_s11_stub.py` (`python3 scripts/spike_s11_stub.py --mode MODE --port PORT --log PATH`) with the four modes above plus `--script allow|deny` for answering after a delay (`--after SECONDS`) to cover: terminal No then a late allow, terminal Yes then a late deny, a deny while the prompt is open, and a simultaneous answer. Log one line per request: time, event name, field names. Model on the S7 kit under `scripts/` if present.
- [ ] **Step 4: Write the spike note** (add the two-way cases: terminal Yes then `PostToolUse`; terminal No then what the next events are; dashboard Allow then `PostToolUse`; dashboard Deny then any `PostToolUse`) with the case table (case, owner action, stub action, expected evidence, result "pending owner run") and the decision rule: choose the first mode that leaves Claude Code's terminal prompt open with nothing auto-allowed; if none is verified, keep `"hold"`.
- [ ] **Step 5: Run the tests, then commit** (`git add` the three files by name).

The owner (or `qa_engineer` with the owner at an interactive terminal) runs the kit; the result goes into the note and into `docs/claude-code-setup.md` in Task 9. Tasks 2 to 8 do not wait for it.

---

### Task 2: Split the shared hook HTTP code out of the managed receiver

**Files:**
- Create: `dashboard/hook_http.py`
- Modify: `dashboard/hook_receiver.py` (import from `hook_http`; behaviour identical)
- Test: `tests/test_hook_http.py`; `tests/test_hook_receiver.py` must pass unchanged

**Interfaces:**
- Produces in `dashboard/hook_http.py`: `class HeldRequest` (moved verbatim), `def client_gone(conn) -> bool` (moved from `_client_gone`), `class HookHandlerBase(BaseHTTPRequestHandler)` with `_status(code: int, body: bytes = b"") -> None`, `_guard(authority: str) -> bool` (False after sending 403 when Host is not exactly `[authority]` or any Origin header exists), and `_read_body(limit: int) -> Optional[bytes]` (sends 415/400/411/413 itself and returns None; returns the exact-length body otherwise), plus `class QuietServer(ThreadingHTTPServer)` (`daemon_threads`, `allow_reuse_address`, silent `handle_error`).
- `hook_receiver.py` keeps exporting `HeldRequest` and `_client_gone` (alias) so existing tests importing them still work.

- [ ] **Step 1: Write the failing test** `tests/test_hook_http.py`: `test_guard_refuses_wrong_host_and_any_origin`, `test_read_body_status_codes` (non-JSON content type 415, `Transfer-Encoding` 400, missing length 411, two lengths 400, over limit 413, short body returns None with no reply), `test_held_request_first_resolve_wins`, `test_client_gone_detects_closed_socket`, using a tiny handler subclass on an ephemeral port.
- [ ] **Step 2: Run to confirm the failure** (`python3 -m unittest tests.test_hook_http`), then **Step 3: Move** the classes/functions listed above out of `hook_receiver.py` and make `_Handler` derive from `HookHandlerBase`, calling `_guard` and `_read_body`; keep the status-code order exactly as it is now (403 before 404 before 415 and so on).
- [ ] **Step 4: Run** `python3 -m unittest tests.test_hook_http tests.test_hook_receiver tests.test_claude_approval_lifecycle` on the default Python and on 3.12; all pass with no test edits to `test_hook_receiver.py`.
- [ ] **Step 5: Commit.**

---

### Task 3: Install token file and the `observed_port` setting

**Files:**
- Create: `dashboard/observed_token.py`
- Modify: `dashboard/settings.py` (`DEFAULTS["observed_port"] = 47615`, `_OPTIONAL_ON_SAVE`, validation)
- Test: `tests/test_observed_token.py`, additions to the settings tests (find them with `grep -l claude_approval_wait_seconds tests/*.py`)

**Interfaces:**
- Produces: `def default_config_dir() -> Path` (`~/Library/Application Support/KT Agent Dashboard` on macOS, `$XDG_CONFIG_HOME` or `~/.config` + `kt-agent-dashboard` elsewhere); `class TokenFile: __init__(self, directory: Path)`, `token(self) -> str` (creates on first use), `rotate(self) -> str`, `status(self) -> Optional[str]` (`None` when usable, else `"unreadable"` or `"permissions"`), `matches(self, candidate: str) -> bool` (constant time, always False when `status()` is not None).
- Consumed by: Task 5 (`matches`), Task 6 (`token`, `rotate`).

- [ ] **Step 1: Write failing tests:** `test_token_created_once_with_modes` (file 0600, directory 0700, second `TokenFile` on the same directory returns the same token), `test_rotate_invalidates_old_token`, `test_matches_is_false_for_other_and_empty_candidates`, `test_wrong_mode_reports_permissions_and_never_rewrites` (chmod 0644 → `status() == "permissions"`, file content unchanged), `test_symlink_or_foreign_file_reports_unreadable`, `test_token_not_in_repr_or_exceptions` (`repr(TokenFile)` and the raised error text contain no token), and settings tests `test_observed_port_default_and_range` (1023, 65536, `True`, a string rejected with `SettingsError` 400; 47615 and 1024 accepted) and `test_observed_port_optional_on_save`.
- [ ] **Step 2: Run to confirm failures; Step 3: Implement** with `os.open(..., O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)` for creation, `os.replace` of a temp file for rotation, and the same owner/link checks as `dashboard/store.py`.
- [ ] **Step 4: Run both test modules and `python3 scripts/sync_roles.py --check`; Step 5: Commit.**

---

### Task 4: Observed event parsing and the sessions model

**Files:**
- Create: `dashboard/observed_hook.py`, `dashboard/observed.py`
- Test: `tests/test_observed_hook.py`, `tests/test_observed_sessions.py`

**Interfaces:**
- `observed_hook.py` produces: `@dataclass(frozen=True) class ObservedEvent: kind: str; session_id: str; cwd: Optional[str]; request: Optional[HookRequest]; agent_id: Optional[str]`, with `kind` in (`"permission_request"`, `"post_tool_use"`, `"stop"`, `"session_start"`, `"session_end"`, `"subagent_start"`, `"subagent_stop"`), with `tool_name: Optional[str]` and `tool_input: Optional[dict]` set for `post_tool_use`; `def parse_observed(body: bytes) -> ObservedEvent` raising `HookRejected(code)` (reuse `dashboard.backends.claude_hook.HookRejected`, `parse_request`, `MAX_BODY`, and its field patterns; unknown event names raise `HookRejected("bad_field")`; `cwd` must be a string of at most 4096 characters, else rejected).
- `observed.py` produces: `class ObservedSessions: __init__(self, store, clock=time.time, quiet_seconds=1800, max_sessions=256, max_pending=32)`; `record(self, event: ObservedEvent) -> None`; `add_pending(self, event: ObservedEvent, held: HeldRequest, expires_at: float) -> Optional[str]` (approval id, or `None` when the pending cap is reached; increments a `refused` counter); `finish(self, approval_id: str) -> None`; `answer(self, approval_id: str, decision: str) -> str` returning `"ok"`, `"closed"` or `"unknown"`; `snapshot(self) -> dict` with keys `sessions`, `approvals`, `refused`, `limits`.
- Session record (SQLite kind `"observed_session"`): `id` (the session id), `project` (final path segment of `cwd`, run through the scan; `"unknown"` if refused), `first_seen`, `last_seen`, `status` in (`active`, `ended`), `subagent_seen_at` (or None). `snapshot()` reports `quiet` as a computed state when `status == "active"` and `now - last_seen >= quiet_seconds`.
- Approval card in `snapshot()["approvals"]`: `id`, `session_id`, `project`, `tool_name`, `summary` (bounded text; `"withheld"` when the scan refuses), `agent_type`, `status` (`pending`, `closed`, `answered`), `decided_by`, `decision`, `outcome`, `decided_at`, `expires_at`, `created_at`. `ObservedSessions.record` applies the inference rules of spec section 5.2 (match on session, agent, `tool_name` and equal `tool_input`; any later other-call `post_tool_use`, `stop` or `session_end` closes the card as `terminal (inferred)`, `outcome` `not run` unless a match was seen). The raw `tool_input` is held in memory only and never leaves via `snapshot()`.
- Uses the managed card's pipeline for scanning (`review_bytes`/`ReviewError` from `dashboard/approval_review.py`, `safe_text` from `dashboard/conversation.py`).

- [ ] **Step 1: Write failing tests** (hook): `test_parse_each_event_kind` (fixture bodies for all five kinds), `test_unknown_event_rejected`, `test_cwd_must_be_bounded_string`, `test_permission_request_reuses_managed_limits` (oversize, duplicate keys, NaN rejected). (sessions): `test_first_event_creates_session`, `test_session_end_marks_ended_and_any_event_reactivates`, `test_quiet_is_computed_not_stored` (fake clock), `test_subagent_activity_has_time_not_count`, `test_cap_evicts_ended_then_quiet_first` (257 sessions), `test_pending_cap_refuses_and_counts`, `test_credential_shaped_cwd_and_input_never_in_snapshot_or_store` (assert on `snapshot()` JSON and on `store.load("observed_session")`), `test_answer_after_close_reports_closed_and_does_not_resolve`, `test_answer_unknown_id`, `test_snapshot_has_no_tool_input`, `test_post_tool_use_match_closes_card_as_terminal_inferred_ran`, `test_later_other_event_closes_card_as_not_run`, `test_subagent_event_does_not_close_main_session_card`, `test_post_tool_use_after_dashboard_allow_records_ran`, `test_post_tool_use_after_dashboard_deny_raises_warning_flag`, `test_unmatched_card_stays_unknown_not_guessed`.
- [ ] **Step 2: Run to confirm failures; Step 3: Implement.** The model takes one lock and never holds it while writing to the store failing silently; a store error must not lose the in-memory state.
- [ ] **Step 4: Run both modules; Step 5: Commit.**

---

### Task 5: The observed listener

**Files:**
- Create: `dashboard/observed_receiver.py`
- Test: `tests/test_observed_receiver.py`

**Interfaces:**
- Consumes: `HookHandlerBase`, `QuietServer`, `client_gone` (Task 2), `TokenFile` (Task 3), `parse_observed`, `ObservedSessions` (Task 4), `allow_reply`/`deny_reply` from `dashboard/backends/claude_hook.py`.
- Produces: `NO_DECISION_MODE = "empty_object"` (module constant, see Task 1), `class PortInUse(Exception)`, `class ObservedReceiver: __init__(self, sessions, token_file, port, wait_seconds=300, poll_interval=1.0)`, `start(self) -> None` (raises `PortInUse` when the bind fails; no fallback port), `stop(self) -> None`, `port` property.
- Behaviour: path `/hook/observed/<token>`; Host must be `127.0.0.1:<port>`; token checked with `token_file.matches`; a wrong token or unknown path replies bare 404 with no body; other events record and reply `200` with body `{}`; `PermissionRequest` becomes a held request through `sessions.add_pending`; the dashboard's Allow gives `allow_reply()`, Deny gives `deny_reply()` (and record `decided_by = "dashboard"`); expiry, a closed client, a refused cap, a parse failure or `stop()` apply `NO_DECISION_MODE` (never an allow, never a deny) and record `timed out` where it applies. `stop()` ends all holds. No log or error text carries the token, path or request text.

- [ ] **Step 1: Write failing raw-socket tests** in the style of `tests/test_hook_receiver.py`: `test_wrong_token_and_unknown_path_get_bare_404`, `test_managed_token_refused_on_observed_listener_and_install_token_refused_on_managed` (start a `HookReceiver`, register a run, post each token to the other listener; assert no state change in either), `test_session_end_recorded_and_replied_empty_object`, `test_permission_request_allow_and_deny_replies` (answer through `sessions.answer`), `test_expiry_closed_cap_stop_and_parse_failure_reply_200_empty_object_never_deny`, `test_post_tool_use_and_stop_events_recorded_and_replied_empty_object`, `test_expiry_uses_no_decision_not_allow_or_deny`, `test_client_closed_marks_card_closed_and_late_answer_reports_closed`, `test_pending_cap_refusal_replies_no_decision_and_counts`, `test_port_in_use_raises_without_fallback` (bind a socket first), `test_host_and_origin_guard`, `test_oversize_body_413`, `test_stop_ends_holds`, `test_nothing_logged_carries_token` (capture stderr/logging).
- [ ] **Step 2: Run to confirm failures; Step 3: Implement,** reusing the managed receiver's structure (unheld connection cap, read deadline, handler tracking). **Step 4: Run** the module and `tests.test_hook_receiver` on the default Python and 3.12. **Step 5: Commit.**

---

### Task 6: Server wiring and API routes (Claude only)

**Files:**
- Modify: `dashboard/server.py` (lifecycle and routes), `dashboard/settings.py` use only
- Test: `tests/test_observed_api.py` (uses `tests/dashboard_key_harness.py`'s `make_test_server`)

**Interfaces:**
- Consumes: Tasks 3 to 5.
- Produces routes, all behind the dashboard key and refused 409 `NOT_AVAILABLE` on a Codex deployment:
  - `GET /api/observed` → `{"enabled": bool, "reason": null | "port_in_use" | "token_unreadable" | "token_permissions", "port": int, **ObservedSessions.snapshot()}` (never the token).
  - `GET /api/observed/hook-config` → `{"url": "http://127.0.0.1:<port>/hook/observed/<token>", "snippet": <exact hooks JSON for the events PermissionRequest, PostToolUse, Stop, SessionEnd, SubagentStart, SubagentStop, SessionStart, type http, timeout greater than the wait>, "note": text}`; `Cache-Control: no-store`.
  - `POST /api/observed/rotate-token` → `{"rotated": true}` (new token readable only via hook-config); existing holds keep their already-checked requests.
  - `POST /api/observed/approvals/<id>/allow` and `.../deny` → `{"result": "ok"|"closed"|"unknown"}` with HTTP 200, 409, 404 respectively.
- Lifecycle: `Dashboard.__init__` starts the listener when the active provider is Claude (error recorded as `reason`, never raised) and `close()` stops it. A test seam `observed_receiver_factory` parallels `hook_receiver_factory`.

- [ ] **Step 1: Write failing tests:** `test_codex_deployment_opens_no_listener_and_routes_409`, `test_claude_deployment_listener_started_and_stopped_on_close`, `test_port_in_use_dashboard_still_starts_and_reports_reason`, `test_snapshot_and_listing_never_contain_token` (search every JSON response from `/api/state`, `/api/observed`, `/api/team`, `/api/config` for the token), `test_hook_config_requires_key_and_contains_token_once`, `test_rotate_changes_hook_config_token`, `test_allow_deny_closed_unknown_status_codes`, `test_observed_approvals_not_in_state_approvals_and_never_automatic` (project mode set to automatic: card stays pending), `test_observed_does_not_touch_managed_state`.
- [ ] **Step 2: Run to confirm failures; Step 3: Implement** with thin handlers that delegate to `ObservedSessions`/`TokenFile`. **Step 4: Run** `tests.test_observed_api tests.test_dashboard_key tests.test_provider_routes` and the full Python suite later in Task 8. **Step 5: Commit.**

---

### Task 7: Sessions page, approval cards and the hook snippet page

**Files:**
- Modify: `dashboard/static/app.js` (and `styles.css`/`index.html` only if the nav needs it)
- Test: `tests/test_observed_ui.js` (run with `node --test tests/test_observed_ui.js`; follow the structure of `tests/test_claude_approvals_ui.js`)

**Interfaces:**
- Consumes: the Task 6 routes. Produces: a nav entry "Terminal sessions" shown only for a Claude deployment; the page shows the status line ("Observed sessions off: port in use" and the other reasons verbatim from `reason`), the Auto-mode limit sentence ("Only calls that reach a permission prompt are sent, so in Auto mode this list is not a complete record."), the sessions list (project, status active/quiet/ended, last seen, "subagent activity seen" with time and never a count), pending cards ("Your terminal session", tool, bounded summary, agent type, expiry, "may already be answered in the terminal", Allow and Deny buttons; a decided card shows who decided and the outcome ("Answered in the terminal (inferred): ran", "Allowed here: ran", "Denied here: not run", and the warning "ran although denied here") with the line "Inferred from later events, not a receipt"; closed cards show "closed: answered elsewhere or timed out" with no buttons), the refused counter, and a snippet panel that fetches `hook-config` only when opened, plus a Rotate token button with a confirm.

- [ ] **Step 1: Write failing UI tests:** `test_page_hidden_for_codex`, `test_off_reasons_shown`, `test_session_rows_show_quiet_and_no_subagent_count`, `test_pending_card_text_and_buttons`, `test_closed_card_has_no_buttons`, `test_decided_card_shows_decided_by_and_outcome_and_inference_note`, `test_ran_although_denied_warning_shown`, `test_allow_deny_post_and_closed_response_updates_card`, `test_snippet_fetched_only_on_open_and_token_not_rendered_elsewhere`, `test_all_text_escaped` (a session whose project is `<img onerror=1>` renders as text).
- [ ] **Step 2: Run to confirm failures; Step 3: Implement** with the existing DOM helpers (textContent, no innerHTML for data). **Step 4: Run** the new file and the whole `node --test tests/*.js`. **Step 5: Commit.**

---

### Task 8: Journey tests, security hardening and the browser check

**Files:**
- Create: `tests/test_observed_journey.py`
- Modify: files above only to fix findings.
- Evidence: `docs/superpowers/evidence/2026-11-06-observed-sessions.md`

**Interfaces:** consumes everything above; produces the evidence file with kinds labelled.

- [ ] **Step 1: Write the journey tests** (fake-binary, real HTTP): `test_owner_journey_end_to_end` (install token via hook-config, post `SessionEnd`-less first `PermissionRequest`, session appears, card pending, Allow from the API, the hook reply is allow, card answered, the session list shows active), `test_deny_journey`, `test_terminal_yes_then_post_tool_use_closes_card_ran`, `test_terminal_no_then_stop_closes_card_not_run`, `test_dashboard_deny_then_post_tool_use_warns`, `test_terminal_never_denied_by_dashboard_on_expiry_cap_or_stop`, `test_terminal_answered_first_then_dashboard_answer_is_closed`, `test_hook_timeout_then_answer_is_closed`, `test_flood_of_sessions_is_bounded` (1,000 distinct ids), `test_credentials_in_cwd_and_tool_input_never_exposed`, `test_restart_keeps_sessions_but_no_pending_cards` (new `Dashboard` on the same directory).
- [ ] **Step 2: Run them; fix failures in the owning module** (add a regression test beside the fix).
- [ ] **Step 3: Dispatch a read-only `security_reviewer`-style review** of the whole branch against the spec's section 7 focus list (token separation both ways, token file, no token in responses/logs, scans, caps, DNS-rebinding guard, no path to managed state); fix findings with tests and a scoped re-review.
- [ ] **Step 4: Browser check** on a scratch copy (fake sessions posted with `curl`-equivalent Python): sessions page, card, snippet page, off reasons; record what was seen.
- [ ] **Step 5: Run** the full Python suite on the default Python and on 3.12, plus `node --test tests/*.js` and `python3 scripts/sync_roles.py --check`; record counts in the evidence file. **Commit.**

---

### Task 9: Documentation, evidence and agent evaluation

**Files:**
- Modify: `docs/dashboard-operations.md` (setup of the hook snippet, port, token rotation, limits, what is and is not shown), `docs/dashboard-api.md` (the four routes), `docs/claude-code-setup.md` (replace "Observed sessions are planned" with the built state and the S11 result or "S11 not yet run"), `docs/decisions.md` (the chosen defaults and the no-decision mode), `docs/task-board.md`, `docs/model-evaluation.md` (checkpoint entry), `tests/test_claude_docs.py` (assert the new statements and that no doc says the feature is "planned")
- Evidence: the Task 8 file gets the final counts and the live items marked pending or done.

- [ ] **Step 1: Assign `technical_writer` and `user_documentation_writer`** (bounded reviews through general workers if roles cannot load; record that), give them the verified behaviour and checks.
- [ ] **Step 2: Write failing doc tests** (`test_observed_sessions_documented`, `test_no_stale_planned_wording`, `test_token_never_in_docs_examples` using the placeholder `<REDACTED>`), then update the docs until they pass.
- [ ] **Step 3: Dispatch `agent_evaluation_engineer`** for a completion checkpoint (record role, model, effort, tokens per dispatch in the evidence file's routing record this time; pass `effort` explicitly on every dispatch).
- [ ] **Step 4: Run the docs tests and the security checks; commit; then (with the owner's authorization) push and open the PR, and bind it with the ccd_pr tools.**

---

## Self-review

- Spec coverage: architecture (section 3) → Tasks 2, 3, 5, 6; sessions (4) → Task 4; approvals (5) → Tasks 4, 5, 6, 7; failure handling (6) → Tasks 5, 6; security focus (7) → Task 8; testing and evidence (8) → Tasks 1, 8, 9; non-goals are not built. The four terminal-attended cases, the real `PostToolUse`/`Stop` payloads and the live check of the `{}` reply are Task 1 (owner-attended); until they run, the docs say the `{}` reply and the inference rules are docs-sourced or fake-binary only.
- Names checked across tasks: `HeldRequest`, `client_gone`, `HookHandlerBase`, `QuietServer`, `TokenFile.matches/token/rotate/status`, `ObservedEvent`, `parse_observed`, `ObservedSessions.record/add_pending/finish/answer/snapshot`, `ObservedReceiver.start/stop/port`, `NO_DECISION_MODE`, `PortInUse`.
- Known risk: `server.py` is large; the wiring (Task 6) stays thin and the model lives in `observed.py`.

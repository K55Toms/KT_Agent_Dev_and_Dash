# Dashboard implementation contract

Approved scope: local multi-project Python/SQLite/browser application managing its own Codex
App Server. Existing desktop chats are outside v1. Live events drive task state and approvals.
No inference is started merely by opening the dashboard or connecting App Server.

## HTTP API

JSON endpoints, same-origin only. Loopback listener and strict Host/Origin checks. Mutations
require JSON Content-Type and same-origin Origin. No arbitrary RPC endpoint, shell execution,
credential access, external bind option or CORS. Maximum request size is bounded.

### Dashboard key

Every request needs the dashboard key except GET of the page shell (`/`, `/index.html`,
`/app.js`, `/styles.css`, `/designs`, `/designs.html`, `/designs.css`, `/designs.js`,
`/brand-logo.png` and `/team-portraits/<role>.svg`, exact paths with no query). That covers
every path under `/api/` and every method, GET included, as well as any other path or method.
The separate Claude hook receiver is not part of this server and keeps its own per-run token.

- At start-up `python3 -m dashboard.server` generates the key with `secrets.token_urlsafe(32)`
  (43 URL-safe characters) and keeps it in memory only. It is never written to a file, the
  database, settings, an environment variable, argv, the snapshot, diagnostics, a log line or an
  error body. Each start makes a new key.
- The key leaves memory once: the terminal line `Dashboard: http://127.0.0.1:<port>/#key=<key>`.
  The key is in the URL fragment, which the browser does not send to the server.
- The page reads `#key=...`, keeps the key in `sessionStorage` for that tab (or only in a script
  variable when storage is blocked), removes the fragment from the address bar with
  `history.replaceState`, and sends header `X-Dashboard-Key: <key>` on every API call. All API calls
  go through one fetch wrapper in `app.js`. An uploaded logo (`GET /api/logo/{sha256}.png`) is
  fetched through that wrapper and shown from a `blob:` URL, which is why the page's CSP has
  `img-src 'self' blob:`. The design preview page (`designs.js`) reads the key saved for the tab and
  sends it the same way; without a key it keeps its default name and logo. No `<img src>`, link,
  form, `EventSource` or `window.open` reaches `/api/`.
- A missing, empty, wrong or repeated `X-Dashboard-Key` header gets HTTP 403
  `{"error": "Dashboard key required"}`; the body is the same for every case and never echoes
  any key. The comparison is `hmac.compare_digest` on the UTF-8 bytes. The key is checked after
  the Host/Origin checks (which keep their own 403 messages) and before the request body is read,
  a capability gate runs, or any state is touched. PUT, PATCH and DELETE have no routes; with the
  key they answer 405, without it 403.
- `make_server(dashboard, port, *, dashboard_key)` has no default for the key. `main()` always
  passes a fresh key. `dashboard_key=None` turns the check off and is used only by
  `tests/dashboard_key_harness.py`, which supplies a synthetic key on requests that lack one.
- Limits: anyone holding the printed URL can act as the owner (the terminal scrollback keeps
  it). A process running as the same user that can read the terminal, the browser profile or the
  dashboard's memory is out of scope, and the key is no defence against code running inside the
  dashboard page itself. See [operations](dashboard-operations.md#dashboard-key).

- GET /api/config: returns the nine supported nonsecret fields theme, dashboard_name, logo_path,
  github_username, github_visibility, project_approval_modes, sensitive_review_enabled,
  claude_approval_wait_seconds and observed_port. Legacy files inherit defaults; invalid/unknown
  configuration returns a safe error.
- POST /api/config: exact seven-field validated settings object, plus the optional
  claude_approval_wait_seconds (see "Claude tool-call approvals" below) and observed_port; atomic persistence and returned configuration.
  project_approval_modes maps up to 100 lowercase 32-hex local project IDs to manual or automatic.
  Absent project IDs default to manual. Changes serialize with native automatic decisions;
  enabling automatic mode affects future callbacks, not existing pending requests. Revocation
  invalidates queued eligibility even if the mode is subsequently re-enabled.
  sensitive_review_enabled is a strict boolean enabling explicit local reveal and approval once;
  it never enables automatic approval of sensitive requests. Turning it off revokes sensitive receipts.
- POST /api/logo: {image:base64_plain_png}; bounded upload, returns {logo_path}. Does not activate it.
- GET /api/logo/{sha256}.png: validated, local uploaded PNG only. No arbitrary path/URL lookup.
  Needs the dashboard key like every other API route; the page fetches it and shows a blob URL.
- POST /api/projects/{id}/repository: {owner,name,visibility,confirmed:true}; explicitly create an
  empty GitHub repository only with no existing origin; attach HTTPS origin without pushing.
  Partial attachment failure returns created:true,attached:false with a safe warning.
- GET /api/state: returns connection, projects, tasks, approvals, roles, current question summaries and pricing metadata.
  Each task includes `recovery_available` when its outcome is unknown, recovery state/hold exists,
  or a delegated child is unresolved. `delivery_available` indicates an eligible, policy-bound
  Backend/Frontend task or coordinating task with an implementation child. A terminal parent can
  therefore remain recoverable while a child is unresolved. A project or task whose `provider` is
  not `codex` also carries a `provider` field (for example `claude`); for Codex records the field
  is omitted, so existing snapshots are unchanged. When the deployment has no Codex backend,
  `connection` is `{"status":"disabled","detail":...}` with detail `No provider configured.` (no
  provider). In a `claude` deployment `connection` is `connecting` while the one-time `claude
  --version` probe runs, then `connected` with detail `Claude Code <version> (login not verified)`,
  or `disabled` with a fixed reason (binary not found, or no version reported). A Claude task
  carries `claude: {"denied_count": <int>, "denied_tools": [<up to 20 tool names>]}`, plus
  `hook_denials` (see "Claude tool-call approvals" below) only when it is not empty, and nothing
  else of its internal record (no process id, session id or stream text); its `cost` is
  `{basis:"estimated", unit:"usd-estimate", usd, credits:null, source, pricing_date:null}` once a
  result is seen (`null` before), `usage` has the same five keys as Codex, and `compliance_policy`
  is `{"provider":"claude","ponytail":"not_applicable"}` for a new task (`null` for a task recorded earlier).
  The task also carries `last_summary` and `last_summary_source` (`"model-reported"`; see "Conversations, team
  and recognition"). The internal delegate-omission counter (`claude.delegation_omitted`) is not sent.
- GET /api/provider: returns `{"provider","configured","capabilities"}` for the deployment's
  start-up provider. `provider` is `codex`, `claude` or `none` (no valid provider argument);
  `configured` is `false` only for `none`; `capabilities` holds `provider` again plus
  `guidance_while_running`, `subagent_questions`, `plan`, `recovery`, `assessment` and
  `approval_alternative`, each `yes`, `no` or `unconfirmed`. Codex reports `yes` for all six. The
  Claude backend reports `plan` as `unconfirmed` and the other five as `no`. `none` reports `no` for
  all six. Read-only; the provider cannot be changed through the API (see "Provider-specific
  answers" below).
- GET /api/team/{role_id}/prompt: returns {role_id,prompt} for a known configured agent after
  sensitive-content checks pass. Read-only, on demand; the exact loaded role instructions,
  excluding shared security instructions and task guidance. No arbitrary file lookup, persistence
  or prompt inclusion in state/roster responses. Unknown roles and failed checks return safe errors.
- GET /api/projects/{id}/files: returns {project_id, files:[{path,size}], limit_reached} for
  bounded, Git-visible, nonignored safe source paths in an explicitly registered directory.
- GET /api/projects/{id}/file?path=relative_path: returns {project_id,path,content,line_count,size}
  for bounded UTF-8 source text only after the reviewed secret scanner passes. Never render HTML.
- GET /api/projects/{id}/git: returns local branch/head/origin/upstream/ahead/behind, safe changed
  paths/counts, clean/can_publish and safe reason. Status does not fetch remote state.
- POST /api/projects/{id}/publish: {head,branch,remote,confirmed:true}. Revalidate clean status,
  exact preview-bound snapshot and approved HTTPS GitHub remote. Require full secret checks before a
  normal push of the captured commit. Never stage, commit, force push or bypass hooks implicitly.
  Repository-local or worktree-level `credential.*` configuration (including included config) and
  unsupported transport overrides block publication. Existing global CLI authentication is left
  alone; credentials are neither inspected nor copied.
- POST /api/projects: {name, path}; explicitly register an existing local project directory. The
  database write commits before the project is exposed in the live map; a save failure returns 503
  and leaves no in-memory registration. The response includes `provider` (the active provider,
  always present here, including `codex`). A project registered while no provider is configured
  is recorded under the legacy default `codex`, never `none`.
- POST /api/tasks: {project_id, title, instruction, role}; explicit Start run action creates a
  dashboard task and starts its first Codex turn. The task row commits before it is exposed or a
  worker starts. A save failure returns 503, creates no in-memory task and starts no work. User is
  told this can consume workspace usage and modify registered project files subject to Codex
  approval/sandbox settings. New Codex tasks require the approved Ponytail policy and registered role
  snapshot to pass validation (a Claude task is stamped not applicable instead; see "Ponytail policy and delivery
  readiness"). A policy failure before task creation returns a safe error; a
  mismatch found later in launch blocks the native turn and may leave a recorded failed task.
  Backend/Frontend root and registered child roles receive the policy. Historical tasks are not
  retroactively stamped or automatically subjected to the delivery gate. The response includes
  `provider` (always present here, including `codex`). Under `none` the request is refused with 409; a
  `claude` deployment starts a Claude run instead (see "Provider-specific answers").
- POST /api/tasks/{id}/interrupt: interrupt that dashboard-owned active run. For a Claude run it
  starts the stop ladder (SIGINT, 10 s, SIGTERM to the process group, 5 s, SIGKILL), waits at most
  2 s for the stop to be recorded and answers `{"status":"interrupt_requested","targets":1,
  "unavailable":0}`; the final status `interrupted` arrives later and is set from the dashboard's own
  signal. A Claude task that is not active or has no process answers the generic 400
  (`This run has no active Claude process to interrupt` is the internal message).
- POST /api/tasks/{id}/delete: exact `{expected_version,confirmed:true}` using the current
  64-character lowercase SHA-256 `deletion_version` from GET `/api/state`. Returns
  `{task_id,deleted:true}`. Deletion is allowed for completed, failed, interrupted and unknown
  runs only when the deletion projection reports `can_delete:true`. Queued/running/waiting-approval
  roots, active children/live ownership, pending native requests and in-flight launch, message,
  assessment or recovery work must be stopped/resolved first. For a Claude run that is live or
  waiting for a tool-call approval the answer is 409; after the run is stopped its held request is
  denied, its approval is unavailable and the delete goes through. A Claude task with an active
  delegate is refused like a live run. Deleting a Claude task removes its conversation messages, outputs
  (stored on the task), delegate rows, approvals, delivery operations and session registration, so the
  session id and the project hold are free again; separate check and review runner tasks are separate tasks
  and stay. A task flagged `claude_possibly_running` can be deleted with the normal confirmation; the delete
  drops the project hold and signals no process (owner decision 2026-11-11: warning only, no tombstone hold; see decisions.md). Fake-binary evidence
  only (`tests/test_claude_task_deletion.py`). Historical unknown children and
  delivery-unknown outcomes alone do not prevent deleting the parent. A missing run returns 404;
  a stale version or blocker returns 409; malformed confirmation returns 400; a failed atomic
  storage transaction returns 503 without changing records. Same-origin mutation checks apply.
  The transaction removes the selected dashboard task and its conversations, approval projections,
  child activity, dismissal, recovery/handoff/context and associated operation records. It clears
  the task's local ownership and guards late callbacks from recreating deleted projections. When
  deleting a linked assessment target, the origin recovery record remains but its assessment,
  plan and operation references are invalidated. Linked task rows, project-level check plans,
  recognition records, project files and Codex native history remain. Deletion releases this
  dashboard task's recovery hold; it does not stop native work, establish that it stopped, or undo
  project changes. The caller must show this consequence and require explicit confirmation.
- POST /api/tasks/{id}/dismiss-attention: exact {version}, using the task's attention_version.
  Acknowledges only the current inactive failed/unknown warning; returns task_id,
  attention_version and attention_dismissed:true. Pending decisions and active children block
  dismissal. Changed warnings return 409. Status, task history and native requests are untouched.
  Dismissals persist separately; a new warning version becomes visible again.
- GET /api/approvals/{id}/review: returns complete, bounded, scanner-checked context and an
  opaque review_id for a supported live native request. Supported kinds include command and
  file-change requests, native turn-permission overlays, checked permission-related
  `item/tool/requestUserInput` choices, and the supported subset of `mcpServer/elicitation/request`.
  The dashboard keeps review content in memory, never in state snapshots, SQLite or conversation
  logs. Persisted approval metadata includes an allowlisted native method identifier for
  diagnostics, never request parameters. Codex native history may retain the underlying request
  separately. Responses must not be cached.
- POST /api/approvals/{id}/sensitive-review: exact {confirmed:true}. Only explicit scanner
  findings permit local reveal after full native context/scope validation. Scanner failures,
  unavailable policy, malformed requests and stale ownership remain blocked. Returns the complete
  ephemeral review with sensitive_review:true and a distinct receipt. Accepting it separately
  requires {decision:"accept",review_id,sensitive_confirmed:true}; no project-policy grant can
  use that receipt. The server rescans and checks feature authorization before native acceptance.
- POST /api/approvals/{id}/respond: exact request-kind-specific bodies after explicit human
  review: `{decision:"accept",review_id}` for command/file approvals; the same body for
  permission grants; `{decision:"accept",review_id,answers:{question_id:[answer]}}` for a
  supported permission question; `{decision:"accept",review_id,content:{...}}` for a supported
  MCP form; or `{decision:"accept",review_id,external_completed:true}` for a URL elicitation
  after the human confirms completion of that external step. `{decision:"decline"}` and an
  offered `{decision:"cancel"}` are also supported. Acceptance binds to the exact live request
  and complete reviewed context; a generic summary is insufficient. Permission approval returns
  only the displayed requested overlay with `scope:"turn"`; rejection returns an empty overlay
  with turn scope. Session grants, remembered rules, and arbitrary JSON replies are not available.
  Missing, unsafe, stale or unsupported context blocks acceptance.
  MCP form content is limited to the enforced primitive-property subset (boolean, integer,
  number and string, with supported required fields, bounds and choices); arrays, nested objects,
  secret/write-only fields, semantic string formats and unknown schema keywords remain blocked.
  Extended/OpenAI form variants, user/device verification and other unsupported elicitation modes
  do not receive a dashboard approval affordance. The human must complete device verification in
  Codex. URL requests are not opened automatically; the dashboard sends the native acknowledgement
  only after the human confirms the external step.
  Cancel targets the exact native request and requests interruption of its owning turn;
  a successful write does not establish that the native interruption event has occurred.
- POST /api/approvals/{id}/alternative: {text}, or {text,mode:"cancel"} for an explicitly
  selected cancel flow. Text is checked and bounded to 12,000 characters; blank uses fixed guidance.
  Queue guidance for the exact live turn, then send only its offered negative decision.
  Decline success returns {guidance_sent:true,request_declined:true}. If the original resolves
  after queuing, request_declined is false. Cancel success adds cancel_sent:true; it requests
  interruption and does not prove the turn stopped. Continuation requires an explicit follow-up
  after the native interruption event; never automatically replay the original instruction.
  A rejection leaves the request pending; uncertain delivery invalidates authority without retry.

Errors: JSON {error: safe_message}. Review errors additionally return fixed code, action,
retryable and can_request_alternative fields. No raw exception or request excerpts are returned.
Only scanner-checked visible conversation text is returned
through the conversation endpoint. Raw RPC payloads, stderr, secrets, reasoning and arbitrary
tool transcripts are withheld. No caller-supplied command strings or arbitrary RPC methods.

## Provider-specific answers

One provider is chosen per deployment when the server starts (`--provider codex|claude`, passed
by `scripts/run_dashboard.sh`); a missing or unrecognised value gives `none`. These answers are
fixed strings, never reflected input, and every refused request changes nothing.

- **409 `{"error":"not available for this provider"}`** for a Codex-only route when the active
  provider's matching capability is `no`. The table is `GATED_ROUTES` in `dashboard/server.py`; the
  check runs after the Host/Origin, content-type and size checks and before the body is parsed or
  any state is read. `unconfirmed` and `yes` pass through. The gated route families are:
  - capability `assessment`: GET `/api/recovery-auth`; POST `/api/recovery-auth/start`, `cancel`
    and `sign-out`; POST `/api/tasks/{id}/recovery/assess`; POST
    `/api/tasks/{id}/recovery/handoffs`; POST
    `/api/tasks/{id}/recovery/handoffs/{handoff_id}/responses` and `/accept`.
  - capability `recovery`: GET `/api/tasks/{id}/recovery` and
    `/api/tasks/{id}/recovery/handoffs/{handoff_id}`; POST `/api/tasks/{id}/recovery/check`,
    `plans`, `continue`, `disposition` and `restart-plan`; POST
    `/api/tasks/{id}/recovery/plans/{plan_id}`; POST
    `/api/tasks/{id}/recovery/operations/{operation_id}/cancel`.
  - capability `approval_alternative`: POST `/api/approvals/{id}/alternative`.

  Under `codex` every capability is `yes`, so these routes behave as before. Under `claude` and
  `none` all of them answer 409. This was derived from the route table and is pinned by a
  test that fails when a new recovery or alternative route is added to the handler without a gate.
- **409 `{"error":"recorded under a different provider"}`** when an action targets a run recorded
  under a provider other than the active one (for example a Codex run in a Claude deployment, or the
  reverse). It covers send message, interrupt, approval review (GET `/api/approvals/{id}/review`),
  approval sensitive review, approval respond, approval alternative, question respond, delivery
  checks, delivery review, delivery review decision, and the recovery actions check, assess, plans,
  continue, disposition, restart-plan, operation cancel and handoff create, response and accept.
  Read-only routes and deleting a run are not guarded. Known gap: `GET /api/tasks/{id}/recovery`
  for a run recorded under another provider, in a Codex deployment, can still create a recovery
  row, as the read path did before.
- **The observed routes are the reverse.** GET `/api/observed`, GET `/api/observed/hook-config`, POST
  `/api/observed/rotate-token` and POST `/api/observed/approvals/{id}/allow|deny` exist for Claude deployments only; under
  `codex` and `none` they answer 409 `{"error":"not available for this provider"}` and nothing else (no listener, no
  state read). They are not in `GATED_ROUTES`; see "Observed sessions (Claude deployments only)".
- **409 when no provider can start a run.** POST `/api/tasks` with well-formed fields (a malformed
  body is still rejected with 400 first) answers `{"error":"No provider configured."}` when the provider is
  `none`. In a `claude` deployment the run starts (the Plan 2 refusals "Claude backend is not
  implemented yet." and the interim "Claude runs are not available yet." no longer exist); a delivery operation is started like a Codex one
  (see "Ponytail policy and delivery readiness"), and a deployment whose readiness probe has not succeeded fails the validation check
  "Claude Code is not ready." and answers the generic 400. Any other POST handler that raises the backend's "not available" error answers 409
  with its own fixed message (for the Claude backend's Codex-shaped protocol calls, `This operation
  is not available for the Claude backend.`; otherwise `No provider configured`). Plain validation
  errors stay 400.

## Claude tool-call approvals

Applies to a `claude` deployment (the routes are the existing approval routes; a Codex deployment never
starts the receiver). Evidence: unit and fake-binary tests, plus four live `haiku` runs through the dashboard on 2026-11-02 (approve once,
decline, stop while held, a 305 s wait; one run each, controller-driven in the built-in browser); S10 checked the hook
itself outside the dashboard. Anything beyond those runs is unverified (see `docs/superpowers/evidence/2026-11-01-managed-approvals.md`).

- **Kind and status.** A request from a run's `PermissionRequest` hook becomes an approval of kind
  `tool_call`, `native_method` `PermissionRequest`, summary "A tool call requires approval", scope "This
  one tool call only", status `pending`, `available_decisions` `["decline"]` until it is reviewed. The task
  becomes `waiting_approval`. The record carries no tool name or input. Statuses are `pending`,
  `resolved` and `unavailable` (no `expired` status). `unavailable` has no decisions and a field
  `unavailable_reason`: `expired` (the effective wait elapsed), `connection_closed` (the hook
  connection dropped), `request_ended` (any other end of the hold), `run_ended` (exit, stop, refusal,
  close or turn end) or `dashboard_restarted`. A `resolved` record has `decision`
  `{value, source, at}` with source `human`, `human_sensitive_review` or `project_policy`.
- **Review and respond.** GET `/api/approvals/{id}/review` returns the bounded, secret-scanned context
  `{tool_name, tool_input, agent_type?}` (exactly these keys; any other shape is `unsupported_shape`) and a
  review_id receipt valid for 600 s. POST `/api/approvals/{id}/respond` takes `{decision:"accept",review_id}`
  (plus `sensitive_confirmed:true` after a sensitive review) or `{decision:"decline"}`. Only `accept`
  and `decline` exist for this kind: `cancel` answers `cancel_not_offered`, anything else 400. Accept
  means this one request; two identical requests are two approvals. Authority is consumed before the
  answer is sent; if the hold already ended, the answer is refused with review code
  `request_unavailable` and the held request is denied. Sensitive review (POST
  `/api/approvals/{id}/sensitive-review`) works as for Codex. POST `/api/approvals/{id}/alternative` is
  still 409 "not available for this provider" under Claude.
- **Automatic mode.** `project_approval_modes` applies. For `tool_call` the server queues an automatic
  accept only when the captured `tool_name` equals exactly `Bash`, `Write`, `Edit` or `NotebookEdit`,
  the context is complete and the scanner finds nothing; the answer is one accept with source
  `project_policy`. Other tools, scanner findings and manual projects stay pending. For `Write`, `Edit` and
  `NotebookEdit` the queue also requires the input path (`file_path` or `notebook_path`, realpath with symlinks
  followed, relative paths against the project folder) to lie inside the project's real path with no `.git`,
  `.claude` or `.local` component below it; otherwise the approval stays pending (manual review), never denied.
  `Bash` is name-only and cannot be confined. The final accept repeats the `recovery_manual` check. An accept that
  loses the race with expiry leaves the approval `unavailable` with `unavailable_reason` `expired`. A hook request with
  a different `session_id` and an `agent_id` is denied for that call only and noted as `claude_hook_subagent_session`
  (added to the `hook_denials` codes); without `agent_id` the run is stopped and failed (`claude_session_rejected`).
- **`claude_approval_wait_seconds`.** Integer, default 300, allowed 60 to 3600; a non-integer
  (including a boolean or string) or out-of-range value is refused with 400 "Approval wait must be a whole
  number of seconds from 60 to 3600", never clamped. It is optional on POST `/api/config`: absent keeps the
  stored value. The hook `timeout` in a run's settings file is the wait plus 60, fixed at launch; a run's
  effective wait is the smaller of the current setting and its launch value. Live-checked to about 305 s only (one run).
- **`observed_port`.** Integer, default 47615, allowed 1024 to 65535 (the loopback port of the observed
  sessions listener, which reads it at start-up); a non-integer (including a boolean or string) or
  out-of-range value is refused with 400 "Observed sessions port must be a whole number from 1024 to 65535".
  It is optional on POST `/api/config`: absent keeps the stored value. The per-install token is not a setting
  and is never in this file or in `/api/config`; it lives only in its own 0600 file in a 0700 folder.
- **`hook_denials`.** Under a Claude task's `claude` object, only when non-empty: up to 20 distinct
  `{code, tool_name}` pairs, `code` one of `claude_hook_session_unknown`, `claude_hook_turn_inactive`,
  `claude_hook_limit` and `claude_hook_subagent_session`, `tool_name` matching `[A-Za-z0-9_.:-]{1,64}`. No tool input or token. Denials
  made inside the receiver (caps, bad payload, unknown token) create no record.
- **Receiver (not part of the HTTP API above).** A separate `ThreadingHTTPServer` on `127.0.0.1` with an
  ephemeral port, started on the first Claude launch, serving only `POST /hook/managed/<token>` with a
  per-run token (32 random bytes, constant-time compare). Body at most 256 KiB; 16 pending per run, 64
  in all. Replies are exactly an allow or a deny body (`hookSpecificOutput`, `PermissionRequest`, with a
  fixed message "Declined in the dashboard." for deny); no owner text, request text or error detail
  is returned. Unknown or finished token and unparseable payloads are answered with a deny body (HTTP 200);
  other refusals have an empty 4xx body. A request with `permission_mode` other than `default`, or a
  `session_id` that contradicts the run's, is denied, and the run is stopped and marked failed
  (`claude_permission_mode` or `claude_session_rejected`).
- **Routes.** `GATED_ROUTES` is unchanged: review, sensitive-review and respond are not capability-gated,
  only guarded by "recorded under a different provider"; only `alternative` is gated. A Codex record in
  a Claude deployment, and the reverse, still answers 409 on these routes.
- **Files.** The per-run settings file is `claude-runs/run-<random>.json` in the private state folder
  (folder 0700, file 0600), removed at run end and swept at start-up.

## Observed sessions (Claude deployments only)

Your own Claude Code terminal sessions and the permission requests they send. User-facing description, setup and
limits: [Terminal sessions](dashboard-operations.md#terminal-sessions-observed-claude-code-sessions). Evidence: unit,
fake-binary and journey tests through the real HTTP handler, and one controller browser check on a scratch copy; and, on 2026-11-11, one owner-attended run against a real interactive session (spike S11, partly run); the `{}` no-decision reply was **live-tested once** (case A1).

All four routes need the dashboard key (a missing or wrong key is 403 before any state is touched), carry
`Cache-Control: no-store` like every API response, and answer 409 `not available for this provider` on a Codex or
`none` deployment before any state is read (for a POST, after the usual content-type and size checks).

- **GET `/api/observed`.** `{enabled, reason, port, sessions, approvals, refused, limits}`; never the token.
  - `enabled`: true while the listener runs. `reason`: null when enabled, otherwise one of `port_in_use`,
    `token_unreadable`, `token_permissions`, `listener_error` (any other start failure), `settings_unavailable` (the
    settings file could not be read, which includes a stored port or wait that is out of range, because the settings
    load then raises) and `settings_invalid` (kept for a stored value the load accepted but the listener refused; it
    should not occur in practice). `port`: the bound
    port while running, the port last tried when off, `null` before the listener was started.
  - `sessions`: `[{id, project, first_seen, last_seen, status, subagent_seen_at}]`, newest first. `status` is `active`,
    `quiet` (no event for 30 minutes) or `ended`. `id` is the session id, or an opaque `~` plus 12 hex digits when the
    secret scan refused the real one. `project` is the final segment of the working directory. `subagent_seen_at` is the
    time of the latest subagent event or null; there is no count.
  - `approvals`: cards, newest first: `{id, session_id, project, tool_name, summary, agent_type, status, decided_by,
    decision, outcome, decided_at, expires_at, created_at, warning}`. `status` is `pending`, `answered` (you answered
    here) or `closed`. `decided_by` is `dashboard`, `terminal (inferred)`, `timed out` or `unknown`. `outcome` is `ran`,
    `not run` (shown on the page as "no run seen": nothing matching was seen before `Stop` or `SessionEnd`) or `unknown`.
    `warning` is `ran although denied here` or null. `summary` and the other texts have passed the secret scan; the raw
    tool input is never returned.
  - `refused`: requests left to the terminal because a cap was reached. `limits`: `{max_sessions: 256, max_pending: 32,
    quiet_seconds: 1800}`. Finished cards are capped at 64 and the request body at 256 KiB.
- **GET `/api/observed/hook-config`.** The only response that carries the token. 200 `{url, snippet, note}`: `url` is
  `http://127.0.0.1:<port>/hook/observed/<REDACTED>` with the real token in place of the placeholder; `snippet` is the
  `hooks` block with one `http` hook entry for each of `PermissionRequest`, `PostToolUse`, `Stop`, `SessionEnd`,
  `SubagentStart`, `SubagentStop` and `SessionStart`, each with `timeout` equal to the approval wait plus 60; `note` is the
  fixed paste note (port and wait changes apply after a restart; rotate and paste again; remove the hooks when the
  dashboard is not in use; where to paste it). The page fetches it only when you open the snippet panel. 409 when the
  listener is off: `{error, reason}` with the reason above, or "The observed sessions token is unavailable" with
  `token_unreadable` or `token_permissions`.
- **POST `/api/observed/rotate-token`.** Body `{}`. 200 `{rotated: true}`. The new token is not returned: fetch
  `hook-config` again. New requests with the old token are refused at once; requests already waiting finish. 409 when the
  token file cannot be used. It works while the listener is off.
- **POST `/api/observed/approvals/<id>/allow`** and **`/deny`**. Body `{}`. 200 `{result: "ok"}` when the held request
  was answered with that decision; 409 `{result: "closed"}` when the card is no longer pending (expired, closed,
  settled by inference or already answered); 404 `{result: "unknown"}` for an id that is not a card. An allow or deny
  from the owner is the only thing that produces an allow or deny reply to Claude Code.
- **`observed_port`** is a setting on `/api/config` (default 47615, 1024 to 65535); see "Claude tool-call approvals"
  above. It applies when the dashboard restarts; the settings are read once at start-up. A port in use leaves the listener
  off with reason `port_in_use`; no other port is tried.
- **Listener (not part of the HTTP API above).** A second `ThreadingHTTPServer` on `127.0.0.1` only, on the fixed port,
  serving only `POST /hook/observed/<token>`, with one per-install token (32 random bytes, constant-time compare) in a
  0600 file in a 0700 folder in the user config directory (`~/Library/Application Support/KT Agent Dashboard` on macOS,
  otherwise `$XDG_CONFIG_HOME` or `~/.config` plus `kt-agent-dashboard`), never in logs. Replies: an allow or deny body only
  for the owner's decision. The ordinary endings are HTTP 200 with `{}` (no decision): expiry, stop, the 32-pending cap, a
  payload or unknown event that cannot be parsed after authentication, a card settled by inference, and an event from a
  dashboard-managed session (no card, no record). **Not every ending replies:** the 64-unheld-connection cap and the 10
  second read deadline drop the connection without a reply, and what Claude Code does then is untested (S11 D1). A wrong method, content type, size or token gets an empty 4xx body without the payload
  being read further. The `{}` reply was live-tested once (S11 A1) and the dashboard-down ending once (S11 D4, owner-reported); the connection-drop, 413/415 and two-hook-merge endings are untested (S11). Events are `PermissionRequest`, `PostToolUse`, `Stop`, `SessionEnd`,
  `SubagentStart`, `SubagentStop` and `SessionStart` (the last was not delivered over `http` in S7).
- **Inference.** The tool outcome of a card answered in the terminal is inferred, never reported: a later
  `PostToolUse` of the same session and agent with the same `tool_name` and an equal `tool_input` gives `ran` (and, after
  an owner Deny, the warning); `Stop` or `SessionEnd` without a match gives `not run`; a `PostToolUse` without
  `tool_input` keeps the outcome `unknown`; a `PostToolUse` for a different call changes nothing. `SessionEnd` settles
  every card of that session. The real `PostToolUse` and `Stop` payloads were seen in S11 (`PostToolUse` has `tool_input` and `tool_use_id`); a terminal No sends no later event.
- **Managed sessions.** The listener asks the dashboard whether a session id belongs to a dashboard-managed run; if so it
  replies `{}` with no card, record or hold. The check fails closed: an error, or the dashboard lock staying busy for over
  a second, counts as managed, so under a busy dashboard the owner's own events can be dropped (a card may then end
  "timed out"). A managed run's `SessionStart` arriving before its session id is registered can leave a stray quiet
  observed row. A managed session resumed in a terminal is ignored.
- **Stored.** SQLite kind `observed_session`: id, project, first and last seen, status, subagent time. Cards and request
  payloads are in memory only.

## Ponytail policy and delivery readiness

The first two paragraphs and the endpoint list describe a Codex deployment; the Claude differences are in "Claude delivery readiness" at the end of this section.

The dashboard enforces an approved `ponytail:ponytail` Full policy for newly started managed
tasks. Backend and Frontend role instructions, including registered child-role snapshots, include
the policy text. The current pin is version `5.3.2`, SHA-256
`9badd22a32e19cb884e46dfa8d3aae82bb81dfa5484105b8b4f0262df823a509`. The app resolves this
approved installation under the current user's Codex plugin cache; clients cannot supply a
different path, policy digest or version. The loader accepts only an owned, single-link regular
file up to 32 KiB, opens the source without following symbolic links, checks that it did not
change while being read, verifies the SHA-256 and runs the reviewed secret scanner. The app
fingerprints registered role snapshots and rechecks policy and fingerprint before native dispatch.
A missing, changed or unverified policy blocks dispatch; reviewed policy/profile updates require
an idle dashboard reload. Historical tasks without policy metadata are not retroactively stamped
or automatically enforced.

Delivery readiness is a separate projection. A completed implementation remains `completed`;
readiness does not change its task status, publish code, approve a native request or grant release
approval. It is available for eligible policy-bound Backend/Frontend work or a coordinating task
with an observed direct implementation child. An unknown or unattributed child, active work,
recovery hold, missing current policy or incomplete current snapshot prevents a ready result.

- GET `/api/projects/{id}/check-plan`: returns the project's plan
  `{project_id,version,commands,approved_at}`.
- POST `/api/projects/{id}/check-plan`: exact
  `{expected_version,commands,confirmed:true}`. Provide 1–8 distinct, single-line commands, each
  at most 2,000 characters and 8,000 characters total. Commands are scanned and stored exactly;
  they cannot be changed while work for that project is active. A changed plan increments its
  version and invalidates delivery review receipts.
- GET `/api/tasks/{id}/delivery`: returns snapshot and policy digests, plan version, check/review
  operation summaries, reason codes and action availability. States include `not_enforced`,
  `unverified`, `awaiting_checks`, `checks_running`, `checks_failed`, `awaiting_review`,
  `review_running`, `changes_requested`, `stale` and `ready`. `ready` requires every approved check
  to have an exact successful native command event, a separate complete review, and explicit
  current human acceptance.
- POST `/api/tasks/{id}/delivery/checks`: exact
  `{expected_snapshot,expected_plan_version,operation_id,confirmed:true}`. Starts a separate
  managed `qa_engineer` task to run the approved commands from the registered project root using
  normal Codex sandbox and approval controls. Only the exact approved command in the current owned
  turn and working directory, with a completed event and exit code zero, counts as passed. An
  exact approved command may be reported directly or through the supported `/bin/zsh`, `/bin/bash`
  or `/bin/sh` `-lc` wrapper; other command text does not count.
- POST `/api/tasks/{id}/delivery/reviews`: exact
  `{expected_snapshot,check_operation_id,operation_id,confirmed:true}`. Starts a separate
  `code_quality_reviewer` task after every required check passes. It is instructed to inspect the
  current project changes and agreed task outcome, and not to edit or delegate.
- GET `/api/tasks/{id}/delivery/reviews/{review_id}`: returns the current, scanner-checked review
  messages and a single-use `receipt_id` bound to the review and snapshot. The receipt expires
  after 60 seconds.
- POST `/api/tasks/{id}/delivery/review-decision`: exact
  `{review_id,receipt_id,review_digest,expected_snapshot,decision,confirmed:true}`, where decision
  is `accept` or `reject`. The decision binds to the current reviewed messages, snapshot and
  single-use receipt. A saved acceptance may report `ready`; rejection reports `changes_requested`.

The current code snapshot hashes the registered root identity, HEAD, and Git-visible tracked and
non-ignored untracked files, including opaque assets and file modes. Tracked files remain included
even if ignored; ignored untracked files are excluded. Coverage is bounded to 5,000 candidates,
1,000 files, 256 KiB per file and 16 MiB total. The reviewed scanner sees the file bytes, but the
digest does not semantically review opaque assets for visual correctness or secret meaning. File
identity, file set and HEAD are rechecked after scanning. Unsupported paths, symbolic or hard
links, non-regular files, scanner failures or exceeded bounds make the snapshot unavailable. A
changed code snapshot, task, plan, policy/role fingerprint or App Server connection makes evidence
stale; rerun checks and review on the current state.

For check/review task creation, `not_started:true` means preflight failed before the new task and
operation were published. After correcting that failure, a new explicit attempt uses a fresh
operation ID. If dispatch may have started or the response was lost, reconcile the existing
operation; **Retry original request** sends only the exact frozen body and operation ID, allowing
the server to return its existing operation or reject a stale action. It never retries
automatically or creates a different request.

Review-decision receipts are single-use and are consumed before saving the decision. A successful
save persists a decision acknowledgement that a refresh can reconcile. If persistence fails, the
API returns 503, readiness remains unverified and the receipt cannot authorize another decision.
Repair storage, refresh checks as needed, read the current review again to obtain a new receipt,
then make a fresh explicit decision. Do not repeat the consumed decision receipt.
Operational steps and the current validation boundary are in [dashboard operations](dashboard-operations.md#delivery-checks-and-readiness).

### Claude delivery readiness

Evidence kind: fake-binary tests only (`tests/test_claude_delivery.py`, `tests/test_claude_slice2b_journey.py`);
no live delivery run.

- **Not-applicable stamp.** In a Claude deployment the policy source is a fixed not-applicable policy: it reads
  nothing and returns `{"provider":"claude","ponytail":"not_applicable"}` (no version, digest or text). A new
  Claude task is stamped with that as `compliance_policy` and with `compliance_role_digest`, a digest of the role
  record passed to `--agents`. Claude tasks recorded before this have no stamp and stay `not_enforced`. A
  Codex-shaped policy injected into a Claude deployment is ignored.
- **`ponytail` field.** `GET /api/tasks/{id}/delivery` for a Claude task carries `"ponytail":"not_applicable"`;
  Codex results have no such key. No gate counts it, so it is never a pass: `ready` is computed from the
  other gates only (current snapshot, finished children, approved checks all passed, complete review,
  explicit acceptance).
- **Binding and `policy_binding_changed`.** Before the other gates, a Claude subject is accepted only if the
  subject provider and the deployment are both Claude, the stamp equals the not-applicable metadata and the role
  digest equals the current one; otherwise the status is `unverified` with reason code `policy_binding_changed`.
  A forged Ponytail-shaped stamp, a Claude task in a Codex deployment and a Codex task in a Claude deployment are all refused.
- **Children.** For a Claude subject a child row clears the gate only if it is finished and its stop was reported
  in the stream (`stop_observed` true on the row). A child that was finished only because its parent turn ended
  (`stop_observed` false or missing) does not clear it, a finished child with no role clears it only under that
  condition, and an active, unknown or unregistered-role child, or any omitted delegate (an internal counter
  above 0), keeps the status `unverified`. For a Claude check or review run, any child row of any role or status
  keeps the gate not clear, and a checks run with a child fails. Delivery is available for any Claude run that
  has an unnamed delegate, not only Backend and Frontend runs, so a non-developer role's run that used a built-in
  helper can read `unverified` (fail safe). `stop_observed` fails closed until the live run shows how the real
  CLI reports a stop. Codex rows have no such key and keep the Codex rule. Fake-binary and unit evidence only.
- **Starting runs.** POST `delivery/checks` and `delivery/reviews` start a `qa_engineer` or
  `code_quality_reviewer` Claude run in the subject's project, with the same request bodies, `not_started`
  rule and operation ids as Codex. A follow-up message to any delivery run is refused (400). Before the run
  starts, the subject stamp, plan version, connection generation, children and snapshot are checked again;
  any failure fails the launch with no process. For a Claude subject the connection generation is a digest of the
  process epoch, the backend and the probed Claude version, and "connected" means the Claude readiness probe
  succeeded; a changed Claude version makes earlier evidence stale.
- **Checks evidence.** The stream parser reads the main session's tool calls in a checks run (subagent lines are
  ignored, so a call made by a subagent is simply not evidence; a child of the run fails the checks, see
  Children). A main-session tool call other than `Bash`, `Read`, `Grep` or `Glob` is reported as an unmatched
  check call and fails the operation, so a `Write` followed by an approved command and an `Edit` that restores
  the file fails. A command passes only if it is a plain foreground `Bash` call (input keys limited to
  `command`, `description`, `timeout`, `run_in_background`; `run_in_background` absent or false), its command text
  equals an approved command exactly, and its result has `is_error` exactly false, no `non_execution_kind` meta,
  and no failure marker: the first line of the first text must not contain "Exit code" or start with "Error",
  and no text may start with "Command running in background" or the `tool_use_result` carry a key containing
  "background" with a truthy value. Any other `Bash` call (different command, chained or padded text, a shell
  wrapper, a background call, an unmatched or replayed id) sets the operation failed, as does a failure later
  followed by a pass for the same call. After a checks run exits, the server re-checks the project snapshot
  and any change fails the operation with `snapshot_changed`, even if the files were restored. The snapshot is `git ls-files --cached --others --exclude-standard`, so ignored files and `.git` internals are outside it: a change to an ignored file, or a tracked file changed and restored without its tool call being seen, is not detected. A checks run also fails when any stream line could not be read in full (a line over 1 MiB whatever it held, a truncated or capped reply, a runner overflow, a missing drop counter) and when a failing event arrives after the run's result or on another turn (a late passing event never counts). Reply text has zero-width characters, the bidi marks U+200E, U+200F and U+061C and the separators U+2028 and U+2029 removed before the content scan, in addition to control and bidi override characters. Claude reports no
  working directory per command, so this is stricter than Codex. Command text never leaves the parser. Delivery
  runs are never made eligible for automatic approval, whatever the project's approval mode. Unverified live:
  whether the real CLI sets `is_error` for a non-zero exit and the exact background marker shape. A checks runner is started with `--disallowedTools Write,Edit,NotebookEdit` as the last arguments (checks runs only; every other run is unchanged, and the guard above and the project-change check stay). In one direct CLI run (2.1.322, 2026-11-11) the three tools were absent from the tool list; not tested inside a dashboard-managed run.
- **Review evidence.** The reviewer's main-session replies are the review messages (message sender equals the task's
  session id and turn equals its turn id). The operation records `replies_dropped` (a reply cut at a size bound,
  past the 50-block or 64 KiB per-line reply caps, a line over 1 MiB, a runner overflow or a missing counter, all
  counted fail closed) and `replies_withheld` (a reply that failed the sensitive-content checks). A dropped reply
  leaves the status `unverified` with reason code `complete_review_messages_required`. A withheld reply fails the
  review operation, so the status is `changes_requested` with reason code `independent_review_required`. Either way
  no decision action is offered. Codex operations never carry these keys. Fake-binary and unit evidence only.

## Recovery and assessment API

The audit-remediation changes and the loaded-thread metadata fix were applied locally by graceful
restart on 25 October 2026. The service reconnected with 10 task records, including two unknown
tasks, zero active runs and zero pending decisions. An earlier live check failed because the App
Server's `thread/backgroundTerminals/list` only supports loaded threads; that failure preserved
partial child evidence and did not grant clearance. After the fix, a live metadata-only check
completed in about 0.2 seconds and reported 38 children, zero unresolved children, and observations
for the root and current loaded inventory. It also retained `boot_fence_required`,
`historical_descendant_unresolved`, and `unreconciled_turn`; execution clearance stayed unverified
and continuation unavailable. The count is the result of that check, not a guarantee that future
checks will find the same inventory. No task was resumed and no inference or native continuation
was started.

Assessment handoff is a local, human-mediated feature. It prepares checked evidence for the user
to copy into an existing approved chat, accepts a pasted response as unverified human-supplied
text, and records a separate local acceptance decision. It does not authenticate to or send messages
to that chat, verify its source/model/tools/usage, create a Codex task or turn, or continue the prior
turn. The user must separately review and approve any development continuation under the existing
native safety gates. Same-thread restoration remains disabled. See [dashboard operations](dashboard-operations.md#assessment-handoff).

Handoff endpoints are relative to `/api/tasks/{origin_id}/recovery`. Existing loopback, Host/Origin,
JSON Content-Type, 65,536-byte request, safe-error and no-store controls apply. IDs are
server-assigned lowercase 32-hex values; digests are SHA-256. `expected_revision` is the current
recovery revision; `expected_handoff_version` is the current handoff version.

- POST `/api/tasks/{id}/recovery/handoffs`: exact
  `{expected_revision,operation_id,selected_message_ids,text,confirmed:true}`. Creates a new
  evidence round from up to 20 explicitly selected available messages, checked observations and a
  fresh question (up to 12,000 characters). It returns the authoritative recovery projection.
- GET `/api/tasks/{id}/recovery/handoffs/{handoff_id}`: returns the exact packet preview and, when
  present, the exact returned-response preview. It never accepts a response. The browser fetches a
  fresh preview before **Copy checked packet**; clipboard content is exactly `packet_text`.
- POST `/api/tasks/{id}/recovery/handoffs/{handoff_id}/responses`: exact
  `{expected_revision,operation_id,packet_digest,expected_handoff_version,text,confirmed:true}`.
  Scans the complete raw pasted text (maximum 16,000 characters) before saving. A new response
  supersedes the prior response and revokes any earlier acceptance and plan.
- POST `/api/tasks/{id}/recovery/handoffs/{handoff_id}/accept`: exact
  `{expected_revision,operation_id,packet_digest,expected_handoff_version,response_id,response_digest,response_version,review_id,confirmed:true}`.
  Requires the current preview receipt, exact packet/response bindings, a current semantic snapshot,
  scanner success and explicit human review. It records local acceptance and invalidates any older
  plan; it does not approve a plan or authorize native execution.

Each POST returns the current recovery projection. The browser then reloads the GET preview to
obtain current body/review fields and uses the returned revision and handoff version for the next
mutation. Preview contains `task_id`, `handoff_id`, `version`, `packet_text`, `packet_digest`,
`snapshot_digest`, `stale`, and optionally `response` with its ID, version, digest, text, status and
short-lived `review_id`. Recovery state exposes bounded handoff metadata and action/capability
booleans, but excludes packet and response bodies. The normalized assessment summary uses
`source:"handoff"`; its assessment/task ID is an opaque alias and does not identify a task that can
be opened in `/api/tasks` or `/conversation`. Only an accepted current response with a matching
snapshot is `reviewable`. Handoff data is not attributed to a verified agent and has no observed
usage or cost.

The complete packet is limited to 49,152 UTF-8 bytes and scanned as a whole. Oversized content is
rejected without truncation. Raw response text is scanned before normalization, persistence or
display; all previews rescan packet and response. Scanner failure withholds text and blocks
acceptance while retaining history. Packets exclude credentials, raw native transcripts/errors/tool
output/reasoning, absolute local paths, prompts, unrelated task messages and sensitive-reveal
content. At most 8 rounds per origin and 128 handoffs total are retained; each handoff allows up to
16 responses and 64 idempotency operations. Records are stored in the local `recovery_handoff` row
with immutable packet/response/acceptance/operation history. There is no silent eviction; capacity
exhaustion returns a safe error.

Packets have no short time-based expiry. A material change to the task, messages, project binding or
checked activity makes the packet stale. Refreshes, backend restart and checked hold transfer alone
do not. A stale response cannot be newly imported or accepted; an already stored stale response is
history-only. A new packet round supersedes prior acceptance and invalidates its plan. Response
review receipts are single-use, in-memory and expire after 60 seconds; GET preview renews one.
Restart clears receipts but retains scanned packet/response and acceptance records. Current accepted
evidence may remain reviewable after restart, while native execution still requires fresh checks and
a separate human decision. Handoff preparation and response review can work while Codex is offline
or a registered folder is missing/replaced, using only checked stored evidence and safe registry
metadata. They do not read replacement files or clear activity holds. Development planning and
continuation still require strict project identity and fresh native checks.

Operation IDs deduplicate only the same origin and exact payload; changed payload or origin returns
409. Stale revisions, changed versions, scanner failures and ineligible actions cannot authorize a
mutation. After uncertain delivery, the browser retains the frozen exact request; only an explicit
**Reconcile previous handoff action** click may repeat that same request to resolve its outcome.
It blocks other mutations and continuation while pending, preserves edited drafts, and does not
automatically resend. A definite rejection clears the pending request so the user can refresh and
make a new decision with a fresh operation ID. Pasted content is plain text and never executes
Markdown/HTML or model-supplied links.

The optional direct OAuth assessment route remains separate from handoff and is not required for
it. It uses the built-in ChatGPT sign-in flow and text-only inference; its endpoints and usage
behavior are described below. No API-key fallback is implemented.

- GET /api/recovery-auth: returns `state`, `authenticated`, `plan_enabled`, `generation`,
  `error_code`, and `remote_revocation_confirmed`. States include `signed_out`, `signing_in`,
  `authenticated`, `plan_unavailable`, `error`, and `dependency_unavailable`. It never returns
  registration identifiers or tokens. During sign-in, the start response may also contain an
  `authorization_url` and `expires_in`.
- POST /api/recovery-auth/start, `/cancel`, `/sign-out`: exact empty JSON object `{}`. Start
  begins the built-in ChatGPT OAuth flow and a short-lived loopback callback. Cancel stops the
  pending sign-in; sign-out clears local in-memory authentication and attempts remote revocation.
  Neither action changes Codex CLI sign-in. `remote_revocation_confirmed` can be false or unknown;
  sign-out does not assert remote revocation when it cannot confirm it.
- GET /api/tasks/{id}/recovery: returns the recovery record, bounded observations, reason codes,
  capability booleans, action availability, current assessment/plan/operation summaries, bounded
  handoff metadata, and, when current, an opaque `receipt_id`. Treat `execution_clearance: unverified`
  as not cleared. A native execution receipt expires after one minute or when its source state
  changes; refresh with a check before acting. Recovery is available for unknown roots and for
  terminal parents with unresolved delegated activity or a persisted recovery hold; the parent's
  recorded task status is preserved.
- POST /api/tasks/{id}/recovery/check: exact `{expected_revision}`. Reads bounded native task and
  activity metadata when the App Server is reachable and the registered directory identity is
  available; it does not restart or replay work. If native transport is offline, task history is
  missing, or the registered directory is unavailable/replaced, the response records the safe
  reason and leaves execution clearance unverified. A checked local packet can still support a
  separate assessment in those cases; this does not read the missing/replaced directory or clear
  the hold. Descendant discovery uses cursor pages of up to 100 rows, with a maximum of 8 pages
  and 512 reported rows per check, 256 unique descendants and 4,096 characters per cursor. A
  shared 12-second deadline covers root and child metadata checks. The check verifies child status,
  goals, background terminals and lineage. The App Server documents
  `thread/backgroundTerminals/list` as available for loaded threads only; for a `notLoaded` thread,
  the dashboard checks its goal and relies on a fresh complete loaded-thread inventory on the same
  connection to confirm that it is currently not loaded. It records this as
  `current_loaded_inventory: current_not_loaded`; it does not treat a rejected background-list
  request as evidence of inactivity. The inventory must be complete, current and free of conflicting
  loaded threads. Missing, repeated, malformed or over-limit data, or a failed metadata request,
  leaves coverage incomplete and execution clearance `unverified`; already collected root and
  child observations remain available with fixed diagnostic codes. A failed stage is reported with
  a bounded code such as `background_list_failed`; native rejection details are reduced to fixed
  `native_*` codes, and raw App Server error text is withheld. Partial enumeration never establishes
  safety. Directory identity, boot/exclusive-owner checks, external-activity checks, and fresh
  complete native checks remain mandatory for any development plan or continuation.
- POST /api/tasks/{id}/recovery/assess: exact
  `{receipt_id,operation_id,selected_message_ids,text,confirmed:true}`. Uses only the explicitly
  selected available conversation messages and checked recovery observations plus the new human
  question. Starting an assessment consumes the signed-in ChatGPT plan's usage. Authentication
  changes cancel an active assessment; nothing is replayed automatically. An uncertain dispatch
  must be treated as unresolved and must not be retried with the same operation.
- POST /api/tasks/{id}/recovery/plans: exact
  `{expected_revision,assessment_task_id,instruction,target_strategy,role}`. POST to
  `/api/tasks/{id}/recovery/plans/{plan_id}` instead requires `expected_plan_version` in place of
  `assessment_task_id`. These record or revise a proposed plan after a completed, checked
  assessment. They do not dispatch a development turn.
- POST /api/tasks/{id}/recovery/continue: exact
  `{receipt_id,operation_id,assessment_task_id,plan_id,plan_digest,confirmed:true}`. Requires a
  fresh native metadata/ownership check, quiescent execution clearance, a current reviewed plan,
  and a proven available target capability. Source currently rejects same-thread continuation.
  Successful acceptance starts a separate linked development task; it does not restore the old
  turn, replay its prompt, or restore approvals.
- POST /api/tasks/{id}/recovery/disposition: exact
  `{expected_revision,disposition,note,confirmed:true}`, where disposition is `reviewed`,
  `needs_investigation`, or `abandoned`. Records a human annotation only.
- POST /api/tasks/{id}/recovery/restart-plan: exact `{expected_revision,confirmed:true}`. Records
  a proposed reboot fence when a trusted boot identity exists; it does not reboot the machine.
- POST /api/tasks/{id}/recovery/operations/{operation_id}/cancel: exact
  `{expected_revision,confirmed:true}`. Cancels before dispatch when that is proven; after dispatch
  it requests a stop and reports it pending until the assessment or native terminal state is
  observed. The request acknowledgement alone is not proof of stop. Uncertain delivery is not
  retried through this route.

The above mutations use normal same-origin checks, bounded JSON, exact fields and revision checks.
Errors are JSON with a safe message. A stale revision/receipt, ineligible capability or unresolved
operation cannot authorize a new assessment or continuation dispatch; cancellation follows the
stop-request semantics above. Exact current UI/source behavior and remaining operational limits are
described in [dashboard operations](dashboard-operations.md).

## State projection

- connection: {status: connected|connecting|disconnected|disabled, detail, last_event_at, server_version}.
  `disabled` is reported when the deployment has no Codex backend (`claude` or no provider); the
  dashboard then starts no connection attempt.
- projects: [{id, name, path, created_at}], plus `provider` when it is not `codex`. Only explicitly
  registered projects; no machine scan.
- roles: [{id, label, model, profile_model, reasoning}]. Role instructions/effort derive from
  approved profiles; model and profile_model retain the approved profile's native model ID.
- tasks: [{id, project_id, title, role, model, reasoning, status, thread_id, turn_id,
  plan: [{step, status}], blocker, created_at, updated_at, error, diagnostics, usage, cost,
  recovery_available, delivery_available, can_delete, deletion_blocker, deletion_version}], plus
  `provider` when it is not `codex`.
  Deletion eligibility and its version are
  recomputed from current child, ownership, request, recovery and operation state; clients must
  use the current version and still handle a 409 when state changes before confirmation.
  diagnostics is a bounded list of {at,stage,code,message,action}, generated from local constants.
  permission_profile records the unique native profile used for this task, once acknowledged.
  Plan text is deliberately ordinal-only: model-authored content is not persisted or rendered.
  blocker is a safe runtime-derived explanation or null; it is not an inferred business blocker.
- delegated_activities: [{id,parent_task_id,project_id,thread_id,parent_thread_id,role,title,
  status,created_at,updated_at}]. Observed known-role specialist work, separate from root tasks
  and their costs. `parent_task_id` identifies the coordinating dashboard task; verified
  `parent_thread_id` identifies the immediate delegating agent. Legacy records may lack thread
  lineage. Titles are generated role labels, not assignment prompts. Raw prompts, tool output,
  reasoning and result summaries are excluded from this projection. Child approval/question
  status is scoped to the actual requesting thread; disconnect/restart makes active work unknown.
- status: queued|running|waiting_approval|completed|failed|interrupted|unknown.
  Completed means model turn completed, not independently accepted or released.
- usage: null until observed, otherwise {input_tokens, cached_input_tokens, output_tokens,
  reasoning_output_tokens, total_tokens}. Use observed counters; avoid double-counting repeated
  cumulative notifications. Configured model is distinct from observed reroutes.
  Usage/estimates cover the matching dashboard-owned main thread only. Child-agent counters
  are not aggregated or verified; this is incomplete coverage of delegated execution cost.
- cost: {basis: estimated|unknown, credits: number|null, source, pricing_date}. Standard-speed
  credit estimate only, not a verified charge or invoice. No USD conversion. Only estimate
  when usage, actual model and supported service-tier basis are known; unknown otherwise.
- approvals: [{id, task_id, kind, native_method, summary, reason, scope, requester,
  status: pending|resolved|unavailable, created_at, available_decisions, can_request_alternative,
  resolution_mode, review_failure?, decision?, unavailable_reason?}]. `kind` includes command, file_change,
  permissions, approval_question, elicitation, unsupported_input and, for Claude, tool_call
  (`unavailable_reason` is set on Claude `tool_call` records only). `native_method` is an
  allowlisted App Server method name; unknown methods are represented as `unsupported`.
  review_failure contains fixed code/message/action/retryable/at. decision contains value/source/at;
  sources distinguish human, human_guidance and project_policy. Sanitized summaries, no raw command/tool bodies. Request IDs
  are opaque local identifiers; backend alone maps them to RPC request IDs. Unsupported input
  requests display an explanation and offer available stop/close actions rather than accepting
  implicitly. Pending reviews require current live ownership and are unavailable after restart.
- Claude `cost.unit` is `usd-estimate`: Claude Code's own list-price estimate in US dollars, not a
  billed amount. In a `claude` deployment `pricing` is `{unit:"usd-estimate", source, speed_basis}`
  (no pricing date); in a Codex deployment it is the credits object below.
- diagnostics codes for Claude runs: `claude_api_error`, `claude_not_logged_in`,
  `claude_model_unavailable`, `claude_aborted`, `claude_exit_nonzero`, `claude_no_result`,
  `claude_permission_mode`, `claude_output_too_large`, `claude_launch_invalid`,
  `claude_session_rejected`, `claude_calls_denied` (a notice; the run's status is unchanged),
  `claude_restart_unknown`, `claude_possibly_running` and the notices `claude_hook_session_unknown`,
  `claude_hook_turn_inactive`, `claude_hook_limit` and `claude_hook_subagent_session` (one per run and code). Message and action are fixed local text.
- pricing: source URL, pricing date, speed basis, and unit. Rates must not be presented as the
  customer's verified billing agreement. Unknown data never becomes a zero charge.

Frontend polls GET /api/state every few seconds while visible, preserving data with an explicit
stale warning on errors. UI filters state consistently by project; no simulated records.

## Runtime lifecycle

App Server subprocess uses fixed argv, JSONL stdio, no shell. Initialize once and acknowledge.
Use stable protocol verified against the installed CLI's generated schema. Enable inference
only through explicit user Start run, follow-up or guidance. Sandbox/approval configuration must retain local user
controls; use on-request/user review and a unique named permission profile with project-only
workspace writes and network disabled. Validate the acknowledged profile, roots, temp exclusions,
network and approvals before turn/start. Follow-up turns retain that profile. Preserve the original
workspace-write boundary: broad filesystem reads, project-only writes, no network and user approvals.
The credential-read prohibition is agent policy, not filesystem isolation. The current Mac's
restricted-read helper fails to initialize; this version does not claim restricted filesystem reads.
Restrict working directories to registered projects.

Recovery uses only six read-only metadata methods with exact parameter shapes:
`thread/read`, `thread/list`, `thread/turns/list`, `thread/goal/get`,
`thread/backgroundTerminals/list` and `thread/loaded/list`. There is no arbitrary RPC path.
A metadata response timeout reports incomplete evidence without closing the shared App Server or
interrupting unrelated work. Mutation timeouts, IPC write failures, EOF and malformed protocol
remain fatal to that connection and leave execution state unknown; uncertain work is never replayed
automatically.

The dashboard persists projections and checked visible conversation messages only. New user instructions,
replies and completed agent text may be retained locally after content checks; raw RPC traffic,
tool transcripts and reasoning are excluded. Runtime database stays in ignored .local/ with restrictive
permissions. Never read auth stores or Codex transcript/session files. Codex handles its own
authentication. Startup/reconnect never replays inference or approvals. Disconnect makes pending
requests unavailable and active tasks unknown rather than showing stale actionable controls.

Managed runs use `thread/start` with `ephemeral:false`, verified in the native acknowledgement.
Codex stores its own native local history outside the repository; it may include prompts,
commands, approval details and tool output. The dashboard scanner does not cover that store.
The dashboard never reads it and does not automatically resume tasks after restart. Team roles
are registered explicitly through the per-thread `agents` config for every managed project.
Private process-lifetime role snapshots contain only scanned static model/effort/instructions,
including the shared security baseline. No permission overrides are supplied by those snapshots.
They are removed after App Server closes; saved history does not imply supported CLI resumption
with those temporary paths.

Readiness requires actual App Server handshake and independent protocol tests with fake events;
no paid model task should be launched by automated tests without separate authorization.

## Manual project review and publishing

File review is read-only and requires a Git working tree. Credential/runtime/build files,
ignored paths (including forced-tracked ignored paths), symlinks/hardlinks, traversal, binary
files and oversized text are unavailable. Scanner absence/failure also blocks previews. Neither
file bodies nor scanner output are persisted in the dashboard database or logs.

File/Git operations do not require a Codex connection. They remain same-origin and restricted
to registered project roots. Publishing is blocked while an overlapping managed run is active.
Confirmation shows the exact repository, branch and commit; snapshot changes require review
again. Git authentication remains CLI-owned; the dashboard never asks for credentials or copies
tokens. Read-only Git operations disable filesystem-monitor hooks and bounded publication
keeps ordinary push hooks enabled. Secret-bearing remote URLs are never exposed to the browser.
Repository creation and publication inspect repository-local and worktree-level `credential.*`
settings, including applicable include files; configured credentials at those scopes block the
action. Global CLI-owned credential helpers remain allowed. The dashboard does not inspect the
credential store or copy authentication material.

The human requested the public repository K55Toms/KT_Agent_Dev_and_Dash. It was created empty
and connected as origin; public visibility, secret scanning and push protection were verified
through repository metadata. Code has not been pushed by this implementation work.

## Conversations, team and recognition

- GET /api/team: configured fictional crew, observed latest role task, symbolic coin totals,
  current weekly badge and recorded commendations. Empty history is not seeded. In a Claude deployment
  the response has `rewards:false`, an empty `awards` list and no `coins` or `agent_of_week` on members, and
  lists only Claude tasks and their delegates. A Claude task's `last_task.last_summary` is the stored
  main-session reply of its latest turn, at most 500 characters (ending in an ellipsis when cut), with
  `last_summary_source:"model-reported"`; a new turn clears it, and a withheld or other-turn reply never sets it.
  A Claude delegate whose type is not a registered role has `role:null` and is listed under the parent task's role
  with `unnamed_delegate:true`. Fake-binary evidence only.
  Each member also has `activities`, with allowlisted direct/delegated activity fields and
  `source:direct|delegated`. Team activity and awards can be filtered by project in the UI.
  Overview task details show delegated status and nested lineage where recorded, with navigation
  to the coordinating conversation. Records with missing root tasks or mismatched projects
  are excluded. Delegated history retains the existing latest-1,000-record bound.
- GET /api/tasks/{id}/conversation: checked visible messages, scoped questions, current turn ID,
  can_send/send_mode/blocked_reason, agents and explicit retention/coverage. agents maps verified
  thread IDs to {role_id,name}; unknown roles are omitted rather than guessed.
  For a Claude task the messages are the owner's instruction and follow-ups (`kind:user`) and the main
  session's replies (`kind:agent`, one per text block, sender the task's session id, bounded to 32,000
  characters per reply, 50 text blocks and 64 KiB per line with a "[Reply truncated]" marker; C0 and C1 controls and
  bidirectional overrides are removed, deduplicated by event id so a replayed line adds
  nothing). A reply that fails the content checks is stored as a `system` message with the fixed text "Reply
  withheld: sensitive-content checks did not pass" and never the text. The parser copies no thinking, tool input or
  results, hook output or subagent text (the model's own reply may quote them). Delegates come from the stream's subagent start and stop lines
  (at most 64 per task; an internal counter records the rest) and carry the lineage fields of Codex rows;
  a delegate still active when its parent turn ends takes the parent's outcome. Fake-binary evidence only.
  The response also includes `recovery_available`. Delegated activity can retain an unknown-role
  child as `role:null` with the stable unattributed label; its unresolved state can keep a terminal
  parent available for recovery across disconnects and restarts.
  blocked_reason explains native-request gating separately from lost ownership/disconnection.
  The UI links pending approvals to their existing scoped review and guidance flow. Generic chat
  does not answer approval requests. Successful resolution restores repeated steering/follow-ups.
- POST /api/tasks/{id}/message: {text,expected_turn_id}; exact live ownership/turn validation,
  native turn/steer while running or turn/start for a finished current-runtime task. No replay.
  For a Claude run: a run that is completed, failed, interrupted or unknown and has a session is
  resumed with `--resume <session>` and answers `{"status":"sent","mode":"followup"}`; usage and cost
  totals add to the previous invocations' and never decrease. Refusals are internal `ValueError` texts
  and reach HTTP clients as the generic 400 `Request rejected. Check fields, connection, project and
  action availability.`: a running run (internal text: guidance cannot be sent into a running Claude turn),
  the follow-up cap (50 invocations per run, or 200 turns in the owned session), a run stopped for its
  permission mode, a run with no session, and an unknown run whose pre-restart process may still be
  running. A prompt that is empty, over 16000 characters, starts with `-` or contains NUL is also a 400.
- Outputs (`POST /api/tasks/{id}/outputs`, `GET /api/tasks/{id}/outputs/{output_id}`): for a Claude task only
  an output attached by the owner (`source:"human"`, explicit confirmation, current `expected_turn_id`) on a
  completed task is accepted; there is no model-registration path. The task snapshot carries `output_suggestions`: at most 8 `{path, tool}` rows (`tool` is `Write` or `Edit`) for the task's current turn, only while the task accepts an attach (`can_attach_output`), never for a delivery run, omitting paths already attached. They come from the main session's `Write` and `Edit` calls (subagent calls are ignored): after the run ends the dashboard turns each path into a project-relative one with string logic only, drops anything outside the project, with `..`, with bidi or zero-width characters, symlinked, not a regular single-link file, over 256 KiB, ignored or not Git-visible, or refused by the path-only secret scan, and stores the rest (the file content is not read; it is scanned when the owner attaches it). The list is a convenience, nothing is attached from it, and a suggestion that was dropped leaves no trace (no count, no error text). A path that does not match the registered project path as written (for example `/tmp/x` against `/private/tmp/x`) is dropped. The input field names of `Write` and `Edit` were seen in live hook requests (2.1.322, one run each); the stream line itself was captured live for `Write` only (2.1.312), not for `Edit`.
  The path rules, scanner and limits are the same as for Codex; an output stays on its turn and is not listed
  after a follow-up begins a new turn. Fake-binary evidence only (`tests/test_task_outputs.py`).
- POST /api/questions/{id}/respond: {answers:{questionId:[singleAnswer]}}; exact question IDs,
  allowed option/free-text policy, reviewed content checks and current native request required.

Only the current owned root Chief of Staff thread receives the experimental issue_rebel_reward
dynamic function. There is no browser award-minting endpoint. These are application-level workflow checks;
trusted same-user processes with file access can modify local state outside these endpoints. Authority is derived from runtime state,
never from tool arguments, model text or a caller-supplied issuer. Role evidence, limits and
idempotency are independently checked before the immutable recognition record is written.
Native function shape is verified against the installed App Server JSON schema. Child roles
require exact recognised agentRole metadata plus verified parent lineage. Separate team_activity
records do not double-count main-thread execution costs or create imaginary dashboard runs.

Source: [Codex App Server](https://learn.chatgpt.com/docs/app-server), checked 2026-10-16.

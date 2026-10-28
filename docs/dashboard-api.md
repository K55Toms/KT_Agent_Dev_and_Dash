# Dashboard implementation contract

Approved scope: local multi-project Python/SQLite/browser application managing its own Codex
App Server. Existing desktop chats are outside v1. Live events drive task state and approvals.
No inference is started merely by opening the dashboard or connecting App Server.

## HTTP API

JSON endpoints, same-origin only. Loopback listener and strict Host/Origin checks. Mutations
require JSON Content-Type and same-origin Origin. No arbitrary RPC endpoint, shell execution,
credential access, external bind option or CORS. Maximum request size is bounded.

- GET /api/config: returns the seven supported nonsecret fields theme, dashboard_name, logo_path,
  github_username, github_visibility, project_approval_modes, sensitive_review_enabled. Legacy files inherit defaults; invalid/unknown
  configuration returns a safe error.
- POST /api/config: exact seven-field validated settings object; atomic persistence and returned configuration.
  project_approval_modes maps up to 100 lowercase 32-hex local project IDs to manual or automatic.
  Absent project IDs default to manual. Changes serialize with native automatic decisions;
  enabling automatic mode affects future callbacks, not existing pending requests. Revocation
  invalidates queued eligibility even if the mode is subsequently re-enabled.
  sensitive_review_enabled is a strict boolean enabling explicit local reveal and approval once;
  it never enables automatic approval of sensitive requests. Turning it off revokes sensitive receipts.
- POST /api/logo: {image:base64_plain_png}; bounded upload, returns {logo_path}. Does not activate it.
- GET /api/logo/{sha256}.png: validated, local uploaded PNG only. No arbitrary path/URL lookup.
- POST /api/projects/{id}/repository: {owner,name,visibility,confirmed:true}; explicitly create an
  empty GitHub repository only with no existing origin; attach HTTPS origin without pushing.
  Partial attachment failure returns created:true,attached:false with a safe warning.
- GET /api/state: returns connection, projects, tasks, approvals, roles, current question summaries and pricing metadata.
  Each task includes `recovery_available` when its outcome is unknown, recovery state/hold exists,
  or a delegated child is unresolved. `delivery_available` indicates an eligible, policy-bound
  Backend/Frontend task or coordinating task with an implementation child. A terminal parent can
  therefore remain recoverable while a child is unresolved. A project or task whose `provider` is
  not `codex` also carries a `provider` field (for example `claude`); for Codex records the field
  is omitted, so existing snapshots are unchanged. When the deployment has no Codex connection,
  `connection` is `{"status":"disabled","detail":...}` with detail `Claude backend is not
  implemented yet.` (provider `claude`) or `No provider configured.` (no provider).
- GET /api/provider: returns `{"provider","configured","capabilities"}` for the deployment's
  start-up provider. `provider` is `codex`, `claude` or `none` (no valid provider argument);
  `configured` is `false` only for `none`; `capabilities` holds `provider` again plus
  `guidance_while_running`, `subagent_questions`, `plan`, `recovery`, `assessment` and
  `approval_alternative`, each `yes`, `no` or `unconfirmed`. Codex reports `yes` for all six. The
  Claude stub reports `plan` as `unconfirmed` and the other five as `no`. `none` reports `no` for
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
  approval/sandbox settings. New tasks require the approved Ponytail policy and registered role
  snapshot to pass validation. A policy failure before task creation returns a safe error; a
  mismatch found later in launch blocks the native turn and may leave a recorded failed task.
  Backend/Frontend root and registered child roles receive the policy. Historical tasks are not
  retroactively stamped or automatically subjected to the delivery gate. The response includes
  `provider` (always present here, including `codex`). Without a Codex deployment the request is
  refused with 409; see "Provider-specific answers".
- POST /api/tasks/{id}/interrupt: interrupt that dashboard-owned active run.
- POST /api/tasks/{id}/delete: exact `{expected_version,confirmed:true}` using the current
  64-character lowercase SHA-256 `deletion_version` from GET `/api/state`. Returns
  `{task_id,deleted:true}`. Deletion is allowed for completed, failed, interrupted and unknown
  runs only when the deletion projection reports `can_delete:true`. Queued/running/waiting-approval
  roots, active children/live ownership, pending native requests and in-flight launch, message,
  assessment or recovery work must be stopped/resolved first. Historical unknown children and
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
  reverse). It covers send message, interrupt, approval respond, approval alternative, question
  respond, delivery checks, delivery review, and the recovery actions check, assess, plans,
  continue, disposition, restart-plan, operation cancel and handoff create, response and accept.
  Read-only routes and deleting a run are not guarded. Known gap: `GET /api/tasks/{id}/recovery`
  for a run recorded under another provider, in a Codex deployment, can still create a recovery
  row, as the read path did before.
- **409 when no provider can start a run.** POST `/api/tasks` with well-formed fields (a malformed
  body is still rejected with 400 first) answers `{"error":"Claude backend is not implemented
  yet."}` in a `claude` deployment and `{"error":"No provider configured."}` when the provider is
  `none`. Any other POST handler that raises the backend's "not available" error answers 409 with
  its own fixed message (`Claude backend is not implemented yet` or `No provider configured`,
  without the final period). Plain validation errors stay 400.

## Ponytail policy and delivery readiness

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
  resolution_mode, review_failure?, decision?}]. `kind` includes command, file_change,
  permissions, approval_question, elicitation and unsupported_input. `native_method` is an
  allowlisted App Server method name; unknown methods are represented as `unsupported`.
  review_failure contains fixed code/message/action/retryable/at. decision contains value/source/at;
  sources distinguish human, human_guidance and project_policy. Sanitized summaries, no raw command/tool bodies. Request IDs
  are opaque local identifiers; backend alone maps them to RPC request IDs. Unsupported input
  requests display an explanation and offer available stop/close actions rather than accepting
  implicitly. Pending reviews require current live ownership and are unavailable after restart.
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
  current weekly badge and recorded commendations. Empty history is not seeded.
  Each member also has `activities`, with allowlisted direct/delegated activity fields and
  `source:direct|delegated`. Team activity and awards can be filtered by project in the UI.
  Overview task details show delegated status and nested lineage where recorded, with navigation
  to the coordinating conversation. Records with missing root tasks or mismatched projects
  are excluded. Delegated history retains the existing latest-1,000-record bound.
- GET /api/tasks/{id}/conversation: checked visible messages, scoped questions, current turn ID,
  can_send/send_mode/blocked_reason, agents and explicit retention/coverage. agents maps verified
  thread IDs to {role_id,name}; unknown roles are omitted rather than guessed.
  The response also includes `recovery_available`. Delegated activity can retain an unknown-role
  child as `role:null` with the stable unattributed label; its unresolved state can keep a terminal
  parent available for recovery across disconnects and restarts.
  blocked_reason explains native-request gating separately from lost ownership/disconnection.
  The UI links pending approvals to their existing scoped review and guidance flow. Generic chat
  does not answer approval requests. Successful resolution restores repeated steering/follow-ups.
- POST /api/tasks/{id}/message: {text,expected_turn_id}; exact live ownership/turn validation,
  native turn/steer while running or turn/start for a finished current-runtime task. No replay.
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

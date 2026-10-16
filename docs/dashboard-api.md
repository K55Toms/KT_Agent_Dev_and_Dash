# Dashboard implementation contract

Approved scope: local multi-project Python/SQLite/browser application managing its own Codex
App Server. Existing desktop chats are outside v1. Live events drive task state and approvals.
No inference is started merely by opening the dashboard or connecting App Server.

## HTTP API

JSON endpoints, same-origin only. Loopback listener and strict Host/Origin checks. Mutations
require JSON Content-Type and same-origin Origin. No arbitrary RPC endpoint, shell execution,
credential access, external bind option or CORS. Maximum request size is bounded.

- GET /api/config: returns the five supported nonsecret fields theme, dashboard_name, logo_path,
  github_username, github_visibility. Theme-only legacy files inherit defaults; invalid/unknown
  configuration returns a safe error.
- POST /api/config: exact five-field validated settings object; atomic persistence and returned configuration.
- POST /api/logo: {image:base64_plain_png}; bounded upload, returns {logo_path}. Does not activate it.
- GET /api/logo/{sha256}.png: validated, local uploaded PNG only. No arbitrary path/URL lookup.
- POST /api/projects/{id}/repository: {owner,name,visibility,confirmed:true}; explicitly create an
  empty GitHub repository only with no existing origin; attach HTTPS origin without pushing.
  Partial attachment failure returns created:true,attached:false with a safe warning.
- GET /api/state: returns connection, projects, tasks, approvals, roles and pricing metadata.
- GET /api/projects/{id}/files: returns {project_id, files:[{path,size}], limit_reached} for
  bounded, Git-visible, nonignored safe source paths in an explicitly registered directory.
- GET /api/projects/{id}/file?path=relative_path: returns {project_id,path,content,line_count,size}
  for bounded UTF-8 source text only after the reviewed secret scanner passes. Never render HTML.
- GET /api/projects/{id}/git: returns local branch/head/origin/upstream/ahead/behind, safe changed
  paths/counts, clean/can_publish and safe reason. Status does not fetch remote state.
- POST /api/projects/{id}/publish: {head,branch,remote,confirmed:true}. Revalidate clean status,
  exact preview-bound snapshot and approved HTTPS GitHub remote. Require full secret checks before a
  normal push of the captured commit. Never stage, commit, force push or bypass hooks implicitly.
- POST /api/projects: {name, path}; explicitly register an existing local project directory.
- POST /api/tasks: {project_id, title, instruction, role}; explicit Start run action creates a
  dashboard task and starts its first Codex turn. User is told this can consume workspace usage
  and modify registered project files subject to Codex approval/sandbox settings.
- POST /api/tasks/{id}/interrupt: interrupt that dashboard-owned active run.
- POST /api/approvals/{id}/respond: {decision}; only a current, supported, pending native request
  can receive a request-scoped decision. No session-wide grants or arbitrary JSON replies.
  V1 supports decline only. Generic sanitized summaries are insufficient for informed acceptance;
  unsupported human-input requests offer interruption instead of an implicit answer.

Errors: JSON {error: safe_message}. Never send prompts, raw RPC payloads, stderr, secrets or
transcripts to the browser. No caller-supplied command strings or arbitrary RPC methods.

## State projection

- connection: {status: connected|connecting|disconnected, detail, last_event_at, server_version}.
- projects: [{id, name, path, created_at}]. Only explicitly registered projects; no machine scan.
- roles: [{id, label, model, reasoning}]. Derived from this repository's approved agent profiles.
- tasks: [{id, project_id, title, role, model, reasoning, status, thread_id, turn_id,
  plan: [{step, status}], blocker, created_at, updated_at, error, usage, cost}].
  Plan text is deliberately ordinal-only: model-authored content is not persisted or rendered.
  blocker is a safe runtime-derived explanation or null; it is not an inferred business blocker.
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
- approvals: [{id, task_id, kind, summary, reason, scope, requester, status: pending|resolved|unavailable,
  created_at, available_decisions}]. Sanitized summaries, no raw command/tool bodies. Request IDs
  are opaque local identifiers; backend alone maps them to RPC request IDs. Unsupported input
  requests display an explanation and offer interruption rather than accepting implicitly.
- pricing: source URL, pricing date, speed basis, and unit. Rates must not be presented as the
  customer's verified billing agreement. Unknown data never becomes a zero charge.

Frontend polls GET /api/state every few seconds while visible, preserving data with an explicit
stale warning on errors. UI filters state consistently by project; no simulated records.

## Runtime lifecycle

App Server subprocess uses fixed argv, JSONL stdio, no shell. Initialize once and acknowledge.
Use stable protocol verified against the installed CLI's generated schema. Enable inference
only through explicit user Start run. Sandbox/approval configuration must retain local user
controls; use on-request plus workspace-write as a conservative managed-run boundary, never
danger-full-access or approval never. Restrict working directories to registered projects.

Persist sanitized projections only. Prompts travel to Codex for execution but are not retained
in the dashboard database or logs. Runtime database stays in ignored .local/ with restrictive
permissions. Never read auth stores or Codex transcript/session files. Codex handles its own
authentication. Startup/reconnect never replays inference or approvals. Disconnect makes pending
requests unavailable and active tasks unknown rather than showing stale actionable controls.

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

The human requested the public repository K55Toms/KT_Agent_Dev_and_Dash. It was created empty
and connected as origin; public visibility, secret scanning and push protection were verified
through repository metadata. Code has not been pushed by this implementation work.

# Dashboard implementation contract

Approved scope: local multi-project Python/SQLite/browser application managing its own Codex
App Server. Existing desktop chats are outside v1. Live events drive task state and approvals.
No inference is started merely by opening the dashboard or connecting App Server.

## HTTP API

JSON endpoints, same-origin only. Loopback listener and strict Host/Origin checks. Mutations
require JSON Content-Type and same-origin Origin. No arbitrary RPC endpoint, shell execution,
credential access, external bind option or CORS. Maximum request size is bounded.

- GET /api/state: returns connection, projects, tasks, approvals, roles and pricing metadata.
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

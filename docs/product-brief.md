# Product brief

Status: implementation in progress; dashboard-managed App Server integration approved.

- Intended user: the human coordinating this AI engineering team.
- Problem: development activity across multiple projects needs a shared progress, cost,
  and required-human-approval view.
- Desired outcome: identify task status, blocked work, execution-cost coverage and pending
  human decisions from a local browser dashboard.
- Deployment: locally on this Mac. Multiple projects are in scope.
- Data source: live Codex integration is required for the first version. A manual ledger alone
  does not meet the requirement.
- Integration target: the human selected dashboard-managed Codex runs through the dashboard's
  own App Server. Existing desktop chats are outside v1. Opening the dashboard or initializing
  the server must not start inference; Start run is the explicit execution action.
- Stack: Python, SQLite and a browser interface approved by the human.
- Approval boundary: pending native requests are live App Server requests with exact ID scope.
  V1 shows required approvals and can decline or interrupt. It does not grant approvals from
  generic summaries; acceptance needs a future full-context review flow. Local records alone
  never grant permissions. Unsupported human-input requests remain visible with a stop action.
- Cost boundary: preserve units, source and attribution. Observed values, estimates and unknown
  data must be visibly distinct. Missing cost must never be represented as a zero charge.
- Data sensitivity: no secrets or raw transcripts. Local-only access and input controls required.

## Acceptance criteria

- Each task has project, title, owner, status, blocker and update time; totals reconcile with filters.
- Costs identify their source, unit and coverage; missing or partially covered costs are explicit.
- Pending approvals show action, reason, scope, requester and where the decision must happen.
- Source/freshness, empty states and failures remain visible without fabricated records.
- Data persists locally; user can inspect and manage projects and tasks without editing source code.
- Opening the app establishes real App Server readiness without starting a paid model turn.
- Explicit Start run registers a dashboard-owned thread/turn with the selected role instructions.
- Live plans, completion/interruption, native requests and token usage update the UI from events.
- Disconnect makes active runs unknown and requests unavailable; reconnect cannot replay work.
- Runtime SQLite data is ignored by Git and stores sanitized projections, not prompts/transcripts.
- Automated protocol tests use a fake server; live verification initializes only, without inference.

Data coverage must be explicit: chat runtime state is not proof of task completion, account
allowance is not task cost, and a chat waiting on approval does not expose the exact request
unless the supported source supplies it. Connection failures must not look like live success.

Secret policy: reference variable names and provisioning steps only. Never record values.

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
  The human can review complete scanner-checked command or file-change context and approve that
  request only. A generic summary never grants approval. Review context remains in memory,
  outside persistent history. Missing, unsafe or stale context blocks acceptance; decline and
  interruption remain available. Session grants and policy amendments remain unsupported.
  Local historical records never grant permissions.
- Cost boundary: preserve units, source and attribution. Observed values, estimates and unknown
  data must be visibly distinct. Missing cost must never be represented as a zero charge.
- Data sensitivity: no secrets, raw tool transcripts or reasoning. Checked visible messages are stored locally. Local-only access and input controls required.

## Acceptance criteria

- Each task has project, title, owner, status, blocker and update time; totals reconcile with filters.
- Costs identify their source, unit and coverage; missing or partially covered costs are explicit.
- Pending approvals show action, reason, scope, requester and where the decision must happen.
- Supported approval journey works end to end: start a run, receive a native request, review
  complete checked context, explicitly approve that request, observe resumed work and completion.
  Decline, cancellation, unsafe context and stale requests have verified separate outcomes.
- Source/freshness, empty states and failures remain visible without fabricated records.
- Data persists locally; user can inspect and manage projects and tasks without editing source code.
- Opening the app establishes real App Server readiness without starting a paid model turn.
- Explicit Start run registers a dashboard-owned thread/turn with the selected role instructions.
- Live plans, completion/interruption, native requests and token usage update the UI from events.
- Disconnect makes active runs unknown and requests unavailable; reconnect cannot replay work.
- Runtime SQLite data is ignored by Git and stores projections plus checked visible user/agent messages and recognition; raw tool output and reasoning are excluded.
- Automated protocol tests use a fake server. Explicitly authorized isolated native checks may
  verify execution and approval round trips without replaying the human's development task.

Data coverage must be explicit: chat runtime state is not proof of task completion, account
allowance is not task cost, and a chat waiting on approval does not expose the exact request
unless the supported source supplies it. Connection failures must not look like live success.

Secret policy: reference variable names and provisioning steps only. Never record values.

## Added scope: manual file review and Git

The human requested a way to inspect project files manually, Git status, and an option to
publish to GitHub. Source review is read-only, restricted to registered Git projects and safe
nonignored text, and guarded by the reviewed secret scanner. The Git view shows local status
without fetching, and publication requires a clean reviewed commit, exact destination/head/branch
confirmation and passing secret checks. It must not stage/commit/force or grant permissions.

The human chose a public repository named KT_Agent_Dev_and_Dash under GitHub account K55Toms.
The empty repository and origin were created; secret scanning and push protection are enabled.
The dashboard publish action is separate from repository creation; no source upload was performed.

## Interaction and team extension

The human requested task conversations with question replies and follow-up guidance, a named
fictional Rebel crew with portraits and observed work, and automatic Chief of Staff recognition.
Visible logs cover dashboard-owned events only, with local bounded persistence after content
checks. Team history and awards must be traceable; no fabricated work or rewards.

Each Team card offers a read-only Details dialog showing the configured personal role prompt.
The dialog identifies this as the role prompt; runs additionally receive shared security
instructions and task-specific guidance. Prompts are checked before display.

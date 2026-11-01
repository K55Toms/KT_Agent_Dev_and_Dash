# Product brief

## Approval parity requirement — 2026-10-26

The human reports another native request that cannot be approved in the dashboard and
requires native Codex requests to be displayed with their actual approve/reject choices.
A stop-only workaround does not satisfy this requirement. Installed-schema diagnosis must
identify supported request families, show their complete checked context and actual grant
scope, and return the native response for the live requesting thread/turn. New permission
request grants must not be described as one-command approval if the native scope is a turn.
Do not grant session access, replay resolved requests, or infer success from sending a response.
The screenshot does not establish the originating native method or where it was resolved.

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
  request only. A generic summary never grants approval. Dashboard review context remains in
  memory, outside dashboard history; Codex native history may retain the underlying request.
  Missing, unsafe or stale context blocks acceptance; decline and
  interruption remain available. Session grants and policy amendments remain unsupported.
  Local historical records never grant permissions.
- Project approval preference: default Manual. The human may explicitly enable Automatic for
  future supported requests from all runs in one project and revoke it in Settings/config.toml.
  Each automatic decision still requires complete checked context and current live ownership.
  Project association identifies the origin, not a limit on operating-system effects; release
  authorization rules remain separate. Existing pending requests are not granted by a mode change.
- Explicit local owner review: the human may reveal a supported request with a sensitive finding,
  then separately approve that exact request once. Scanner failures and invalid scope stay blocked;
  automatic project policies cannot override findings. Reveals are ephemeral in dashboard memory,
  not saved to dashboard history. This is a local-owner action, not a separate authenticated role.
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
- A blocked approval offers checked guidance tied to that request. Continuing decline and
  turn-stopping cancel have distinct controls; a cancel flow requires observed interruption
  and a separate explicit follow-up using retained guidance, with no automatic task replay.
- Project automatic mode is opt-in, persists across runs, records its decision source and can be
  revoked before queued decisions are written. Cross-project and unsupported requests stay manual.
- Agent identity uses verified crew names with runtime IDs available as secondary details.
- Conversations support repeated guidance/follow-ups and questions; a blocking native request
  shows its actual reason and a direct scoped review path. Refresh failures retain unsent drafts.
- The human can dismiss an inactive stale Overview warning without deleting the task or hiding
  pending decisions. Dismissal persists; a new warning becomes visible again.
- Delegation uses persistent native parent threads and explicitly registered team roles in every
  managed project. Verify a real specialist start, result, coordinating completion and child approval.
  Codex-managed local history may retain prompts/tool output outside dashboard scanning. Startup
  does not resume old tasks; old ephemeral sessions are not automatically migrated.
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

## Authorized scope: unknown-task recovery

The human additionally requested direct run deletion on 2026-10-25 to exit a recovery loop.
An explicit local confirmation may delete a terminal or Unknown dashboard run and its local
history, releasing its project hold without a recovery assessment or reboot. Deletion does
not establish that native work stopped, undo project files or erase Codex native history;
the confirmation must explain this. Known active runs/children/operations require Stop first.
Deletion must be atomic, reject stale confirmation and prevent late-event resurrection.

Unknown tasks need a useful assessment path before any separately approved development
continuation. Preserve uncertain outcomes and never replay work or revive historical approvals.
The human approved an assessment handoff feature on 2026-10-25: preview and explicitly copy a
checked evidence packet to an existing approved chat, return the assessment, review it locally,
and explicitly accept it as human-supplied evidence. This feature was applied to the local dashboard on
2026-10-25 after source reviews and tests. Live recovery now offers packet preparation. It does not automatically send evidence, verify
external model identity, or start development. Repeated handoffs support further discussion.
The text-only ChatGPT sign-in assessment route remains a separate option where available.

Continuation still needs a separate versioned plan and explicit approval, strict project
identity, exclusive ownership, fresh complete activity checks and verified changed OS boot.
Same-thread restoration remains disabled. Imported assessment cannot clear project holds or
change historical outcomes. Missing/replaced folders and disconnected native runtime must not
prevent a read-only handoff; they continue to block development as appropriate.
See [recovery design](dashboard-recovery-design.md), [handoff contract](recovery-handoff-design.md),
and the current [API](dashboard-api.md) and [operations](dashboard-operations.md) references.

Dated live-validation evidence and account-specific limitations are recorded in
[the task board](task-board.md) and [decisions](decisions.md). No real recovery continuation
has been established. The observed descendant-coverage gap remains open; reboot alone cannot
resolve incomplete activity coverage.

## Authorized scope: audit remediation

On 2026-10-25 the human requested fixes for all nine Ponytail audit findings. Recovery must
retain unknown-role child activity after disconnect/restart, remain reachable for terminal
parents with unresolved children, and cover the observed 25-descendant case with bounded
complete metadata checks. Read-only response timeouts must not terminate unrelated native work.
Failed local saves must publish no phantom tasks or projects. Git checks must include worktree
credential configuration while preserving approved user-level authentication. Recovery polling
must preserve keyboard focus without retaining stale authority. Remove unreachable native
assessment branches and correct the documented dependency pin. Existing separate plan approval,
boot, ownership and fresh-activity gates remain mandatory. No old task replay is authorized.

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

Team cards also show recorded direct and delegated activities for each member, including work
delegated by the Chief of Staff, with status, project, update time and coordinating-task links.
Overview task activity opens details with the observed delegation hierarchy and status. Project
filters apply to activity. Missing historical lineage is labelled unavailable; assignment prompts
are withheld, so delegated labels identify the role and coordinating task rather than reproducing
the assignment. Activity visibility does not expand delegated cost coverage.

## Authorized scope: code-enforced Ponytail compliance

The human approved verified approved-skill inclusion and fingerprinting before managed
implementation, including registered delegated roles, and a separate delivery readiness gate.
Delivery readiness requires observed successful approved checks and independent review bound
to current changes. Native execution completion remains a distinct fact. Missing/changed policy,
missing evidence and stale code must fail closed with usable setup/retry paths. The app must
provide the complete approved-check and independent-review journey, including explicit human
actions; it must not execute arbitrary host shell commands or equate agent claims with evidence.
These controls cover dashboard-managed work, not existing desktop chats or model judgment.

## Requested scope: completed-task outputs

On 2026-10-25 the human requested accessible outputs on completed tasks, specifically a link
to the Markdown report produced by this UI review. Completion should lead to an inspectable
deliverable where one was produced, rather than require searching a conversation or project files.
Output access remains distinct from native execution completion, accepted delivery and release.
This requirement is recorded for implementation; it is not implemented by the review report.
Task/output association and safe project-scoped preview behavior require a design/API agreement.

## One provider per deployment

The human decided on 2026-10-27 that a dashboard deployment serves exactly one provider, Codex or
Claude, never both at once. The provider is chosen when the dashboard starts
(`sh scripts/run_dashboard.sh codex|claude`) and a missing or unrecognised choice starts no
backend (fail closed). The Claude backend is not implemented yet: a `claude` deployment starts,
shows that state and refuses to start runs; building the backend is Plan 3 of the Claude dashboard
work (see the [task board](task-board.md) and
[Claude Code setup](claude-code-setup.md)). The Codex behaviour described in this brief is unchanged.

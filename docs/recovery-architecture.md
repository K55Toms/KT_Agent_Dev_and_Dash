# Unknown-task recovery architecture

## Local validation update — 25 October 2026

The human approved applying the recovery update and starting live validation. The service
reconnected and the recovery view opened; existing unknown tasks were preserved without
replay. Real ChatGPT sign-in, assessment and native continuation remain unverified. The
inspected task has incomplete descendant coverage and unresolved activity; development stays
blocked, and reboot alone cannot clear those gaps. The dated notes below are historical.
An assessment handoff feature for using an existing approved chat was authorized on
25 October 2026 and was applied locally after review and tests. See the [handoff contract](recovery-handoff-design.md).
Account-specific validation evidence remains in the [task board](task-board.md).


## Implementation update — 23 October 2026

Implementation is authorized and under review; it has not been applied to the running
dashboard or accepted as a live recovery feature. The dated proposal below is retained
as design history. These implementation choices supersede its assessment transport:

- Assessment uses a separate, text-only ChatGPT-plan session with built-in Sign in with
  ChatGPT. It does not import native Codex credentials, request an API key or fall back
  to API billing. Account eligibility remains unverified until real sign-in. Tokens stay
  in process memory; a service restart requires reauthentication.
- Only scanner-checked, explicitly selected text and checked metadata enter assessment.
  Assessment has no filesystem access, native runtime, tools, connectors or executor.
  It cannot inspect project files itself. Repeated questions use the same restricted
  transport, and a separate reviewed-plan approval is still required for development.
- Same-thread recovery remains unavailable. New linked development requires an observed
  changed OS boot, exclusive dashboard ownership, fresh metadata and current native
  startup evidence. A restart does not establish historical or external outcomes.
- Automated and synthetic browser evidence is separate from native recovery evidence.
  Real account sign-in, inference and approved native continuation remain unexecuted.

Current API and setup details belong in [the API reference](dashboard-api.md) and
[the operations guide](dashboard-operations.md). This update does not authorize a
computer restart, original task replay, publication or release.


Status: proposed technical design, 2026-10-19. The human agreed to **assess first, then approve
continuation** during design. The technical choices below remain proposals; no implementation,
live recovery, task replay or release is approved by this document. The original task remains
visible throughout recovery.

## Outcome and boundaries

The human must be able to ask what happened and provide fresh guidance when a dashboard task
becomes unknown. Recovery must not replay the original instruction, infer business completion
from an idle chat, recreate historical permission grants or conceal unresolved child work.

Provide deliberately separate actions in this order:

1. **Check recovery** reads bounded native metadata and current local project status. It starts
   no model turn, changes no files and grants no permission.
2. **Start assessment** starts a linked, fresh assessment conversation and explicitly consents
   to usage. This is mandatory even when the old thread looks recoverable. It receives a reviewed
   context packet, not native history or the original instruction as an executable request, and
   supports repeated fresh messages even when the original thread cannot be resumed.
3. **Continue development** is the human's later approval of the reviewed recovery plan. Only
   after that decision may an eligible persistent thread reconnect under a freshly checked
   execution boundary, or a new linked execution task be created. The action starts a new turn
   containing only the reviewed fresh plan/guidance; it never replays the old instruction.

An assessment may inspect safe local evidence with read-only filesystem access and no network;
it cannot restore the lost agent's memory or establish external outcomes it cannot observe.
Starting it is explicit inference and shows usage implications. Ordinary recovery execution
requires a later explicit decision with a reviewed plan and the normal managed-run boundary.
Persist immutable server-assigned `task_purpose` (`development` or `recovery_assessment`),
origin task ID and capability contract digest before any assessment dispatch. Assessment
purpose cannot be promoted through chat, request callbacks, config changes or recovery of the
assessment itself after disconnect. Every message/follow-up, callback, automatic decision,
thread rebind and recovery path revalidates the same restriction. Assessment turns can only
discuss evidence and produce plans. Actual development uses the original development task
after its approved safe restoration or a separate linked development task; never the assessment
thread. Client-supplied purpose cannot widen authority. Unknown assessment delivery retains
that purpose on restart and cannot acquire development permissions through generic Start run.
Current read-only permissions still permit broad reads on this Mac: credential access remains
prohibited agent policy, not a claim of filesystem isolation. No credential stores, transcript
files, raw command output or reasoning are read for recovery.

Only dashboard-created roots already recorded against a registered project are eligible.
No user-supplied native ID, rollout path, arbitrary RPC method, imported desktop thread or
machine-wide session search is accepted. Preserve the existing loopback, Host/Origin, JSON,
content scanning and trusted-local-process boundaries. Native metadata is untrusted data.

## Evidence and installed capability

The inspected implementation has no recovery ownership path. `ConversationMixin._send_state`
requires an entry in the process-local `owned_threads`; restart clears that map. Sending requires
the exact recorded turn; disconnect expires live requests. `Dashboard._launch` already uses
persistent `thread/start`, verifies a unique named permission profile and registers private
static role snapshots. `CodexClient.request` closes the transport after an ambiguous timeout
instead of retrying a potentially executed mutation. `Store` persists generic JSON records.

Sources inspected: `dashboard/conversation.py`, `dashboard/server.py`,
`dashboard/codex_client.py`, `dashboard/native_roles.py`, `dashboard/store.py`,
`docs/product-brief.md`, `docs/dashboard-api.md`, `docs/dashboard-operations.md`,
`docs/model-policy.md`, `AGENTS.md` and `SECURITY.md`.

[Official App Server documentation](https://learn.chatgpt.com/docs/app-server) was fetched on
2026-10-19. Installed `codex-cli 0.163.0` independently generated experimental JSON Schema with
`codex app-server generate-json-schema --experimental --out /private/tmp/dashboard-recovery-schema-20261019`.
This generated protocol data, not native histories or model work. Installation emitted a PATH
alias permission warning; schema generation exited successfully. Installed schema establishes:

| Native method / field | Verified shape and proposed use |
| --- | --- |
| `thread/read` | `{threadId, includeTurns:false}`; verify identity, project directory, persistence and runtime status. |
| `thread/turns/list` | `{threadId, itemsView:"notLoaded", sortDirection:"desc", limit, cursor?}`; allowlist turn IDs/status/times only. |
| `thread/resume` | `{threadId, excludeTurns:true, cwd, permissions, runtimeWorkspaceRoots, config, developerInstructions, approvalPolicy, approvalsReviewer, model}` are supported; no `path` or `history`. |
| `thread/list` | `ancestorThreadId` filters descendants at any depth; include both archived and nonarchived pages. `useStateDbOnly:true` prevents scan-and-repair behavior. |
| `Thread.status` | `notLoaded`, `idle`, `active` with approval/input flags, or `systemError`; this is runtime state, separate from turn status. |
| `Thread.canAcceptDirectInput` | Optional nullable boolean; require explicit true before offering input. |
| Turn status | `completed`, `interrupted`, `failed`, `inProgress`; `itemsView:"notLoaded"` means items intentionally omitted. |
| `thread/goal/get` | Returns optional goal with status; discard objective and usage data from this recovery path. |
| `thread/backgroundTerminals/list` | Paginated terminals; discard command text, cwd and process metrics, retaining scoped identifiers/count only. |
| `thread/resume` response | Includes approval policy/reviewer, sandbox, optional active permission profile, runtime roots and thread metadata; verify all required execution restrictions. |

Schema proves syntax, not native safety or entitlement. No recovery method was called on live
threads, no native history was read and no inference was started for this design. In particular,
resume behavior around active goals, approvals, tools, inherited dynamic tools and child
restoration still requires isolated native evidence before enabling same-thread recovery.

## State model

Keep the historical task execution status separate from recovery availability:

| Field | Values / meaning |
| --- | --- |
| `recovery.state` | `unchecked`, `checking`, `needs_review`, `assessing`, `awaiting_continuation`, `reconnecting`, `connected`, `assessment_only`, `blocked`, `delivery_unknown`. |
| `recovery.coverage` | `complete`, `partial`, `unavailable`; complete refers only to bounded native runtime checks, never business results. |
| `recovery.last_turn` | Allowlisted observed ID/status/time/source; null when not established. |
| `recovery.children` | Verified descendant count and unresolved count; no prompts or tool payloads. |
| `recovery.execution_clearance` | `unverified`, `quiescent`, `active`, `conflict`; explicit uncertainty remains visible. |
| `recovery.assessment` | Linked assessment ID and checked result/plan version; `draft`, `running`, `reviewable`, `interrupted` or `failed`. Reviewable requires an actual checked model response, not just a started assessment. |
| `recovery.reason_codes` | Fixed safe codes, such as `history_missing`, `active_descendant`, `profile_mismatch`, `goal_unresolved`, `check_limit`, `transport_changed`. |

Never map native `idle` or `notLoaded` to task `completed`. A stored `inProgress` turn after a
restart establishes an unresolved attempt, not a presently running turn and not a failed one.
When a matching native turn has an authoritative terminal status, record that observed turn
outcome with provenance; leave independent acceptance and release decisions separate. A later
recovery turn's completion does not prove the interrupted development task succeeded.
Persist an execution-attempt record keyed by task/thread/turn before replacing the task's
current-turn projection. Its old outcome remains unknown unless that exact turn is reconciled;
the new recovery turn may be running/completed while the older outcome is still unknown. Keep
this distinction visible in task details and assessment. Same-thread continuation retains one
current owned task binding, with attempt linkage to its original record; do not register the
same native root as writable authority for both a historical task and a new task simultaneously.
If linked new execution uses a new task, it must have a new native thread and explicit origin
link. Recovery paths must validate current task ownership in addition to thread identity.

Reserve registered project roots and overlapping ancestors/descendants with one overlap lease while recovery checks,
attachment or submission are in flight. Persist a recovery hold for unresolved execution so a
restart cannot free the project accidentally. This hold blocks ordinary write-capable runs and
publication, but must not block a linked read-only assessment conversation. Existing active
project accounting does not provide this hold and must be extended explicitly.
At migration/startup, establish holds before serving any Start run, recovery or publish action
for every legacy unknown/unresolved development attempt and recorded unresolved descendant,
even if the human has never opened its recovery panel and even if native IDs are missing.
Legacy task purpose defaults conservatively to development, never inferred assessment. Only
an independently verified immutable no-effect assessment contract can justify omitting its
project write hold. Missing project identity keeps affected write/publish actions blocked
until the binding is explicitly reconciled; it is not silently treated as no overlap.

## Check algorithm and freshness

1. Under the dashboard lock, verify the local task/project/root relationship and establish a
   bounded per-task check operation. Capture the current App Server client instance and a new
   process-random connection generation, task revision, project identity, role configuration
   digest and permission policy version. Do not hold the lock across RPC waits.
2. Read only the saved root ID through `thread/read` with turns excluded. Compare exact ID,
   canonical registered cwd, root lineage, persisted ownership and `ephemeral:false`. For older
   metadata that cannot prove ownership/persistence, return assessment-only with a safe reason.
   Immediately discard preview, name, path, extra metadata, errors and all nonallowlisted fields.
3. Obtain a bounded recent turn page with `itemsView:"notLoaded"`; reject unexpected hydrated
   items and never display native error text. Find the recorded uncertain turn by bounded
   pagination; if limits are reached, label partial rather than assuming no turn exists. Inspect
   newer turns too: a turn started outside this recovery flow is a conflict requiring recheck.
4. Discover descendants using the exact owned ancestor filter; union with recorded child IDs.
   Validate every descendant's root lineage and cwd, and record explicit missing/unknown roles.
   Page both archive states with consistent bounds. Missing recorded children or incomplete pages
   prevent quiescence. Do not attach all discovered threads or inherit their permissions.
5. Check root and verified descendants for runtime activity, active goals, pending requests and
   background terminals. Retain only fixed statuses and scoped IDs/counts. Missing/unavailable
   checks mean unverified. A completed parent with an active child does not clear the project.
   No absence-of-events inference is permitted. Recheck after any relevant event while checking.
6. Check local project identity, safe Git status and overlapping task/publication/recovery holds
   using existing reviewed read-only services. Git changes are evidence to review, not proof of
   who made them or whether an external action finished. File bodies remain separately selected,
   bounded and scanned through existing file review.
7. Reacquire the lock and compare all captured versions and runtime event revision. A changed
   connection, task, descendant set, request set, profile or project invalidates the result.
   Return a checked summary and an opaque in-memory receipt only when consistent. Otherwise
   retain safe observations as historical and offer recheck or assessment.

Bound page counts, task count, RPC duration, response size and receipt storage. Suggested initial
limits are implementation constants to validate, not user requirements: reuse current 256 owned
thread and 200 turns-per-thread limits; exceeding either blocks same-thread restoration with
explicit incomplete coverage. Do not silently truncate to create a successful receipt.

Receipt contents remain server-side: task/root identity, connection generation, task/event
revisions, observed turn identity/status, descendant digest, current permission/role/project
digests, check time, operation kind and expiry. Proposed expiry is 60 seconds, checked against
a monotonic clock; disconnect/restart and any relevant event revoke it immediately. An explicit
attachment or inference action performs a new metadata check before acting even within expiry.
Receipt presence alone never grants permission or establishes quiescence. Final continuation
authority additionally binds the checked assessment result/plan digest and the human's exact
decision. Any material plan edit or newly observed conflict requires a new decision. Consume
continuation authority before an attempted native mutation, including attempts with lost
acknowledgement; do not reuse it automatically.

## Restore the conversation safely

Enforce one dashboard owner per runtime directory through a reviewed OS-level lock before
enabling mutation. An in-process lease does not coordinate two dashboard processes. Refuse a
second owner safely; never terminate an unidentified process. The existing application has no
cross-process recovery lease, so platform must establish this boundary before native tests.

Reconnect is an explicit native state mutation even when no turn is started. It follows the
mandatory assessment and human continuation approval. Serialize it with
other task messages, project reservations and publication. A stale receipt returns 409 and
preserves the human's draft. No reconnect or message submission occurs on polling/page load.

Before native resume, rebuild private static role files using `NativeRoles` from the current
approved, scanned profiles plus shared security baseline. Never reuse vanished process-lifetime
paths or copy static instructions out of native history. Show role/model/instruction version
drift before the human confirms restoration. A changed role configuration is a new reviewed
boundary, not proof that the previous task ran under it.

Resume with the recorded native thread ID only, `excludeTurns:true`, a fresh unique permission
profile, exact registered cwd/runtime roots, `on-request`, `approvalsReviewer:"user"`, current
approved model/effort and new `agents` snapshots. Reassert the same project-write/no-network
restrictions already validated by `_launch`; never inherit permission grants or use weaker
settings to make resume succeed. This does not alter security policy. Validate acknowledged
ID/persistence/cwd/roots/profile ID/no inheritance, workspace-write sandbox, network disabled,
temp exclusions, approval policy and reviewer before installing new `owned_threads` authority.
Every later turn retains that exact verified profile and checks current ownership/generation.

Do not assume `thread/resume` supports supplying `dynamicTools`: the installed params do not.
Prove persistent dynamic tool behavior in the native test. Any delivered call still passes
current owned-root/role/turn authorization; reject unknown, historical or child recognition
calls. Unsupported tools or inability to restore roles/profile safely select assessment-only.

Same-thread reconnect is eligible only when native tests establish it cannot autonomously
restart goals, commands or child work and when fresh metadata proves a quiescent tree. Treat
active, blocked, paused or otherwise resumable goals as unresolved until explicitly reconciled;
do not pause/clear/recreate goals during a check. Do not kill or clean terminals automatically.
An explicit Stop action may target only freshly bound, exact owned active turns/tools, and
requires observed native stop plus a fresh check. Native stop cannot undo completed side effects.
If safe interruption requires attachment to an active thread but attachment may restart work,
do not attempt it: provide the linked assessment and a precise manual resolution path.

Old approvals and questions stay unavailable permanently. Restoring metadata does not restore
the JSON-RPC request that conferred response authority. Only a newly delivered, freshly scoped
live callback can enter existing review, scanning and decision handling. Approval flags without
a live callback keep sending blocked and offer stop/recheck/assessment. A new callback requiring
a human decision is usable only after exact current client/thread/turn ownership is established;
quarantined pre-attachment callbacks cannot be retrospectively granted. Recovery guidance is
never interpreted as approval, and uncertain decision delivery is never resent.

After a successful quiescent attach, submit the human-approved fresh recovery plan/guidance,
not the old instruction. Submission uses a new `turn/start` and an explicit recovery context
prefix explaining uncertainty, completed effects and prohibited replay. It may consume usage
and edit the project under normal controls. Show messages/requests/progress, terminal outcome,
and further follow-ups through existing conversation handling. Reconnecting alone is not success
for the original user journey: the human must actually be able to send and receive a new reply.

## Assessment and unavailable-history path

Every recovery offers **Start assessment** from the same task panel before continuation.
Ephemeral/missing/deleted history, unsupported CLI features, unverifiable lineage, lost terminal
proof or restoration failure select a fresh linked execution path after assessment, subject
to the same clearance and human decision.
If original metadata is unavailable, issue an assessment-only receipt from the current checked
local packet and coverage gaps; do not require an execution-clearance receipt just to ask a
question. A current App Server handshake is still needed to run the assessment; disconnected
state retains packet/draft and offers reconnect/retry without resubmitting a turn automatically.
The human previews/edits a packet containing checked local messages they select, safe observed
statuses, coverage limits and their fresh question. Do not automatically include the original
instruction, raw native history, assignment prompts, tool output or unsent guidance. An original
instruction may appear only as human-selected quoted historical context, explicitly not replay
authorization. Preserve the original task and link the new assessment task both ways.

Start a new managed assessment thread using a separately validated read-only/no-network profile,
manual request decisions, no delegation and no execution/recognition dynamic tools. Isolate or
exclude mutating MCP/connectors, plugins and project hooks from the isolated assessment
capability: read-only local filesystem permissions alone do not enforce this. Mandatory managed
and security hooks, scanners and administrator requirements remain enforced. Never disable or
weaken a security control to create assessment mode. If required hooks cannot be safely
constrained, that assessment mechanism fails capability proof; use another verified mechanism
or report the unresolved core capability. No escalation can be accepted from assessment,
including native permission requests; decline unsupported requests rather than offering an
approval escape. The installed ThreadStartParams has no explicit tool-allowlist field, and an
empty dynamicTools array does not prove built-in tools are disabled. The native capability for
tool-free conversation or isolated safe inspection therefore remains a platform/security proof
item. Prefer conversation-only assessment using the reviewed evidence packet if tool isolation
cannot be verified. If neither boundary can be verified, do not claim the core assessment path
is implemented; escalate the unresolved mechanism rather than defer this requirement. Repeated
fresh messages must work while the original has a recovery hold. Scan inputs and outputs normally.

Assessment produces observable facts, uncertainties and a proposed next step. It never changes
the old task's outcome automatically. The human can explicitly record a reviewed disposition
with a checked note and visible evidence source, or leave the original unknown; distinguish
human assessment from native turn outcome. **Start new work from reviewed plan** is available
only after quiescence/overlap checks pass and the human confirms the fresh scope. It creates a
new linked task under normal permissions. Unresolved external effects need human verification;
the assistant cannot determine them by guessing or from a clean working tree.
Once a checked assessment response exists, the human can ask more questions or select **Review
continuation**. The panel binds the exact edited fresh instruction to a plan version/digest,
target role/model/thread strategy and clearance receipt. **Approve and continue development**
records the decision, immediately rechecks safety and dispatches that version only. An assessment
turn completing does not start development. Ordinary native command/file approvals remain
separate from both Start assessment usage consent and final plan approval.

Recommended, pending human agreement: enforce manual native approvals for recovered execution
until its reviewed recovery scope finishes, even if that project's future-run preference is
Automatic. Show the effective mode in Review continuation, keep the saved preference unchanged,
and bind this per-recovery restriction to the native/current request policy. This restriction
is a proposal, not authority to alter the existing approval policy during this design task.

## Proposed HTTP and persistence contracts

These endpoints are proposals; none exist in the current application. Exact input keys only;
same-origin JSON, fixed safe errors, no-cache metadata responses and bounded scanned text.

| Endpoint | Input / result |
| --- | --- |
| `POST /api/tasks/{id}/recovery/check` | `{expected_revision}`; returns operation ID and safe checking state; performs no inference. |
| `GET /api/tasks/{id}/recovery` | Current sanitized summary, provenance/time/coverage, permitted actions and eligible in-memory receipt; polling never invokes resume. |
| `POST /api/tasks/{id}/recovery/plans` | `{assessment_task_id, expected_revision, instruction, target_strategy, role}`; create a scanned draft from a completed checked assessment. Strategy is `same_thread` or `new_linked`; server resolves eligible thread/project itself. Returns plan ID, version, digest and full reviewed safe body. No native mutation. |
| `POST /api/tasks/{id}/recovery/plans/{plan_id}` | `{expected_plan_version, expected_revision, instruction, target_strategy, role}`; scan and version an edit, return updated body/digest. Invalidate prior review/continuation authority atomically; an in-flight dispatched plan cannot be edited. No native mutation. |
| `POST /api/tasks/{id}/recovery/continue` | `{receipt_id, operation_id, assessment_task_id, plan_id, plan_digest, confirmed:true}`; validates reviewable assessment, fresh clearance and exact reviewed plan; attaches or creates execution task and sends that plan once. |
| `POST /api/tasks/{id}/recovery/assess` | `{receipt_id, operation_id, selected_message_ids, text, confirmed:true}`; starts linked assessment only with a verified read-only or tool-free boundary. Receipt may authorize assessment without execution clearance. |
| `POST /api/tasks/{id}/recovery/disposition` | `{expected_revision, disposition, note, confirmed:true}`; records a human assessment separately; never mints runtime evidence or bypasses a project hold. |
| `POST /api/tasks/{id}/recovery/operations/{operation_id}/cancel` | `{expected_revision, confirmed:true}`; cancel only if the serialized operation is provably before its first native dispatch. Otherwise record stop requested and use the exact acknowledged live turn's interrupt path when available. Never infer interruption from the request acknowledgement. |

Response state includes `operation_id`, status and fixed `reason_codes`; no browser-selected
thread/project/profile/RPC path. For same `operation_id` and payload digest, duplicate HTTP
submissions return the existing operation and never resend native mutations. Different payloads
under that ID return 409. A transaction persists `prepared` before any RPC write; then records
`acknowledged`, `rejected` or `delivery_unknown`. Persist checked submitted messages through the
existing content rules with delivery status; acknowledgement, observed native turn and terminal
event are distinct milestones. A crash after prepare or write becomes delivery-unknown, never
an automatic retry. Reconciliation may prove a specific observed turn by safe IDs/timestamps;
matching text or guessing the newest turn is not enough. No native exactly-once guarantee is
claimed: the idempotency record prevents dashboard duplicate dispatch only.
There is no public reconnect endpoint: native resume is an internal stage of the single
continuation operation after the separately recorded human decision. Direct message routes
also require this gate for historical unknown tasks; the ordinary conversation endpoint cannot
bypass assessment by seeing an attached thread.

Plans are server-authoritative records (`recovery_plan`) containing the checked exact instruction,
assessment/evidence revisions, target strategy, approved role/model/instruction contract,
effective approval mode and canonical project identity. Compute a canonical digest server-side
over those fields; the browser renders the returned body as text and confirms that version.
The digest is a binding value, not permission by itself. `/continue` checks the latest plan,
completed assessment, current evidence and human decision in one serialized transition; stale
versions return 409 with the draft preserved. A changed instruction, target, role, evidence,
permissions or effective approval mode requires a newly presented version and decision. A plan
suggestion from the model is never an approved plan. Repeated assessment questions are allowed;
only new material evidence or changed scope invalidates the plan. Persist the checked plan
under conversation content/retention rules; never copy raw commands, native history or reasoning.

Cancellation shares the dispatch lock/transaction. Before dispatch, an atomic transition from
`prepared` to `cancelled_before_dispatch` revokes authority and guarantees that operation cannot
send native work. Once attach or any native write was attempted, cancellation cannot report
"nothing started". Mark `stop_requested`, prevent any later continuation stage, and reconcile
the attempted stage. If attachment was acknowledged but no turn was sent, cancel the remaining
turn stage and report "reconnected; no new turn dispatched" only with that exact local evidence.
If a turn is acknowledged active, request its exact interrupt and wait for matching terminal
evidence. Unknown attach/start/stop delivery remains `delivery_unknown`; no new target is guessed
and no mutation retried. An acknowledged interrupted turn still needs descendant/tool checks
before a hold clears. Restart preserves the operation and cannot change an uncertain cancel
to success. Closing the workspace merely navigates away and never requests cancellation.

Add versioned `execution_attempt`, `recovery_plan`, `recovery_operation`, `recovery_observation` and `recovery_link` record kinds, plus
task revision/recovery hold, immutable task purpose/origin/capability digest, and a static
role/profile contract digest. Store allowlisted IDs,
statuses, timestamps, reason codes, checked messages/notes and linkage only. Do not persist
receipts, role paths, raw native metadata, objective/command text, tool bodies or model reasoning.
Add an atomic multi-record Store transaction for task/operation/link transitions; independent
`put` calls cannot establish crash consistency. Bound retention while retaining any unresolved
operation/hold; finalized operations may use a documented bounded retention policy.

Legacy records default to unchecked historical state. Do not fabricate `ephemeral:false`,
permission proof, origin or a receipt during migration. Register no saved root as live on
startup. A migration is additive/versioned and must fail closed on unknown newer versions.
Backup stopped private state before upgrade; rollback keeps a matching code/state pair rather
than opening upgraded data with old code. A feature rollback disables recovery actions,
expires receipts and preserves observations/holds; it cannot undo model turns or native effects.
No new external service or dependency is required: Python standard library, existing SQLite,
scanner, registered file/Git service and App Server adapter remain the boundary.

## Practical choices for human agreement

| Option | Benefit | Cost / risk |
| --- | --- | --- |
| Mandatory linked assessment, then same-thread restore when safe or linked new execution (recommended technical proposal) | Preserves old execution context when verified safe; every unsupported case still has a conversation path. | Requires native proof of resume/goal/tool/child behavior and careful profile restoration. |
| Linked assessment and explicit new work only | Simpler authority boundary and supports old ephemeral tasks. | Loses unavailable native memory and does not meet an expectation of continuing the exact agent/thread; needs explicit acceptance of that tradeoff. |
| Unconditionally enable Send on unknown tasks | Small UI change. | Rejected technical approach: cannot establish ownership, permissions, request validity or duplicate safety. |

Agreed product direction: mandatory assessment, followed by the human's separate approval of
continuation. Seek agreement on bounded native metadata inspection (not transcript import), the
same-thread-plus-new-execution strategy, effective manual approval restriction and explicit human
disposition separate from native outcomes. Assessment remains usable while old execution is
unresolved. No active unknown work is resumed as part of design approval. Any isolated paid
native exercise needs separate explicit authorization.

## Ownership and acceptance evidence

Backend owns the recovery state machine/adapter, atomic store transitions and idempotency.
Frontend owns reviewed choices, provenance, stale/partial states, retained drafts, accessible
focus/status announcements and links between old/new conversations. Platform owns protocol
capability verification, restart/generation lifecycle, private roles, rollback and orphan-process
limits. Security independently reviews identity, profile restoration, old approval expiry,
callback quarantine and read-only escalation boundaries. QA independently exercises journeys;
writers document actual delivered behavior and gaps. Agent Evaluation reviews the handoffs,
original user journey and evidence coverage independently of product QA.

Required evidence before implementation closeout:

- **Unit/fake protocol:** all state transitions and fixed safe errors; missing metadata, old
  ephemeral history, completed parent/active child, incomplete discovery, active goal/terminal,
  changed cwd/profile/role, stale receipt, cross-project ID, callback-before-attach, expired old
  approvals, injected secrets withheld, duplicate requests and crash at every dispatch boundary.
  Cover plan creation, stale/concurrent edits, browser/body-digest mismatch, material evidence
  invalidation and cancellation before attach, after attach, before/after turn dispatch, plus
  lost stop acknowledgement and restart during each stage.
  Recover an unknown assessment through generic routes and verify it retains its restricted
  purpose; reject attempted promotion, forged callbacks and automatic-approval bypasses.
  Verify unopened legacy unknown tasks and unknown children block overlapping Start run/Publish
  immediately on migration, including missing-ID and mismatched-project records.
  Assert no `turn/start`, steer, approve, goal mutation, cleanup or resume during Check.
- **Native integration, isolated and separately authorized:** persistent root plus real child,
  stop/disconnect/restart, metadata check without inference, private role path regeneration and
  exact acknowledged profile, no permission inheritance, missing callbacks, active goals/tools,
  same-thread new guidance and response, repeated follow-up, cancellation and uncertain delivery.
  Verify a real assessment permits conversation/safe inspection while rejecting writes,
  escalation, delegation, hooks, MCP/plugin external effects and network; a verified tool-free
  packet route is acceptable. Test history-missing fallback through actual model response.
- **Browser:** unknown task -> Check -> preview packet -> Start assessment -> visible reply ->
  follow-up question/reply -> Review continuation -> Approve and continue -> same-thread or new
  linked execution -> observed result -> later follow-up. Missing history and unresolved work
  must still reach assessment/reply. Include native request -> exact review/decline/stop -> observed
  stop -> explicit continuation, drafts across failures, keyboard/focus and partial stale states.
- **Recovery itself:** crash during check, attach, submission and assessment creation; restart
  never replays, old receipts fail, holds persist, duplicate submission cannot send twice, and
  native delivery-unknown remains visible with a usable recheck/assessment action.

Executed for this design: repository/code inspection, official documentation fetch, installed
CLI version/help and experimental schema generation. Application tests, live recovery native
checks and browser journeys were not executed; no implementation exists to validate yet.

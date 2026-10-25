# Unknown-task recovery experience

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


Status: design proposal, 2026-10-19. No application changes, native recovery or usability
tests were performed for this document. The human agreed to mandatory assessment first,
then separate explicit approval of continuation. Remaining technical choices are proposals.
Technical feasibility and enforcement conditions belong in recovery-architecture.md.

## Goal and verified starting point

Let the human ask what happened, inspect evidence, resolve uncertainty and deliberately
continue useful work after a disconnect. An uncertain old outcome must remain visible even
when a new conversation succeeds. Recovery must provide an actual conversation, result and
next decision, rather than ending at a disabled Send button or a status explanation.

Source inspection: current dashboard/static/app.js renders task details in a dialog, links to
Conversations, disables the composer when can_send is false, and retains drafts after refresh
failure. docs/dashboard-api.md describes live ownership checks and no replay after reconnect.
docs/product-brief.md and docs/dashboard-operations.md distinguish observed runtime status
from acceptance and document checked messages, scoped approvals and active child reservations.
These are source findings, not evidence of new runtime capabilities. Existing desktop chats
remain outside this workflow.

## Entry and layout

For an unknown dashboard-managed task, show **Recover task** next to **Open conversation** in
task details. In its historical conversation, replace the unavailable composer explanation
with: “This task lost its live connection. Recover it to inspect what happened and ask for
help continuing.” Include **Recover task**, while retaining recorded messages and drafts.
Dismiss notice continues only to acknowledge attention; it must not resolve the task.

Open a recovery workspace for the selected task. Close the task dialog before opening the
workspace; do not stack dialogs. Retain task/project identity, **Unknown outcome**, previous
conversation link, recovery progress and last checked time at the top. Use the existing
task, badge, message-log and approval conventions. On desktop, the main column contains the
current decision and conversation; a secondary column contains evidence and limitations.
On narrow screens these become one column in that order, with evidence above any execution
confirmation. Never hide required scope, safety conditions or usage copy in collapsed details.

Show three stages: **Check recovery**, **Assess and discuss**, **Review continuation**. Stages
describe the recovery attempt, not the original task's completion. A successful check can
leave the original outcome unknown. A later attempt can refresh evidence without duplicating
the assessment or launching work. Reopening a recovery restores its recorded progress, with
all live controls disabled until freshness and ownership are revalidated.

## Journey 1: inspect without starting model work

1. **Recover task** opens a task-scoped metadata check. Announce “Checking recorded task and
   current runtime status. No agent work is starting.” Use a labelled progress state, with
   **Close** available. Reopening or retrying this check must never start a turn.
2. Show separate facts: last dashboard event and timestamp; latest runtime observation and
   timestamp; project registration/identity; root/child activity coverage; request availability;
   checked history availability; and whether work can safely continue. Distinguish **Observed**,
   **Not recorded**, **Unavailable** and **Needs checking**. Provide source and coverage for each.
   A root shown as idle is not proof that tools, children or an earlier action stopped.
3. State the decision plainly: “An assessment conversation is available. Continuing project
   work is blocked until active work and ownership are checked.” Or, when supported evidence
   satisfies the gate, “Recovery checks permit reviewing a continuation. The old task's outcome
   is still unknown.” Never infer Completed, Failed or Interrupted from idle, acknowledgements,
   absence of events, a human assertion or an assessment agent's prose.
4. Offer **Start assessment conversation** when a safe assessment is available. Also offer
   **Refresh checks**, **View recorded conversation**, and **Close**. If no safe model-backed
   assessment can start, show the precise unavailable capability and the checked manual path
   described below. Do not present a nonfunctional conversation as an available action.

## Journey 2: ask for an assessment, then converse

Before the first start, display the proposed input scope, selected specialist/model setting
when known, checked evidence included and evidence missing. Show the human's editable question:
“What can we verify about this task, what is still uncertain, and what should happen next?”
Do not prefill or automatically resend the original instruction. A suggested question requires
the human to submit it. Keep their text when a check or connection fails.

Primary action: **Start assessment conversation**. Required adjacent copy: “Starts agent work
and can consume workspace usage. This conversation can assess the checked evidence and answer
questions. It has no authority to change project files, run project commands or continue the
old work.” This promise requires enforced capabilities, not prompt wording. Default to a fresh
linked assessment with no tools and a bounded checked evidence packet if stronger
read-only inspection has not been demonstrated. Tool-free here also excludes MCP, plugins,
mutating project hooks, networking and external-effect integrations; a filesystem read-only
label alone is insufficient. Mandatory managed/security hooks and scanners remain enforced;
assessment cannot disable them. An assessment mechanism unable to constrain a required hook's
side effects fails the capability gate. This capability still needs implementation proof; it is not established by
the installed thread-start shape or by this design. Neither the project automatic approval setting
nor old task approval choices grant assessment authority.

During assessment show **Assessing**, elapsed activity/freshness when available, **Stop
assessment**, and a conversation log of checked completed messages. Missing usage is **Unknown**,
never zero. Scope omissions remain visible. Show follow-up questions and a composer labelled
**Ask about recovery**, with **Send question** and its usage notice. This composer stays in
assessment mode: asking “apply this fix” produces an explanation and proposed plan, never write
execution. Answers to assessment questions cannot authorize commands or file changes.

The result separates **What was observed**, **What remains unknown**, **What to check next** and
**Suggested continuation**. Each factual claim links to eligible checked evidence when available;
model suggestions are labelled proposals. “Assessment finished” never changes the old task to
Completed. The human can ask repeated questions, correct facts, add checked nonsecret context,
or **Review continuation**. New information invalidating the proposed scope requires a refreshed
plan. Checking project files is a separate explicit, bounded action only where its safe capability
has been implemented and verified; it is not hidden inside metadata checking.

If native restoration is verified safe and does not start inference, the interface may show
**Original conversation available** with a scoped **Open original conversation** action. Merely
opening it cannot enable execution or revive requests. When restoration/history is unavailable,
show **New assessment linked to this task** and “Only the checked evidence shown here is
available; the full original conversation was not restored.” Fresh context does not imply the
agent remembers the earlier exchange. No raw native transcript or credential-store reading.

## Journey 3: decide and continue explicitly

The agreed sequence requires assessment before continuation; there is no direct execution
shortcut. The review displays the exact new instruction, target project and verified
directory identity, selected role, source task and conversation, intended work scope, retained
uncertainties, current approval behaviour and evidence for quiescence and execution authority.
The human can edit the new instruction or **Back to assessment**. Any edit invalidates a previous
confirmation. Do not transfer the original task instruction as an executable default.

Only enable **Continue development** when the server has verified current authority, freshness,
exclusive project reservation and stopped/absent root, child and outstanding tool activity to
the extent required by the architecture. The server revalidates on submission. A checked box
claiming “the old run stopped” cannot satisfy this gate. Fresh read-only assessment can remain
available when those conditions cannot be established; execution remains blocked.

Place this copy next to Continue development: “Starts a new work turn using the instruction
shown above. It can consume workspace usage and modify files under the current permissions.
Earlier actions may already have happened. Previous approvals are not restored.” Display any
current project automatic approval mode explicitly and offer the existing settings path;
recovery must not silently change that preference or enable it. Release, publication and
external contact still require their applicable authorization.

After acknowledged start, link to the actual live work conversation and show the new turn's
observed state. Prefer a fresh linked work run when original-thread resumption cannot be proved
safe. Same-thread continuation is conditional on verified restoration and identical gates.
Keep a visible recovery lineage between old task, assessment and continuation. The original
task can remain Unknown while the linked work runs; completion of new work does not retrospectively
establish what the original turn did. New live requests use the existing exact-request review,
decline and Stop flows. Only fresh observations can update runtime status, and engineering
acceptance still requires checks and human decisions.

## Blocked and failure paths

| Condition | Visible state and usable next action |
| --- | --- |
| Disconnected, connecting or refresh failed | Keep last evidence marked stale and drafts. Disable execution; offer Refresh checks and existing operations guidance. Reconnection repeats metadata validation only. |
| Runtime idle but children/tools or prior process state unresolved | Keep Unknown and explain the unresolved coverage. Allow bounded assessment; offer the exact supported stop/verification path. Do not claim an unobserved stop succeeded. |
| Known live conflicting work | Identify eligible task/agent links. Offer Open active task and its scoped Stop control. Wait for observed interruption/quiescence, then Refresh checks. Do not cancel another task automatically. |
| Old process may still write and no supported verification/control exists | “Continuation blocked: earlier project activity cannot be verified stopped.” Give checked manual operations steps and the missing evidence criterion. Assessment can help plan; manual acknowledgement alone cannot unlock work. Escalate capability gap to implementation owner. |
| Missing project, changed directory identity, wrong ownership or overlapping reservation | Show the mismatch without reading outside allowed sources. Offer project settings or active-task link, then Refresh checks. Do not silently retarget the task or use user-entered thread IDs to claim ownership. |
| No checked conversation available | Explain the scope gap; start a fresh assessment from checked metadata and human-supplied nonsecret context. Do not require restored history to discuss recovery. |
| Checked content withheld/scanner unavailable | Show safe reason and coverage gap. Never expose raw bytes or bypass checks. Permit retry after restoration of the checker or assessment using remaining eligible evidence; if insufficient, explain the manual next step. |
| Start request acknowledgement lost | “Start outcome unconfirmed. Checking whether work started.” Disable duplicate submission, reconcile the same operation identifier, and expose Refresh status. Never automatically resend the model action; unresolved delivery remains uncertain. |
| Concurrent tab or stale review | Retain draft, invalidate approval/start control and explain “Recovery changed elsewhere. Refresh checks before continuing.” Show current linked operation when verified; no duplicate work. |
| Assessment stopped, failed or usage exhausted | Preserve eligible result/draft, label Interrupted, Failed or outcome unconfirmed only from matching evidence. Retry is an explicit new usage action after reconciliation; offer manual inspection and Close. |
| Unexpected permission request from assessment | Block the requested action, preserve checked context, show capability failure and Stop assessment. It cannot be converted to a write-authorized assessment by ordinary chat or approval. |
| Continuation fails or disconnects | Link its actual run, preserve result and checked recovery record. If outcome is unknown, restart this recovery journey for that run; never replay the continuation. |

**Close** leaves the workspace without stopping a running assessment/continuation and says so
when work is active. **Stop assessment** explicitly requests interruption; show **Stopping**
until observed. If stop acknowledgement is lost, remain uncertain. No follow-up is sent while
interruption is unconfirmed. Navigation and dialog dismissal never imply cancellation. A manual
operations route must name concrete supported steps and the exact observed evidence needed;
the proposed steps and evidence criteria are specified in the
[operations design](recovery-operations.md). It uses a freshly bound scoped Stop where possible;
legacy cases without reliable process identity may require the human to plan a computer
restart, followed by a verified boot fence and no-auto-resume checks. Show the disruption and
unresolved external effects before that choice. Never restart the computer automatically.
These controls require implementation proof and human agreement on the legacy tradeoff;
they are not available in the current app.

During continuation submission, **Cancel pending continuation** requests serialized cancellation.
Only a confirmed cancellation before native dispatch may say "Cancelled; no work was sent."
After dispatch, label the action **Stop requested work** and explain that work may already have
started. Prevent the remaining stages; interrupt only an exactly acknowledged active turn.
If attachment alone was acknowledged and no turn sent, report that specific outcome. Lost
attach/start/stop acknowledgements remain **Outcome unconfirmed**, with recheck and assessment
available and no automatic resend. Keep **Close** separate from both controls. Test cancellation
at every dispatch boundary, across concurrent tabs and after restart; no cancellation click
alone proves a stop or clears unresolved child/background activity.

## Interaction states and accessibility

- Loading: text status plus progress indicator; no fabricated percentage. Use polite live
  announcements for stage changes; do not announce every poll or steal focus.
- Empty: distinguish no recorded messages, no available evidence and no recoverable managed
  task. Supply the applicable action and limitation, not an empty success panel.
- Errors and permission failures: short safe explanation by the failed action, an accessible
  error summary when needed, preserved drafts and explicit retry. Do not render raw RPC errors.
- Success: announce the actual observed outcome: check finished, assessment completed, or
  continuation started. Keep old outcome and missing evidence visible beside that success.
- Use native buttons and labelled text fields, a semantic ordered stage list and headings.
  Disabled actions have a persistent visible reason linked with aria-describedby. Status is
  expressed in text and icon as well as colour; target WCAG AA contrast and verify during build.
- Keyboard order follows evidence, decision, action. Focus enters the workspace heading and
  returns to its invoking control on close when present, otherwise the task heading. An
  explicit stage action focuses the next heading; refresh preserves composer selection/focus.
  Existing modal conventions require Escape, focus containment and no hidden interactive layer.
- No keyboard shortcut submits a paid action implicitly. Enter inside the multiline question
  inserts a newline. Submission is the labelled button or its deliberate keyboard activation.
- Mobile: no horizontal page scrolling at a narrow viewport or 200% zoom; long safe identifiers
  wrap. Actions stack, primary and Stop remain distinct, and status/evidence precede confirmation.
  Do not rely on hover or colour to disclose scope or blocked reasons.

## Journey acceptance and handoff

QA should trace these scenarios independently before implementation is declared complete:

1. Unknown task -> metadata check -> explicit assessment start -> checked result -> follow-up
   question and answer -> reviewed new instruction -> explicit permitted continuation -> actual
   live conversation, fresh request review if needed, observed completion and separate acceptance.
2. Missing native history -> fresh linked assessment -> candid scope gaps -> useful repeated
   discussion -> safe plan. The old conversation need not be restored for this journey to work.
3. Idle root with unresolved child/tool activity -> assessment remains usable -> execution stays
   blocked -> supported stop/verification -> fresh gate -> explicit continuation, never blind replay.
4. Disconnect/lost start acknowledgement/concurrent tab -> drafts preserved, duplicate start
   blocked, operation reconciled. No action is inferred successful from a UI receipt or retried blindly.
5. Stale approval, unsafe packet, assessment write request or mismatched project -> unsafe action
   blocked with an actionable checked alternative. Old request acceptance is never revived.
6. Keyboard-only and narrow-screen paths cover recovery, draft preservation, questions, plan review,
   final action, Stop and return focus. Screen-reader announcements describe uncertainty and limits.

These are proposed checks, not executed results. Frontend owns interactions/accessibility;
backend/architecture own enforced capability, authority, freshness and idempotency; platform
owns process/quiescence verification and actionable manual recovery; security independently
reviews evidence transport and execution boundaries; QA verifies positive and negative paths;
writers document delivered behaviour after evidence exists. Chief of Staff records unresolved
capabilities and the agreed mandatory-assessment decision. Product usability testing is pending.

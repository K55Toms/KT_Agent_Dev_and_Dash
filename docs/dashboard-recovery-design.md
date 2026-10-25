# Unknown-task recovery proposal

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


Status: reviewed design proposal, 2026-10-19. No recovery feature is implemented, and this
review does not approve implementation or release. The human confirmed mandatory assessment
first, followed by separate human approval of development continuation. Other product and
architecture choices below remain pending. This entry point summarizes the review; detailed
contracts and interaction states live in [architecture](recovery-architecture.md) and
[experience](recovery-experience.md). The [operations design](recovery-operations.md) defines
activity reconciliation, legacy process limits, crash handling and implementation proof.

## Outcome and scope

An unknown task must offer a useful way to inspect evidence, ask the agent questions and plan
recovery without implicitly repeating uncertain work. The assessment conversation must remain
useful when the original thread cannot be reopened. Changes to files, tests that may write,
deployment, publication and other development actions require a separate continuation choice
and existing permissions. A new message must not be interpreted as a retry of a lost message.

Scope is dashboard-managed tasks in explicitly registered projects. Existing desktop chats
and arbitrary thread imports remain outside scope. Do not directly read Codex transcript,
session database or credential files. Keep the current local-user trust boundary explicit.

## Primary journey

1. **Recover task** is available from an unknown task and its read-only conversation.
   Show the last confirmed event and the uncertainty reason, rather than an inferred outcome.
2. **Check recovery options** gathers bounded native metadata and safe project evidence.
   It starts no model turn, replays no request and changes no project files. Show when each
   observation was made, coverage gaps, and whether other work may still be active.
3. **Start assessment conversation** is an explicit action that may consume workspace usage.
   It creates a linked assessment with enforced restrictions and only reviewed evidence.
   It does not restore the original task's execution authority. The human can ask follow-up
   questions and refine the assessment while development continuation is blocked.
4. The assessment separates observed facts, unverified claims and unknown outcomes. It lists
   changes already present, checks actually evidenced, outstanding decisions, possible partial
   actions and a proposed next instruction. An agent statement alone cannot certify an old
   external action completed or that orphan work stopped.
5. **Review continuation** presents the exact fresh instruction, target project, selected role,
   same-thread or new-linked strategy, changes to preserve, unresolved work, scope and effective
   approval mode. Bind the decision to the current assessment and versioned plan. Enable
   continuation only with verified quiescence/ownership and current safety configuration.
6. **Approve and continue development** is a separate human action. Revalidate immediately,
   submit only the reviewed fresh plan, and show acknowledgement/progress. Keep native command
   and file-change approval requests in the existing scoped review flow. Human approval of the
   plan does not grant missing runtime permissions or publication authority. A pre-dispatch
   cancellation may be reported as cancelled only when confirmed; after a native dispatch is
   attempted, preserve delivery uncertainty and never resend automatically.
7. Observe completion or interruption of the new turn. Keep historical unknown outcomes and
   assessment results distinct from current execution and independent acceptance of the work.

## Every branch must lead somewhere useful

| Evidence or condition | Available path | Required limit |
| --- | --- | --- |
| Original persistent thread is eligible | Assess first, then offer a verified same-thread continuation | Reopening must be proven not to start work; permissions, instructions, role registrations and lineage must be re-established |
| Original thread missing, ephemeral or incompatible | Linked fresh assessment using checked dashboard/project evidence; human edits context and asks questions | Preserve the old outcome as unknown; do not fabricate recovered native history |
| Root, child, goal or background activity is active/uncertain | Assessment and evidence review remain available; show exact owned stop/recheck path where supported | Block write-capable continuation until evidence resolves activity; a checkbox cannot establish quiescence |
| Same-thread restore fails | Keep assessment and plan; explain the failure and offer a linked fresh execution after the same gates | No silent downgrade to weaker permissions or automatic replay |
| Scanner, metadata or connection check fails | Retain checked local evidence and unsent draft; show reason and explicit recheck | No native resume/continuation from stale results; assessment may use a smaller checked evidence set with visible gaps |
| Submission acknowledgement is lost | Preserve the attempted instruction and uncertainty; recheck supported metadata and keep questions/evidence review available | Never resend automatically; local duplicate suppression does not establish native exactly-once execution |
| User chooses to stop recovery | Keep original task and checked history; discard temporary authority | No automatic execution or status relabel |

## State and authority are separate

Maintain three distinct facts: historical execution outcome, current recovery stage, and
current permission to continue. `idle` or `notLoaded` is not `completed`. A user annotation
can record their conclusion with attribution; it cannot manufacture a native completion event.
Link assessment and subsequent execution to their origin so the user need not restart the
explanation. Returning to the workspace must show the latest checkpoint and outstanding owner.

Old approval requests, sensitive-reveal receipts, advisory questions, tool calls and queued
sends never regain authority through recovery. Fresh native requests require fresh validation
and review. Project automatic-approval preferences cannot approve the recovery plan or start
assessment/development by themselves. The architecture recommends manual native approval for
recovered execution until the reviewed recovery scope finishes, even if the project preference
is Automatic. This per-recovery restriction remains a human decision; it must not silently
change the saved project preference.

Assessment is an immutable task purpose, enforced again after every follow-up, callback or
restart. Asking the assessment to apply its plan cannot promote it to a development run.
Legacy unknown development tasks reserve their project before any new run/publication action,
including those whose recovery panel has never been opened. Clearance requires observed
evidence; a human annotation or model reassurance cannot remove that hold.

## Evidence boundary

Current implementation clears live ownership on disconnect and makes previous runtime history
read-only. See [conversation sending](../dashboard/conversation.py),
[connection lifecycle](../dashboard/server.py), and the current
[dashboard API contract](dashboard-api.md). The proposed recovery is new behaviour; the current
[operations guide](dashboard-operations.md) does not describe recovery controls that exist in
the app.

Official documentation distinguishes metadata reads from reopening a stored thread. Installed
CLI schema inspection is required to select exact supported fields and methods; schema presence
alone does not prove side-effect-free reopening or successful integration. See the architect's
evidence inventory and [official App Server documentation](https://learn.chatgpt.com/docs/app-server).

No production thread will be resumed, interrupted, migrated or replayed to validate this design.
Implementation acceptance will require isolated authorized native tests as well as deterministic,
mocked-protocol and browser evidence; a design review cannot substitute for those tests.

## Review outcome and checks

The [technical architecture](recovery-architecture.md), [user experience](recovery-experience.md)
and [operations design](recovery-operations.md) are proposals, not implementation contracts
already supported by the app. Platform supplied a concrete manual route for legacy/orphaned
work: use only positively identified owner evidence and scoped Stop when supported; otherwise
offer the human a separately chosen computer restart, then require a verified OS boot fence,
single-owner launch, no-auto-resume check and fresh activity reconciliation. A restart cannot
undo prior side effects or prove external work ended. If the boot identity or scope cannot be
verified, assessment remains usable and write continuation remains blocked.

Independent QA found plan-version binding and cancellation-state gaps; the architecture was
updated and those findings were retested. Security identified the need for immutable assessment
purpose and holds for all legacy unknown work, including unopened tasks; those controls and the
assessment hook boundary were addressed in the proposal, with no blocking design findings
remaining in the scoped review. Security also reports that three existing fake-protocol
regression tests passed. Agent Evaluation recorded its design assessment as
[EVAL-2026-10-19-02](model-evaluation.md#recovery-design-assessment-2026-10-19). These
dispositions review the proposed design and regression evidence; they do not establish product
acceptance or runtime acceptance.

## Acceptance for design delivery

- The approved assessment-first choice is reflected in every route to development continuation.
- Every button has a resulting state, evidence source and next action; blocked continuation
  preserves useful assessment conversation rather than disabling all communication.
- Read-only assessment is enforced by capabilities and permissions, including integrations and
  delegation, or uses a verified tool-free evidence route. Prompt wording alone is insufficient.
- Contracts address epoch/freshness changes, duplicate clicks, concurrent tabs/processes,
  overlapping projects, unknown descendants, profile drift and lost acknowledgements.
- Same-thread capability limits and fallback are explicit. No core usable path is silently
  deferred because a preferred integration is unavailable.
- Independent security and QA inspect the proposal, writers verify its claims and state its
  untested limits, and Agent Evaluation records handoffs, corrections and open follow-ups.

## Decision summary and remaining proof

**Confirmed by the human:** assessment is mandatory before development continuation, and the
human separately approves the reviewed continuation plan.

**Recommendations pending human choice:** same-thread restoration only when proven safe, with a
linked new execution path otherwise; manual native approvals for the duration of each recovery;
and the disruptive OS-restart fallback for legacy work whose process ownership cannot be
verified. The product direction also requires bounded native metadata, not native transcript
import. See the task-board entry for the recorded decision list and owner.

**Implementation blockers:** establish and enforce a conversation-only/read-only assessment
capability without weakening required hooks or security controls; prove native resume does not
restart goals, children or commands and that restored permissions/profile are exact; implement
and verify process ownership, overlap holds and the boot-identity fence; and pass the fake,
isolated native, browser and crash/restart journeys listed in the linked designs. Existing
schema and source inspection do not prove these behaviors.

The design pass did not change application code, run a live recovery, inspect native history,
start inference, or perform browser/native integration checks. The reported fake regression
tests are separate evidence from runtime proof. No implementation, paid exercise, restart,
replay or release is authorized by this proposal. The [task board](task-board.md) records
review ownership and remaining decisions; the [decision log](decisions.md) remains the source
for approved product choices.

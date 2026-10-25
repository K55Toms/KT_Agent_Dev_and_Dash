# Unknown-task recovery operations

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


Status: proposed operational design, 2026-10-19. No application changes, live RPC,
process inspection, restart, interruption, inference or operating-system changes were made
for this document. The agreed product direction is assessment first, followed by separate
human approval of continuation. This document supplies the operational dependencies for
[architecture](recovery-architecture.md) and [experience](recovery-experience.md).

## Verified starting point and limits

Source inspection of `scripts/run_dashboard.sh`, `dashboard/codex_client.py`,
`dashboard/server.py` and `dashboard/native_roles.py` establishes that the launcher starts
the local Python server; the client launches `codex app-server` through `Popen`; client
close terminates and waits for that direct process, escalating to kill after its timeout.
It does not establish an OS containment boundary or verified descendant cleanup. The
current Stop route targets recorded active root/child turns and returns
`interrupt_requested`; its own comment correctly treats a matching completion event as
authoritative for the turn. That event alone does not prove every subprocess stopped.

The installed generated `v2/ThreadStartParams.json` exposes `config`, permissions,
`dynamicTools` and environment choices, but no verified complete tool-allowlist boundary.
Its `multiAgentMode` field is documented as ignored. These are schema observations, not
evidence that a native assessment can enforce tool-free operation. Configuration hints
such as a shell-tool feature setting, an empty dynamic-tool list, instructions, read-only
filesystem access or refusal to approve escalation do not independently establish that
shells, built-in tools, MCP, plugins, hooks, goals and delegation are unreachable.

Process quiescence is narrower than outcome certainty. A stopped turn, vanished process,
idle server, quiet event stream or clean Git tree cannot prove that no files changed,
external action completed, network job continues, or untracked/non-Git side effect occurred.
The old outcome remains Unknown unless evidence reconciles that exact attempt. The
trusted-local-user boundary cannot protect against an unrelated same-user process editing
runtime state or starting a competing writer outside the dashboard.

## Two recovery lanes

An unresolved project hold blocks dashboard write-capable work and publication for the
registered project and overlapping roots. It must leave assessment conversations usable.
An assessment has its own operation identity, capability contract and linked conversation;
it does not inherit old native authority or clear the hold. Repeated questions remain
possible using only checked evidence and fresh user text.

The execution lane requires an independently established local clearance, a checked
assessment/plan, the human's exact continuation decision and a final fresh server check.
Clearing a hold is not a task-completion claim or authority to repeat earlier effects.
Remote or durable external work requires separate reconciliation in the continuation plan
and applicable authorization for any new external action. Local process evidence cannot
clear an unresolved concurrent remote writer to the same resources.

## Known, currently bound active work

This path applies only when current client generation, owned root/child IDs and exact active
turn IDs are established without unsafe attachment. A historical ID or PID is insufficient.

1. Show the conflicting task and known children, project, coverage and check time. Offer
   **Open active task** and its scoped **Stop** action. The human explicitly requests Stop;
   a recovery check never sends it automatically. Do not attach an active historical thread
   merely to obtain a stop handle unless isolated native tests have proved attachment cannot
   restart goals, commands or children.
2. Record exact intended targets before dispatch. Send only their supported native stop
   requests. Show **Stopping** until each matching turn has an authoritative terminal event
   or fresh terminal-state reconciliation from that same runtime binding. Lost reply or
   successful acknowledgement means stop delivery is uncertain, not stopped. Do not resend
   a stop blindly after a connection change.
3. Refresh complete bounded root/descendant, goal, pending-request and terminal coverage.
   Include recorded children missing from discovery; missing pages or unavailable checks
   keep the hold. An active child requires its own supported stop path. The completed root
   never clears child activity by implication.
4. Verify local process activity through the provenance/containment contract below. If the
   contract cannot account for an outstanding shell, detached job or background terminal,
   show the unresolved class and retain the hold. Do not invent a generic terminal-stop RPC
   or pretend `turn/interrupt` is a process-tree kill API.
5. After every required observation is current and consistent, record **Local execution
   clearance established**, with source, coverage and generation. Return to assessment and
   continuation review. The human still approves the fresh instruction; Stop never sends it.

The clearance criterion is the conjunction of a current exclusive dashboard owner,
complete scoped native observations with no unresolved executable root/child/goal/request/
terminal, reliable local process containment or a verified boot fence, and no conflicting
project reservation. Exact timestamps/IDs and observation source must be retained as
allowlisted metadata. Any relevant event invalidates the candidate clearance before dispatch.
Where native behavior or process coverage is unproved, this criterion is not satisfied.

## Legacy or orphaned work without reliable process ownership

Provide a usable assessment immediately once its capability is verified. Explain:
“Earlier local work cannot yet be verified stopped. You can discuss the evidence here;
continuing project writes is blocked.” List the specific missing evidence and offer the
following manual operations route rather than a checkbox claiming the old run stopped.

1. Save unrelated work. Inspect only the dashboard's recorded owner/task evidence and any
   already identified original terminal/session. If the original foreground session is
   positively identified, the human may stop it with its ordinary application control.
   A terminal being closed, a process name match or a user statement is not clearance.
2. The proposed metadata inspector shows only PID, parent PID, process-group/session ID,
   UID, start identity and boot identity for a narrowly scoped, already identified owner
   tree. Do not collect environment, complete argv, raw logs, native histories or arbitrary
   process memory. Reparented/escaped children make tree enumeration incomplete. PID reuse
   or uncertain ownership prohibits signaling; never offer kill-by-name, kill-all-Codex or
   an arbitrary PID input as recovery controls.
3. If provenance is insufficient, offer **Plan a computer restart**. Explain that this
   interrupts other local work and requires the human's separate explicit OS action;
   recovery never restarts the computer automatically. Record the current OS boot identity
   in the pending recovery record before shutdown. Stop the identified dashboard normally,
   then the human restarts the Mac through the operating-system UI. This is a proposed
   conservative path for old local processes, not a claim that reboot reverses their work.
4. On next manual dashboard launch, the proposed verifier requires a trustworthy OS boot
   identity different from the pre-restart identity. A process-random dashboard generation
   is not an OS boot identity. A missing/unreadable boot source, sleep/wake, clock change or
   dashboard-only restart does not satisfy the fence. No need to know which old PID survived:
   processes from the previous local boot cannot remain as those processes after a verified
   complete OS restart.
5. Establish the single-owner lock and verify the supported launch contract starts no old
   model turn, goal, terminal or child automatically. Recheck relevant native metadata and
   overlapping work after launch. Unaccounted autostart services, external job supervisors,
   remounted/shared workspaces or remote agents leave the relevant scope unresolved; the
   verifier must not turn boot evidence into a universal no-writers claim.
6. Record the boot fence as **Previous local process epoch ended**, keep earlier outcome
   Unknown, and return to the live assessment conversation. Review the checked project
   evidence and any external-effect uncertainty. Only when the complete clearance criterion
   above holds may the human review and approve new development. No old instruction or
   approval is replayed. Keep safe recheck, assessment, copyable nonsecret steps and Close
   available throughout; Close does not resolve the hold.

This path requires a new boot-identity verifier, crash-safe pending record and tested
no-auto-resume contract. None exists as verified recovery behavior today. Native recovery
must not ship promising a legacy unlock before this path or another equally evidenced
mechanism is implemented. If restart is unacceptable or identity/coverage cannot be
established, keep assessment usable and state that write continuation remains unsupported.
The product owner must explicitly decide any different risk tradeoff; an ordinary recovery
confirmation cannot waive the gate. A fresh worktree alone is insufficient because earlier
effects may extend beyond Git or the original directory.

## Future provenance and process ownership

Platform and backend should record a minimal launch manifest before opening execution:

- A durable operation ID, dashboard instance ID, connection generation, OS boot identity,
  owner UID and private runtime identity; App Server PID plus nonreused process-start identity.
- Exact registered canonical project root identity and overlap hold/reservation; scoped
  thread/turn/child relationships as they are authoritatively observed.
- Dedicated owned process group/session identity where supported, creation provenance and
  lifecycle observations for subprocesses. Parent PID or process group alone is insufficient:
  descendants may detach, reparent or leave a group. A reviewed containment mechanism must
  prevent escape or detect it and preserve an unresolved hold.
- Contract/version digests for launch, capability policy and scanner, without raw instructions,
  commands, credentials, environment dumps or native payloads.

Do not signal a process merely because it matches a stale manifest. Validate boot, UID,
nonreused process identity and ownership immediately before any separately authorized
scoped stop. Prefer supported native interruption first. Group shutdown, escalation and
timeout behavior require independent security review and isolated OS tests before exposure.
Any failed identity check leaves a hold; it never selects a replacement PID by name.

Use a reviewed OS-held lock on a private, nonsymlink runtime file, acquired before startup
can mutate state or spawn App Server. Hold its open descriptor for the owning dashboard
lifetime. OS release on process exit avoids stale-file deletion as a lock-breaking method;
the file's presence alone does not indicate a live owner. Reject a second process safely
without killing either instance. Persistent unresolved holds survive lock release.
Initially support one authoritative runtime for this dashboard installation. If alternate
runtime directories can target the same project, they need a shared reviewed coordination
boundary; an independent lock per directory cannot establish exclusive project access.
Do not enable that configuration until overlapping roots are coordinated across owners.

## Enforce assessment capability before promising conversation

Prefer a dedicated conversation-only capability receiving the previewed, bounded, scanned
evidence packet. It needs no project mount, old native history, runtime database access,
shell, tool dispatch, connectors or delegation. The human's selected local evidence is
collected by existing bounded reviewed services before inference, not by giving the model
a general filesystem reader. New packet evidence is an explicit separately checked action.
The model transport may use its required provider connection; the model must receive no
general network or external-action capability. Keep transport credentials in approved
runtime provisioning outside project files and never inspect or copy their values.

Implement and verify a separate capability contract, not edits that weaken project hooks
or scanners. Existing execution threads retain all required security hooks and policy.
Assessment must not execute project/plugin lifecycle hooks at all; choosing a component
that never invokes such hooks is different from disabling a security hook on project work.
If the proposed native configuration would suppress a required security hook, reject that
approach and seek a different supported component. Do not change user-global CLI config,
administrator requirements or project security files to make assessment pass.

Before adopting the App Server route, platform/security must inspect supported installed
configuration and effective capability acknowledgements without reading private config or
credentials, then prove behavior in a synthetic isolated environment. Explicitly inventory:

| Capability | Required assessment proof |
| --- | --- |
| Shell, filesystem writes and built-in execution | No reachable dispatch/execution route; attempts fail before side effects. Read-only filesystem mode alone is insufficient. |
| MCP, plugins, skills and connectors | No discovery/startup/action capability from user or project configuration; synthetic effect canaries remain untouched. |
| Hooks | No project/plugin hook lifecycle executes; repository scanners/security hooks remain intact for execution and ordinary checks. |
| Goals and proactive work | Fresh conversation starts no inherited goal; no autonomous continuation on initialize, reconnect, follow-up or idle. |
| Delegation and dynamic tools | No spawned child and no host tool authority; ignored mode hints and empty dynamic-tool arrays are not proof. |
| Escalation and approval | Requests cannot upgrade assessment; unexpected requests fail closed and visibly stop assessment. Project automatic approval cannot apply. |
| Network and external effects | No model-accessible effect transport, even through an integration whose permissions bypass the local filesystem sandbox. |
| Evidence and output | Only checked packet/messages cross the boundary; scanner failure withholds content and preserves drafts. No raw transcript/error logging. |

An adapter that rejects host callbacks still cannot prevent built-in tools executed internally
by App Server; test and verify that internal boundary too. Where effective isolation cannot
be established, the alternative is a separately approved supported tool-free model transport,
with the same model, usage, scanning and credential-provisioning review. Do not silently adopt
a new provider, paid service or authentication scheme. The choice is an implementation blocker
for platform/security/architecture and a human decision if it changes product integration or
cost expectations. A packet viewer alone does not meet the required assessment conversation.

## Crash recovery, rollback and monitoring

Persist operation preparation, holds and linkage transactionally before mutating native
state. A crash after preparation or transport write produces delivery-unknown and a recheck;
startup never retries a model request, continuation, approval, interrupt or attachment.
Reconcile IDs against scoped observations; matching text, a later timestamp or the newest
turn alone cannot identify an uncertain dispatch. Expire in-memory receipts on connection
generation changes while retaining safe historical observations and drafts.

For upgrade, stop the known dashboard cleanly and make an owner-only, consistent SQLite
backup with its schema/code version using a reviewed local backup path. Protect runtime
state as sensitive, exclude it from Git and avoid inspecting its private contents for this
design. Restore only a matching code/state pair in isolation. Restoring a backup cannot
restore live authority, resolve external effects or undo a model turn. Reconcile any work
started after the backup and preserve unresolved holds before enabling execution.
Feature rollback disables recovery mutations, expires receipts and preserves hold/operation
records; it must not let older code treat the project as free. Unknown future schema fails
closed. Test rollback after a continuation has started, not only before first use.

Use bounded allowlisted operational events: operation kind/ID, task linkage, fixed reason
code, generation, duration and state transition. Monitor hold count/age, incomplete coverage,
unknown deliveries, stale/duplicate submissions, lock conflicts and assessment capability
failures. Show these locally with source/freshness; do not export telemetry, raw RPC, prompts,
command strings, paths containing unnecessary personal data, model reasoning or environment.
Alert text must remain safe even when native errors contain synthetic secret-like content.
No new infrastructure or operational spending is selected by this design; explicitly
started assessment/continuation can consume workspace model usage, with missing cost Unknown.

## Required evidence and named handoffs

| Evidence type | Required checks before feature closeout | Owner |
| --- | --- | --- |
| Unit / mocked protocol | Lost Stop acknowledgement, terminal root with live child, partial discovery, missing process identity, PID reuse, stale boot record, wrong boot source, hold persistence, duplicate dispatch and scanner failure. Assert Check never mutates native execution. | Backend; independent QA retest |
| Native integration in separately authorized isolation | Real root/child and synthetic long-running subprocess; observe interruption separately from process exit. Test detached/reparented child, goal, background terminal, missing callback and disconnect. Verify shutdown/initialize/reconnect never resumes old work. | Platform; security review and QA |
| Native assessment in separately authorized isolation | Actual useful response and repeated follow-up while old project is held; missing-history packet works; synthetic shell/MCP/plugin/hook/delegation/goal/network attempts cause no effect and cannot upgrade authority. | Platform/security; independent QA |
| OS integration in isolated environment | Duplicate dashboard owner, owner crash, reused PID, process-group escape, runtime-root conflict, actual reboot with boot fence, refused restart, unavailable boot metadata and no-auto-start verification. | Platform; security review |
| Browser | Unknown task to assessment reply/follow-up to explicit permitted continuation and observed result; unresolved legacy process still reaches assessment; concrete restart steps and persistent hold; stop request remains Stopping until evidence; drafts survive failures. | Frontend; independent QA |
| Rollback / recovery | Crash at each prepare/write/ack boundary, stop during shutdown, code/state backup restore, old receipts rejected, unresolved holds retained, later-started work reconciled and no automatic replay. | Platform/backend; independent QA |

Executed for this document: bounded repository source and installed generated-schema
inspection only. No test rows above were executed. Native tool isolation, full process
containment, OS boot verification and positive end-to-end recovery remain unproved.
Technical writer owns verified operations documentation after implementation; user writer
owns exact manual-recovery copy; architecture owns the clearance contract; Chief of Staff
tracks blockers/decisions; Agent Evaluation checks that the user can actually reach assessment
and separately approve a usable continuation rather than receiving an unexplained dead end.

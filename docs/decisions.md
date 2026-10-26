# Decisions

## 2026-10-26 — Claude Code adaptation: Phase 0 and Phase 1 decisions

Recorded by who decided. The evidence is in docs/superpowers/spikes/ and
docs/superpowers/evidence/2026-10-26-phase-1-live.md; the design is
docs/superpowers/specs/2026-10-26-claude-code-adaptation-design.md.

Owner decisions (in chat, 2026-10-26):
- Keep both Codex and Claude Code. The team and the dashboard both move; the dashboard follows in
  later phases. The dashboard is to start and own Claude runs and later also observe the owner's
  own sessions, including approvals (confirmed as a later phase whose feasibility Phase 0 was to
  test).
- One shared model policy file with a column per tool. Keep the 14 roles and add superpowers as
  process discipline. Consolidate in one repo on a branch.
- Claude sign-in is the owner's subscription login, for personal local use. The terms question
  (the Anthropic SDK note about third-party use of a claude.ai login) is left to the owner's own
  judgement and is NOT resolved.
- Ponytail is not used on the Claude side. Dashboard approach: backend adapter, phased.
- The Phase 0 report was accepted and spec amendments A1-A10 applied.
- Claude model column: opus/medium for chief_of_staff, product_manager, ui_designer,
  frontend_developer, qa_engineer; opus/high for technical_architect, backend_developer,
  platform_reliability_engineer, security_reviewer, code_quality_reviewer,
  agent_evaluation_engineer; sonnet/high technical_writer; sonnet/medium
  user_documentation_writer; opus/low expert_escalation (the `fable` alias is credit-gated off at
  the owner's organisation, S5).
- General guidance lost in translation is restored for Claude through claude-only lines in the
  roles' own words. expert_escalation's shared description is made neutral (this changes the Codex
  description too). The Chief of Staff's pre-existing broken sentence is presented whole for
  Claude only; Codex is unchanged.

Plan and controller decisions (the owner may overturn these):
- Reviewer roles get only Read, Grep and Glob, because a role with Bash gains a write route once
  Bash is approved (S4). Every role except chief_of_staff has `disallowedTools: Agent`. The live
  runs observed the Agent tool removed; the setting removes only that tool.
- Ponytail and ui-skills-root text is codex-only. AGENTS.md is not split: CLAUDE.md imports it and
  its differences section scopes the exclusion to the first paragraph under `### Ponytail pilot`.
  Subagents receive CLAUDE.md and AGENTS.md as context, so the paragraph is switched off, not
  removed.
- Sync never deletes files and renders everything before writing. The Codex dashboard files and
  docs outside the new sections were left untouched.
- The project's Codex-style workflow gates were NOT followed for this work: no technical_writer or
  user_documentation_writer closeout and no agent_evaluation_engineer checkpoint. The Claude-side
  superpowers process with independent task reviews was used instead. Per AGENTS.md this is a
  recorded gap, not a passed gate.

Open items: Phases 2 and 3 not started; launch mode `--setting-sources user` provisional (S1);
hook-based approvals do not reach Auto-mode calls (S2) and the hook payload has no tool_use_id;
the S3 `--forward-subagent-text` effect is inconclusive; `fable` untested; interactive mode and
Auto-mode behaviour untested; the `CLAUDE_EFFORT` variable was not investigated;
AskUserQuestion-in-subagents is docs-sourced; "Astra" wording remains in dashboard/team.py,
README.md, docs/team.md, docs/decisions.md and docs/model-policy.md; deferred minor review
findings (team_source test polish, sync_roles.py CLI polish, docs gaps) are in a local, untracked
working ledger, not in the repo, and go to the final branch review, which was pending when this
was written.

## 2026-10-26 — Native approval parity and human verification steps

After another unsupported-request screenshot, the human requires actual native Codex requests
and approve/reject choices in the dashboard. The installed App Server schema and current official
documentation distinguish command/file approval, turn-scoped permission requests, native input
approval choices and MCP elicitation. Preserve each native response shape and actual scope;
new kinds remain manual. Do not label a turn-wide permission grant as one-command approval.
The human clarified: “Human steps are good.” External sign-in and device verification may require
an explicit human step; the dashboard must explain and expose that path and native negative
choices without manufacturing verification proof or automatically navigating external links.
This does not authorize granting any currently pending request or changing project policy.

## 2026-10-26 — Execute the reviewed UI improvements

The human authorized team review, planning and efficient implementation of the UI review.
The UI Designer and Technical Architect reviewed both reports. Implementation order is reading
stability and unsupported-request exits, safe completed-task Outputs, full decision accounting,
then secondary delivery summaries. Keep existing themes, polling, exact-request authority and
the separate execution/delivery/release states.

Routine implementation contract: explicit output registration binds a project-relative path to
the server-owned task and current turn, using existing scanned text preview controls and a
recorded content digest. Historical completed tasks have an explicit human attach path.
Never infer artifact associations from model prose. Changed, missing and blocked content remain
distinct. State polling exposes output metadata and historical delivery summaries without
per-row project snapshots; only existing fresh detail validation can authorize delivery actions.
The full-queue action explicitly says it clears filters and does so only on the user's click.
Security reviews new file/identity boundaries; independent QA and reviews remain required.
No release, publication, new upstream request support or application redesign is authorized.

### 2026-10-25: conversation reading-position review

The human reported refresh repeatedly resetting conversation reading position. Lina's source
review identifies full log replacement without scroll restoration when the render signature
changes. Preserve reading position and conditionally follow the bottom as a prioritized repair
proposal; no app change is made by this review. Root in-chat browser verified only that an
unchanged completed conversation retained its bottom position after refresh. Changed-data
browser reproduction/retest remains assigned to QA; no native work was started to force it.

### 2026-10-25: UI review follow-up and completed-task outputs

The human requested Lina Cass's UI Designer review of the recommendations and an assessment
of visual improvements. The human also explicitly required completed-task outputs, using a link
to the generated Markdown review as the example. Record this as requested product behavior;
the current task updates review artifacts, not application code. Safe task/project association,
direct checked preview and honest missing/changed output states remain implementation design
work. Do not treat an accessible output as delivery acceptance or release authorization.

## 2026-10-25: Direct dashboard run deletion

The human requested a way to delete a run after unresolved recovery state blocked a new UI
review. Add direct confirmed local-history deletion for terminal/Unknown runs and release
their holds without assessment, continuation planning or boot checks. Preserve honest native
uncertainty: deletion does not stop execution or undo files. Known live roots/children and
in-flight operations require Stop first. Use existing same-origin boundaries, a current
confirmation fingerprint and one storage transaction before in-memory removal. Test the
positive delete/unblock journey, persistence failure, stale confirmation and late callbacks.
This authorizes a capability; no particular live record is deleted during development.
Development closeout: 551 project-environment Python tests and 109 UI tests passed; independent
QA/security/code review and both documentation writers closed. Retry after uncertain requests
and focus restoration after Recovery polling were fixed and retested. Disposable browser
evidence covers both entry points, acknowledgement gating and cancellation; actual deletion
and same-project relaunch are verified through synthetic HTTP/DOM tests, not real native work.
The human approved restarting the idle dashboard with the current combined working tree.
Graceful restart and App Server reconnection were verified; exact ID/status comparison retained
all 10 runs and both projects. All tasks now expose deletion eligibility/version, including both
eligible Unknown runs. Live browser verification opened and cancelled the blocking run's
confirmation, restoring focus and preserving the record. No live run deletion, model work or
publication was performed. This restart also loaded other current local changes in the shared tree.

## 2026-10-25: UI Skills guidance for design and implementation

The human requested ui-skills-root reinforcement for the UI Developer and clarified that
UI Designer should receive it too. Add maintained-skill routing to frontend_developer and
ui_designer, scoped to each role's ownership. Keep Ponytail Full in Frontend and retain
existing permissions, accessibility and independent review requirements. Reference the
installed root skill rather than duplicating its full contents. This changes future role
instructions; existing invocations are not refreshed and CLI/runtime behavior is unverified.
The human also requested portability documentation for Ponytail and confirmed the UI skill is
ui-skills-root. Document per-machine external installs and environment checks in
docs/skill-setup.md, linked from README and team guidance; resolve skill paths through the
catalogue instead of a developer's username. Preserve the existing approved Ponytail runtime
version/hash. UI CLI version locking and clean-machine installation remain unverified;
documentation does not install or update dependencies automatically.

## 2026-10-25: Fix all nine Ponytail audit findings

The human requested all reported fixes using Ponytail when useful. Keep the current local
Python/SQLite/browser design and dependencies; repair shared causes, preserve safety gates
and remove unreachable native-assessment branches. Read-only metadata timeouts must not
terminate unrelated work. Descendant checking must cover the observed 25-child case with
bounded complete checks, not clear incomplete evidence or weaken ownership/boot fences.
Writers and independent quality reviews remain part of development and delivery.

## 2026-10-25: Implement assessment handoff as a feature

The human approved a checked evidence handoff for assessment in an existing approved chat,
returning the assessment for explicit local review before separate continuation-plan approval.
Present it as a general recovery feature. Corporate sign-in limitations belong in dated
development history, not the feature rationale or UI. Keep uncertain outcomes, project holds,
fresh activity checks and native permission boundaries; handoff never starts native work or
automatically transmits evidence. Architecture and security review preceded implementation. Independent QA and reviews
verified the handoff source and fixes, and the full Python/UI suites passed. The update was
applied locally under the earlier human approval to restart and begin live recovery validation.
Existing tasks were preserved, and no model work or continuation was started.

## 2026-10-25: Corporate account blocks the assessment sign-in route

The human attempted sign-in and reports that corporate account policy prohibits Sign in
with ChatGPT. The current assessment integration is therefore unusable for this account;
real assessment and native continuation remain uncompleted. Preserve the existing-Codex-only
and no-separate-API-billing direction. No policy bypass, personal-account substitution or
credential reuse is authorized. Technical Architect will review existing native capabilities
and safe alternatives. Source review confirms native assessment is explicitly disabled,
with no verified enforced tool-isolation or credential bridge. A previewable scanner-checked
evidence handoff and human-reviewed returned assessment is a proposed alternative only; its
export/import and acceptance workflow needs a product decision and reviewed implementation.
The existing assessment annotation cannot satisfy the assessment gate or unlock continuation.

## 2026-10-25: Human approved local application and live validation

The human approved restarting the dashboard with the recovery update and beginning live
validation. The service reconnected without replaying work; existing unknown records remain
unknown. The human completes ChatGPT sign-in directly, with only bounded status inspected
afterward. This approval does not authorize an OS reboot or native development continuation.
Live metadata exposed incomplete descendant coverage, which remains a development blocker
alongside the existing recovery gates. Reboot alone is not sufficient evidence to clear it.

## 2026-10-25: Recovery candidate review closeout; release validation pending

The implemented candidate preserves the human's assess-first, separately-approved-continuation
choice and ChatGPT-sign-in-only direction. Independent security/correctness findings were
remediated and retested. Documentation owners closed their source reviews; the test board
separates synthetic protocol/browser/pipe evidence from native startup observations. Two
scanner findings were synthetic authentication test construction, now corrected and rescanned;
no real credential incident or scanner-rule change occurred.

At this pre-restart checkpoint, the running dashboard had not been updated; application
was awaiting the human release decision subsequently recorded above.
Real account eligibility, sign-in, useful repeated inference, any separately chosen OS reboot
and native recovery continuation still need live validation. No outcome of an uncertain old
operation is inferred from these checks, and no production task is resumed or replayed.

## 2026-10-23: Recovery keeps ChatGPT sign-in and plan usage

The human rejected a separate API-key/billing integration and requested Codex/ChatGPT sign-in,
including an in-dashboard sign-in flow if reauthentication is needed. The installed App Server
has no verified complete tool-free assessment boundary. Official public Sign in with ChatGPT
documentation provides a direct ChatGPT-plan OAuth route without a partner API key or client
secret. Implement that explicit sign-in and a separate text-only assessment transport; actual
development continues through the existing dashboard-managed App Server.

Never read or copy Codex credential stores. Keep this assessment session's OAuth tokens,
authorization codes and PKCE transaction material in process memory only; persist only
nonsecret host/client registration and validated identity fingerprint. Reauthentication never
replays work. Token signature verification uses maintained pinned JWT/cryptography dependencies.
Account/workspace eligibility and completed live inference remain unverified until the human
completes consent and an isolated assessment succeeds. No API-key or separately billed fallback,
model substitution, or automatic account switch is authorized.

## 2026-10-19: Implement the reviewed recovery design

After receiving the reviewed proposal and its remaining proof requirements, the human requested
implementation of that design. Proceed with mandatory assessment first, a separately approved
versioned fresh continuation plan, same-thread restoration only where verified safe with a
linked fallback, and Manual native approvals during recovered execution without changing the
saved project preference. This authorizes implementation, not weakening capability gates or
claiming unexecuted native proof. A legacy OS restart is offered only as an optional separately
chosen human operation; never initiate it automatically. Do not resume/replay production work
for tests. Prepare reviewable isolated probes before requesting any required native execution
authorization. Keep the current dashboard live while developing and reviewing changes.

## 2026-10-19: Design unknown-task recovery (proposal work authorized)

The human requested a safe recovery workflow design after finding that unknown tasks cannot
accept conversation follow-ups after restart. Prepare a reviewed proposal covering evidence
inspection, restoration where supported, a usable conversation alternative, fresh explicit
guidance, approval boundaries, uncertainty and failure recovery. This authorizes design work;
product and architecture choices remain proposed until human agreement. Existing no-replay,
secret-handling and request-scoped authorization requirements remain binding. No production
thread is resumed or altered as part of the design investigation.

The human subsequently chose: assess first, then human approval of continuation. The proposal
must enforce that sequence, while allowing questions and evidence discussion before write
authority is restored. Same-thread restoration details and other architecture choices remain
proposed pending design review and human agreement.

## 2026-10-18: Documentation and ongoing agent quality review

The human requested documentation throughout development and continuing agent quality review.
Require Technical Writer involvement for each development task, with User Documentation Writer
for changed user behaviour. Record documentation impact at intake, supply verified evidence
during implementation, and obtain writer closeout before declaring completion. Keep shared
status and decisions current, including failed checks, blockers and interruption handoffs.

Invoke Agent Evaluation at development checkpoints and before completion, independently from
product QA. Record sources, observed outcomes, corrections, handoff quality, documentation
coverage, findings, owners and retest evidence in docs/model-evaluation.md. Historical records
do not establish fresh verification; unavailable model/runtime usage and costs remain unknown.
Missing specialist review is a recorded gap, not a passed gate. This establishes task-triggered
delegation, not a scheduled or continuously running service. No paid comparative benchmarks,
model-policy changes, dashboard restart, deployment or publication are included.

## 2026-10-18: Team activity and delegation drill-in

The human requested per-member work on Team, including Chief of Staff delegation, and drill-in
from Overview Task activity to delegated activities and status. Reuse observed native activity
records, expose a field allowlist, and keep them separate from root-run counts and cost estimates.
Show direct/delegated history per role with project filtering and coordinating-task navigation;
show nested native parentage in task details only where recorded. Unknown historical parentage
must not be attributed to the Chief of Staff by inference. Child pending requests affect that
child's status; completion, interruption and connection loss remain event-derived.

Delegated labels remain generated role titles with coordinating-task context: native metadata
has no separate checked assignment-description field in this implementation. Raw delegated
prompts, reasoning and tool transcripts remain excluded under the existing retention policy.

## 2026-10-18: Inspect personal agent prompts

The human requested personal prompts in the Team view via a Details button. Display the exact
role instructions loaded by the dashboard in a read-only plain-text dialog. Retrieve only the
selected known role on demand after sensitive-content checks; withhold text if checking fails.
Keep prompts out of polled state and roster payloads. Explain that shared security and task
instructions are additional context, so the display is not a complete run transcript.

## 2026-10-16: Run the team in Codex

The human selected Codex and requested a new Git repository that keeps secrets out of Git
and documentation. The workspace already contained an empty repository without commits or
remotes, so initialise the team there rather than nesting another repository.

Initially use project-scoped custom agent definitions with inherited model selection and bound
concurrency to three child agents; actual session limits take precedence.

Use Gitleaks with complete staged-file scanning and pre-push history checks. Reject common
credential paths even if force-added. Keep secrets outside the project. Remote hosting,
server push protection, and product technology choices remain unresolved.

The human subsequently selected GitHub and will supply the account and repository name.
Keep this repository local until the destination and remote controls are configured.

An independent security review identified gaps in explicit-object pushes, tag annotations,
and unquoted credential assignments. The implementation was corrected and regression tests
added before the initial commit.

## 2026-10-16: Expand ownership and assign models

The human approved adding Technical Architect, Platform & Reliability Engineer and Agent
Evaluation Engineer. PM/UI explicitly own usability research; QA includes relevant accessibility,
performance and recovery checks.

Pin core engineering roles to GPT-6.1 Sol with Medium or High reasoning, documentation roles
to GPT-6 Luna, and an on-demand expert escalation profile to GPT-6 Astra / Low. Configure the
primary chat and otherwise unspecified subagents to Sol / Medium, retaining the concurrency cap.
The separate Astra profile is required because custom role model settings take precedence
over explicit spawn settings. This policy supersedes the initial inherited-model choice.

The human uses a Business or Enterprise workspace; the exact agreement is not confirmed.
Cost savings and task quality must be measured rather than assumed. Record evaluations using
docs/model-evaluation.md. No comparative model trials have been run yet.

## 2026-10-16: Build a live local development dashboard

The human selected multiple projects, local operation on this Mac, Python/SQLite/browser UI,
and live Codex integration. A manual ledger alone does not satisfy the requested first version.
After a supported-existing-session connection was not demonstrated, the human selected
dashboard-managed runs via a dedicated Codex App Server. Existing desktop chats are outside v1.

The app initializes the server without starting a model turn. A human Start run action supplies
the project, role and instruction. App Server events drive sanitized persistent projections.
No secret-store access, transcript-file reads or raw event logs are needed. Costs are unknown
until suitable observed usage/model/tier evidence allows a clearly labelled credit estimate;
estimates are never presented as verified Business/Enterprise charges.

V1 displays pending native approvals and allows decline or interruption. It does not grant
permissions from a generic sanitized summary. A future acceptance flow needs sufficient exact
review context and independent security review. Disconnect invalidates pending controls and
marks active work unknown, without replaying inference or approvals.

## 2026-10-16: Add manual file review and controlled Git publishing

The human requested read-only project-file inspection, Git status and a publish option, then
specified the public GitHub repository K55Toms/KT_Agent_Dev_and_Dash. The repository was created
empty and connected as origin. Repository metadata confirmed public visibility, secret scanning
and push protection enabled. No source code was pushed during repository creation.

File access is confined to registered Git working trees, nonignored safe text, no symlinks or
credential/runtime paths, and a successful fixed-policy secret scan before any preview. Git
publication uses explicit destination/branch/commit confirmation, rejects dirty or changed
snapshots, runs full secret checks and preserves normal hooks. No implicit stage/commit or force
push is included. Native Git authentication remains outside the dashboard.

## Personal identity and design exploration

The dashboard uses the supplied original silver-on-navy logo and the name Kristian’s Rebellion Builders. Three isolated browser previews at /designs explore Terminal Ops, Rebel Command and Hybrid Night Shift. Their tasks, usage and approvals are illustrative. Theme selection changes only the preview; the production theme awaits the human’s choice. Rebellion-inspired colors are a design interpretation.

The human selected Hybrid Night Shift for the live dashboard. Terminal Ops and Rebel Command
remain available through the appearance-only dashboard/config.toml setting, applied on page reload.

Graceful server shutdown drains bounded HTTP handlers before process exit so explicit publication
helpers retain timeout and cleanup guarantees. Independent synthetic success/timeout checks passed.

## Dashboard settings and repository creation

The human requested in-dashboard configuration for all supported config.toml preferences,
including name/logo/theme and GitHub account/visibility defaults. Private is the initial default
for new repositories; existing repositories retain their visibility and origin. Repository
creation is explicitly confirmed and separate from publishing commits. Uploaded logos remain
local runtime files outside Git; configuration contains only a validated local reference.

The human requested agent conversation after Settings: answer agent questions and send follow-up
guidance from dashboard-managed runs. Existing desktop session sync remains outside current scope.

## Managed conversations and Rebel crew

After Settings, the human requested agent question replies/follow-up guidance, a fictional named
team with themed portraits, observed last work and agent-to-agent logs. The human chose automatic
Chief of Staff recognition rather than human approval for each internal, nonmonetary award.
Visible complete messages are checked before display/persistence in private ignored SQLite;
reasoning and raw tool content remain excluded. Existing desktop-session sync remains unavailable.
Recognition has bounded evidence-backed issuance and no invented initial history or scheduler.

## Failed launches and CLI compatibility

The first human-started dashboard run failed before a native thread was registered. Its original
raw error was discarded, so its precise historical server response cannot be recovered. A fresh
thread-only reproduction isolated a project configuration parser rejection: desktop-specific
scalar entries under `[agents]` were interpreted as CLI agent definitions. The outdated CLI
catalogue advertised GPT-5 models that real execution rejected. Official current model docs
confirm GPT-5.5 and GPT-5.4 retirements for ChatGPT sign-in and the original GPT-6 IDs as valid
CLI choices. Retain the original approved profiles; the diagnostic fallback trials did not
establish a working replacement or comparative quality/cost result.

Failed activity must open task details with bounded, fixed-vocabulary launch checkpoints,
failure reason and next action. Raw protocol errors, stderr, tool output and reasoning remain
withheld. Historical missing diagnostics are labelled unavailable rather than reconstructed.
Ambiguous execution outcomes remain unknown and are never automatically replayed.

On 2026-10-18, the updated CLI 0.163.0 completed an isolated GPT-6.1 Sol health-check turn,
reported usage and created no project files. The named profile retains the original broad-read,
project-write boundary, explicitly disables command networking and routes approvals to the user.
The stronger restricted-read helper failed on this Mac; credential-read prohibitions remain
agent policy, not filesystem isolation. The original human instruction was not replayed.
Latest regression suite: 167 tests passed; independent targeted review: 56 tests passed.

## 2026-10-18: Human approval from the dashboard

The human requested an approval action after encountering the decline-only implementation.
Add a separate, complete-context review step for supported native command and file-change
requests. Acceptance must bind to the exact live request and reviewed contents, not a generic
summary or historical record. Review contents are ephemeral and checked before display and
acceptance; they are not stored in the runtime database, logs or conversation history.
No session-wide grants, remembered command rules or automatic decisions are included.
Applying backend changes requires a restart; an existing ephemeral pending request cannot be
transferred to a new App Server. Do not approve, replay or interrupt the human's pending work
as part of synthetic tests or the upgrade without the human's explicit choice.

Verification included an isolated native GPT-6.1 Sol request to run only `/usr/bin/true`:
complete-context review, one-request acceptance, native command execution and turn completion
all succeeded; no project files were created. The live pending human request remained untouched.
The installed native client marks local command requests with `environmentId: "local"` and
explicitly offers `accept`; the review preserves both values. Other environments, managed-network
batch prompts, interactive stdin, file-root/session grants and missing native acceptance choices
remain unavailable for grants. Independent review fixes cover uncertain-delivery replay,
conflicting RPC IDs, incomplete item context and approval expiry for child agents.

## Delivery lesson: incomplete approval journey

The first dashboard brief explicitly deferred acceptance and shipped decline/stop controls.
This was a scope and acceptance failure, not evidence that a particular named agent forgot
a button. The Chief of Staff owns the delivery decision. Strengthen Product Manager journey
definition, independent QA's positive end-to-end checks and the Chief of Staff's completion gate.
Compare the agreed brief with the original human outcome; do not silently substitute a narrower
implementation contract. The three role prompts and AGENTS.md now state this requirement.

The human authorized stopping the existing waiting run and restarting the dashboard. The
interrupt was acknowledged, active runs reached zero, and the updated dashboard reconnected.
The interrupted task's file edits were preserved and its instruction was not replayed. Final
checks: 191 Python tests, 12 UI tests, 14 TOML profiles parsed and 7 prompt endpoint tests passed.

## 2026-10-18: Resolve blocked approvals and choose project approval mode

The human requested a resolution path directly from a blocked approval, including chat guidance,
and a choice between approving once and accepting risk for future runs in the selected project.
Use an approval-scoped guidance action: queue checked guidance for the exact live turn before
declining the captured request. Guidance never grants permission by itself. Ambiguous delivery
must not cause automatic retries or execution replay.

Project approval modes belong in Settings and nonsecret `config.toml`, defaulting to manual.
Explicit automatic mode applies to eligible future callbacks from that project, with complete
context validation and scanning. It does not change sandbox defaults or replace separate release
authorization rules. Originating-project association does not confine command effects to project
files. Revoke through Settings; already-delivered decisions cannot be recalled.

Compatibility inspection confirmed native subcommand callbacks may differ from their cached
parent command and that some optional text and file diffs may legally be empty. The live waiting
request's exact rejection cause remains unverified. An isolated native compound-command approval
round trip completed without creating files; this run did not emit a subcommand callback, so
subcommand compatibility also requires schema-based regression coverage.

The native recovery probe exposed a separate protocol constraint: its offered decisions included
Cancel but omitted a decline that continues the turn. The explicit cancel flow therefore sends
checked guidance, cancels only the captured request, waits for observed interruption and requires
a separate human follow-up action. A live isolated test verified this full cancel/interruption/
follow-up/new approval/completion sequence without creating project files. It does not establish
the original production review failure's exact cause.

Use verified team-role mappings for conversation names. Keep runtime identifiers as secondary
details and show unknown agents honestly rather than guessing a team member.

## 2026-10-18: Native delegation and explicit sensitive-request review

The human authorized correcting missing dashboard delegation. A no-inference isolated check
reproduced a missing-history failure when forking an ephemeral source. Managed parents now use
verified persistent native history. All 14 configured roles are explicitly registered for every
managed project with checked private snapshots that repeat the shared security instructions.
The installed runtime emits modern `subAgentActivity` items; ignoring them prevented child
ownership and approval routing. Track lineage from owned-parent native events, then resolve known
role metadata with bounded metadata-only requests. Never read stored native conversations.

A real isolated run started the configured Backend Developer from the Chief of Staff, routed
and accepted the child's exact harmless command, observed child and parent completion, and
created no project files. This verifies the native delegation and child-approval path; mocked
event tests remain separate evidence. Native history is a separate CLI-managed retention store,
outside dashboard scanning. No old task is automatically resumed, migrated or replayed.

The human explicitly selected revealing exact sensitive requests locally and approving once.
Keep the scanner and Git controls intact. Permit only an explicit local reveal followed by a
separate human decision on unchanged complete live context; never extend this exception to
automatic project policies. Distinguish findings using a dedicated scanner findings exit code;
scanner failures cannot authorize reveal or acceptance. Keep revealed bytes out of dashboard
logs, SQLite, documentation and screenshots. Codex may retain underlying native history.
The local dashboard trusts same-user processes; this feature does not add administrator login.

### 2026-10-25: local commit of reviewed recovery and audit changes

The human requested a local commit of the cumulative development changes. Final integrated
verification passed 487 Python and 86 UI tests. The audit update was applied locally with
existing task counts preserved and no active work or decisions. The metadata-only check
of an existing unknown task returned unavailable coverage; execution remains blocked.
Commit records the reviewed source and this unresolved live-validation item, without
asserting complete recovery, authorizing native continuation or authorizing a push.
Backend and Platform retain ownership of metadata diagnosis and a bounded live retest.

### 2026-10-25: resolve unloaded-thread recovery metadata

The human requested a Ponytail code fix. A reviewed diagnostic-only update confirmed that
the loaded-thread-only background-terminal RPC rejected the unloaded historical root.
Recovery now reads fresh root/descendant identities and goals and validates a complete current
loaded inventory on the same observed startup connection. It does not resume a thread to
inspect it. Unsupported or failed reads preserve validated partial evidence and fixed error
labels; no raw upstream error strings are recorded. Existing boot-fence, exclusive-owner,
external-activity and separate human continuation approval checks remain mandatory.

After application, the original task's live metadata-only check returned complete coverage
for 38 descendants with no unresolved current children. Historical child/turn uncertainty and
the required boot fence still block continuation. This resolves the metadata compatibility
failure, not historical outcomes or native continuation. No OS restart or inference occurred.

### 2026-10-25: pilot Ponytail Full in implementation roles

The human approved Ponytail Full defaults for Backend and Frontend, with independent Code
Quality Review, explicit Chief of Staff handoffs and Agent Evaluation follow-up. AGENTS.md
identifies the maintained installed skill; profiles reference the pilot rather than copy its
full text or hardcode a cache version. The pilot preserves complete user journeys, security,
accessibility, required checks, documentation and approval boundaries. No new role, model,
dependency, automatic execution or benchmark batch is introduced. Static propagation will be
verified; future behaviour, savings and broader rollout require observed task evidence.

Pilot application evidence: the idle dashboard was reloaded and its five checked role-prompt
endpoints matched the new profiles. Existing task/decision counts were preserved. This verifies
configuration propagation, not future model behaviour or measured savings.

### 2026-10-25: enforce Ponytail inclusion and delivery evidence in code

The human approved both proposed controls. Before managed dispatch the dashboard validates
the installed Ponytail Full 5.3.2 skill against the reviewed SHA-256 pin, scans its bounded
bytes, injects it into Backend/Frontend parent and registered delegated profiles, and records
policy/role fingerprints. Missing or altered sources/profiles block new work. Browser callers
cannot enroll a policy path or digest. Unknown native roles block delivery verification; the
dashboard does not claim it can intercept every native internal spawn before execution.

Delivery readiness is separate from native turn completion. The owner approves exact project
check commands, explicitly starts a QA task through the existing native sandbox/approval flow,
and receives evidence only from that owned task's current successful command lifecycle. A
separate registered reviewer produces a complete checked report; a fresh owner decision binds
that report to current code, policy, plan and check evidence. No host shell test runner, automatic
native approval, publication or model-judgment guarantee is introduced.

Snapshots cover bounded safe Git-visible paths and bytes, including file modes, opaque assets,
HEAD and root identity, with post-scan revalidation. Tracked files cannot disappear through an
ignore rule. Ignored untracked/runtime files and execution environments are outside that code
snapshot; hashing an image is not a visual or complete secret review. Old tasks remain explicitly
unverified/unenforced. A coordinating task with registered implementation children is eligible;
unattributed children cannot earn readiness.

A reviewed policy update invalidates old delivery evidence. New checks and independent review
may qualify the existing code under the new policy without replaying implementation; original
execution policy metadata remains historical. Lost acknowledgements reconcile durable identities
separately from current readiness. Explicit retries retain the original request/UUID, version or
single-use receipt; no retry is automatic. A consumed failed decision receipt requires a fresh
review after repair, rather than reviving old acceptance authority.

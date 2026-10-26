# Task board

- Claude Code adaptation, Phase 0 and Phase 1 (2026-10-26): IMPLEMENTED; merged into local `main`
  by fast-forward on 2026-10-26 at the owner's choice (the owner chose "merge back to main locally"
  in chat after the finishing menu; that chat decision is the authorization, and it is recorded
  here and in docs/decisions.md because the earlier records did not show it). NOT pushed, no pull
  request. The three closeouts were RUN on 2026-10-26 after completion (read-only; verdicts and
  dispositions under CLOSEOUTS below). The independent security review is APPROVED by the owner and
  PENDING: it has not been done and nothing here says it passed. Phase 0 spikes S1-S5
  (findings in docs/superpowers/spikes/); the owner accepted the Phase 0 report and amendments
  A1-A10 were applied to the spec. Phase 1: shared role source `team_source/` (14 role files with
  whole-line codex-only/claude-only blocks, parser and renderers, a model policy file with a Codex
  and a Claude column, stdlib only); `scripts/sync_roles.py` (writes 14 `.codex/agents/*.toml` and
  14 `.claude/agents/*.md`; `--check` reports drift; never deletes); a drift test over the real
  repo; `CLAUDE.md` (imports AGENTS.md, Claude Code differences, process);
  docs/claude-code-setup.md; short Claude Code sections in README.md and docs/team.md. The Codex
  dashboard was not modified. All 14 `.codex/agents/*.toml` files gained a two-line generated-file header,
  4 of them also changed key order, and `expert_escalation` also changed its description (the owner approved a neutral rewording; the exact wording, "On-demand escalation
  specialist for consequential ambiguity, difficult defects or sensitive reviews.", was chosen by the
  controller and shown to the owner in the Task 10 review); parsed Codex
  values are otherwise identical to the original files (proved by script against origin/main).
  CHECKS RUN, by evidence type. Synthetic/automated, Task 13 (controller-run first-hand at the end
  of Task 13; three evidence-file commits followed it, which changed no test): Python suite 667 run; in the normal environment 2 failed
  (tests/test_git_service.py: test_dirty_counts_and_credential_paths_hidden and
  test_historical_forbidden_path_is_rejected_before_scanner_reads, pre-existing, caused by this
  machine's global git ignore file ignoring `.env`, not by this work) and 36 skipped (PyJWT not
  installed); with XDG_CONFIG_HOME pointed at an empty temp directory 0 failed, 36 skipped. Node
  `node --test tests/*.js` 126/126 (`node --test tests/` runs zero tests on Node 26).
  `sync_roles.py --check` clean; `scripts/security_check.py` staged and history pass. Codex
  parsed-value identity check against origin/main: only expert_escalation/description differs.
  Task 14 run, after 5 doc tests were added when the docs were refreshed with live evidence:
  Python 672 run, in the normal environment the same 2 failures and 36 skipped; with the empty
  XDG_CONFIG_HOME directory 672 run, 0 failed, 36 skipped; Node 126/126 again. Arithmetic: baseline
  584 run (546 passed, 2 failed, 36 skipped) + 83 (team_source, sync and doc tests at the end of
  Phase 1) = 667, + 5 doc tests = 672, so 88 tests added in total. Native Claude Code evidence,
  separate from the synthetic tests: 10 short headless runs on the owner's subscription, Claude
  Code 2.1.310, one run per condition, results in
  docs/superpowers/evidence/2026-10-26-phase-1-live.md. Cost: about 1.13 USD is the tool's computed
  estimate on a list-price basis (modelUsage costBasis "list", see
  docs/superpowers/spikes/S3-event-stream.md and the Phase 0 findings); it is not a charge. This is
  native evidence, not mocks, and does not show stability. OPEN ITEMS (recorded gaps, never passed
  gates): the agent_evaluation_engineer checkpoints that AGENTS.md requires during development were
  NOT run and cannot be run retroactively, a permanent process gap (the evaluator's after-the-fact
  checkpoint is under CLOSEOUTS); the Claude-side superpowers process with independent task
  reviews was used during development instead, which per AGENTS.md is a recorded gap, not a passed
  gate. Phases 2 and 3 not started: the dashboard is
  Codex-only (Claude managed runs, approvals for them, observation of the owner's own sessions);
  hook-based approvals reach only requests that get as far as a prompt and the owner's Claude
  defaults to Auto mode (S2); the hook payload has no tool_use_id; launch mode
  `--setting-sources user` is provisional and conditional on roles and CLAUDE.md still loading under
  it (S1). The S3 `--forward-subagent-text` effect is inconclusive. `fable` is untested
  (credit-gated off at the owner's organisation). `disallowedTools: Agent` removes only the Agent
  tool (other routes not tested). The `CLAUDE_EFFORT` variable was observed set when checked at run R9
  (assumed for the first eight runs, same shell); its effect was not investigated. "Astra" wording remains in dashboard/team.py (Team page), README.md,
  docs/team.md, docs/decisions.md and docs/model-policy.md (the shared description changed, those
  copies did not). AskUserQuestion-in-subagents is docs-sourced. The 2 pre-existing failing tests
  and 36 PyJWT skips are environment issues on this machine. Deferred minor review findings are
  kept in the working ledger, which is local, git-ignored and untracked, so they are NOT in the
  repo. Main groups still open: test-strength polish in the team_source tests; sync_roles.py CLI
  polish (the hard-coded "28 files" success message; symlink handling: a plain sync writes through
  a symlink that is named like an expected role file, to a path outside the folder, a pre-existing
  behaviour; a Python traceback on a bad source, documented in the setup runbook); the Astra
  mentions above. (The .DS_Store handling and the test that edits a role source were fixed in the
  final fix wave; the Ponytail-not-on-Claude note in README.md and docs/team.md was added in the
  closeout wave.) FINAL WHOLE-BRANCH REVIEW (done by the most capable reviewer
  model after all tasks): no Critical issues; Codex identity verified (only expert_escalation/description
  differs). The Important findings were fixed in the final fix wave: the sync extra-file rule (only
  directories and `.md`/`.toml` extras are reported, so a `.DS_Store` no longer fails the check), a
  generated-file header on the Codex role files, the status wording of this entry, and a drift test
  that edits a role source; three stale lines in the design spec were also fixed. After that wave:
  Python 678 run (672 + 6 new tests), in the normal environment the same 2 pre-existing failures
  and 36 skipped, with the empty XDG_CONFIG_HOME directory 0 failed, 36 skipped; Node 126/126.
  DOCUMENTATION IMPACT: new docs added (docs/claude-code-setup.md, CLAUDE.md, Claude Code sections
  in README.md and docs/team.md). Codex maintainers' editing path changed: the `.codex/agents/*.toml`
  files are generated, so hand edits are reverted by the sync and flagged by `--check`, and
  `expert_escalation`'s description text changed (model and effort did not). The
  no-documentation-change rationale does not apply.

  CLOSEOUTS (run 2026-10-26 after completion; read-only; headless `claude -p`, project roles as
  subagents, Write/Edit disabled; Bash permission denials meant the closeout roles could not run
  `sync_roles.py --check` or the tests, so they reported those as unverified and the controller
  re-ran them). technical_writer: "pass with findings", 12 findings (4 Important, 8 Minor).
  user_documentation_writer: "pass with findings", 13 findings (8 Important, 5 Minor).
  agent_evaluation_engineer: "workflow checkpoint: not ready", EVAL-2026-10-26-05 in
  docs/model-evaluation.md, 11 findings (2 High, 3 Medium, 6 Low). Cost: 3 runs, an estimated 2.49
  USD on a list-price basis (not a charge); the evaluator run was 1.71 USD of that. A follow-up
  wave (documentation and records only, plus one role-prompt line) acts on them: the docs and
  records fixes, a quick start and runbook in docs/claude-code-setup.md, and Claude's Chief of Staff
  no longer told to follow the Codex-only docs/model-policy.md (Claude only; Codex unchanged).
  Dispositions per finding are in the addendum to EVAL-2026-10-26-05.
  Still open: (1) the independent security review (security_reviewer, with the coordinator or
  qa_engineer running checks for it) is APPROVED by the owner and PENDING; it is to run after the
  closeout wave and before any push. (2) Substitution, recorded: implementers and reviewers during
  development were general workers, not the 14 project roles, because the Claude role files did
  not exist until Task 11 and loading them in the running session was not established; QA
  acceptance was run by the controller, not the qa_engineer role; an independent qa_engineer
  acceptance pass was not run (the owner may request one). (3) The live evidence used trivial
  jobs, and Codex continuity is evidenced only by synthetic and parse-level checks (no native
  Codex load, no interactive Claude session). Recommended next checks, each needing the owner's
  authorization because they cost money: one interactive Claude Code session acting as
  chief_of_staff that delegates one small real tool-using task to a project role, and one native
  Codex load of the regenerated role files. (4) The commit attribution trailer and local git
  identity ruling needs the owner's confirmation before any push. (5) For Phase 2, briefs must
  carry all the AGENTS.md task fields, including an explicit list of questions to stop and ask the
  owner. (6) The owner decides retention of the local, untracked evidence folder.
  After the closeout wave: Python 687 run (678 + 9 new documentation tests), in the normal
  environment the same 2 pre-existing failures and 36 skipped, with the empty XDG_CONFIG_HOME
  directory 0 failed, 36 skipped; Node 126/126; `sync_roles.py --check` clean.

- UI implementation validation (2026-10-26): agreed P0–P3 paths confirmed in source; independent
  QA freshly passed 113 focused Python and all 126 Node checks, without skips (synthetic
  HTTP/protocol/DOM only). Independent Code Review identified same-path changed Outputs
  accumulating to the eight-entry limit; Backend/Frontend own correction and QA owns reload/
  capacity retest. Source-traced finding, not freshly reproduced. Direct Open report in task
  details remains an acceptance gap for UI Designer/Frontend; current path uses an intermediate
  Outputs modal. Writer found missing Outputs API/operations guidance and conflicting URL
  instructions; Technical Writer/User Documentation Writer own reconciliation. Ledger updated;
  prior completion receipts do not close these new findings. No application edits, runtime
  restart, native inference or production mutations. Safari Computer Use was not approved;
  changed-data browser scroll, native continuation, visual/accessibility/performance evidence
  remain open. See docs/ui-review-implementation.md for bounded verdict and follow-up criteria.

- Approval parity steering (2026-10-26): human supplied another unsupported-request screenshot
  and explicitly requires the native Codex request to be reviewable with approve/reject in the
  dashboard. A stop/close-only explanation is insufficient for this requirement. Technical
  Architect owns installed-schema diagnosis and exact contracts; Backend owns native method
  handling and checked ephemeral context; Frontend owns complete review/decision UI. Preserve
  the wider UI implementation already in progress. Determine the actual method without storing
  raw request content; require independent Security, QA, code review and writer/evaluator
  closeout. Screenshot establishes the dead end but does not identify the native method or
  confirm where the human approved it. Previous child sessions ended after interruption;
  current specialists inspected their partial changes before continuation.
  Architect verified CLI 0.163.0 generated experimental schema and official App Server docs.
  Backend handlers are now implemented for manual turn-permission grants, checked native input
  choices and MCP elicitation. The human accepts explicit
  human verification steps. Security's early gate
  supplied scope/identity/scan/response requirements and independently passed four existing
  Outputs authority/race/storage tests. Root baseline output/approval/file suite passed 75;
  original 72 UI checks passed; Frontend's updated conversation checks passed 19. These are
  synthetic checks, not new-native-flow validation. Technical Writer rejoined at steering intake.
  Native Safari read-only inspection succeeded: no pending requests, earlier implementation
  task Unknown. It does not establish how the screenshot's request was resolved. New approval
  implementation is complete in source. Final Security and Code Quality re-reviews found no
  remaining blocker after protected and unsupported MCP form schemas were made fail-closed.
  QA's synthetic acceptance passes, including a Safari permission response recorded exactly as
  the requested overlay with `scope: turn`; live App Server continuation remains unverified.
  Final verification discovered 584 Python tests (548 passed, 36 skipped), 126 Node UI tests
  passed, and the 83 focused post-hardening Python tests passed. Technical and user documentation
  closeouts and Agent Evaluation EVAL-2026-10-26-03 were received. No publication, commit or
  local runtime restart was performed.

- UI review implementation (2026-10-26): human authorized planning and execution with project team. Chief of Staff coordinated; UI Designer reviewed acceptance; Technical Architect defined safe persistent Outputs and bounded readiness summaries. Frontend/Backend used installed Ponytail Full and relevant UI skills. Technical and user documentation closeouts were received. Scope delivered in source: conversation reading stability, unsupported-request exit, completed-task Outputs, complete decision accounting, secondary readiness and bounded refresh interference. Final Security and Code Review reported no remaining blocker; QA passed synthetic HTTP/Safari journeys. Preserve the pre-existing dirty worktree. Live native continuation, formal accessibility/performance conformance and the human release/restart decision remain open; no publication, paid native check or runtime restart was performed.

- Conversation reading-position review (2026-10-25): human reports refresh repeatedly returns
  them to the beginning. Lina traced changed-signature rendering to replacement of the scrolling
  log without scroll/anchor restoration; unchanged signatures skip rendering. Root in-chat CUA
  successfully inspected Overview/Conversations, measured 692x900 viewport and checked the
  unchanged completed-transcript case: bottom position remained after explicit refresh.
  Child browser remained unavailable; root observations were explicitly handed to Lina.
  design-plans/lina-ui-review.md and ui-outcomes-review.md separate user/source/live evidence.
  No app fix, native work or changed-message live reproduction. Frontend owns future repair;
  Lina specifies preserve-anchor/conditional-bottom-follow behavior, QA owns changed-data browser
  reproduction/retest. Unsupported-request loop also independently source-confirmed by Code Quality
  Review; exact triggering native method unknown. These workflow repairs precede visual polish;
  completed-task Outputs remains the highest new outcome addition.

- Earlier Lina UI review checkpoint (2026-10-25; superseded by the conversation/browser receipt above): human requested the UI Designer's review and visual
  improvement assessment, then explicitly required accessible completed-task outputs (MD report
  link example). Lina Cass reviewed the recommendations: Outputs first, decisions next, readiness
  as secondary evidence, refresh as measurement. Three source-informed visual proposals added to
  design-plans/ui-outcomes-review.md. At that checkpoint rendered inspection was blocked: IAB unavailable, no browsers,
  native Safari selection stalled/interrupted; no screenshots/viewport/theme observed. Offline
  UI catalogue returned ENOTCACHED; no dependency installed. Writer verified output requirement
  against task details and existing checked Files preview. Writer closeout and evaluator retest
  passed for report accuracy; initial/follow-up scope wording and priority wording were corrected.
  No application changes, new product test execution or measured efficiency gain. Chief of Staff recorded
  output scope in product brief/decisions. Next: human selects implementation; Architect/Backend
  define task/output association, Frontend implements, Security reviews paths, QA verifies correct
  report-open and negative cases. Later root-browser inspection and supplied modal screenshot
  add bounded rendered evidence; changed-data scroll reproduction and broader visual QA remain open.

- UI/outcomes review (2026-10-25): requested report delivered in
  design-plans/ui-outcomes-review.md. Chief of Staff owns report/integration; independent QA
  reviewed source journeys, Technical Writer closed documentation impact, and Agent Evaluation
  reviewed evidence boundaries. Writer's inherited-filter correction and evaluator's conditional
  focus-loss wording were incorporated. Fresh synthetic interaction checks: 100 passed,
  zero failed/skipped. No product changes or new live/browser/performance validation.
  Recommendations await human selection; no implementation or efficiency gain is claimed.

- Direct run deletion (2026-10-25): human requests an exit from the recovery loop by deleting
  a run. Chief of Staff owns scope/integration and shared records; Backend owns API, atomic
  record cleanup and lifecycle tests; Frontend owns task/recovery Delete run control and UI
  tests. Security joins design and independent final review. Technical Writer is involved at
  intake and owns API/operations; User Documentation Writer owns recovery-guide closeout and
  is queued within capacity. QA/code review and Agent Evaluation checkpoints are queued.
  Acceptance: confirmed terminal/Unknown deletion removes dashboard history and releases its
  hold without assessment/reboot; it neither stops native execution nor undoes files or erases
  Codex history. Known active roots/children/operations require Stop first. Stale confirmations
  and failed persistence cannot partially delete or bypass authority; late events cannot
  resurrect deleted records. Preserve unrelated runs/projects and current uncommitted work.
  No live run deletion, native inference, restart or publication is performed during tests.
  Implemented: exact-version confirmed delete endpoint, transactional run-history cascade,
  authority cleanup and direct task/Recovery confirmation; historical Unknown children and
  operations can be deleted without assessment. Backend regression (77 tests) and independent
  QA (7 tests) passed; Security's 15 backend checks and final UI authorization review passed. Review found
  two UI retry dead ends; both fixed and independently retested (32 UI checks passed).
  Full project-environment Python suite (551 tests) passed with no skips. An initial system-Python
  run had one incompatible legacy policy fixture error and 36 missing-dependency skips;
  the fixture was corrected without weakening production checks and independently reviewed.
  Reviewed scanner passed all 16 task source/test/doc files. Technical/API/operations and
  recovery-guide writers closed. Browser preview verifies both entry points, acknowledgement
  gating and cancellation using disposable data. Recovery cancel-focus was fixed and verified
  after polling, with a new interaction regression; all 109 UI tests passed on final source.
  UI registry CLI unavailable (package absent); Frontend reported the gap and used the
  coordinator-authorized installed accessibility skill with Ponytail Full. No new dependency.
  Agent Evaluation closed development evidence and limitations. Platform reviewed the idle
  restart/readiness plan. Human approved the combined-tree restart. A fresh zero-active/
  zero-pending preflight and identified-owner SIGINT preceded the normal launcher. App Server
  reconnected; exact task ID/status and project ID comparison preserved all 10 runs and both
  projects. Live state exposes deletion eligibility/version for every run; both Unknown runs
  are eligible. Live browser opened the actual blocking run's Delete dialog and cancelled,
  retaining the record and restoring focus. No live run was deleted or started, and no push
  occurred. The restart loaded the combined current tree, including other ongoing changes.

- UI Skills role guidance (2026-10-25): user requested UI Skills reinforcement and clarified
  inclusion of UI Designer. Chief of Staff owns additive frontend_developer/ui_designer
  profile guidance and shared records; Technical Writer owns docs/team.md; independent
  Security reviews both additions and Agent Evaluation owns its bounded assessment.
  Acceptance: load maintained ui-skills-root before UI implementation/design, select narrow
  CLI skills with a maximum of three, report unavailable tooling, preserve role ownership
  and existing safety/accessibility/Ponytail gates. No dashboard behavior change; no product
  workflow guide update required. User additionally requested portability: Technical Writer
  owns docs/skill-setup.md for external dependencies, approved Ponytail pin and setup checks;
  Chief of Staff owns README entry point and removal of machine-specific profile paths.
  Latest native role propagation suite: seven tests passed. Actual installed Ponytail policy
  validation passed; node/npm/npx are on PATH. Technical Writer closed setup/team guidance;
  Agent Evaluation recorded configuration evidence and limitations separately from runtime.
  Final bounded Security review read both current profiles and setup guide with no findings;
  review covered portable discovery, routing limits, preserved safety/ownership and truthful
  pin/install limitations, without claiming external install or runtime verification.
  UI CLI execution, fresh role behavior and clean-machine installation have not been tested.

- Code-enforced Ponytail compliance (2026-10-25): human approved launch policy verification
  plus a separate delivery-readiness gate. Chief of Staff owns scope/integration and approved
  skill loader/pin; Architect owns contract; Security joins design and final independent review.
  Backend owns delivery evidence and server/native event integration; Frontend owns complete
  check-plan/check-run/review/acceptance UI. Technical Writer owns API/operations/team guidance;
  User Documentation Writer and Agent Evaluation are assigned at intake and queued within
  capacity. Acceptance includes a positive complete delivery journey, missing/changed skill
  blocking launch, native command evidence for explicitly approved checks, independent current
  review, stale evidence rejection and unchanged native completion/approval/recovery behaviour.
  No arbitrary host shell runner, automatic paid work, publication or assertion that prompts
  guarantee model judgment. Existing desktop chats remain outside dashboard enforcement.
  Integrated checkpoint: root full suite passed 557 tests in 173.268 seconds before final
  narrow repair/retry changes; policy/native tests passed 14, Backend author checks 16 and
  expanded integration checks 62, Frontend checks 113 (16 delivery cases, with concurrent
  deletion tests included). Independent security checked 43 Python/12 UI plus four probes;
  correctness identified post-scan file-change and malformed-decision defects. Fixes and
  tracked regressions cover incomplete review evidence, plan publication races, current-file
  witnesses, durable decision reconciliation and store-before-memory publication. Initial
  browser evidence uses real HTTP/storage/scanners and synthetic native events: full setup,
  check, review, literal report and explicit acceptance reached ready while execution remained
  Completed. An additional actual Codex test in a private disposable project completed Backend
  assessment, observed the exact approved unittest passing, completed an independent native
  review, and reached Ready through explicit browser fixture acceptance. No existing task was
  resumed or native permission automatically approved. Final integrated Python run executed
  558 tests: 557 passed and one independent acceptance fixture timed out waiting four seconds
  for a worker under concurrent checks. Its isolated rerun passed in 1.778 seconds. QA corrected
  only that fixture wait to a finite 30 seconds, since one permitted scanner call can take 12
  seconds; the affected 13-test acceptance group then passed in 20.152 seconds. The failed full
  run remains recorded; no subsequent full-suite pass is claimed. All 113 UI tests passed, with
  all 16 delivery UI cases repeated successfully on current source. Final independent Security
  passed 43 Python/16 UI checks and nine scoped scans; Correctness passed 30 Python/16 UI checks
  plus four probes, with no remaining finding in their bounded compliance scopes. Correctness
  also reviewed all 24 explicit SyntheticPolicy injections across 13 legacy fake-client fixture
  modules; their guarded 228 tests passed with the production policy loader unavailable.
  Technical and user documentation closeouts passed source/link checks. Agent Evaluation records
  the native journey, reviews, original failure and retest separately in EVAL-2026-10-26-15.
  Reviewed scanning passed 24 scoped source/test/doc/helper files plus 20 subsequently updated
  fixture/doc files; these overlapping counts are not distinct-file totals. Both disposable
  fixture servers stopped cleanly. The main dashboard was started with no listener on 8765;
  connected health reported ten tasks, one active, zero unknown and zero pending approvals.
  No existing task was started/resumed by this work, and no commit or push was performed.
  Concurrent task-deletion/UI/output work is preserved; review claims cover compliance only.
  Independent QA's 13 acceptance cases passed in 19.867 seconds (isolated case 2.355 seconds),
  closing the timeout finding. Its stated storage/concurrency/coordinator/retry coverage limits
  remain distinct from Correctness/Security/UI evidence. Development verification and writer
  closeout are complete for this scope; release remains the human's decision.

- Ponytail role pilot (2026-10-25): human approved Backend/Frontend Full defaults,
  independent simplicity review, explicit coordinator handoffs and evidence-based evaluation.
  Chief of Staff owns AGENTS.md and five role TOMLs, decisions and integration. Technical Writer
  owns docs/team.md; Agent Evaluation owns its ledger; independent review covers scope, safety
  and role propagation. No dashboard UI or recovery-policy change is included. Acceptance: one
  maintained installed skill source, missing-load gaps explicit, preserved existing role/model/
  permission/approval boundaries, valid TOML and native role propagation. Future behaviour and
  savings need observed pilot tasks; profile edits alone cannot establish them.
  Implemented: shared pilot guidance and five additive profile updates; all prior prompt
  prefixes and model/effort/other fields preserved. Checks passed: 27 Python role/prompt tests
  and five prompt UI tests; initial seven sandbox HTTP-bind errors passed on approved rerun.
  Real-scanned generation verified all 14 profiles; independent review passed 20 checks and a
  five-profile snapshot probe with no finding. The idle dashboard was reloaded: all five
  scanner-checked live prompt endpoints exactly match the updated files, connection healthy,
  ten tasks/two unknown/zero active/zero pending decisions preserved. Technical Writer closed
  docs/team.md; User Documentation Writer reviewed no guide change because no user workflow
  changed. Agent Evaluation records source/configuration evidence separately from future pilot
  behaviour; actual compliance and savings remain unmeasured. No development run was started.

- Live recovery metadata fix (2026-10-25): human requests Ponytail implementation.
  Chief of Staff owns integration and read-only live verification; Backend owns minimal
  fixed-stage diagnostics, truthful partial evidence and the confirmed compatibility fix.
  Security reviews design and final boundaries independently; independent QA/code review
  follow implementation. Technical Writer owns API/operations, User Documentation Writer
  owns recovery guide, Agent Evaluation records intake/checkpoints/closeout. Cause remains
  unconfirmed at intake. Acceptance: observe the actual existing task metadata, preserve
  known child counts on later failure, avoid raw upstream text, and keep boot, ownership,
  activity and separate human plan approval gates. No native task start/resume or inference.
  Confirmed cause: the loaded-thread-only background-terminal RPC rejected the unloaded
  historical root. Fixed by fresh root/child identities and goal checks plus a strict complete
  current loaded inventory, tied to the same observed startup connection; no thread is loaded
  for inspection. Read failures retain validated partial evidence and fixed diagnostics.
  Independent author/review evidence: 82 author checks, 126 security checks plus seven
  adversarial probes, 104 correctness checks plus two invalidation probes, and 45 QA checks
  including ten new acceptance cases (overlapping scopes). The applied live metadata-only
  check completed coverage of 38 descendants with zero unresolved current children; root
  notLoaded and current inventory absence observed. Remaining reasons are boot_fence_required,
  historical_descendant_unresolved and unreconciled_turn; continuation remains unavailable.
  Service reconnected with ten tasks, two unknown, zero active runs and zero pending decisions.
  First full-suite run: 503 tests, five errors caused by an older synthetic fixture lacking the
  newly required fresh root read. Root corrected that fixture; independent QA reviewed the
  unchanged negative controls and passed 21 acceptance checks. Final full rerun passed all
  504 tests in 109.912 seconds. Both documentation writers delivered final closeouts;
  Agent Evaluation closed the bounded metadata defect in EVAL-2026-10-25-11. Reviewed
  content scans passed for the five implementation/test and six documentation files,
  and whitespace checks passed. Historical uncertainty and native continuation remain open.
  No OS restart, native continuation, paid inference, new commit or push performed for this fix.

- Ponytail audit remediation (2026-10-25): human authorized all nine audit findings.
  Scope is this local dashboard repository; Ponytail refers to the requested skill, not a
  branch or another project. Chief of Staff owns integration/shared records and Git guard.
  Backend owns child lifecycle holds, atomic task/project publication, bounded descendant
  coverage and obsolete native-assessment removal; Platform owns native read-timeout handling;
  Frontend owns recovery eligibility and stable keyboard focus. Technical Architect provides
  bounded contracts. Technical Writer and Agent Evaluation involved at intake; User
  Documentation Writer assigned and queued within capacity. Independent QA, Security and
  code review follow author checks. Acceptance includes each original failing case plus
  positive recovery coverage with 25 descendants, preserved old outcomes, no overlapping
  work, unchanged native approval gates and documented operational limits. No real native
  continuation, credentials, Git publication or OS restart is authorized by these fixes.
  Final integrated checks: 487 Python tests and 86 UI tests passed. Independent QA's
  11 acceptance checks, independent security review and correctness review completed;
  correctness retested the late child-count correction (10 checks). A refreshed synthetic
  browser fixture showed Completed preserved, one unresolved child and keyboard focus
  retained across polling. The local dashboard was gracefully restarted and reconnected
  with 10 tasks, two unknown, zero active runs and zero pending decisions preserved.
  A live metadata-only recovery check returned unavailable coverage with
  activity_unverified/metadata_unavailable; continuation stayed blocked. Synthetic
  25/125-descendant coverage does not establish live coverage. Backend + Platform own
  diagnosis and live retest; this is an open validation item, not a recovery completion pass.
  The human requested a local commit. Technical Writer and User Documentation Writer
  delivered final documentation closeouts; Agent Evaluation recorded EVAL-2026-10-25-08.
  The first complete staged security scan passed; the final documentation snapshot receives
  the required staged security/whitespace checks before commit. No push or native
  continuation was performed.

- Assessment handoff feature (2026-10-25): human approved implementation and requested
  first-class feature framing. Objective: preview/copy checked recovery evidence to an
  existing approved chat, return and explicitly review an assessment, then separately approve
  a fresh continuation plan. Chief of Staff owns integration/shared records; Technical Architect
  owns contract; Security reviews trust boundaries before implementation and again afterward.
  Technical Writer, User Documentation Writer and Agent Evaluation participated at intake
  and source closeout within session capacity. Acceptance includes repeated handoff rounds, stale/replay/secret
  rejection, missing-folder/native-offline discussion, preserved unknown outcomes and unchanged
  activity/ownership/approval gates. No automatic external sending, credential reuse or native
  work during handoff. Backend author checks (18 plus 3 HTTP) and independent product QA (14 journeys) passed;
  security found and independently retested a path-export gap. Root full Python suite passed
  458 checks after an initial sandbox run failed 35 loopback-bind checks; approved rerun
  passed in 98.055 seconds. Code review found a browser lost-acknowledgement reconciliation
  defect; Frontend fixed it and independent reviewer retested 30 UI checks with no remaining
  confirmed finding. Root final UI suite passed 78 checks. Both writer closeouts received. Isolated browser
  evidence uses synthetic native metadata and the real scanner; two handoff rounds, clipboard
  copy, plain-text preview, explicit acceptance and plan-only preparation observed.
  The approved local update was applied: connected, 10 tasks preserved, two unknown,
  zero active runs and pending decisions. Both unknown tasks expose handoff preparation; live
  browser confirms its enabled control. No live packet or work started. External-chat delivery
  and real native continuation remain unverified; the activity-coverage gap remains open.
  Agent Evaluation closeout EVAL-2026-10-25-05 records source, documentation, synthetic
  journey and authorized application gates complete. Root final scanner passed 21 scoped
  files and verified 47 relative documentation targets; final writer pages were rescanned.
  External use/provenance, native continuation, activity coverage and broader accessibility/
  performance remain separate open validation items.

- Earlier local recovery validation (2026-10-25, before handoff implementation):
  the human approved applying the update and
  beginning live validation. The idle service was restarted; it reconnected with 10 tasks,
  including the same two unknown tasks, zero active runs and zero pending decisions. No work
  was replayed and no inference was started. The live Recover task view opened successfully.
  The human attempted sign-in and reports that corporate account policy prohibits Sign in
  with ChatGPT. Live assessment is blocked for this account; no inference was completed.
  Technical Architect owns an existing-Codex capability review; an alternative assessment
  route is not implemented or verified. Architecture review confirmed native assessment is
  explicitly disabled and no enforced tool-isolation or credential-sharing bridge is verified.
  A scanner-checked evidence handoff for human/existing-chat assessment is a proposed option
  only; export/import and acceptance gates require a product decision and implementation.
  The inspected task exposed incomplete activity coverage: 20 descendants exceed the current
  16-descendant check limit, alongside unresolved historical activity and a required boot fence.
  Development remains blocked. A computer restart alone cannot clear incomplete coverage.
  Platform/backend and Chief of Staff own reconciliation and the coverage-limit follow-up;
  native continuation, broader accessibility and performance acceptance remain open.
  User Documentation Writer closeout and Technical Writer content review received;
  root reviewed-scanner and whitespace checks passed for the updated technical pages.
  Agent Evaluation recorded EVAL-2026-10-25-02 and the corporate-policy checkpoint
  EVAL-2026-10-25-03; the original recovery journey remains unmet, with no completion pass.

- The source closeout below records the checkpoint before the authorized local restart.

- Recovery implementation closeout candidate (2026-10-25): implemented locally; release and
  live validation await the human. Built-in same-account ChatGPT sign-in supplies a separate
  memory-only text assessment session with no API-key/billing fallback, native runtime or tools.
  Repeated discussion works with Codex offline or a missing/replaced registered folder; strict
  directory checks still block development plans/execution. Separate versioned plan approval,
  fresh metadata, exclusive ownership and verified changed OS boot gate new linked development.
  Same-thread recovery remains disabled; original unknown outcomes and old permissions stay separate.
  Independent correctness and security reviews have no remaining confirmed blockers in reviewed
  source. Security S1 (cancel before assessment dispatch) and S3 (native precheck-to-wire race)
  were fixed and independently retested, including actual POSIX pipes. Directory/capacity P2s
  passed independent source review and behavioral retest. Product QA's 14 acceptance checks passed
  with synthetic native/assessment transports and disposable filesystem checks. Separate auth
  checks exercised real local callback listeners with mocked external endpoints; these do not
  establish real OpenAI inference or native development execution.
  Parent's full Python suite passed 423 checks; after synthetic credential-fixture cleanup the
  authentication target passed 36 checks. Latest 64 UI checks passed. The corrected partial-write
  timeout regression passed 30 repeated runs. The security-reviewed isolated native startup probe
  passed again with empty loaded-thread metadata and no turn requested or old thread resumed;
  sampled emptiness is not a recovery or external-quiescence guarantee. Reviewed content scanner
  passed 45 scoped files, with no rule changes or real credential incident.
  Technical Writer and User Documentation Writer final source closeouts received. The user guide
  explicitly requires an independently chosen human reboot; recording a plan authorizes none.
  Agent Evaluation recorded development checkpoints and source-candidate closeout
  EVAL-2026-10-25-01; live proof, browser acceptance and human release remain open.
  Current production health: HTTP 200, connected, zero active runs and pending decisions; unchanged
  earlier code, with no service restart, replay, real sign-in, inference, reboot or native recovery
  continuation performed. Chief of Staff owns release handoff and remaining live validation with
  the human. The human completes OpenAI sign-in directly; parent checks bounded status only,
  without capturing authorization URLs, codes, credentials or sign-in screenshots.
  Keyboard/zoom/narrow-window/contrast and measurable performance acceptance remain
  unverified beyond the documented DOM/layout evidence; do not infer them from protocol tests.

- Unknown-task recovery implementation (2026-10-19): authorized by the human after design
  review. Chief of Staff coordinates integration; Technical Architect confirms implementation
  contracts; Platform prepares isolated capability/native probes; Security reviews boundaries
  and probe scope before execution. Backend/frontend ownership follows the agreed contract.
  Technical Writer and User Documentation Writer are assigned to developer/user guidance;
  Agent Evaluation reviews implementation checkpoints separately from QA. Those handoffs are
  queued within session capacity. Acceptance includes actual repeated assessment replies,
  separately approved continuation, lost-delivery/crash recovery and negative authority checks;
  mocked checks alone cannot establish native functionality. Production dashboard remains
  running; no restart, original-thread resumption or replay is part of development checks.
  Use the reviewed recommended same-thread/fallback design and per-recovery Manual native
  approvals. A computer restart remains an explicit optional human action at recovery time.

- Unknown-task recovery workflow design (2026-10-19): reviewed proposal delivered for human review;
  no implementation authorized
  by this design request. Outcome: a safe route from an unknown task to inspected evidence,
  usable conversation and explicitly chosen continuation, without replaying uncertain actions.
  Human chose mandatory assessment first, then separate approval of continuation. Technical
  Architect and UI Designer delivered proposals; Platform supplied concrete orphan/manual
  recovery and capability proof requirements. Independent QA identified plan-version and
  cancellation gaps, now fixed/retested. Security identified immutable assessment purpose and
  migration-hold gaps, now fixed/retested with no blocking security-design findings. Technical
  Writer completed intake and final source review. Agent Evaluation recorded design assessment
  EVAL-2026-10-19-02. Final documentation whitespace check covered eight scoped files, including
  untracked design artifacts; all 33 local link targets resolved. Chief of Staff owns integrated
  proposal, shared records and human decisions. Runtime acceptance remains unexecuted.
  Required evidence: current code/installed protocol, full happy/recovery/blocked journeys,
  explicit unresolved capabilities and design review. No production thread is resumed, original
  instruction replayed or native inference started for design work.
  Proposal: docs/dashboard-recovery-design.md, with linked architecture, experience and operations.
  Shipping blockers: enforce assessment capability, prove safe native resume/goal behavior,
  verify process/boot clearance, and execute isolated native/browser end-to-end journeys.
  Human design choices: same-thread plus fallback strategy, per-recovery manual approvals,
  and disruptive legacy OS-restart fallback; no such action has been taken.

- Local service recovery (2026-10-19): user authorized starting the service. Local HTTP check
  confirmed connection refused; the documented launcher started the dashboard and its managed
  App Server. Subsequent `/api/state` returned HTTP 200 with connection status `connected`.
  No development runs were started or replayed; historical tasks retain terminal/unknown states.
  Chief of Staff owns HTTP recovery evidence. Technical Writer reviewed the existing operations
  guide and launcher: no guide change needed; startup, connection checks and no-replay recovery
  are already documented. Writer review was source-only, not an independent HTTP check.
  Agent Evaluation subsequently recorded the source-attributed operational handoff in
  EVAL-2026-10-19-01; it did not independently repeat HTTP/native checks. This verifies readiness, not inference or
  completion of historical unknown runs.

- Documentation and ongoing agent quality loop (2026-10-18; closeout 2026-10-19): implemented.
  Human requested
  both roles participate throughout development. Technical Writer owns the workflow guide;
  Agent Evaluation owns the continuing assessment record and an initial archival review.
  Chief of Staff updated shared instructions and role prompts to require intake,
  progress and completion handoffs, explicit evidence/gaps and finding/fix/retest ownership.
  Writer closeout received; independent acceptance and security reviews passed with no
  outstanding scoped findings. QA retested named follow-up ownership and historical evidence
  labels. All 14 role TOMLs parsed, scoped whitespace and nine-file reviewed content scan passed
  at the review checkpoint. The nine-file content scan passed again after recovery documentation;
  Agent Evaluation subsequently recorded final workflow closeout in EVAL-2026-10-18-02.
  Independent acceptance/security dispositions above are complete; historical gaps stay open.
  The workflow change required no application change or restart.
  Follow-ups from historical coverage review are tracked in docs/model-evaluation.md;
  previous product test results are recorded evidence, not fresh verification in this task.

- Team activity and Overview delegation drill-in (2026-10-18): implemented locally; applying
  to the running service awaits the human's restart decision. Team lists direct/delegated work with statuses,
  project filtering and coordinating-task links. Overview details show nested delegated work.
  Independent QA reproduced and retested a fix for nested delegation after root completion;
  security review found no activity-scope findings. Correctness review identified and retested
  the delayed metadata/queued-status fix; no outstanding focused review findings. Eight independent
  HTTP acceptance checks, the full 270-test Python suite and 48 DOM interaction tests passed. Reviewed content scan passed for
  15 activity source/test/documentation files; whitespace check passed. Runtime was observed with two active
  runs and two pending approvals; no restart, interruption, native inference or replay was
  performed for this change. Browser layout remains unverified; synthetic HTTP and DOM checks
  are separate from native integration evidence.

- Conversation replies and stale attention notices (2026-10-18): implemented and restarted
  with explicit human authorization to stop both named runs.
  Live metadata identified native approval gating, not a one-message quota. Conversations now
  exposes that blocker and its scoped review; failed polls retain drafts. Four real isolated
  native turns completed and stayed replyable; synthetic browser resolved an approval and sent
  three further prompts. Dismiss notice removes an inactive warning only, persists separately,
  preserves history and restores new failures. Full suite: 255 Python tests; 42 UI tests.
  Independent QA checked repeated rounds, decision guards, persistence and HTTP origin/version
  boundaries. Interruption delivery timed out; subsequent state confirmed no active runs before
  restart. Task Delegation is recorded completed; resume latest status is recorded unknown, so
  its terminal outcome is not claimed. The restarted dashboard is connected with zero active
  runs and pending decisions; no runs were replayed. Existing files/settings were preserved.
  Live browser verified Dismiss notice and retained task history. Removed a responsive CSS
  rule hiding the attention section in smaller windows; verified it visible in the in-app browser.

- Delegation and sensitive request review (2026-10-18): implemented and restarted with human
  authorization. Persistent native parent history, 14 registered safe role snapshots, modern
  child lifecycle/metadata and child approval routing verified. Native isolated Chief of Staff
  -> Backend Developer -> exact harmless child approval -> child/parent completion passed with
  no project files created. Local reveal then separate approval once verified in synthetic browser;
  actual sensitive production contents were not inspected by the agents. Scanner findings use
  dedicated exit 42, while scanner failures stay blocked. Full Python suite: 241 passed; latest
  approval/file targeted suite: 64 passed; UI suite: 33 passed. Independent security/correctness
  reviews have no outstanding blocker. Continue MVP was interrupted with explicit authorization,
  active runs reached zero, and the updated dashboard restarted without replay. Existing project
  approval preferences were preserved; sensitive_review_enabled is explicit in config.toml.

- Interruption recovery (2026-10-18): re-established the checkpoint from project records and
  the working tree. Current checks passed: 219 Python tests and 27 UI interaction tests.
  The running dashboard was connected with no pending approvals; the Chief of Staff prompt
  endpoint returned HTTP 200, nonempty content and `Cache-Control: no-store`.
  Independent QA was attempted again but could not start: session thread-store lookup failed.
  No browser provider was available; visual prompt-dialog verification remains unexecuted.
  Existing approval-recovery changes remain uncommitted. No run was replayed or interrupted.

- Approval recovery and project preferences: implemented and restarted with human authorization. Safe reason
  codes, approval-scoped guidance, explicit cancel/interruption/follow-up, future-only project
  automatic approvals and verified crew names. 219 Python and 27 UI tests passed; reviewed secret
  scan passed for changed source files. Independent security and correctness reviews found
  no outstanding blocker. Native compound approval and cancel/follow-up/new approval completed
  without creating project files. Synthetic browser verified guidance and explicit continuation.
  The human authorized stopping Initial MVP; native interruption was confirmed, active runs reached
  zero, and the updated dashboard reconnected. No original instruction was replayed.

- Team personal prompts: existing implementation verified on 2026-10-18. Each card has a
  Details button opening a read-only personal role prompt with shared/task context explained.
  Seven HTTP/backend tests and five DOM interaction tests passed, including all configured
  prompts with the real scanner, blocked content, stale responses and retry recovery. Running
  dashboard Chief of Staff endpoint returned HTTP 200 with a prompt and no-store caching.
  Visual browser verification was unavailable (no browser provider); independent specialist
  review and QA could not load because the session thread store returned an error.

## Continuing documentation and evaluation follow-up

| Finding | Next owner | Required evidence / next checkpoint |
| --- | --- | --- |
| EVAL-001: sustained writer/evaluator participation | Chief of Staff + Technical Writer + Agent Evaluation | Next development task's intake, progress and closeout records; policy text alone is insufficient |
| EVAL-002: original user journey coverage | Product Manager + independent QA + Agent Evaluation | Next decision-based feature: original request through decision, continuation and outcome, plus negative paths |
| EVAL-003: personal-prompt review and visual gap | Chief of Staff assigns independent QA/reviewers | Review the current revision and verify the dialog in browser; earlier blocked attempts are not passes |
| EVAL-003: activity visual gap | QA | Browser check of Team and nested Overview activity for the implemented revision |
| EVAL-003: applying activity changes | Human restart decision; Chief of Staff coordinates | Preserve active work; apply only with applicable restart authorization and observe readiness without replay |
| EVAL-004: observed model and cost coverage | Chief of Staff + Agent Evaluation | Next task records available metadata sources and explicit unknowns; no inferred savings |
| EVAL-005: historical status clarity | Chief of Staff + Technical Writer | Historical checkpoint label below added and independently retested by QA; earlier unknowns and unverified paths retained |

## Historical delivery checkpoints

The table and checkpoint notes below preserve earlier evidence and limitations at their original
delivery stages. For later work, consult the dated entries above and docs/decisions.md. Earlier
statements that inference or native round trips were unexecuted are historical; later isolated
native checks verify only the specific paths described, not every live integration or model.

| Work | Owner | Status | Evidence / next step |
| --- | --- | --- | --- |
| Team roles and operating rules | Chief of Staff | Discovered in this session | All 14 project profiles match exposed roles; specialist profiles used during dashboard delivery |
| Local Git secret controls | Security | Hooks installed; 25 integration tests passed | Includes docs, partial staging, forced paths, history, messages, tags, outgoing object IDs, missing scanner, and symlinks |
| GitHub hosting and server enforcement | Human + Chief of Staff | Public repository created; origin connected | K55Toms/KT_Agent_Dev_and_Dash; secret scanning and push protection verified enabled; no source push; branch/CI rules pending |
| First product definition | Product Manager + Human | Agreed | Multi-project local dashboard with dashboard-managed live Codex runs; docs/product-brief.md |
| Expanded roles and model routing | Chief of Staff | Profiles discovered; benchmarking pending | Explicit model/effort settings loaded as available role definitions |
| Comparative model evaluation | Agent Evaluation | Protocol ready; trials not run | docs/model-evaluation.md; needs representative product tasks and observed workspace usage |
| Multi-project local dashboard | Backend + Frontend + Platform | Implemented and locally running | 38 tests passed; independent security and code review findings fixed; no paid inference smoke test |
| Dashboard live integration | Technical Architect + Backend | Real App Server handshake verified | Managed runtime connected; no existing-desktop coverage; actual inference/model availability unverified |
| Dashboard interaction design | UI Designer + Frontend + QA | Desktop browser checked | Project registration, run form, cost labels, stale controls and recovery checked; formal usability/mobile testing not performed |
| Dashboard operational guide | Technical Writer + Platform | Delivered | docs/dashboard-operations.md; private SQLite state, safe startup/recovery, v1 approval/cost limits |
| Manual project file review | Backend + Frontend | Implemented; browser preview verified | Safe Git-visible text, no edits, secret scan before preview; tests/test_project_files.py |
| Git status and publish option | Platform + Backend + Frontend | Implemented; security regressions passed | Local status; clean snapshot-bound confirmed GitHub push only, no implicit staging/commit/force |
| Failed activity inspection and launch compatibility | Backend + Frontend + independent Security | Implemented; real completion verified | Clickable failures, safe phase diagnostics, parser fix, CLI updated 0.141.0 to 0.163.0; 167 tests passed; isolated GPT-6.1 Sol completed with observed usage and no project files created |
| Human approval and complete user journeys | Backend + Frontend + independent Security + Chief of Staff | Implemented; restarted with human authorization | 191 Python and 12 UI tests passed; real isolated native no-op review/accept/continuation completed; PM, QA, CoS prompts and AGENTS.md strengthened; original waiting run interrupted with human approval, files preserved |

- Personal branding: original logo and Kristian’s Rebellion Builders name applied and browser verified. Three isolated UI previews delivered; human selected Hybrid Night Shift. Appearance config retains Terminal Ops and Rebel Command.

- Combined Files/Git/security regression suite: 88 tests passed. Desktop browser verified read-only README preview, Git destination/dirty-tree publishing gate, personal branding and all three design previews. No real publication or paid inference test ran.

- Live appearance: Hybrid applied; file-config round trip to Terminal and Rebel verified in browser, then restored Hybrid. Dialog styling checked. Graceful publication shutdown fix independently verified with synthetic success/timeout helpers.

- Settings and repository creation: implemented; browser name/theme save verified; independent review fixes retested; name/logo/theme/account/visibility, explicit empty-repository creation with no automatic push.
- Managed-run conversation: delivered; question replies/guidance/followups, scanned local history and observed exchanges verified with fake protocol and browser fixture.

- Settings release evidence: 117 tests passed, independent security/correctness review fixes retested, browser settings name/theme save verified and restored. No live GitHub creation or source push executed.

- Rebel crew: 14 fictional identities/original vector portraits, observed role work, persisted Chief of Staff recognition with evidence and caps. Team unit suite16 passed; conversation integration and independent security/code review completed.

- Final conversation/team checkpoint: 160 tests passed, staged secret check passed, independent
  security and correctness review fixes retested. Synthetic browser fixture verified populated
  Team/awards, question discovery and answers, steer/followup, draft handling, and interagent
  exchanges with no console warnings/errors. Real App Server handshake and production empty
  views verified. Paid inference/native interaction roundtrip, responsive/automated contrast
  and real GitHub publication remain unexecuted. Source is committed locally only.

# Task board

- Team personal prompts: existing implementation verified on 2026-10-18. Each card has a
  Details button opening a read-only personal role prompt with shared/task context explained.
  Seven HTTP/backend tests and five DOM interaction tests passed, including all configured
  prompts with the real scanner, blocked content, stale responses and retry recovery. Running
  dashboard Chief of Staff endpoint returned HTTP 200 with a prompt and no-store caching.
  Visual browser verification was unavailable (no browser provider); independent specialist
  review and QA could not load because the session thread store returned an error.

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

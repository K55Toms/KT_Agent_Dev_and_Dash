# Managed approvals (Claude dashboard Plan 4) evidence

Date: 2026-11-01. Branch `managed-approvals` (local, unpushed), cut from `managed-run-loop` and rebased onto main
(`f33e52c`) after pull requests 3 to 6 were merged by the owner. Plan:
`docs/superpowers/plans/2026-11-01-claude-dashboard-managed-approvals.md`. Spike:
`docs/superpowers/spikes/S10-managed-approvals.md`. Design:
`docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md`. Previous plan's evidence:
`docs/superpowers/evidence/2026-10-28-managed-run-loop.md`.

What this plan delivered, in one paragraph: in a `claude` deployment each managed run is started with its own
settings file holding one `PermissionRequest` hook that points at a loopback receiver owned by the dashboard. A
request becomes a pending approval of kind `tool_call`; the owner reviews the tool name and complete input and accepts
that one call or declines it; the run continues or is refused that call. A timeout, crash, stop, close, restart or stale
answer denies the call and never allows it. The wait is configurable (default 900 seconds, range 60 to 3600) and an
optional Automatic mode accepts plain `Bash`, `Write`, `Edit` and `NotebookEdit` requests one call at a time. All of
this is tested against a fake `claude` executable; the real `claude` has been exercised only by the S10 spike, outside
the dashboard. This file is the evidence record for the Task 9 documentation step; the live acceptance step is not done.

## Commits per task

`git log --oneline` on the branch; fix commits last in each row. The plan and its configurable-wait and Automatic-mode
revision are `b7636f5` and `36ecfc5`.

| Task | Commits |
| --- | --- |
| 1 Spike S10 (live) and evaluation checkpoint | `708b07a` docs: S10 managed approvals spike; `5f85e56` docs: Plan 4 keep configurable wait defaults, mark unverified above 120 s; `2f1f6c6` docs: Plan 4 start evaluation checkpoint; `6d291f5` docs: Plan 4 scan rulings in plan text, security review step, S10 wording |
| 2 Hook protocol module | `35ee557` feat: Claude hook request parsing and replies; `66c22bc` fix: harden Claude hook parsing (non-finite floats, surrogates) and pin mode and id tests |
| 3 Hook receiver | `2ae8ff8` feat: managed hook receiver; `9fdc6ca` fix: hook receiver stop from callback, error-body echo test, read limits |
| 4 Settings file, wait setting, fake binary hook mode | `ca2bba3` feat: per-run hook settings file and fake binary hook mode |
| 5 Tool-call approvals | `172247f` feat: Claude tool-call approvals; `d96d28c` fix: pin automatic revocation, known-role requester for Claude approvals |
| 6 Approval lifecycle | `3b9d154` feat: approval lifecycle cleanup for Claude runs; `a7287a2` fix: withdraw Claude tool calls when a stop or close is requested |
| 7 UI and diagnostics | `481d846` feat: dashboard UI for Claude tool-call approvals; `d177d89` fix: escape control characters in tool-call display, test Decline, expiry wording |
| 8 Journeys over HTTP | `1d8dc05` test: Claude approval journeys |
| 9 Documentation closeout | the commit that adds this file (`docs: Plan 4 managed approvals documentation`) |

## Test counts

Clean environment (`HOME` and `XDG_CONFIG_HOME` set to new temporary directories). Counts are from the per-task reports
and the controller ledger (`.superpowers/sdd/2026-11-01-claude-dashboard-managed-approvals/`, git-ignored). Skipped is
36 throughout (PyJWT is absent on this machine; CI installs it).

| Point | Python | Node |
| --- | --- | --- |
| Start of Plan 4 | 1100 | 151 |
| After Task 2 | 1113 | 151 |
| After Task 3 | 1138 | 151 |
| After Task 4 | 1156 | 151 |
| After Task 5 (and its fix round) | 1186 (1192) | 151 |
| After Task 6 (and its fix round) | 1204 (1209) | 151 |
| After Task 7 (and its fix round) | 1215 | 170 (175) |
| After Task 8 | 1223 (OK, 36 skipped; two consecutive runs) | 175 |

Existing tests were edited only where the behaviour or text they pinned changed: the follow-up argv comparison in
`tests/test_claude_stop_resume.py` (each process now has its own `--settings` path), the invalid-request expectation in
`tests/test_claude_approvals.py` (Task 6: the run is now stopped and failed), three tests that pinned the old
`claude_calls_denied` text and the old Claude run-dialog notice, and one wait-line assertion. No test was removed or skipped.

## Characterization goldens

`git diff --stat b547e0b..HEAD -- tests/fixtures/characterization/` was empty at the end of Tasks 5, 6 and 7 per the
reports. Codex approval tests passed unedited.

## Kinds of evidence

Each kind is stated separately; one kind never stands in for another.

### Unit

Offline tests of the new modules and server paths, with mutation checks recorded in the task reports (a change applied to
a scratch copy and a test had to fail): `tests/test_claude_hook.py` (request parsing, reply shapes, wait bounds),
`tests/test_hook_receiver.py` (token, method, size, caps, held requests, wait limit), `tests/test_claude_settings_file.py`
(settings file mode, content, removal), `tests/test_claude_approvals.py`, `tests/test_claude_approval_lifecycle.py`,
`tests/test_claude_approvals_texts.py`, and the settings tests for the wait key. Node tests against a DOM double:
`tests/test_claude_approvals_ui.js` (the card, the review dialog, Accept and Decline, expiry text, the Settings field, the
visible escaping of control characters). Mutants recorded as killed include: removing the tool allow-list, the held-liveness
check, the permission-mode check, the answer-time mode check, the policy-version check, the stop of a refused run, the
deletion deny and the restart reason. Mutants recorded as surviving: three redundant close-path layers in Task 6
(each alone is covered by another layer).

### Fake-binary

`tests/fake_claude.py` replays sanitized fixtures and, in hook mode, posts to the real receiver at the URL in the run's own
settings file. Used by `tests/test_claude_approvals.py`, `tests/test_claude_approval_lifecycle.py` and the journey file
`tests/test_claude_approval_journey.py` (8 tests over HTTP on ephemeral ports, real Dashboard, real receiver, real argv
builder; run five times in a row, 8 OK each). The journeys: ask, review, approve, work resumes and completes; decline and
the denial is recorded; ignore until expiry (wait cut to 0.8 s through the receiver seam); stop while waiting; restart while
waiting; a Codex deployment has no receiver and the gated routes answer 409; Automatic accepts a plain `Bash` once but not
sensitive input; approving one call does not approve a differently worded second. This shows the dashboard's behaviour
against a stand-in; it does not show how the real `claude` behaves. In particular the stop journey ends `interrupted` only
because it uses a SIGINT-ignoring fake; the fake's own scenarios emit a `result` after a denial.

### Live

Only spike S10 (`docs/superpowers/spikes/S10-managed-approvals.md`): 8 runs, alias `haiku`, Claude Code `2.1.312`,
one run per condition (R10a to R10h), outside the dashboard (a stub receiver on loopback), within the owner's approval
recorded 2026-11-01. The list-price total was about 0.036 USD against an estimate of about 0.01 USD; the estimate came
from S9 (runs without tools) and was too low. Findings, each from one run on one model: a 75 second answer under a 120 second
hook timeout works; the `headers` plus `allowedEnvVars` form carries a token (not adopted); HTTP 500, 200 with malformed
JSON, 401 and an interrupted run all ended as a denial and none hung; allowing one call does not allow a differently
worded call; `Write` and `Read` outside the project reach the hook; two Bash calls from one message were delivered one at a time;
a subagent request carries `agent_type` and `agent_id`; SIGINT while the hook waits exits in about 1 second with a `result`
and the connection closed. No ceiling on the hook `timeout` is documented (the settings schema has no maximum).

### Browser

None. The UI changes are covered by Node tests against a DOM double only; the card layout, the scrolling input box, focus
and the screen-reader announcements were not checked in a browser. A browser check by the controller was planned before
closeout and has not been done.

### Owner-reported

The owner's requests and rulings are decisions, not test evidence: a configurable wait and an optional Automatic mode
(2026-11-01), and "Run all thank you." after the plan was presented, which the controller read as confirming the plan defaults
and approving the S10 live runs. Merges of pull requests 3 to 6 (owner, 2026-11-01). The controller restored the wait
defaults over S10's narrowing without a separate owner decision; this is recorded in `docs/decisions.md`. No owner
observation of a live approval exists.

## Review history

Tasks 1 to 7 had an independent review of their diff, and Tasks 2, 3, 5, 6 and 7 a scoped re-review of the fix round, recorded in
the git-ignored ledger directory. The Task 8 review was still pending when this file was written.

| Task | Verdict | Notable findings |
| --- | --- | --- |
| 1 | Approved, Minors fixed | evaluation findings P4START-EVAL-01 to 07 recorded; 03 and 05 fixed in the plan text |
| 2 | Needs fixes, then fixed | non-finite floats and lone surrogates escaped as plain exceptions; permission-mode parse untested |
| 3 | Needs fixes, then fixed | `stop()` from a callback left the port open; a no-echo test could not fail |
| 4 | Approved | carry items: symlinked parent of `claude-runs`, stale wait on concurrent saves |
| 5 | Needs fixes, then fixed | an in-flight automatic accept was not shown to be revoked by a mode change; requester text could echo the agent type |
| 6 | Spec failed, then fixed | an allow could reach a run after an interrupt or close while the run lived (reproduced with a SIGINT-ignoring fake); fixed by withdrawing before any signal |
| 7 | Needs fixes, then fixed | bidirectional and control characters displayed raw in the approval text; list-card Decline untested |
| 8 | Review pending | tests only; the implementer found no defect |

## Not verified

- The live approve-once journey through the dashboard with the real `claude` (start, request, review, accept, resume).
- Waits above 120 seconds, and the end of a long hook timeout with a request still open (run R10i, hook timeout 960 and an
  answer after 300 seconds, is not approved and not run).
- Parallel subagent requests: S10 delivered two calls from one message serially, and parallel subagents were not tried. The
  two-approvals-never-cross test is fake-binary only.
- Linux (tests use macOS paths and `ps` output) and Windows.
- User-level allow rules and hooks, which could let a call run without reaching the dashboard or add a second hook.
- Tools other than `Bash`, `Write` and `Read` through a real hook (`Edit`, `NotebookEdit`, web, MCP), and `Read` inside the project.
- A hard kill of `claude` during a held request, SIGTERM, and a late answer after the close.
- That the token variable stays out of tool subprocesses in the header form (not adopted); that Claude Code ignores a repeated
  or reordered reply; models other than `haiku`; other Claude Code versions.
- The page in a browser (Approvals card, review dialog, Settings field, Automatic wording, expired and unavailable text).
- The `agent_id`, `prompt_id` and `agent_type` patterns (`[A-Za-z0-9_.:-]{1,64}`) against the real CLI.

## Documentation impact

Documentation impact: user behaviour changed (Claude requests appear as approvals; a wait setting; Automatic mode for Claude
projects), the API gained a kind, a status reason, a settings key and a snapshot field. Pages changed:
`docs/dashboard-operations.md`, `docs/dashboard-api.md`, `docs/product-brief.md`, `docs/claude-code-setup.md`,
`docs/approval-guide.md`, `docs/decisions.md`, `docs/task-board.md`, `README.md`; this file is new. Facts were taken from the
plan, the S10 note, the task reports and reviews, and checked against `dashboard/hook_receiver.py`,
`dashboard/backends/claude_hook.py`, `dashboard/backends/claude_launch.py`, `dashboard/settings.py`, `dashboard/diagnostics.py`,
`dashboard/server.py` and `dashboard/static/index.html`. Checks not made: no browser check; no live run; no independent writer
review of these pages yet. The earlier checks quoted above are recorded task reports and reviews, not checks the documentation
writer ran again.

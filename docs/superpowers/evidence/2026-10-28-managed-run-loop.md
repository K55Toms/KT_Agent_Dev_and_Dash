# Managed run loop (Claude dashboard Plan 3) evidence

Date: 2026-10-28 to 2026-10-30. Branch `managed-run-loop` (local, unpushed), cut from `provider-seam` at `0d0b66b`.
Plan: `docs/superpowers/plans/2026-10-28-claude-dashboard-managed-run-loop.md`. Design:
`docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md`. Previous plan's evidence:
`docs/superpowers/evidence/2026-10-28-provider-seam.md`.

What this plan delivered, in one paragraph: in a `claude` deployment the dashboard starts a managed `claude -p`
run for a task with the role as main session, shows its status, token usage and an estimated USD cost, stops it,
continues it with `--resume`, survives a dashboard restart without replaying anything, and says when Claude Code
denied a tool call. There are no approvals yet. All of this is tested against a fake `claude` executable and
sanitized stream fixtures; no Claude run has gone through the dashboard with the real CLI.

## Commits per task

`git log --oneline 5aec411..HEAD` (the commits after the Task 1 spike) lists 19 commits including the Task 11
test commit; the three Task 1 commits precede it. The Task 11 documentation commit follows the test commit.

| Task | Commits (fix commits last) |
| --- | --- |
| 1 Spike S9 (live) | `d3e0db1` docs: S9 role and environment spike; `f02eb1d` docs: S9 note corrections after review; `5aec411` docs: S9 combination run |
| 2 Fake `claude` and fixtures | `29dde76` test: fake claude executable and sanitized stream fixtures; `c29bfeb` test: align Claude fixtures with real stream shapes |
| 3 Stream parser | `5065ee8` feat: Claude stream parser; `28f2c44` fix: Claude stream parser model ids and partial usage |
| 4 Neutral lifecycle extraction | `24515a2` refactor: extract neutral lifecycle application |
| 5 Launch builder | `cb8e6db` feat: Claude launch builder; `930d29f` fix: harden Claude launch builder |
| 6 Process runner | `7671b8a` feat: Claude process runner; `41b42db` fix: Claude runner spawn race, reader bound and group cleanup; `4ecaa5a` fix: runner close waits for group cleanup |
| 7 Readiness and start gate | `83ac3c3` feat: Claude readiness and provider-aware start gate; `48862c0` fix: Claude readiness script test safety and docs |
| 8 Managed run lifecycle | `3ed3298` feat: Claude managed run lifecycle; `c0bd6e4` fix: Claude run launch failure handling and pins |
| 9 Stop, shutdown, restart, follow-up | `41e98bc` feat: Claude stop, shutdown, restart and follow-up; `18a48e5` fix: unknown Claude tasks no longer block their project |
| 10 Cost, usage and UI wording | `2e94f30` feat: Claude cost, usage and UI wording; `375a70a` fix: Claude UI wording, denied names and cost guards |
| 11 Journey test and closeout | `08afae7` test: Claude fake-binary journey over HTTP; the documentation commit (this file and the docs) follows it |

## Test counts

Clean environment (`HOME` and `XDG_CONFIG_HOME` set to new temporary directories). Counts after each task are
from the per-task reports and the controller ledger (`.superpowers/sdd/2026-10-28-claude-dashboard-managed-run-loop/`,
git-ignored). Skipped is 36 throughout (PyJWT is absent on this machine; CI installs it).

| Point | Python | Node |
| --- | --- | --- |
| Start of Plan 3 | 924 | 133 |
| After Task 2 | 940 | 133 |
| After Task 3 | 976 | 133 |
| After Task 4 | 989 | 133 |
| After Task 5 | 1004 | 133 |
| After Task 6 | 1024 | 133 |
| After Task 7 | 1040 | 137 |
| After Task 8 | 1062 | 137 |
| After Task 9 | 1089 | 137 |
| After Task 10 | 1091 | 151 |
| After Task 11 (final run, see Final verification) | 1099 (OK, 36 skipped) | 151 |

Task 1 (a spike) adds no tests. No existing test was removed or skipped. Existing tests were edited in two
places: the Task 7 stub-pinning edits (four tests, listed in the Task 7 report) and, outside that exception, two
tests in Task 8 that pinned the removed "Claude runs are not available yet." refusal
(`tests/test_claude_readiness.py` and `tests/test_provider_routes.py`).

## Characterization goldens

`git diff --stat b547e0b..HEAD -- tests/fixtures/characterization/`: empty output (run in Task 11). Codex
behaviour is unchanged as far as the goldens and the Plan 2 lifecycle parity suites can show.

## Kinds of evidence

- Unit tests (offline): all of Tasks 2 to 10, with mutation checks recorded in several task reports (a change
  was applied to a scratch copy and a test had to fail).
- Fake-binary journey: `tests/test_claude_journey.py`, 8 tests over HTTP on ephemeral ports (the eighth, `test_a_second_fresh_run_on_one_dashboard_is_refused_as_session_rejected`, pins the shared-session-id refusal). They run
  `tests/fake_claude.py` (replaying sanitized fixtures) through the real argv builder, process runner and HTTP
  handler: provider and connection, a successful run with usage, cost and no sensitive markers in the state,
  a denied-call run, a follow-up with `--resume` and added totals, stop, the Codex-only 409 answers, and the
  restart sweep. This is fake-binary evidence, not a live run.
- Live: only the four spike S9 runs (Task 1), alias `haiku`, Claude Code 2.1.312 (plus one accidental `claude --version` call in Task 7, which made no model call and kept no output), about 0.004 USD at list
  price in total (the per-run `total_cost_usd` values are 0.0010149, 0.00084515, 0.00077745 and 0.0010532).
  Findings with qualifiers are in `docs/superpowers/spikes/S9-role-and-environment.md`; one run per condition.
- Owner-reported: none. The owner confirmed the plan defaults on 2026-10-28 (decisions, not test evidence).
- Browser evidence: none. The UI changes are covered by Node tests against a DOM double.

## What remains untested

- A real `claude` through the dashboard (start, stream, completion, follow-up, stop).
- A long real run; the 16 MiB line cap and the stop ladder against the real CLI.
- Approvals (Plan 4); with no hook, denied calls are only seen in the fake fixture.
- Linux (the tests hard-code `/private/tmp` and use macOS `ps` output) and Windows.
- Aliases other than `haiku` (S9), and user-level allow rules or hooks, which could change what reaches the dashboard.
- The CLI's snapshot-on-resume behaviour (the original appended system prompt is kept) and `--resume` against a
  real session.
- Process-group behaviour of the real CLI and its descendants (a descendant that leaves the group is not reached).
- `--effort` effect (accepted, not observable in S9) and the missing `claude-code-guide` agent in the scrubbed
  environment of S9 (cause unknown).
- The look of the page in a browser (denied-call line, cost estimate, Claude wording).
- A Claude deployment with an invalid `.claude/agents/*.md` role file (it fails at construction; no Dashboard-level
  test) and user-level allow rules or hooks (calls would run without a denial).
- The instruction text is passed as a command-line argument and is visible through `ps` while a run lasts.

## Not run

The optional live smoke run (Plan Task 11, Step 3) was **not run**: it needs the owner's separate approval, which
has not been given. Recorded as a gap. Ready-to-run description for when the owner approves:

- Alias `haiku`. Open point for the owner: the dashboard takes the model from the role, and every generated
  role in `.claude/agents/` uses `opus` or `sonnet` (checked), so a `haiku` run through the dashboard needs a
  scratch role or a temporary role change outside this plan's scope; the cost estimate below is only valid
  for `haiku`. Do not run it on `opus` without a new cost statement.
- One run through the dashboard (`sh scripts/run_dashboard.sh claude`) on a scratch project outside the repository
  with a trivial instruction, then one follow-up, then one stop of a second slow run if a run is still cheap.
- Record `claude --version`, the status sequence, the usage counters, the cost estimate, the follow-up totals and
  whether the denied-call notice appears. Expected cost estimate from S9: about 0.001 USD for a tiny run (list
  price, not a billed amount); state the estimate to the owner before the run.
- Write the note as `docs/superpowers/spikes/S10-dashboard-live-smoke.md`, labelled live evidence with its
  qualifiers (one run, one alias, one machine).

## Review history

Tasks 2 to 10 had an independent review of their diff, recorded in the git-ignored ledger directory (Task 1 and Task 11 are documentation: Task 1's note was reviewed and corrected, Task 11 awaits the controller's writer review).

| Task | Verdict | Fix rounds | Notable findings |
| --- | --- | --- | --- |
| 1 | Approved | 2 (note corrections, then the R9e combination run) | 4 Important and 6 Minor fixed in the S9 note. |
| 2 | Needs fixes, then fixed | 1 (`c29bfeb`) | The reviewer found fidelity differences from the real stream shapes; fixed in `c29bfeb` (bad_model, interrupted, new subagent fixture, SIGINT-tail and timing items). |
| 3 | Approved | 1 | 2 Important and 5 Minor fixed (model id regex, partial usage, byte cap). |
| 4 | Approved | 0 | Old and new lifecycle byte-identical; one note: the new test alone cannot see changes inside the extracted method, parity and characterization suites cover it. |
| 5 | Needs fixes, then fixed | 1 | Important: resume session id validation; plus hardening (dotfile imports, bounded read, containment). |
| 6 | Approved after scoped re-review | 2 | Spawn race on a concurrent stop, reader bound, group cleanup, close waiting for cleanup. |
| 7 | Approved | 1 | Script test safety, docs; disclosure: the real `claude --version` ran once by mistake; a reviewer mutation briefly ran a scratch `dashboard.server`. |
| 8 | Approved | 1 | Storage error after registration, overflow after a result keeps status (ruling), new code `claude_session_rejected`. |
| 9 | Approved | 1 | Important: unknown Claude tasks blocked their project; fixed by ruling (hold only while flagged). |
| 10 | Approved | 1 | Snapshot leaked the whole internal `claude` record (process id, session id); reduced to the denied summary. Cost guards. |
| 11 | Independent writer review follows from the controller | n/a | Not yet done at the time of writing. |

Final whole-branch review (`0d0b66b..d78d53f`): CHANGES NEEDED, 0 Critical, 3 Important, 12 Minor. Important:
the Dashboard launch line was not pinned for the environment allow-list (a mutation to `dict(os.environ)`
survived); stale README and two stale comments; the instruction text is visible through `ps` (ruling: kept,
disclosed). Fixed in the closeout-fix commits: new test
`test_child_environment_is_the_allow_list_at_the_dashboard_launch` in `tests/test_claude_runs.py`, which fails
against `dict(os.environ)` in a scratch mutation (checked); README and comments; disclosures in the docs; test
and doc minors. Behaviour-changing minors were not made and are on the task board.

## Final verification (Task 11, clean environment)

- `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests`: `Ran 1099 tests in 217s`, `OK (skipped=36)`
- `node --test tests/*.js`: tests 151, pass 151, fail 0, skipped 0
- `python3 scripts/sync_roles.py --check`: `role files are in sync`
- `python3 scripts/security_check.py staged`: `Security check passed: staged.` (run with the closeout files staged)
- `python3 scripts/security_check.py history` (read-only, no push): `Security check passed: history.` (read-only, nothing pushed)
- Journey test: 8 tests, three consecutive runs OK; no `fake_claude` process left afterwards.
- A first full run, made before this file existed, failed only the documentation link test (`broken link
  superpowers/evidence/2026-10-28-managed-run-loop.md` in `docs/claude-code-setup.md`): 1099 tests, 1 failure,
  36 skipped. Expected while the file was missing.

## Documentation impact

Documentation impact: user behaviour changed (a `claude` deployment now starts, stops and continues runs; a new
cost unit; a denied-call notice) and the API fields and diagnostics changed. Pages changed:
`README.md` (found stale by the writer and final reviews), `docs/dashboard-operations.md`, `docs/dashboard-api.md`, `docs/product-brief.md`, `docs/claude-code-setup.md`,
`docs/decisions.md`, `docs/task-board.md`; this file is new. The stale statements the Task 7 review listed were
fixed (`claude-code-setup.md` stub passages and the "not supported yet" list, `dashboard-api.md` 409 and
connection text, `product-brief.md` "not implemented yet"); `docs/decisions.md` (Plan 2 entry) and the older
`docs/task-board.md` Plan 2 entry describe the stub as history and were left.

Self-check against `.claude/agents/technical_writer.md` and `.claude/agents/user_documentation_writer.md`, made
by the Task 11 implementer; the independent writer review follows from the controller.

- Facts were read in the code and tests, not copied from reports: the environment allow-list in
  `dashboard/backends/claude_launch.py`, the stop timings in `ClaudeRun`, the follow-up limit and refusal texts in
  `dashboard/conversation.py`, the diagnostics codes and notice text in `dashboard/diagnostics.py`, the snapshot
  reduction and `CLAUDE_PRICING` in `dashboard/server.py`, and the HTTP answers by running the journey test (for
  example a stop request for a finished run answers the generic 400, not the internal message).
- Planned work is kept apart from delivered work: approvals (Plan 4), conversation, team view, outputs and delivery
  readiness (Plan 5) and observed sessions (Plan 6) are described as not done. Fake-binary and live evidence are
  labelled separately; no page says a real Claude run was driven through the dashboard.
- One value could not be verified from code and is stated as an expectation only: the smoke-run cost range (from S9).
- The plan numbering in older text (slice 2b as Plan 4, Phase 3 as Plan 5) was corrected to the plan document's
  numbering in `docs/claude-code-setup.md`.
- Secrets and paths: no credential, home-directory username path or full session id was written (fixture session
  ids are the synthetic ones and are not quoted); searched with `grep` before the commit.
- Checks not made: no browser check of the wording; no live run.

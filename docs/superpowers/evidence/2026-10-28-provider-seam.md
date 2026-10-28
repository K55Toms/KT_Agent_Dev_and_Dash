# Provider seam (Claude dashboard Plan 2) evidence

Date: 2026-10-28. Branch `provider-seam` (local, unpushed), cut from `phase-2-design` at `b547e0b`.
Plan: `docs/superpowers/plans/2026-10-28-claude-dashboard-provider-seam.md`. Design:
`docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md`. Baseline before this plan:
`docs/superpowers/evidence/2026-10-27-phase-2-baseline.md`.

What this plan delivered, in one paragraph: a provider-neutral backend interface with a Codex adapter,
a start-up provider setting that fails closed, the provider recorded on projects and runs, provider
labels and 409 answers, and spike S8 on project instructions. The Claude backend is a stub. Codex
behaviour is meant to be unchanged; the evidence for that is below and is offline only.

## Commits per task

`git log --format='%h %s' b547e0b..HEAD` (the closeout commit follows these 18).

| Task | Commits (fix commits last) |
| --- | --- |
| 1 Spike S8 (live) | `65627b9` docs: S8 project instructions spike; `430c4fe` docs: S8 note corrections after review |
| 2 Characterization tests fail instead of skip in CI | `a599a5a` test: fail characterization tests without scanner in CI; `30acab4` test: guard the third scanner skip site and the function path |
| 3 Neutral types and `Backend` protocol | `857543e` feat: neutral backend types |
| 4 Codex translator | `8e18664` feat: Codex notification translator; `249947d` fix: Codex translator keeps raw turn error |
| 5 `CodexBackend` for launch, guidance, interrupt | `43aa68b` refactor: route Codex launch, guidance and interrupt through CodexBackend; `b4a9085` fix: pass validated client to CodexBackend |
| 6 Run lifecycle through neutral events | `be85d81` refactor: handle Codex run lifecycle through neutral events; `240bd0f` test: pin turn/started approval guard and recovery terminal |
| 7 Approval answering through the backend | `4b9b76f` refactor: answer Codex approvals through CodexBackend; `826bbd3` test: pin consume-before-respond ordering for approval answers |
| 8 Provider resolution and start-up setting | `d9b3505` feat: start-up provider setting that fails closed; `8b7ee08` test: pin fail-closed provider default in main |
| 9 Provider recorded on projects and runs | `283f3e3` feat: record provider on projects and runs |
| 10 Provider-aware routes and UI labels | `4719689` feat: gate Codex-only routes and label the provider; `316ff67` test: close Task 10 review gaps |
| 11 Documentation closeout | `docs: provider seam closeout` (this commit) |

## Test counts

Full Python suite in a clean environment (`HOME` and `XDG_CONFIG_HOME` set to new temporary
directories), Node suite alongside. Counts after each task are taken from the per-task reports and
the controller ledger (`.superpowers/sdd/2026-10-28-claude-dashboard-provider-seam/`, git-ignored).
Skipped is 36 throughout (PyJWT is absent on this machine; CI installs it).

| Point | Python | Node |
| --- | --- | --- |
| Plan 1 end (Plan 2 baseline) | 758 | 126 |
| After Task 2 | 762 | 126 |
| After Task 3 | 768 | 126 |
| After Task 4 | 792 | 126 |
| After Task 5 | 810 | 126 |
| After Task 6 | 839 | 126 |
| After Task 7 | 858 | 126 |
| After Task 8 | 874 | 126 |
| After Task 9 | 885 | 126 |
| After Task 10 | 908 | 133 |
| Now (run by the Task 11 implementer, see Final verification) | 908 (OK, 36 skipped) | 133 |

Net change: +150 Python tests, +7 Node tests. Task 1 (a spike) and Task 11 (documentation) add no
tests. Task 11 changed no file under `dashboard/` or `tests/`. No existing test was removed or
skipped; the only existing test edits were the Task 2 decorator swaps at
`tests/test_characterization_conversation.py`, `tests/test_characterization_approvals.py` and
`tests/test_characterization_runs.py` (a third silent-skip site found in Task 2, same intent) plus
`tests/characterization.py`.

## Characterization goldens

`git diff --stat b547e0b..HEAD -- tests/fixtures/characterization/` (run by the Task 11 implementer):
empty output, exit 0.

The plan text names `85c14bc` as the base; against that commit the same command lists three files
as added (`approvals.json`, `conversation.json`, `runs.json`, 3525 insertions), because Plan 1 created the
goldens after `85c14bc`. `b547e0b` is Plan 2's starting point and already contains them, so the empty
result above means Plan 2 did not change any golden.

## Kinds of evidence

- Unit tests (offline, fake App Server clients and scripted notifications): all of Tasks 2 to 10,
  including the mutation checks recorded in several per-task reports (a change was applied to a scratch copy and a
  new test had to fail). These show the code does what the tests say, not that a live Codex or Claude
  session behaves the same.
- Codex characterization goldens (offline snapshots of the existing Codex projection, from Plan 1):
  unchanged, see above. They pin run lifecycle, approvals and conversation projections.
- One live spike: S8 (Task 1), `docs/superpowers/spikes/S8-project-instructions.md`. Four runs of
  `claude` on the `haiku` alias, one per condition, subscription login. One of the four failed at
  start-up before any model call (a relative path in the harness). Findings: `--append-system-prompt` and its
  file form made both codewords visible under `--setting-sources user`; `--add-dir` alone did not; no
  documented environment variable was found, so that run was not made. One run per condition, a trivial
  prompt, and the spike does not test the `@AGENTS.md` import resolved by Claude Code itself.
- Owner-reported items: none. The owner has not yet reviewed the results.
- Browser evidence: none. The UI changes are covered by Node tests against a DOM double; no one looked at
  the page in a browser in this plan.

## What remains untested

- No Claude run has gone through the dashboard. The Claude backend is a stub that raises "not
  implemented"; Plan 3 builds it.
- The Codex native end-to-end path (a real App Server, a real model turn, a real approval) was not re-run
  live in this plan. The refactor of launch, guidance, interrupt, run lifecycle and approval answering
  rests on unit tests, the goldens and review.
- No browser check of the provider labels, the chip, the disabled connection indicator or the disabled Start
  run control for `claude` or no provider.
- A `turn/completed` notification whose status is a list or object still raises `TypeError` in
  `dashboard/conversation.py` (pre-existing, unchanged module; recorded in `docs/decisions.md`).
- Carried forward, not fixed (full wording in `docs/task-board.md`):
  - Codex wording still reachable under the Claude stub (empty task list, usage empty state, plan and
    checks notices, delete announcement, "Create Codex thread"), and static page text that shows Codex
    wording until `/api/provider` answers.
  - A future provider should require both recovery and assessment capabilities for the assessment routes
    nested under `/recovery` (handoffs): today the mapping is a judgement that is equivalent for every
    current provider.
  - `GET /api/tasks/{id}/recovery` for a run recorded under another provider still creates a recovery row
    under Codex.
  - `ProviderUnavailable` is a `ValueError`: Plan 3 must raise it before any state change or catch it ahead of
    the generic `ValueError` handlers, or a failed launch or send could record `unknown` with a recovery hold.
  - Parked review minors: vacuous assertions in `tests/test_backends_base.py`, and the untested provider
    exemption in `Capabilities` validation.
- Owner decisions still open: review of these results, whether to push or open a pull request, and a go for
  Plan 3.

## Review history

Every code task had an independent review of its diff, written to the git-ignored ledger directory. The
reviewer model is named only where the ledger names it.

| Task | Verdict | Fix rounds | Notable findings |
| --- | --- | --- | --- |
| 1 | Approved | 1 (by the controller) | 1 Important and 4 Minor fixed in the note (`430c4fe`). |
| 2 | Approved | 1 (by the controller) | Important: a third silent-skip site (`tests/test_characterization_runs.py`); Minor: a function-path test was added. |
| 3 | Approved | 0 | Minors parked: vacuous assertions in `tests/test_backends_base.py`, provider exemption untested. |
| 4 | Approved with 1 Important | 1 | Important: the raw `turn.error` must be kept so error classification is unchanged (`249947d`). Several carry-forward notes for Task 6. |
| 5 (opus) | Needs fixes | 1 | Unguarded paths resolved the client at send time, weaker than the old captured client; fixed with an optional keyword-only `client=` (`b4a9085`). |
| 6 (opus) | Approved, 0 Critical or Important | 1 | Two pinning tests added (`turn/started` keeps `waiting_approval`; recovery terminal call precedes the stale filter). Accepted deviation on non-string `turn.id`; residual `TypeError` recorded. |
| 7 (opus) | Needs fixes | 1 (tests only) | Important: consume-before-respond (Review Focus 8) was not pinned by tests; Minors: guidance kind shim, `str` subclass case, dead tuple element. |
| 8 (opus) | Approved with 1 Important | 1 (tests) | Important: the `main()` fail-closed default was untested (`8b7ee08`). |
| 9 | Approved, 0 Important | 0 | Three Minors routed to Task 10 (record provider on recovery-created tasks, 409 for the mismatch refusal, guard the remaining recovery routes). |
| 10 (opus) | Approved, 0 Important, 4 Minors | 1 | Completeness test now expands alternations; 'none' wording; test scope; docstring (`316ff67`). |
| 11 | Pending | n/a | An independent writer review follows from the controller. |

## Final verification (Task 11, clean environment)

Run by the Task 11 implementer on 2026-10-28 from the repository root:

- `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests`: `Ran 908 tests in 143.222s`, `OK (skipped=36)`. (A second identical run made earlier in the same session, before this file existed, ran 908 and had the one expected doc-link failure described below.)
- `node --test tests/*.js`: tests 133, pass 133, fail 0, skipped 0.
- `python3 scripts/sync_roles.py --check`: `role files are in sync`, exit 0.
- `python3 scripts/security_check.py staged`: `Security check passed: staged.`, exit 0 (run with the closeout files staged).
- `python3 scripts/security_check.py history` (read-only, no push attempted): `Security check passed: history.`, exit 0.
- `sh scripts/run_dashboard.sh` with no argument, with `Codex`, with `claude2` and with `codex ` (trailing
  space): each printed `Usage: sh scripts/run_dashboard.sh codex|claude` and exited 2; `sh -n` exited 0. No
  server was started with a valid argument.
- A first Python run, before this evidence file existed, failed one documentation test (`broken link
  superpowers/evidence/2026-10-28-provider-seam.md` in `docs/claude-code-setup.md`). That was expected
  while the file was missing; the run above is the one made after the file was added.

## Documentation impact

Documentation impact: user behaviour changed (the launch command takes a required argument; a `claude`
deployment exists and shows a stub state) and the API gained a route and fixed 409 answers. Pages
changed: `README.md` (Start), `docs/dashboard-operations.md`, `docs/dashboard-api.md`,
`docs/product-brief.md`, `docs/claude-code-setup.md`, `docs/decisions.md`, `docs/task-board.md`, and the
plan's Interfaces text. This file is new.

Self-check against `.claude/agents/technical_writer.md` and `.claude/agents/user_documentation_writer.md`,
made by the Task 11 implementer (not an independent writer review, which follows from the controller):

- Every route, status code, error string, capability value and label was read in `dashboard/server.py`,
  `dashboard/backends/*.py`, `dashboard/static/app.js` and the Task 8 to 10 tests; the gated route families
  were copied from `GATED_ROUTES`, and the list of actions guarded by "recorded under a different provider"
  from the call sites of `_require_active_provider`. The exact error strings (with and without the final
  period) were compared against `tests/test_provider_routes.py` and `tests/test_provider_setting.py`.
- The launcher behaviour (exit 2 for no argument, `Codex`, `claude2`, `codex `) was executed; nothing else
  about the launcher was run. The sentence "no dashboard environment variables" still holds: the provider
  is a launcher argument passed as `--provider`, and `docs/dashboard-operations.md` keeps the sentence.
- The user-visible start-command change is called out in `README.md` and in a bold paragraph in
  `docs/dashboard-operations.md`, with the one-word fix (add `codex`).
- Planned work is kept apart from delivered work: the Claude backend, slice 2b and Phase 3 are described
  as not done; the `claude` deployment is described as a stub and no page says a Claude run works.
  `docs/claude-code-setup.md` labels what was seen as "checked against the source and its unit tests, not
  by a browser or a live run".
- Recovery guidance for users: how to get back to Codex (`sh scripts/run_dashboard.sh codex`), that records
  under the other provider are kept but refuse actions, and that the provider cannot change while running.
- Checks not made: no browser check of the UI wording; no live Claude or Codex run; no independent writer
  review yet. `docs/model-evaluation.md` has an older sentence quoting the argument-less launcher as a
  historical record; it was left as history.
- Secrets and paths: the changed files contain no credential, no home-directory username path and no full
  session id (searched with `grep` for `/Users/` and the account name; no match). Scratch paths in S8 are
  written as `<scratch>`.
- One stale statement was corrected while here: `docs/claude-code-setup.md` said it was not tested whether
  `--setting-sources user` loads the project `CLAUDE.md`; spike S6 later tested it (not visible under
  `user`, visible under `user,project`, one run each). Role files and `.mcp.json` remain untested.

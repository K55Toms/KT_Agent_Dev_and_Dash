# Phase 2 baseline record

Date: 2026-10-27

This records the Codex-side test baseline before any Claude dashboard refactor. Later plans compare
their counts against it.

## Commit

- Checkout: branch `phase-2-design`, `git rev-parse HEAD` = `85c14bce6465cb5f70e483afa5ceb754e0ea3d19`.
- `main`: `git rev-parse origin/main` (after `git fetch origin`) = `3c9e534509a70211a87966fb5729d71503d68bb0`.
- `phase-2-design` differs from `origin/main` only in two files under `docs/` (372 lines added). No
  code or test file differs, so the results below are the `main` code baseline (3c9e534).

## Tools

- Python 3.15.0
- Node v26.11.1

## Results

| Suite | Seconds | Tests run | Failures | Errors | Skipped |
| --- | --- | --- | --- | --- | --- |
| Python (`unittest`) | 116 (115.989 reported by unittest) | 738 | 0 | 0 | 36 |
| Node (`node --test`) | 0.2 (duration_ms 195; 0.36 wall) | 126 | 0 | 0 | 0 |

## Commands

Python, clean environment (isolated `HOME` and `XDG_CONFIG_HOME`, because the dashboard strips
`GIT_*` variables):

```
HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests
```

Node:

```
node --test tests/*.js
```

## Skips

Skips differ between this machine and CI. PyJWT is absent on this machine (`import jwt` raises
`ModuleNotFoundError`), which accounts for the 36 skipped Python tests; CI installs PyJWT and
recorded 738 Python tests with none skipped at the last record.

## Run-lifecycle characterization (Task 2)

`tests/test_characterization_runs.py` pins the Codex run lifecycle projection (7 tests, goldens in
`tests/fixtures/characterization/runs.json`). To prove the tests detect regressions, each mutation
below was applied to a scratch copy of the repository (never to `dashboard/` in the working tree), and
only the new module was run there. The unmutated copy passed (7 tests, 0 failures).

| Mutation (in `dashboard/server.py`, scratch copy) | Result | Failing test |
| --- | --- | --- |
| (a) `turn/completed` status map sends `failed` to `completed` | Detected | `test_failed_turn_projection` |
| (b) the `turn/plan/updated` branch is disabled | Detected | `test_start_to_completed_projection` |
| (c) the stale-turn guard is ignored | Detected | `test_stale_turn_event_is_ignored` |

The scratch copy was deleted afterwards.

## Approval characterization (Task 3)

`tests/test_characterization_approvals.py` pins the Codex approval flows (6 projection tests plus 2 tests of
the `CHARACTERIZE=1` scanner guard, goldens in `tests/fixtures/characterization/approvals.json`). Besides the
snapshot, the tests assert the exact replies and rejections the dashboard sends to the native client. Each
mutation below was applied to a scratch copy of the repository (never to `dashboard/` in the working tree),
and only the new module was run there. The unmutated copy passed (8 tests, 0 failures).

| Mutation (in `dashboard/server.py`, scratch copy) | Result | Failing test |
| --- | --- | --- |
| (a) `respond_approval` replies `decline` when the decision is `accept` | Detected | `test_command_approval_pending_then_accepted` |
| (b) pending approvals are no longer cleared on `turn/completed` (`_finish_approvals` disabled and `turn/completed` removed from `_approval_event`) | Detected | `test_pending_approval_finished_when_turn_completes` |
| (c) the unknown-thread rejection in `_approval` is removed | Detected (error: the request then reaches code that expects a task) | `test_approval_for_unknown_thread_is_rejected` |

The scratch copy was deleted afterwards.

## Conversation and question characterization (Task 4)

`tests/test_characterization_conversation.py` pins the Codex conversation items and question flows (5 tests,
goldens in `tests/fixtures/characterization/conversation.json`). Each golden entry holds the normalized
snapshot and the normalized stored conversation view (`Dashboard.conversation()`, with message ids made
stable); the tests also assert the exact replies and rejections sent to the native client. The module does
not stub the secret scanner, so it is skipped when gitleaks is unavailable. Each mutation below was applied
to a scratch copy of the repository (never to `dashboard/` in the working tree). The unmutated copy passed
(5 tests, 0 failures). Where the new module failed, the existing conversation tests were not needed; where
it is noted, they were also run (`tests.test_conversation`, 18 tests).

| Mutation (scratch copy) | Result | Failing test (new module) | Existing `tests.test_conversation` |
| --- | --- | --- | --- |
| (a) `_expire_questions` in `dashboard/conversation.py` marks expired questions `resolved` (answered) instead of `unavailable` | Detected | `test_question_expires_on_turn_completed` | Passed (did not detect it) |
| (b) `dashboard/server.py` no longer rejects an `item/tool/call` from an unowned thread or a stale turn | Detected | `test_unsupported_tool_call_is_rejected` | Passed (did not detect it) |
| (c) `safe_text` in `dashboard/conversation.py` no longer scans stored conversation text | Detected | `test_agent_message_with_sensitive_text_is_withheld` | Detected (`test_question_identifier_and_all_options_pass_one_complete_scan`, `test_sensitive_question_id_is_withheld_after_full_scan`) |

The scratch copy was deleted afterwards.

Totals after Task 4 (clean environment, as above): Python 758 tests run (753 + 5 new), 0 failures, 0 errors,
36 skipped (119.4 s); Node 126 tests, 126 pass, 0 failures.

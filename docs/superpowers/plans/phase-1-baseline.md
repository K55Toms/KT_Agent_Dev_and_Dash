# Phase 1 test baseline

Recorded before any Claude Code adaptation code changes. Later tasks compare their regression
results against these counts. Nothing was fixed or adjusted to make the counts match.

- Date: 2026-10-26
- Branch: `claude-code-adaptation` (cut from `origin/main` e3afb04104e7acb18132c5121d13a66600cde798)
- Commit under test (HEAD): `4339842` (docs-only commits on top of origin/main)

## Starting point verification

- `git rev-parse origin/main`: `e3afb04104e7acb18132c5121d13a66600cde798`
- `git status -sb`: clean (`## claude-code-adaptation`)
- `git log --oneline origin/main..HEAD`: 15 commits, all documentation (spec, plan, spike findings, amendments)
- `git diff --stat origin/main..HEAD`: 8 files, 2003 insertions, every file under `docs/superpowers/`;
  no file outside `docs/superpowers/` differs from origin/main.
- `sh scripts/bootstrap.sh`: re-run (idempotent), reported "Repository hooks installed."

## Tool versions

| Tool | Version |
|---|---|
| python3 | 3.15.0 (project requires 3.11+) |
| node | v26.11.1 |
| git | 2.56.0 |
| gitleaks | 8.30.1 |

## Python

Command: `python3 -m unittest discover -s tests -v`

| Ran | Passed | Failed | Errors | Skipped | Wall-clock |
|---|---|---|---|---|---|
| 584 | 546 | 2 | 0 | 36 | about 1m55s (unittest reports 114.7s) |

Result line: `FAILED (failures=2, skipped=36)`. Passed is derived (584 - 2 - 36); unittest does not print it.

### Failures (pre-existing, environment related)

Both are in `tests/test_git_service.py` (`GitServiceTests`):

1. `test_dirty_counts_and_credential_paths_hidden` - `state["hidden_changes"]` was 0, expected 1.
2. `test_historical_forbidden_path_is_rejected_before_scanner_reads` - the fixture `git commit` returned 1.

Cause (diagnosed read-only, nothing changed): both tests write a `.env` file into a temporary
repository and expect Git to see it. The tests isolate `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_NOSYSTEM`,
but not Git's default XDG ignore file. This machine has `~/.config/git/ignore`, which lists `.env`
(line 17), so Git silently ignores the file: it is not counted as a hidden change, and the fixture
commit has nothing to commit and exits 1. A scratch repository confirmed `git check-ignore` matches
`.env` through that file. This is a host-configuration difference, not a Python 3.15 issue. The
project's task board reports these tests passing on a machine without that global ignore entry.

### Skipped tests (36)

All 36 skip for one reason: `Reviewed PyJWT[crypto] dependency is not installed`. No other skip
reasons appear. This matches the task board's "36 skipped". The tests it hides are the PyJWT-based
checks; they do not run on this machine until PyJWT[crypto] is installed.

## Node

Working command: `node --test tests/*.js`

| Ran | Passed | Failed | Cancelled | Skipped | Wall-clock |
|---|---|---|---|---|---|
| 126 | 126 | 0 | 0 | 0 | about 0.25s (reported 189 ms) |

Important: the brief's `node --test tests/` does NOT work on Node v26.11.1. It exits cleanly but
runs zero tests (`tests 0, pass 0`), which would look like a pass. Use the explicit glob. The
repository documentation does not state a Node test command (the `docs/` grep found none); the
seven JS test files are `tests/test_*_ui.js`.

## Project secret checks

| Command | Result |
|---|---|
| `python3 scripts/security_check.py staged` | passed ("Security check passed: staged.") |
| `python3 scripts/security_check.py history` | passed ("Security check passed: history.") |

## Comparison to the task board's expected counts

- Python total 584 and 36 skipped match. Passed is 546, not the expected 548, because of the two
  host-environment failures above.
- Node 126 passed matches (with the explicit glob command).

## Reference for later tasks

Expect the same 2 Python failures and 36 skips on this machine until the environment changes.
Treat any additional failure, any change in total (584 Python, 126 Node), or any change in the skip
count as a regression introduced by the task.

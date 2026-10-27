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

# Live proof evidence (Claude deployment)

Plan: `docs/superpowers/plans/2026-11-10-live-proof.md`. Owner go for Parts 1 and 2 given in chat on 2026-11-10 (alias
`haiku`, 5 runs, about 0.06 USD).

Status: **blocked before any model turn.** The Claude Code CLI's subscription login could not authenticate. Nothing in
Parts 1 to 4 is proven yet.

## Setup (done, no model use)

- `claude` 2.1.312. Scratch clone of `main` at `1c1860f`; every Claude role set to `haiku` / `low` in the clone's
  `team_source/models.toml` and regenerated with `scripts/sync_roles.py` (28 files). The real tree and its roles were not
  changed.
- Fresh state folder (the clone's own `.local`), port 8766, a scratch git project (`notes-seed.txt`, `check.sh`) outside the
  repository.
- Browser: the dashboard opened with its key URL; the project was added through the Add project dialog; the Start run dialog
  showed "Configured: haiku · low reasoning".
- Side effect outside the scratch folders: starting the `claude` deployment created the per-install token folder and file for
  Terminal sessions in the owner's user configuration folder (folder mode 0700; contents not read). None existed before.
- The dashboard was stopped afterwards; ports 8766 and 47615 are closed and no `claude -p` process remained.

## Launches so far

| # | Kind | What | Result | Reported cost |
| --- | --- | --- | --- | --- |
| 1 | live, through the dashboard (browser) | M1 development run, role `chief_of_staff`, `haiku` | Failed in about 5 s: "Claude Code reported an API error", diagnostic `claude_api_error`, 0 tokens | 0 |
| 2 | live, direct CLI (diagnostic) | `claude -p` one-word prompt, `--model haiku --effort low --setting-sources user --max-budget-usd 0.02` | Exit code 1; `result` line: `subtype` success, `is_error` true, `terminal_reason` `api_error`, `api_error_status` absent; message says authentication failed because the OAuth session expired and could not be refreshed | 0 |

Launch 2 was not in the plan. It was used to find the cause of launch 1 and counts against the approved five.

## Findings

1. **Blocker (owner action):** the CLI login is expired or cannot be refreshed from where these runs start. Not known which:
   launch 2 ran from the controller's shell, launch 1 from the dashboard process. The owner signing in again in their own
   terminal, then one successful `claude -p` there, would separate the two.
2. **Product finding (new, open):** an expired login is shown as `claude_api_error` ("Claude Code reported an API error"),
   not as `claude_not_logged_in`. `classify_claude` reads `api_error_status` and `terminal_reason` only; here the status is
   absent and the reason is `api_error`, so the sign-in cause is carried only in the withheld result text. The advice text
   does mention sign-in. One observation, CLI 2.1.312. Owner: backend_developer; not fixed here (no code change during the
   proof).
3. `haiku` with effort `low` reached session start (`init` line, model resolved, permission mode `default`). Whether the
   pairing completes a turn is still not verified.

## Not done

M1 (rerun), M2, M3, M4, the browser steps (output attach, delete), S12, Part 3 and Part 4.

# S8: project instructions in managed Claude runs (spike findings)

Date: 2026-10-28. Claude Code version: `2.1.312 (Claude Code)` (`claude --version`, saved per run in
`out/<run>.version`; identical in all runs below).
Model alias: `haiku` (the `init` event reported `model=claude-haiku-5-5` in all three completed runs).
Fixed flags in every run: `-p --output-format stream-json --verbose --setting-sources user --model haiku`,
stdin `/dev/null`, cwd an empty directory, subscription login, no API key, no `--settings`, no `--agents`.
Permission mode observed in all three completed runs: `init.permissionMode` = `default`.

Owner approval: 2026-10-28, at most 4 live runs, `haiku` only, one run per condition, no repeats.
**Runs used: 4.** R8a, R8b (first attempt, failed at start-up, see below), R8b (second attempt) and R8c. R8d was not run.
`<scratch>` below means `/private/tmp/claude-501/.../scratchpad/s8` (outside the repo). Raw streams stay there and
are not committed. No credential, token or environment variable was used, printed or recorded.

The question: S6 found that the project `CLAUDE.md` is not loaded under `--setting-sources user`. The dashboard
launches managed runs with that flag, so which mechanism hands the project's `CLAUDE.md`, including its
`@AGENTS.md` import, to such a run? The owner chose `--append-system-prompt` (the dashboard expands the
`@AGENTS.md` import itself) as the first candidate and `--add-dir` as the alternative.

Scratch project `<scratch>/project/` (no `.claude/` folder):
- `CLAUDE.md`: `Instruction one: the codeword is `amber-harbor-1111`.`, a blank line, then `@AGENTS.md`.
- `AGENTS.md`: `Instruction two: the codeword is `cedar-lantern-2222`.`
- `<scratch>/expanded.txt`: `CLAUDE.md` with the `@AGENTS.md` line replaced by the content of `AGENTS.md`
  (the two instruction lines, separated by a blank line).
- cwd of every run: `<scratch>/empty/` (an empty directory), so nothing can come from the working directory.

Prompt for every run (`<scratch>/prompt.txt`): "List every codeword in your project instructions, quoted exactly;
answer NONE if you see none. No tools." Neither codeword is in the prompt.

## Step 2: what `claude --help` documents (version 2.1.312)

- `--append-system-prompt <prompt>`: listed as its own option ("Append a system prompt to the default system prompt").
- `--add-dir <directories...>`: listed as its own option ("Additional directories to allow tool access to").
- `--system-prompt <prompt>`: listed as its own option.
- **File forms**: there is no option entry for `--append-system-prompt-file` or `--system-prompt-file`. The only mention
  is inside the `--bare` description, which says to provide context via `--system-prompt[-file]`,
  `--append-system-prompt[-file]`, `--add-dir (CLAUDE.md dirs)`, `--mcp-config`, `--settings`, `--agents`, `--plugin-dir`.
  That was read as showing a file form exists, so R8b was run (it worked, see below). The `--bare` text also says
  `--add-dir` is a way to supply "CLAUDE.md dirs", but only under `--bare`; it does not say what `--add-dir` does
  under `--setting-sources user`.
- **Environment variable for `CLAUDE.md` from `--add-dir` directories**: none appears in `claude --help` (the only
  `CLAUDE_CODE_*` names in the help are `CLAUDE_CODE_SIMPLE=1` under `--bare` and `CLAUDE_CODE_SAFE_MODE=1` under
  `--safe-mode`). So the help gives no variable to test and **R8d was not run**. The owner's rule for this step was
  to note a variable only if the documentation mentions one; no other documentation was consulted.
- `--system-prompt-snapshot <on|off>`: "Record the system prompt once per conversation and reuse it verbatim on every
  request and resume ... `on` (the default ...): the prompt is rendered on the conversation's first request — a
  `--system-prompt` or `--append-system-prompt` included — sent, and recorded; every later request and resume sends the
  record as-is, even when a later launch passes different text, until the conversation is compacted. `off`: never record;
  the prompt is rendered fresh every request."

## Verdict table

| Run | Mechanism | Both codewords seen? | `@AGENTS.md` import resolved? | Answer (exact) |
|-----|-----------|----------------------|-------------------------------|----------------|
| R8a | `--append-system-prompt "$(cat expanded.txt)"` | **yes** | Not applicable to the model: the dashboard-side expansion put `AGENTS.md`'s text in the argument, and the model saw it. | `- `amber-harbor-1111`` / `- `cedar-lantern-2222`` |
| R8b | `--append-system-prompt-file <abs path>/expanded.txt` | **yes** | Same as R8a (the file holds the pre-expanded text). | `Two codewords appear in my instructions: 1. "amber-harbor-1111" 2. "cedar-lantern-2222"` |
| R8c | `--add-dir <scratch>/project`, no other instruction flag | **no** (neither) | **No**: not even `CLAUDE.md`'s own line was seen, so the import was never reached. | `NONE` |
| R8d | `--add-dir` plus an environment variable | Not run | Not run | No documented variable in `claude --help` |

Each result is one run of one condition on one model alias. Nothing was repeated except the start-up failure of
R8b described below (which made no model call).

## Runs

All commands run from `<scratch>/s8` through `run.sh`, which calls `launch.py` (stdin `/dev/null`, cwd `<scratch>/empty`)
and `summarize.py`. The argv is always `claude -p "<prompt.txt>" --output-format stream-json --verbose --setting-sources user
--model haiku <extra flags>`.

### R8a: `--append-system-prompt` with the expanded text

Extra flags: `--append-system-prompt "$(cat <scratch>/expanded.txt)"` (the text is the two codeword lines, 110 bytes in the file).
Version `2.1.312 (Claude Code)`. Observed: `result` `success`, `is_error: false`, `terminal_reason: completed`,
`num_turns: 1`, no tools used, no permission denials, exit 0, 9.98 s wall time (`duration_ms` 6729), `total_cost_usd`
0.00788 (client-side list-price figure, not a charge).
Final text: both codewords, quoted exactly.

### R8b: `--append-system-prompt-file`

First attempt: extra flag `--append-system-prompt-file expanded.txt` (relative path) with the run's cwd being the empty
directory. The CLI exited at once with code 1 after 0.21 s, empty stdout, and `.err` saying
`Error: Append system prompt file not found: <scratch>/empty/expanded.txt`. This was a harness mistake (a relative path
resolved against the cwd). No model call was made (no stream, no `init`), but it is counted as a run used to stay
inside the owner's cap. It also shows the flag exists in 2.1.312: the error is a missing file, not an unknown option.

Second attempt: `--append-system-prompt-file <scratch>/expanded.txt` (absolute path), otherwise identical. Observed:
`success` / `completed`, 1 turn, no tools, exit 0, 9.17 s (`duration_ms` 6219), `total_cost_usd` 0.00377.
Final text: both codewords, quoted exactly.

### R8c: `--add-dir <scratch>/project`

Extra flags: `--add-dir <scratch>/project` only. Observed: `success` / `completed`, 1 turn, no tools, no denials, exit 0,
5.79 s (`duration_ms` 2457), `total_cost_usd` 0.00385. Final text: `NONE`.
So under `--setting-sources user` the added directory's `CLAUDE.md` was not visible to the model, and neither was the
`AGENTS.md` it imports.

## What each run does not prove

- R8a and R8b prove that text placed in the appended system prompt reaches the model under `--setting-sources user`.
  They do not prove that Claude Code resolves an `@AGENTS.md` import: the import was expanded by the harness before the
  run, which is also what the dashboard would do. They do not test how well the model follows such instructions (only
  that it can quote them), whether an appended system prompt carries the same weight as a loaded `CLAUDE.md`
  (which Claude Code normally supplies as context, not as system-prompt text), or any model other than `haiku`.
- R8a and R8b were one run each, with a prompt that allows `NONE`; a chance difference cannot be excluded, though
  both runs found both codewords and R8c found none.
- R8c shows `--add-dir` alone does not load `CLAUDE.md` in this configuration. It does not show it can never do so:
  an environment variable or another setting source may change that. `claude --help` documents none, and none was
  tested (R8d not run). R8c used `--add-dir` with an empty cwd; a project that is also the cwd was not tested with
  `--add-dir`.
- Interaction between `--append-system-prompt` and the owner's user-level configuration (plugins, hooks, injected
  context): the user-level `SessionStart` hook seen in S6 may also run here; the codewords are unique to this spike,
  so no user-level source could have supplied them, but the runs do not show whether that configuration changes how
  the appended text is weighed.
- Nothing here covers a changed `CLAUDE.md` or `AGENTS.md` between turns (see the resume caveat), nested imports
  (`@file` inside the imported file), or relative-path imports from a directory other than the project root. The
  real `CLAUDE.md` has a single `@AGENTS.md` line; `AGENTS.md` has no `@import` line.
- Not tested: `--system-prompt` (replace instead of append), `--system-prompt-file`, `--bare`, `--setting-sources
  user,project` with an import (S6 R5c saw a plain `CLAUDE.md` without an import), interactive mode.

## Argv size of the real files

Measured in the repository root at the time of the spike (bytes):

| File | Bytes |
|------|------:|
| `CLAUDE.md` | 4,092 |
| `AGENTS.md` | 7,256 |
| Expanded text (`CLAUDE.md` with the `@AGENTS.md` line replaced by the content of `AGENTS.md`) | 11,337 |

`getconf ARG_MAX` on this machine: **1,048,576** bytes. The expanded text is about 1.1 percent of that. `ARG_MAX` limits
arguments plus environment together; the size of the environment was not measured (reading it is outside this spike's
rules), but 11 KB of arguments leaves a very wide margin. The only `@` import line in `CLAUDE.md` is `@AGENTS.md`. Two
side effects of the inline form: the text is visible in the process list (`ps`) to other local users while the run lasts,
which is acceptable for the project's instruction files but not for anything secret, and a very large file would need
the `-file` form instead.

## Resume caveat (from `claude --help`; not run)

`--system-prompt-snapshot` is `on` by default: the system prompt, including `--append-system-prompt` text, is rendered on
the conversation's first request and recorded, and every later request and every `--resume` sends that record as it is,
even when a later launch passes different text, until the conversation is compacted. So a managed run resumed after
`CLAUDE.md` or `AGENTS.md` changed would still carry the old text. Passing `--system-prompt-snapshot off` renders the
prompt fresh every request according to the help text; that was not run. The dashboard should either accept the stale
text for the life of a conversation or pass `off` after a separate check.

## Recommendation

**Plan 3 should use `--append-system-prompt "<expanded text>"`**, with the dashboard reading the project's `CLAUDE.md`,
replacing each `@AGENTS.md` import line by that file's content, and passing the result as the argument. It worked in R8a
and is a documented option in `claude --help`. `--append-system-prompt-file <absolute path>` also worked (R8b) and avoids
putting the text in the process list, but its only help mention is inside the `--bare` description, so it is the fallback
rather than the first choice; it needs an absolute path (the first attempt failed on a relative one). `--add-dir`
alone does not work (R8c) and should not be used for this. Open items for Plan 3: decide how the dashboard treats
a stale system prompt on resume, and whether a user-level configuration could change how the appended text is weighed.

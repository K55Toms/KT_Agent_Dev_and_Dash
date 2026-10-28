# S9: role as main session, scrubbed environment, effort (spike findings)

Date: 2026-10-28. Claude Code version: `2.1.312 (Claude Code)` (`claude --version`, saved per run in
`out/<run>.version`; identical in all runs below).
Model alias: `haiku` (the `init` event reported `model=claude-haiku-5-5` in all three runs).
Fixed flags in every run: `-p --output-format stream-json --verbose --setting-sources user --model haiku`,
stdin `/dev/null`, cwd an empty directory, subscription login (`init.apiKeySource` = `none`), no API key, no `--settings`.
Permission mode observed in all three runs: `init.permissionMode` = `default`.

Owner approval: 2026-10-28, at most 4 live runs, `haiku` only, one run per condition, no repeats.
**Runs used: 3.** R9a, R9c and R9d. R9b (the `--append-system-prompt` control) was not run because R9a worked. The
fourth run was kept for a widened environment and was not needed. One harness mistake before R9a (a bash 3.2
`set -u` error on an empty array in `run.sh`) stopped the wrapper before `claude` was started, so no run, no model call;
it is not counted and is disclosed here.
`<scratch>` below means `/private/tmp/claude-501/.../scratchpad/s9` (outside the repo). Raw streams stay there and are not
committed. No credential, token or environment variable value was used, printed or recorded; only the variable NAMES
passed to R9c and R9d are recorded.

The question: the dashboard launches a managed run for a role (for example `backend_developer`). Which mechanism makes
the role the main session, does a scrubbed environment (no `ANTHROPIC_*`, `CLAUDE_CODE_*`, cloud-provider variables)
still log in with the subscription, and is there a main-session effort setting?

Scratch project `<scratch>/project/.claude/agents/slate_role.md` in the generated role format
(front matter `name: slate_role`, `description`, `model: haiku`, `effort: low`, `disallowedTools: Agent`; body: "You are
the slate role. The codeword in your role instructions is `slate-orchard-3333`. When asked for the codeword in your role
instructions, state it exactly."). The runs do not read that file: `<scratch>/build_json.py` builds the `--agents` JSON from
it (`description`, `prompt` = the body, `tools` = `["Read"]`, `model` = `haiku`), the shape used live earlier. The cwd of
every run is `<scratch>/empty/`, so nothing can come from the working directory. Prompt (`<scratch>/prompt.txt`): "State
the codeword in your role instructions; answer NONE if you have none. No tools." The codeword is not in the prompt.

## Step 1: what `claude --help` documents (version 2.1.312)

- `--agent <agent>`: "Agent for the current session. Overrides the 'agent' setting."
- `--agents <json-or-file>`: "JSON object defining custom agents, or with --print the path to a file that holds one",
  example `{"reviewer": {"description": "Reviews code", "prompt": "You are a code reviewer"}}`.
- `--append-system-prompt <prompt>`: "Append a system prompt to the default system prompt" (no `-file` entry; see S8).
- `--effort <level>`: "Effort level for the current session (low, medium, high, xhigh, max)". So a main-session effort
  switch is documented.
- No effort environment variable appears in `claude --help`. The only `CLAUDE_CODE_*` names in the help are
  `CLAUDE_CODE_SIMPLE=1` (under `--bare`) and `CLAUDE_CODE_SAFE_MODE=1` (under `--safe-mode`).
- `--bare`: skips hooks, plugin sync, auto-memory, keychain reads and CLAUDE.md discovery, sets `CLAUDE_CODE_SIMPLE=1`,
  and says Anthropic auth is "strictly `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings` (OAuth and keychain are never
  read)". So `--bare` cannot use the subscription login and must not be used by the dashboard. Not run.
- Not documented in the help: whether an `--agents` definition may carry `effort` (the generated `.claude/agents/*.md` files
  have it in front matter), and whether `--agent` applies the definition's `tools` and `model` to the main session. The
  runs below tested the second only for `tools`.

## Verdict table

| Run | Mechanism | Environment | Codeword seen? | `init.tools` | Answer (exact) |
|-----|-----------|-------------|----------------|--------------|----------------|
| R9a | `--agents '<json>' --agent slate_role` | inherited | **yes** | `["Read"]` | The codeword in my role instructions is `slate-orchard-3333`. |
| R9b | `--append-system-prompt "<role body>"` | not run | not run | not run | not run (R9a worked) |
| R9c | R9a again | **scrubbed** (allow-list names only) | **yes**, logged in and answered | `["Read"]` | The codeword in my role instructions is `slate-orchard-3333`. |
| R9d | R9c plus `--effort low` | scrubbed | **yes** | `["Read"]` | The codeword in my role instructions is `slate-orchard-3333`. |

Each result is one run of one condition on one model alias. Nothing was repeated.

## Runs

All commands run from `<scratch>` through `run.sh`, which calls `launch.py` (stdin `/dev/null`, cwd `<scratch>/empty`) and
`summarize.py`. The argv is always `claude -p "<prompt.txt>" --output-format stream-json --verbose --setting-sources user
--model haiku <extra flags>`. `<json>` is the 300-character `--agents` value built from the role file.

| Run | Extra flags | Exit | Wall time | `duration_ms` | `total_cost_usd` (list-price estimate, not a charge) |
|-----|-------------|------|-----------|---------------|---------|
| R9a | `--agents <300-char arg> --agent slate_role` | 0 | 8.52 s | 5084 | 0.0010149 |
| R9c | same, scrubbed environment | 0 | 5.19 s | 2036 | 0.00084515 |
| R9d | same plus `--effort low`, scrubbed environment | 0 | 4.35 s | 1148 | 0.00077745 |

Every run: `result` `subtype=success`, `is_error=false`, `terminal_reason=completed`, `num_turns=1`, no tool used, no
permission denials, `stop_reason=end_turn`, `modelUsage` only `claude-haiku-5-5`, one `init` event, one `result` event.
`init.agents` listed `slate_role` next to the built-in agents in all three. `init` has no field naming the active agent
(`agent` is absent); the evidence that the role is the main session is the answer plus `init.tools` being exactly the
role's `["Read"]`.

### Scrubbed environment (R9c, R9d)

`launch.py --scrub-env` builds the child environment from nothing: it copies, by NAME, only `PATH`, `HOME`, `USER`, `LANG`,
`LC_*`, `TMPDIR`, `SHELL`, `TERM` that are present in the parent, after dropping any name starting with `ANTHROPIC_`,
`CLAUDE_CODE_`, `AWS_`, `GOOGLE_`, `VERTEX`, `BEDROCK`, and passes that dict as the child's environment (the same effect
as `env -i NAME=value ...` without putting values in the process list). Names actually passed (recorded in the run meta
file): `HOME`, `LC_CTYPE`, `PATH`, `SHELL`, `TMPDIR`, `USER`. `LANG` and `TERM` were not set in the parent, so they were not
passed. R9c and R9d logged in and answered with no widening, so **the decision-2 allow-list is enough on this machine**.

One difference between R9a and R9c/R9d: `init.agents` in the inherited environment also listed `claude-code-guide`, the
scrubbed runs did not. The cause was not investigated (an inherited `CLAUDE_CODE_*` variable is a candidate, not
established).

### Effort (R9d)

`--effort low` was accepted (exit 0, normal result). The stream carries no effort field: `init.per_turn_effort_active` was
`true` in all three runs, including those without `--effort`, so it does not reflect the flag. R9d's output was 3 tokens
against 6 in R9a and R9c, and the wall time was shorter, but one run per condition on a one-line answer shows nothing about
effort.

## What each run does not prove

- R9a shows `--agents` plus `--agent` puts the role's `prompt` in the main session's instructions and applies its `tools`
  list to the main session, under `--setting-sources user` with an empty cwd. It does not show that the definition's `model` was used: `--model haiku` was also passed,
  and the role's model was `haiku` as well. It does not show that a definition's `effort` is accepted or applied (not in
  the JSON, not tested).
- R9b was not run, so `--append-system-prompt` as a role mechanism was not compared (S8 proved it for text only).
- Role instructions were quoted, not obeyed: no run tested whether the model follows the role's rules, or how the
  `--agents` prompt is weighed against the default system prompt or the owner's user-level configuration (the
  user-level SessionStart hook seen in S6 and S8 may have run; its output was not inspected).
- R9c and R9d show the scrubbed environment logs in on this machine with this login. They do not show it works on a
  machine whose login depends on a dropped or unlisted variable (for example a subscription token supplied by environment variable, a proxy variable, or `XDG_*`),
  nor that the host session's own variables played no part in R9a. They do not show which of the dropped prefixes (if
  any) was present in the parent, because values and the full list of names were deliberately not read.
- The effort switch is documented and accepted; its effect on a haiku run, on the `.claude/agents` front-matter `effort`,
  and on a resumed run (`--resume`) was not observed.
- `--agent <role>` and `--resume`, `--system-prompt-snapshot` (S8), real-size role bodies, special characters in the
  `--agents` argument (backticks, quotes, non-ASCII beyond what the JSON encoder escapes), and `--agents` given as a file
  path were not tested. The 300-character JSON is far below `ARG_MAX` (1,048,576 here); 14 roles in one `--agents`
  argument were not measured, but the dashboard needs to pass only the chosen role.
- One run per condition, a prompt that allows `NONE`, `haiku` only; interactive mode and other model aliases untested.

## Recommendation for Task 5

Build `--agents '{"<role>":{"description","prompt","tools","model"}}' --agent <role>` (R9a, R9c), pass `--effort <level>`
from the role's effort (accepted in R9d, effect unobserved, and `--effort` is a session-level flag), and launch the child with
the decision-2 allow-list only (`PATH`, `HOME`, `USER`, `LANG`, `LC_*`, `TMPDIR`, `SHELL`, `TERM`; no widening was needed here);
keep `--append-system-prompt` (S8) for the project instructions and `--append-system-prompt "<role body>"` as the untested fallback.

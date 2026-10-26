# S3: Claude Code event stream mapping (spike findings)

Date: 2026-10-26. Claude Code version: `2.1.310 (Claude Code)` (`claude --version`).
Scratch project (outside the repo): `<scratchpad>/s3`, with two subagent definitions,
`.claude/agents/tool-worker.md` (`tools: Bash`, `model: haiku`, told to run one `echo` and reply in a
sentence) and `.claude/agents/text-worker.md` (`tools: Read`, `model: haiku`, told to answer in text only).
Every `claude` command ran from inside that directory, with `--model haiku` and stdin from `/dev/null`
(exact command lines per run are under "Runs"; runs 3 and 4 did not use `--include-partial-messages`).
Six short real runs were used (the
owner approved at most six). Raw streams stay in the scratch directory and are not committed; they contain
message text. `summarize_stream.py` and `inspect_tasks.py` (scratch only) print structure, enum values and
numbers, never message text. Nothing in this file quotes user or model text. No credential, token or
environment variable was printed or recorded.

The user's own `SessionStart` hook ran in every run and shows up as `hook_started` and `hook_response`
system events. That depends on the owner's settings, so a clean install may not emit them.

## Summary

| # | Question | Result |
|---|----------|--------|
| a | Does `--forward-subagent-text` change what a text-only subagent emits? | INCONCLUSIVE (confounded, see below). Text-only subagent text did appear as an `assistant` event with the flag and did not without it, but the two runs also differed in whether the subagent ran in the background |
| b | Is `usage` cumulative or per message? | PER MESSAGE (per API call), not a running total; and the `assistant` event copy is a start-of-message snapshot that under-reports output tokens |
| c | Shape of a genuine failure | OBSERVED for two kinds: invalid model name, and a tool call denied in headless mode |
| d | Shape of an interruption | OBSERVED for SIGINT while text was streaming (`result` with `error_during_execution`). The first attempt did not behave as intended (see Run 5) |
| e | Every dashboard projection mapped | See the mapping table. Two have no real Claude equivalent (plan updates, an approval request awaiting an answer) |

## Runs

| Run | Kind | Exit | Stream lines |
|-----|------|------|--------------|
| 1 | success, with `--forward-subagent-text` | 0 | 126 |
| 2 | success, without the flag | 0 | 79 |
| 3 | failure: invalid model | 1 | 5 |
| 4 | failure: tool denied in headless mode | 0 | 20 |
| 5 | interrupt attempt (did not behave as intended) | 0 | 65 |
| 6 | interrupt | 0 | 29 |

Verbatim command lines (inputs only; `<scratchpad>` stands for the session scratch directory, and each
command ran with `<scratchpad>/s3` as the working directory):

```
# Runs 1 and 2 (P is the shell variable below; the same string for both)
P='First delegate once to the tool-worker agent. Then delegate once to the text-worker agent asking it for a one-sentence greeting. Then reply done.'

# Run 1
claude -p "$P" --model haiku --allowedTools Agent --output-format stream-json --verbose --include-partial-messages --forward-subagent-text < /dev/null > run1-forward.ndjson 2> run1.err

# Run 2 (identical to run 1 except the last flag is absent)
claude -p "$P" --model haiku --allowedTools Agent --output-format stream-json --verbose --include-partial-messages < /dev/null > run2-noforward.ndjson 2> run2.err

# Run 3
claude -p "say hi" --model no-such-model-xyz --output-format stream-json --verbose < /dev/null > run3-badmodel.ndjson 2> run3.err

# Run 4
claude -p "Create a file named s3-denied.txt containing hello, using the Write tool." --model haiku --output-format stream-json --verbose < /dev/null > run4-denied.ndjson 2> run4.err
```

Runs 5 and 6 were started from a Python script (`Popen` with `stdin=subprocess.DEVNULL`, stdout piped to
`run5-sigint.ndjson` / `run6-sigint.ndjson`, stderr to `run5.err` / `run6.err`), with these argument lists:

```
# Run 5 (<scratchpad>/s3/run_interrupt.py): SIGINT 4 s after the first Bash tool_use event
["claude","-p","Run this single Bash command and then say done: sleep 40","--model","haiku","--allowedTools","Bash(sleep:*)","--output-format","stream-json","--verbose","--include-partial-messages"]

# Run 6 (<scratchpad>/s3/run_interrupt2.py): SIGINT on the 8th text delta
["claude","-p","Count from 1 to 600, one number per line, no other text.","--model","haiku","--output-format","stream-json","--verbose","--include-partial-messages"]
```

Provenance of the run 1 and run 2 prompts: the stream does not echo the user prompt (`task_started.prompt`
holds only the main session's delegation text to each subagent). No script or shell history of runs 1 to 4
was saved in the scratch directory; the command lines above are copied from the commands issued in the
session that ran them, where both runs 1 and 2 used the same `$P` string. That identity cannot be re-verified
from the scratch files alone, so treat it as reported, not proven. Runs 5 and 6 are verifiable from the two
saved scripts. The `claude` stderr for run 3 was one line; the others were empty.

SIGINT was sent from a Python `subprocess` parent (`Popen.send_signal(signal.SIGINT)`), not from a shell
background job, because a shell may start background jobs with SIGINT ignored.

## Event shapes seen (key names only)

Top-level `type` values: `system`, `stream_event`, `assistant`, `user`, `rate_limit_event`, `result`.
Every event carries `session_id` and `uuid`; the session id was one value per process in every run.

- `system` subtypes seen: `hook_started`, `hook_response`, `init`, `commands_changed`, `status`
  (`status: "requesting"` was the only value seen), `thinking_tokens`, `background_tasks_changed`,
  `task_started`, `task_progress`, `task_updated`, `task_notification`, `task_summary`,
  `post_turn_summary`, `permission_denied`.
- `init` keys include `model`, `permissionMode`, `claude_code_version`, `tools`, `agents`, `cwd`,
  `session_id`, `mcp_servers`, `plugins`, `skills`.
- `assistant` keys: `message`, `parent_tool_use_id`, `session_id`, `uuid`, `timestamp`, `request_id`; on
  subagent events also `agent_id`, `subagent_type`, `task_description`. `message` has `id`, `model`,
  `content[]` (block types seen: `text`, `thinking`, `tool_use`), `usage`, `stop_reason`.
  One `assistant` event is emitted per content block, so a message with a thinking block and a tool call
  produced two events with the same `message.id`. `message.stop_reason` was null in every `assistant` event.
- `user` keys: `message` (`content[]` blocks `tool_result` or `text`), `parent_tool_use_id`,
  `tool_use_result`, `tool_result_meta`, and `agent_id` / `subagent_type` on subagent events.
- `stream_event` (only with `--include-partial-messages`): `event.type` one of `message_start`,
  `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`;
  plus `api_message_id`, `parent_tool_use_id`. It was 76 of 126 lines in run 1.
- `task_started`: `task_id`, `run_id`, `tool_use_id`, `subagent_type`, `task_type` (`local_agent`),
  `is_backgrounded`, `spawn_depth`, `description`, `prompt`.
- `task_progress`: `last_tool_name`, `usage` `{total_tokens, tool_uses, duration_ms}`.
- `task_notification`: `status` (`completed` seen), `summary`, `output_file`, `usage` (same three keys).
- `task_updated`: `patch` with `status` and `end_time`. `background_tasks_changed`: `tasks[]`.
- `permission_denied`: `tool_name`, `tool_use_id`, `message`.
- `result` keys: `subtype`, `is_error`, `terminal_reason`, `stop_reason`, `api_error_status`, `num_turns`,
  `duration_ms`, `duration_api_ms`, `total_cost_usd`, `usage`, `modelUsage`, `model_usage_since_last_result`,
  `permission_denials`, `subagent_stats`, `result_index`, `process_turn_index`, `session_id`; and `errors`
  on the interrupt result.

## Finding a: does `--forward-subagent-text` change what a text-only subagent emits? INCONCLUSIVE

Flag name confirmed in `claude --help`: `--forward-subagent-text` ("Forward subagent text and thinking
blocks as assistant/user messages with parent_tool_use_id set", print mode with `stream-json` only). The
`CLAUDE_CODE_FORWARD_SUBAGENT_TEXT` environment variable was not tested.

Same prompt, one run each:

| | Run 1 (with flag) | Run 2 (without flag) |
|---|---|---|
| `task_started.is_backgrounded` | true for both subagents | false for both |
| `result` events in the process | 3 (`result_index` 0, 1, 2), with a second and third `init` | 1 |
| Tool-calling subagent: child `assistant` event with `tool_use` Bash | yes, `parent_tool_use_id` set | yes, `parent_tool_use_id` set |
| Tool-calling subagent: child `assistant` event with its final `text` | yes | no |
| Text-only subagent: child `assistant` event with `text` | yes (1) | no (0) |
| Child `user` event carrying the delegated prompt as `text` | no | yes (2) |
| Child `user` event carrying the Bash `tool_result` | yes | yes |

So the text-only subagent's reply was visible as a subagent-attributed `assistant` event in the flag run and
absent in the no-flag run. But the flag is not isolated: the two runs also differ in whether the harness ran
the subagents in the background, and I cannot tell from one pair whether the flag caused that. A second
confound is visible in the model's own tool input: in run 1 the two main-session `Agent` `tool_use` inputs
had keys `description`, `prompt`, `subagent_type` (no `run_in_background`; `subagent_stats.requested` was
background 0, foreground 0, unset 2), while in run 2 both inputs also carried an explicit
`run_in_background: false` (`subagent_stats.requested` was foreground 2, unset 0). The foreground run was
therefore one where the model itself asked for foreground, and that choice is a plausible driver of the
foreground/background difference independent of the flag. Each condition was run once; the budget did not
allow a repeat. What can be said:

- Without the flag, a subagent that calls a tool still produced child `assistant` and `user` events with a
  non-null `parent_tool_use_id` (this confirms the S4 observation).
- With the flag, subagent text blocks appeared as child `assistant` events in the one run made.
- Where the subagent's final answer appears depends on the run mode, not on the flag as far as seen:
  - Background (run 1, with flag): both main-session `tool_result` blocks for the Agent call are
    `async_launched` stubs (`tool_use_result` has `status: "async_launched"`, `isAsync: true`, `agentId`,
    `outputFile`, `prompt`, `resolvedModel`, `canContinueAgent`; no `content`). They do not contain the
    subagent's answer. The answer was carried by `system/task_notification.summary`, and in this run each
    summary was identical to the text of the corresponding child `assistant` event (checked for both
    subagents, by string equality, not printed). `output_file` also points to the persisted transcript.
  - Foreground (run 2, no flag): the main session's `tool_result` has `tool_use_result` with `status:
    "completed"`, `content[]` (text block), `totalTokens`, `usage`, `toolStats`; each `task_notification.summary`
    was contained in that `content` text. Run 2 has no child text events, so the `content` text could not be
    compared with the subagent's own `assistant` text; I do not know that they are the same.
- No `thinking` block was emitted for any subagent in either run (the subagents were not asked to think), so
  the thinking half of the flag was not exercised.

A follow-up should repeat each condition two or three times and pin `run_in_background` in the prompt
(for example, ask for the subagent to be run in the foreground, or in the background, in every run) so the
flag is the only difference. Until then Phase 2 should not assume the two run modes behave the same.

## Finding b: `usage` shape (observed)

`usage` appears in: `assistant` events (`message.usage`), `stream_event` `message_start`
(`event.message.usage`) and `message_delta` (`event.usage`), `task_progress` / `task_notification` (top-level
`usage` with only `total_tokens`, `tool_uses`, `duration_ms`), and `result` (`usage` and `modelUsage`).

- Per message, not cumulative. Across the main session's API calls in run 1 the `output_tokens` seen in
  `assistant` events went 8, 8, 16, 8, 8, 2, 16, 4, 7, 5 (not monotonic), while `cache_read_input_tokens`
  rose as the context grew (21539, 39321, 41335, 42083, 42659). Each message's usage describes that one API
  call. (The sequence mixes main and subagent messages; the subagent ones start their own cache at 0.)
- The `assistant` event's `message.usage` is a snapshot from the start of the message. In run 1 the main
  message `Pfbj` had `output_tokens: 8` in both of its `assistant` events but 291 in its `message_delta`
  event. The final per-message output count exists only in the `stream_event` `message_delta`, so
  `--include-partial-messages` is needed to get accurate per-message output tokens. Subagent messages had
  no `stream_event` lines at all in these runs (every `stream_event` had a null `parent_tool_use_id`), so
  their per-message usage is only the snapshot.
- The `result` event's `usage` is not the run total. In run 1 the three `result` events reported
  `output_tokens` 493, 171 and 5 in `usage`, while `modelUsage` for the same events said 790, 790 and 795, so
  the two do not agree and `usage` should not be summed or used as a total. Its exact scope was not worked out.
- `modelUsage` (per model: `inputTokens`, `outputTokens`, `cacheReadInputTokens`,
  `cacheCreationInputTokens`, `costUSD`, `thinkingTokens`, `contextWindow`) and `total_cost_usd` are
  cumulative for the process: run 1 results 0, 1, 2 had `outputTokens` 790, 790, 795 and cost 0.00704,
  0.00704, 0.00759. `model_usage_since_last_result` holds the delta (second result `{}`, third
  `outputTokens: 5`).
- The `modelUsage` output count (795) is larger than the sum of the main session's `message_delta` outputs
  (669), which is consistent with subagent tokens being included. That is an inference from the arithmetic,
  not a direct observation.
- `total_cost_usd` is a client-side estimate computed from token counts and a price table
  (`modelUsage[...].costBasis` was `"list"`, i.e. list price). It is not a billed amount and may differ on a
  subscription login. Docs not re-fetched for this wording; the `costBasis` value is what was observed.
- Failure and interrupt runs: the invalid-model run reported zeros everywhere and `total_cost_usd` 0. The
  interrupt run also reported `total_cost_usd` 0, empty `modelUsage` and zero `usage`, even though text was
  already streaming: tokens consumed before an abort are not reported.

## Finding c: failure shapes (observed)

Run 3, invalid model name (exit code 1):

- Events: `hook_started`, `hook_response`, `init`, one `assistant`, one `result`. No `stream_event` lines and
  no API call.
- The `assistant` event has `message.model: "<synthetic>"`, `message.stop_reason: "stop_sequence"`, a text
  block (the error message), and extra keys `error: "model_not_found"`, `is_api_error_message: true`,
  `api_error_status: 404`.
- The `result` event has `subtype: "success"` (not an error subtype), `is_error: true`,
  `terminal_reason: "api_error"`, `api_error_status: 404`, `duration_api_ms: 0`, `total_cost_usd: 0`.
- stderr had one line of the form `[claude-code:unrecognized_model] {...}`; stdout had the stream.
- Consequence: `result.subtype` alone does not indicate failure. A consumer must test `is_error` and
  `terminal_reason`, and the exit code (1 here).

Run 4, tool denied in headless default permission mode (exit code 0):

- The model called `Write`; the stream shows `system/permission_denied` with `tool_name`, `tool_use_id`,
  `message`, followed by a `user` event whose `tool_result` block has `is_error: true`. The model then
  replied in text and the run ended normally. The file was not created.
- The `result` event has `subtype: "success"`, `is_error: false`, `terminal_reason: "completed"`, and
  `permission_denials` of length 1 with entry keys `tool_name`, `tool_use_id`, `tool_input`.
- So a denied tool call is not a run failure. It is an event inside a successful run, visible in two places:
  `permission_denied` (live) and `result.permission_denials` (summary).

## Finding d: interruption shapes (observed, one attempt that failed and one that worked)

Run 5 (did not behave as intended): the prompt asked for a Bash `sleep 40`. The harness refused the standalone
sleep itself (the `tool_result` came back with `is_error: true` almost at once), so no long operation
existed to interrupt. SIGINT was sent 4 s after the Bash `tool_use` event, while the model was streaming its
next reply, and the process ended 0.8 s later. The stream ended after a complete `message_stop`, exit code
0, and there was no `result` event at all. I cannot say whether that
absence was caused by the signal (the run was within a second of finishing normally) so this run is not
used as evidence of the interrupt shape beyond "a process can end with exit 0 and no `result` event".

Run 6 (SIGINT sent when the 8th text delta arrived, 3.6 s after launch; process exited 1.1 s later with
code 0):

- Events after the signal: the last `assistant` text event, a `user` event with a `text` block holding the
  marker `[Request interrupted by user]` (no `parent_tool_use_id`), `message_delta`, `message_stop`, then
  the `result`.
- `result`: `subtype: "error_during_execution"`, `is_error: true`, `terminal_reason: "aborted_streaming"`,
  `stop_reason: null`, `num_turns: 2`, `total_cost_usd: 0`, `modelUsage: {}`, and `errors` as a one-element
  list holding a diagnostic string.
- The exit code was 0 even though `is_error` was true, so the exit code cannot be used to detect an
  interrupt. The dashboard should read `terminal_reason` and `subtype`.
- Not tested: SIGINT while a tool is running, while a subagent is running, or SIGTERM / SIGKILL. A hard kill
  would leave no `result` event, which a dashboard must treat as `unknown`, not `failed`.

## Mapping: dashboard projection to stream-json

Confidence: "observed" means seen in these runs. "untested" means I did not see it emitted and no source
was consulted (no Claude Code docs page was fetched in this spike); it is an expectation or an absence of
evidence, not a documented behaviour.

| Dashboard projection | Claude stream-json carrier | Confidence |
|----------------------|----------------------------|------------|
| Status: running | A process that has emitted `system/init` and no `result` yet; `system/status` (`status: "requesting"` only value seen) and `task_*` events give liveness. There is no explicit "running" field | observed (inferred) |
| Status: completed | `result` with `is_error: false` and `terminal_reason: "completed"` (`subtype: "success"`) | observed |
| Status: failed | `result` with `is_error: true` and `terminal_reason: "api_error"` plus `api_error_status`; exit code 1 for the invalid-model case. `subtype` stays `success`, so do not key on it | observed (one kind) |
| Status: interrupted | `result` with `subtype: "error_during_execution"`, `terminal_reason: "aborted_streaming"`, preceded by a `user` text event `[Request interrupted by user]`. Exit code 0 | observed (SIGINT while streaming only) |
| Status: unknown | A stream that ends with no `result` event (seen in run 5; also expected for a hard kill, which was not tested) | observed (run 5); the hard-kill case is untested |
| Plan or live progress | No equivalent of Codex plan updates. Nearest signals: `task_started`, `task_progress` (`last_tool_name`, `usage`), `task_updated`, `task_summary`, `post_turn_summary` (`status_category`, `needs_action`) for subagents and turns. A task-list tool was not in the `init` `tools` list in these `-p` runs (no name containing Todo, Plan or TaskCreate; `Task`, `ListAgents` and `TaskStop` were there) and none was called, so whether its calls would appear as `tool_use` blocks is untested | observed (absence); task-list tool untested |
| Visible messages (user and agent) | `assistant` events with `text` blocks, `message.content[].text`; the delegated prompt and replayed user text are `user` events. Streaming increments in `stream_event` `content_block_delta` (needs `--include-partial-messages`). The plain user prompt is not echoed as an event in these runs | observed |
| Token usage | `message.usage` per message (snapshot), `message_delta.usage` (final per message, partial-messages only), `task_notification.usage` / `task_progress.usage` per subagent (`total_tokens`, no input/output split), `result.modelUsage` and `result.total_cost_usd` cumulative per process. See Finding b | observed |
| Native permission requests and approvals | Denials only: `system/permission_denied` (live) and `result.permission_denials`. No stream event announced a pending request awaiting an answer in `-p` mode. Pending-approval handling comes from the S2 mechanisms (SDK `can_use_tool` callback or a `PermissionRequest` hook), not from the stream | observed (denial); request event: no equivalent |
| Delegation lineage | `task_started` (`task_id`, `tool_use_id`, `subagent_type`, `spawn_depth`, `prompt`, `is_backgrounded`); `tool_use_id` equals the `id` of the main session's `Agent` `tool_use` block, and child `assistant` / `user` events carry that same value in `parent_tool_use_id` plus a distinct `agent_id` per subagent (checked in runs 1 and 2). `task_notification` (`status`, `output_file`) closes it; `result.subagent_stats` gives totals. All subagents ran under a single `session_id`: a child run is not a separate session in the stream | observed |
| Completion | `result` (`subtype: success`, `terminal_reason: completed`), per subagent `task_notification.status: "completed"` and `task_updated.patch.status` | observed |
| Failure | `result.is_error` with `terminal_reason`, `api_error_status`; subagent failure statuses were not produced (`subagent_stats.failed` was 0), so the failed form of `task_notification` is unseen | observed (run level); subagent failure untested |
| Interruption | See the status row and Finding d | observed (one signal) |

Stream-shape caveats that affect any consumer:

- One process can emit several `result` events and several `init` events. In run 1 the backgrounded
  subagents finished after the first turn and each completion started a new turn (`result_index` 0, 1, 2;
  `num_turns` 2, 2, 1; cumulative cost). Treat `result` as end of a turn, not end of the process, and use
  process exit (or a quiet period after the last `result`) as the end of the run. In the foreground run 2
  there was one `result`.
- Child events carry `parent_tool_use_id` non-null; main-session events carry it null. `stream_event` lines
  from subagents were not seen.
- In the backgrounded run the Agent `tool_result` reached the main session before the subagent's own events
  (child events and `task_started` interleave with the parent's next turn). Rely on ids, not on event order.

## Dashboard projections with no Claude equivalent

1. Codex "plan" updates (a structured, replaceable plan list pushed by the agent). Claude has no plan
   event in this stream; the closest are the `task_*` and `post_turn_summary` events, which describe
   subagent work and turn status, not an agent's plan. A task-list tool may fill this gap but was not
   present or exercised here.
2. A pending native approval request (the "waiting for the human" state as an event). The stream shows
   only the denial after the fact in `-p` mode. The dashboard must get the waiting state from the approval
   channel (S2), not from stream-json.
3. An explicit "running" status field. Running is inferred from the absence of a terminal `result`.
4. A dedicated lineage record for child runs as sessions. Children share the parent's `session_id`; lineage
   is `parent_tool_use_id` / `task_id` / `agent_id` inside one stream.
5. Cost that is authoritative. `total_cost_usd` is an estimate and was 0 for failed and interrupted runs.
6. Per-subagent input/output token split in the stream (only `total_tokens` appears in `task_*` usage).

## Implications for Phase 2

- Keying on `is_error` and `terminal_reason` rather than `subtype` or exit code is necessary: failure and
  interrupt both had `is_error: true` with exit code 1 and 0 respectively, and a plain denial was
  `is_error: false`.
- Use `stream_event` `message_delta` for accurate per-message output tokens, and `modelUsage` for the run
  total; do not sum `assistant`-event `usage` fields.
- A subagent's final answer reached the main stream without the flag in the one foreground run
  (`tool_result.content`, which contained `task_notification.summary`), and in the one background run through
  `task_notification.summary` (the `tool_result` was only a launch stub). Use `task_notification.summary`
  and `output_file` as the cross-mode source for the final answer, and treat that as observed only for these
  four subagent runs. The foreground `content` was not compared with child text. If live subagent text
  matters, repeat the flag test with `run_in_background` pinned before relying on the flag.
- Handle zero, one or several `result` events per process, and a stream with none.

## Limits of this spike

- Haiku only, one run per condition, tiny prompts; model behaviour (delegation order, backgrounding) may
  vary between runs.
- Only `-p` mode with default permissions plus an `Agent` allow rule. Interactive sessions were not
  exercised, and neither were `CLAUDE_CODE_FORWARD_SUBAGENT_TEXT`, `--input-format stream-json`,
  `--replay-user-messages`, hook events (`--include-hook-events`), or resumed sessions.
- Failure kinds tested: invalid model and headless tool denial. Rate-limit, network, max-turns, budget
  and subagent failures were not produced.
- Interruption tested only by SIGINT during text streaming (one valid run). SIGINT during a tool call or a
  subagent, SIGTERM and SIGKILL were not tested. The earlier attempt (run 5) was inconclusive.
- Token-count conclusions come from a handful of messages; the claim that `modelUsage` includes subagent
  tokens is an inference.
- No Claude Code docs page was fetched in this spike. Everything marked observed comes from the streams;
  rows marked untested have no source behind them (neither a docs page nor an earlier S2/S4 finding) and
  are expectations to be checked in Phase 2.

# S4: Claude Code team loading (spike findings)

Date: 2026-10-26. Claude Code version: `2.1.296 (Claude Code)` (`claude --version`).
Scratch project (outside the repo): `<scratchpad>/s4`, with `CLAUDE.md` (one line, `@AGENTS.md`),
`AGENTS.md` (rule containing `S4-MARKER-7731`), `.claude/agents/reader.md`
(`tools: Read, Grep, Glob`, `model: haiku`, `effort: low`) and `.claude/agents/writer.md`
(`model: sonnet`, no `tools`). All `claude` commands were run from inside that directory.
The main session used `--model haiku` unless stated, and all runs were non-interactive (`-p`).

## Summary

| # | Question | Result |
|---|----------|--------|
| a | Does the `@AGENTS.md` import in `CLAUDE.md` work? | PASS |
| b | Can a `tools: Read, Grep, Glob` role write a file by any route? | PASS (it cannot; see caveat) |
| c | Which model does each role actually use? | PASS, but not by the method the brief specified |
| d | Which `effort` values are accepted, and what happens with a bad one? | PASS (docs value set recorded; bad value silently ignored) |

## (a) `@AGENTS.md` import: PASS

Command:

```
claude -p "What is the S4 marker string in your project instructions?" --model haiku --output-format json
```

Answer: "The S4 marker string is **S4-MARKER-7731**. It's Rule 1 in the project's `AGENTS.md`, which
`CLAUDE.md` imports." The run took 1 turn with no tool calls (`num_turns: 1`, no permission
denials), so the marker came from loaded context rather than from the model reading the file.

## (b) Read-only role: PASS (cannot write), with a caveat

Command:

```
claude -p "Use the reader agent to create a file named s4-out.txt containing hello" --model haiku --output-format stream-json --verbose
```

- The main session delegated to `reader` (`task_started`, `subagent_type: reader`).
- The reader made 0 tool calls (`tool_uses: 0`) and reported: its tools are Read, Grep and Glob, none can
  write or create files, it tried no workaround. `s4-out.txt` does not exist afterwards.
- It never reached for a shell or any other route. It has none: the tool allowlist removes them.
- Caveat: the main session then tried to write the file itself with its own Write tool, and that call
  was denied only because headless `-p` mode had no write approval. So "file absent" alone would be
  weak evidence. The stronger evidence is the reader's own report and the zero tool calls.

### Follow-up: does listing `Bash` defeat read-only? YES

A variant `.claude/agents/reader-bash.md` (same as reader but `tools: Read, Grep, Glob, Bash`):

1. Default permissions (`claude -p "Use the reader-bash agent to create a file named s4-bash-out.txt
   containing hello, by running a shell command such as: echo hello > s4-bash-out.txt" --model haiku
   --output-format stream-json --verbose`): the agent ran `echo hello > s4-bash-out.txt`. The harness
   blocked it with `Output redirection to '<path>' needs approval` (a `permission_denied` event). No
   file created. This block is the headless permission prompt, not the tool list.
2. Same command plus `--allowedTools "Bash"` (stands in for an approval): the file was created and
   contains `hello`.

Conclusion: adding `Bash` to a role's `tools` gives it a write route. It is gated only by the session's
permission rules, not by the role definition. A role that must be read-only must not list `Bash`
(and `disallowedTools` or `permissions.deny` rules would be needed as a second layer if Bash is ever
allowed). Note: the docs page lists a `safe-researcher` example with Bash and describes it as unable
to write; this test shows the tool allowlist alone does not guarantee that.

## (c) Model per role: PASS (differs as aliases imply)

Important finding: in `stream-json` output, subagent assistant messages are NOT emitted at all. Every
`assistant` event has `parent_tool_use_id` null (only one `user` event, the delegated prompt, carries
a non-null parent). So the brief's method (`message.model` where `parent_tool_use_id` is non-null)
yields nothing. Two other sources work:

- The final `result` event's `modelUsage` lists every model that billed in the run.
- Subagent transcripts are persisted at
  `~/.claude/projects/<project-slug>/<session-id>/subagents/agent-<id>.jsonl`; each assistant message
  has `message.model`. The `task_notification` event's `output_file` points to it.

Runs and results:

| Run (main model) | Agent | `modelUsage` models | Subagent transcript `message.model` |
|---|---|---|---|
| `--model haiku`, "Use the writer agent to say hi" | writer (`model: sonnet`) | haiku-5-5 and sonnet-5-5 | `claude-sonnet-5-5` |
| `--model haiku`, reader prompt (step b) | reader (`model: haiku`) | haiku-5-5 only | `claude-haiku-5-5` (same as main, so not discriminating) |
| `--model sonnet`, "Use the reader agent to say hi" | reader (`model: haiku`) | sonnet-5-5 and haiku-5-5 | `claude-haiku-5-5` |

The third run removes the ambiguity: with a sonnet main session the reader still ran on haiku, so the
`model` frontmatter is honoured. Exact IDs seen: `claude-haiku-5-5`, `claude-sonnet-5-5`.

## (d) Effort: PASS

Docs (https://code.claude.com/docs/en/sub-agents, fetched 2026-10-26): "Options: `low`, `medium`,
`high`, `xhigh`, `max`; available levels depend on the model." It overrides the session effort level
but not the `CLAUDE_CODE_EFFORT_LEVEL` environment variable (unset here). The fetch tool returned
only the first 100000 of 116349 characters of the page; this section was in the part read.

Proof the field takes effect (not just present): subagent transcripts record the effective effort per
turn. `reader` with `effort: low` recorded `"effort":"low","perTurnEffort":"low"` (two separate runs).
`writer`, with no `effort`, recorded `"effort":"medium","perTurnEffort":"medium"` (session default).

Bogus value: set `effort: bogus-value` in `reader.md` and ran
`claude -p "Use the reader agent to say hi" --model haiku --output-format stream-json --verbose`.
Observed: exit 0, `is_error: false`, agent listed and ran normally, no warning in stderr or in the
stream, and the transcript recorded `"effort":"medium"` (the default). So an invalid value is
silently ignored and falls back to the session default; there is no error or warning. A typo in
`effort` will therefore go unnoticed. (The file was restored to `effort: low` afterwards.)

## Implications for later tasks (7 to 10)

- `@AGENTS.md` import in `CLAUDE.md` is a safe way to share instructions with Codex's `AGENTS.md`.
- Enforce read-only roles by omitting `Bash` (and any write tool) from `tools`. Do not rely on
  prompts. If a reviewer role needs Bash, add deny rules and re-test.
- Verify models from `modelUsage` or the subagent transcripts, not from the stream's per-message
  `message.model`. Use a main session on a different model than the role under test.
- Validate `effort` values ourselves (for example in the dashboard or a lint), because Claude Code
  will not report a bad one.

## Limits of this spike

- Only `-p` (non-interactive) mode. Interactive permission prompts and interactive tool behaviour were
  not exercised.
- Single run per condition; model behaviour (for example whether the main session retries) may vary.
- `effort` effect on actual reasoning depth was not measured, only the effort value Claude Code applied.

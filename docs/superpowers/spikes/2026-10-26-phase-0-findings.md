# Phase 0 findings and proposed spec amendments

Date: 2026-10-26. Branch: `claude-code-adaptation`.
Status: for the owner to read and decide on. Nothing in the spec or the plan has been changed by this report.
Every spec or plan change below is PROPOSED only.

Sources: the four spike files in this folder (`S4-team-loading.md`, `S1-auth-launch-mode.md`,
`S2-approvals.md`, `S3-event-stream.md`), the spec
(`docs/superpowers/specs/2026-10-26-claude-code-adaptation-design.md`) and the plan
(`docs/superpowers/plans/2026-10-26-claude-code-phase-0-1.md`). Citations use the form
"S4 (c), lines 65-93": spike file, section, line numbers of that file. Nothing here comes from
outside those files. Where a spike marks something as untested or an inference, this report keeps
that label.

Verdict words: pass, fail, inconclusive, untested. "Holds" and "does not hold" are used only for a
specific spec claim.

## Terms used in this report

- **Headless / `-p` mode**: Claude Code run from a command line with no person at a terminal
  (`claude -p "prompt"`). No permission prompt can be shown, so anything that would prompt is denied.
- **Interactive session**: the normal terminal session the owner types into.
- **Subagent / role**: one of the 14 team roles, defined in `.claude/agents/<role>.md`.
- **stream-json**: the line-by-line event feed a headless run can print (`--output-format stream-json`).
  The dashboard would read it for status, messages and usage.
- **Hook**: a setting that makes Claude Code call a command or a web address at a set moment. The
  `PermissionRequest` hook is called when Claude Code is about to show a permission prompt.
- **Managed run**: a Claude run the dashboard starts and owns. **Observed session**: a session the owner
  starts in their own terminal.
- **Agent SDK `can_use_tool` callback**: the other way a program can answer permission requests for a run
  it started (S2 Step 1, lines 25-31).
- **Auto mode vs manual mode**: Claude Code permission modes. In Auto mode, Claude Code approves
  lower-risk calls itself without asking. In manual mode it asks. This is Claude Code's own setting, not the
  dashboard's per-project "Automatic approval mode" (spec section 1, line 40).
- **Alias**: the short model name used in a role file (`haiku`, `sonnet`, `opus`, `fable`).
- **effort**: a role-file field that sets how hard the model thinks.
- **`modelUsage`**: a field in the final `result` event listing every model that was billed in the run.

## 1. Verdict per spike

- **S4 Team loading: PASS** (S4 Summary, lines 10-17). `@AGENTS.md` import works; a
  `Read, Grep, Glob` role could not write; the `model` field is honoured (checked by `modelUsage` and
  persisted subagent transcripts, not by the method the plan specified); `effort` takes effect, and a
  bad value is silently ignored. Limits: `-p` mode only, one run per condition (S4 lines 124-129).
- **S1 Auth and launch mode: PASS for login and for the hook-skipping check; launch mode PROVISIONAL**
  (S1 Summary, lines 11-19). A headless run works on the subscription login. A project hook runs in
  headless mode by default. `--setting-sources user` keeps the login and skipped the hook. Whether
  project agents and `CLAUDE.md` still load under it is UNTESTED, and the recommendation depends on that
  (S1 lines 142-146).
- **S2 Approvals: MIXED** (S2 Summary, lines 14-21).
  - Managed callback: allow-once PASS (one run), 5 s wait PASS, longer waits untested.
  - Hook in an interactive session: HOLDS in manual mode, DOES NOT HOLD in Auto mode.
  - Dashboard down: PASS for headless runs, and confirmed for an interactive session in manual mode (owner-reported).
  - Dashboard silent or timed out in an interactive session: UNTESTED.
- **S3 Event stream: PASS for the mapping, with one INCONCLUSIVE item** (S3 Summary, lines 20-26).
  Usage shape, two failure shapes and one interruption shape were observed. The effect of
  `--forward-subagent-text` is INCONCLUSIVE (two confounds). Several dashboard needs have no Claude
  equivalent (section 4 below).

Reading across all four: the questions Phase 1 needs (S4: import form, reviewer tools, effort, model
check method) are answered. S1, S2 and S3 mostly feed Phase 2 and Phase 3. Nothing in the four files
says Phase 1 cannot proceed. That is this report's reading; the decision is the owner's (section 7).

## 2. Decisions table

| # | Question | Answer from Phase 0 | Source | Confidence |
|---|----------|---------------------|--------|------------|
| 1a | `CLAUDE.md` form for Task 12 | Use the `@AGENTS.md` import. It worked: a one-turn run with no tool calls returned the marker string that exists only in `AGENTS.md`, so it came from loaded context. | S4 (a), lines 19-29 | Pass. One run, `-p` mode, a one-line `CLAUDE.md`. A real `CLAUDE.md` with a "Claude Code differences" section overriding Codex-specific text in `AGENTS.md` was not tested. |
| 1b | Did the reviewer tool allowlist (`Read, Grep, Glob`, no Bash) hold? Does Bash defeat read-only? | It held: the reader role made 0 tool calls, said it has no tool that can write, and the file was not created. Bash defeats read-only: a role with `Bash` added created the file once the session allowed Bash, and was stopped only by the session's headless permission block, not by the role definition. So reviewers must not list Bash. | S4 (b), lines 31-63 | Pass for the allowlist, one run, on a `haiku` reader (the plan assigns `opus` to reviewers). "File absent" alone is weak: the main session's own write was denied by headless permissions (S4 lines 43-45). |
| 1c | Valid `effort` values for Task 9's Claude validator; bogus values | Per the docs page S4 fetched: `low`, `medium`, `high`, `xhigh`, `max`; "available levels depend on the model". Codex set differs: `low`, `medium`, `high`, `xhigh` (Task 9 brief, line 14), so `max` is Claude-only. A bogus value is silently ignored: exit 0, no warning, the default (`medium`) applied. So our validator is the only guard. | S4 (d), lines 95-111 | Docs-sourced. Only `low` (applied) and the session default `medium` were seen taking effect; `high`, `xhigh`, `max` and per-model availability were not tested. Recommendation: validator accepts the five documented values. The proposed table uses only `low`, `medium`, `high` (plan lines 34-40). |
| 1d | Model aliases: which were exercised, and which proposed assignments are unexercised | Exercised: `haiku` (ID seen `claude-haiku-5-5`) and `sonnet` (`claude-sonnet-5-5`). Not exercised in any spike (S1, S2, S3 and S4 runs used `haiku`; S4 also used `sonnet`): `opus` and `fable`. The plan's proposed table gives `opus` to 11 roles and `fable` to `expert_escalation`; only the two writers (`sonnet`) use an exercised alias; no role uses `haiku`. The alias list `sonnet, opus, haiku, fable` comes from docs, not from a run. FLAG for Task 15 (and see open question 5). | S4 (c) lines 65-93; S1 lines 5-6; S2 line 9; S3 line 7; spec lines 62-63; plan lines 32-40; Task 9 brief line 14 | Exercised aliases: pass. `opus`, `fable`: untested. The effort pairings (`opus` high, `fable` low) are also untested. |
| 1e | Phase 2 launch mode | Provisional: `claude -p ... --setting-sources user` (keeps subscription login, skipped the project hook in the test). Condition: project agents or `--agents` roles, and `CLAUDE.md` with its import, must still load under it. This is UNTESTED; if they do not load, S1's answer becomes "none found: API key or trusted projects only". Owner decision recorded 2026-10-26: subscription login, for personal, local use. The terms question raised by the SDK overview note was read, not interpreted, and stays the owner's own judgement; it is NOT resolved. Fallback if reversed: API key supplied outside the project by environment variable. | S1 lines 123-150 | Provisional. One run per condition; only a `SessionStart` hook tested (S1 lines 170-181). |

## 3. What Phase 0 changes in Phase 1

### (i) Task 15 Step 4: the model check

Current wording (Task 15 brief, line 12): "From Step 2's and Step 3's streams, record the `message.model` for
each subagent message. Pass: it matches the `models.toml` Claude column's alias for that role."

Why it should change: S4 found this method gave no usable answer in the model-check runs, because
text-only subagents produced no assistant events in the stream; it showed a model only for a subagent that
called a tool (S4 (c), lines 67-77). S3 saw the same pattern: without `--forward-subagent-text`, a
text-only subagent had no child text events, while a tool-calling subagent did (S3 Finding a, lines 124-126,
141-143). S4's reliable sources are `result.modelUsage` and the persisted subagent transcripts (S4 lines
77-82). S4 also says the main session must run on a different model than the role under test, because when
they are the same `modelUsage` cannot tell them apart (S4 table, line 89, and Implications, line 119).

Proposed replacement for Step 4:

> - [ ] **Step 4: Model and effort.** Run Steps 2 and 3 with `--model sonnet` for the main session so it
>   differs from the roles under test (`opus` per the proposed table). From each run record: (a) the keys of
>   the final `result` event's `modelUsage`: both the main and the role's model must appear; (b) for each
>   subagent, the `message.model` of every assistant message and the `effort` / `perTurnEffort` values in its
>   persisted transcript (located by the `task_notification` event's `output_file`, under
>   `~/.claude/projects/<project-slug>/<session-id>/subagents/`); (c) `task_started.subagent_type`, which
>   must equal the role id; (d) `claude --version` and the `init` event's `claude_code_version`. Pass: every
>   subagent assistant message's model is the model ID that the alias in `models.toml` resolved to, and the
>   recorded effort equals the `models.toml` Claude effort. Record the exact model ID seen for `opus`
>   (no ID for `opus` or `fable` was observed in Phase 0, so these are new observations, not expected
>   values). Do not use the stream's per-message `message.model` as the pass criterion; record whether child
>   assistant events appeared at all. Before the run, note (set or unset only, never the value) whether the
>   model- or effort-overriding environment variables are set, because the docs say they override role
>   frontmatter (spec line 63; S4 lines 99-100).

Notes: the effort check is added because a wrong or unsupported `effort` is ignored silently (S4 lines
106-111) and transcripts do record the effective value (S4 lines 102-105). The environment-variable check
is added because the spec and S4 cite those overrides from the docs; neither was tested.

Task 15 Step 2 needs a related edit. For text-only roles, the subagent's final answer reaches the main stream
through the Agent `tool_result` content (foreground run) or `task_notification.summary` (background run); the
cross-mode source is `task_notification.summary` plus `output_file` (S3 Implications, lines 301-306).
Proposed addition to Step 2: add `--model sonnet`, `--output-format stream-json --verbose` and `< /dev/null`
(S1 lines 43-45: an unredirected stdin gave a 3-second wait and a warning), take the quoted sentence from
`task_notification.summary` or the persisted transcript, not from child assistant events, wait for process
exit, and expect zero, one or several `result` events (S3 lines 269-273). The Ponytail scan should cover
`result.result`, the summary and the transcript.

### (ii) Task 15 Step 3: the read-only check

Current wording (Task 15 brief, line 11): "Run `claude -p "Use the security_reviewer agent to create a file named
evidence-out.txt"`. Pass: the file does not exist afterwards (delete it if it does and record a fail)."

Why it is weak: in S4, the file was absent partly because the main session's own write was denied by the
headless permission block, so absence did not prove the reviewer had no write route (S4 lines 43-45); the
Bash variant was stopped by the same block, not by the tool list (S4 lines 52-55). Also, the plan's Step 3
command has no `--output-format stream-json --verbose`, yet Step 4 reads "Step 3's stream".

Proposed replacement for Step 3:

> - [ ] **Step 3: Read-only.** Run `claude -p "Use the security_reviewer agent to create a file named
>   evidence-out.txt. Do not create it yourself. If the agent cannot, say so." --model sonnet --output-format
>   stream-json --verbose < /dev/null`. Record: (a) whether `evidence-out.txt` exists afterwards (delete it if
>   it does); (b) every tool name the reviewer called, read from its persisted subagent transcript (zero calls
>   is acceptable); (c) any `system/permission_denied` events and `result.permission_denials`; (d) the `init`
>   event's `permissionMode`; (e) the reviewer's own statement of its tools, labelled as self-report. Pass: every
>   tool the reviewer called is `Read`, `Grep` or `Glob`, and no write-capable call by the reviewer appears in
>   its transcript. The absent file is supporting evidence only. If the file exists but the reviewer's
>   transcript shows no write-capable call, record "written by the main session" and tell the owner; do not
>   record a reviewer fail on file existence alone.

Why (d): the owner's Claude now defaults to Auto mode (S2 lines 184-186), and S2 did not record the
permission mode for headless runs (S2 line 260-261); recording it tells the reader how much a denial
or an absence means.

### (iii) Other effects on Tasks 7-14

| Task | Effect |
|------|--------|
| 7 (parser) | No change. |
| 8 (renderers) | No wording change. Two notes: the `tools` allowlist and the `effort` and `model` fields were exercised in S4; `disallowedTools: Agent` (plan Decision 2) was NOT exercised in any spike, so "no recursive delegation" rests on the docs claim (spec lines 62, 65) until a live check. |
| 9 (policy) | Effort set for the Claude column: `low`, `medium`, `high`, `xhigh`, `max` (section 2, row 1c). Because Claude ignores a bad `effort` silently, the validator is the only guard. Flag `opus` and `fable` as unexercised when showing the owner the file in Step 1 (row 1d). |
| 10 (extract roles) | No change. |
| 11 (sync and drift) | No change. |
| 12 (`CLAUDE.md`, setup doc) | Use `@AGENTS.md` import (row 1a); `test_claude_md_references_agents_md` fits. The statement "subagents cannot ask the owner questions" and "reviewers have read-only tools and the coordinator or QA runs checks" are consistent with S4 for tools; the first rests on the docs only (spec line 65) and was not tested. Whether the differences section overrides conflicting `AGENTS.md` text was not tested. The setup doc should say approvals and observed sessions are Phase 2/3 and not yet supported, which matches S2 and S3. |
| 13 (regression) | No change. |
| 14 (project records) | No wording change required. The records may cite this report for the open items. |
| 15 (live evidence) | Replacement wording for Steps 2, 3 and 4 above. |

## 4. Findings that matter for Phase 2 and Phase 3 (not Phase 1 work)

1. **Auto mode and the permission hook.** In Auto mode the `PermissionRequest` hook was never called for
   a Bash command that Auto mode approved itself; in manual mode it was called and its allow was applied.
   The dashboard therefore sees only calls that reach a prompt. Whether Auto mode sometimes escalates a
   riskier call to a prompt (which would then reach the hook) is untested. Source: S2 owner interactive
   check, lines 184-199, and Implications lines 220-226.
2. **The hook payload has no `tool_use_id`.** Fields received: `cwd`, `effort`, `hook_event_name`,
   `permission_mode`, `permission_suggestions`, `prompt_id`, `scratchpad_dir`, `session_id`, `tool_input`,
   `tool_name`, `transcript_path`. Correlate on `session_id`, `prompt_id` and tool input; never treat two
   identical commands as one request. The body contains local paths, so treat it as sensitive. Source: S2
   lines 98-111, 234-235.
3. **The dashboard is not the only answerer.** In manual mode the owner reported a permission prompt visible
   before the hook's allow was applied, so the terminal can answer while the dashboard request is pending.
   What happens to each side when the other answers first is untested. Source: S2 lines 200-210, 258-259.
4. **Hook timeout and dashboard-down, headless.** A hook that took 30 s with `timeout: 20` was cut off at
   about 20 s (inferred from run duration, 25.6 s); the call was not run and not allowed. An 8 s delayed
   allow was applied. With the dashboard down, the headless run denied. The docs say HTTP hook failures are
   non-blocking by default, and an `onFailure` setting (v2.1.295 and later) accepts `continue` or `block`;
   `block` was not tested. Interactive: DOWN falls back to Claude Code's own prompt (manual mode,
   owner-reported); silent or timed out was not tested. Source: S2 lines 113-169, 211-214, 238-242.
5. **Managed-run fail-closed has to be built.** The callback must wait with a timeout and return deny when no
   human answers. A callback that raises or hangs was not tested. Allow applies to one call only (one
   run). Source: S2 lines 53-55, 243-245.
6. **Managed runs only see calls that would prompt.** Plain `echo` and `ls` ran without any callback;
   approval tests need a prompting command (for example `>> file`). Source: S2 lines 33-40, 227-231.
7. **Usage is per message, and cost is an estimate.** `usage` describes one API call; do not sum
   `assistant`-event usage. The `assistant` copy is a start-of-message snapshot; the final output count is in
   `stream_event` `message_delta` (needs `--include-partial-messages`). The `result.usage` field is not the run
   total; `modelUsage` and `total_cost_usd` are cumulative for the process. `total_cost_usd` is a list-price
   estimate, 0 for failed and interrupted runs. Source: S3 Finding b, lines 162-194.
8. **`result` is the end of a turn, not of the process.** A run with background subagents emitted three
   `result` events. Use process exit (or a quiet period) as the end of the run. A killed process may leave no
   `result` event; treat that as unknown, not failed. Source: S3 lines 269-273, 242-243.
9. **Key on `is_error` and `terminal_reason`, not `subtype` or exit code.** Invalid model: `subtype` stayed
   `success`, `is_error: true`, `terminal_reason: api_error`, exit 1. Interrupt while streaming: `is_error: true`,
   `terminal_reason: aborted_streaming`, exit 0. A denied tool call is `is_error: false`, `completed`, visible in
   `permission_denied` and `result.permission_denials`. Source: S3 Findings c and d, lines 196-243.
10. **No Claude equivalent for several dashboard projections.** Plan updates; a pending-approval event
    (the stream only shows a denial afterwards, so the waiting state must come from the approval channel); an
    explicit running status (inferred from no `result` yet); child runs as separate sessions (all share one
    `session_id`; lineage is `parent_tool_use_id`, `task_id`, `agent_id`); authoritative cost; a
    per-subagent input/output token split. A task-list tool might fill the plan gap but was not present or
    tested. Source: S3 lines 279-292, 258.
11. **`--forward-subagent-text` effect: INCONCLUSIVE.** Text-only subagent text appeared as a child
    assistant event with the flag and not without it, but the two runs differ in two ways: the subagents ran
    in the background with the flag and in the foreground without it, and the model's own `Agent` tool input
    differed (an explicit `run_in_background: false` only in the no-flag run). One run each. Where the final
    answer appears depends on the run mode. A follow-up should repeat each condition two or three times with
    `run_in_background` pinned. Phase 2 should not assume the two run modes behave the same. Source: S3
    lines 112-160, 301-306.
12. **Two stream-handling details.** Redirect stdin when launching `claude -p` (S1 lines 43-45, 167-168). In the
    backgrounded run, the Agent `tool_result` reached the main session before the subagent's own events;
    rely on ids, not order (S3 lines 276-277).

## 5. Version note

S4, S1 and S2 were recorded on Claude Code `2.1.296`; S3 on `2.1.310`, after an update installed between
them (S4 line 3, S1 line 3, S2 line 3, S3 line 3). S2 notes that the Agent SDK ships its own bundled CLI
(`2.1.310`) which was not used: `managed.py` pointed the SDK at the system `claude` so all S2 runs used
`2.1.296` (S2 lines 6-8). Where this could matter:

- The managed approval path was proven on `2.1.296` through the system CLI. If Phase 2 lets the SDK use its
  bundled CLI, that combination was not tested.
- The stream shapes in S3 (events, `terminal_reason` values, `--forward-subagent-text`) are from `2.1.310`.
  S4's observation about missing subagent events is from `2.1.296`. S3 reports its tool-calling-subagent
  result as confirming S4 (S3 lines 141-143), but the two were never run side by side on one version.
- The launch-mode flags (S1) and the hook behaviour (S2) are from `2.1.296`. The `onFailure` hook field needs
  `2.1.295` or later (S2 lines 158-161); `2.1.296` satisfies that.
- Recommendation: every later evidence file records `claude --version`; the `init` event also carries
  `claude_code_version` (S3 lines 89-90).

## 6. Spec amendments (PROPOSED, not applied)

Nothing below has been applied to the spec. Each needs the owner's yes. Section and line numbers are the
spec's.

### A1. Section 3, "Not verified" paragraph (lines 74-75)

Current: "Not verified: whether `CLAUDE.md` can import `AGENTS.md`; the exact `PermissionRequest` timeout;
whether hook-driven approval behaves the same in every permission mode."

Proposed: "Verified in Phase 0: `CLAUDE.md` can import `AGENTS.md` with `@AGENTS.md` (Spike S4). Partly verified:
a configured HTTP hook `timeout` of 20 s ended a headless wait at about 20 s, inferred from run duration; the
600 s default is from the docs and not tested (S2). Found not to hold: hook-driven approval is not the same in
every permission mode. It worked in manual mode and the hook was not called for calls that Auto mode approved
itself (S2)."

Evidence: S4 (a) lines 19-29; S2 lines 113-127, 184-199.

### A2. Section 3, "Session approvals" row (line 68)

Current: "A `PermissionRequest` hook fires in interactive sessions, including ones the owner starts. A command or
HTTP hook can return allow or deny. A silent hook leaves the normal prompt in place."

Proposed: "A `PermissionRequest` hook fires in interactive sessions the owner starts when the session is in manual
permission mode; it is not called for calls that Auto permission mode approves itself. Per the docs, an HTTP hook can
return allow or deny; only allow was tested (a 3 s delayed allow was applied interactively, an 8 s one headless),
and a hook deny was not exercised, headless or interactive. The payload has no `tool_use_id`. A permission prompt
can be visible while the hook waits. If the hook cannot be reached (connection refused), the normal prompt
appears (owner-reported, manual mode). A reachable but silent hook, and a hook timeout, were not tested in an
interactive session. In headless mode an unanswered or timed-out hook results in a denial."

Evidence: S2 lines 188-214, 103-106, 120-127.

### A3. Section 3, "Managed approvals" row (line 67)

Current: "...may wait indefinitely, and returns allow or deny. Allow applies to that call unless a permission
update is returned."

Proposed: keep the docs sentence but add: "Phase 0 tested three consecutive 5 s waits and a deny with a message,
and allow applied to one call only; longer waits, a callback that raises, and a callback that never returns
were not tested."

Evidence: S2 lines 47-66, 262-267. Reason: the spec presents a docs claim as a finding; the spike confirmed
only part of it.

### A4. Section 4.1, `CLAUDE.md` bullet (lines 98-100)

Current: "`CLAUDE.md` is thin: it imports `AGENTS.md` (if Spike S4 confirms that works; otherwise it references it)..."

Proposed: remove the condition: "`CLAUDE.md` is thin: it imports `AGENTS.md` with `@AGENTS.md` (confirmed in
Spike S4) and adds Claude-specific notes..."

Evidence: S4 (a), lines 19-29.

### A5. Section 4.2, capability-flags bullet (lines 111-112)

Current: "Each backend declares capability flags. The UI shows per run what is supported. Known difference: Claude
subagents cannot ask the owner questions."

Proposed: append: "Differences seen in Spike S3 (six short `haiku` runs in `-p` mode; no docs page was fetched): no
plan-update event was seen, and a task-list tool was not present or tested, so plan support is unconfirmed rather
than absent; no event for a pending approval was seen in `-p` mode (only denials, after the fact), so the waiting
state is expected to come from the approval channel, and interactive sessions were not tested; no explicit
running field was seen (running is inferred from the absence of a final `result`); child runs shared the
parent's session id in the runs checked (lineage is `parent_tool_use_id`, `task_id`, `agent_id`); usage was per
message in the messages inspected; cost is a list-price estimate, and was 0 in the one failed and one
interrupted run."

Evidence: S3 lines 279-292, 162-194.

### A6. Section 4.3, observed sessions (lines 125-130)

Current: states a receiver that accepts hook events including permission requests; observed sessions are
"read-only apart from approvals".

Proposed: add: "Approvals reach the receiver only for calls that reach a permission prompt. In Auto permission mode
the calls Auto mode approves itself are never sent, so the dashboard must not present its list as a complete
record of what a session did. Requests are correlated on `session_id`, `prompt_id` and tool input, because the
hook payload has no tool call id. The terminal prompt and the dashboard can both be live at once; what happens
when both answer is untested and is a Phase 3 test item."

Evidence: S2 lines 184-210, 103-106, 220-226.

### A7. Section 7, first bullet, fail closed (lines 175-177)

Current: "Fail closed: if the dashboard is down or an approval is unanswered, a managed run denies and an observed
session falls back to Claude Code's own prompt. Nothing is auto-allowed. Unknown state stays unknown."

Proposed: "Fail closed. Managed run: the approval callback itself must return deny when no human answers in its wait
(Phase 0 showed the deny path and headless denial of unanswered requests; it did not test a callback that raises
or hangs). Observed session: if the dashboard is down (connection refused), Claude Code's own prompt appears and
nothing is auto-allowed (confirmed once in manual mode, owner-reported). A reachable but silent dashboard, and
the hook timeout in an interactive session, are untested. Nothing was auto-allowed in any Phase 0 run where no
one answered. Unknown state stays unknown."

Evidence: S2 lines 148-152, 211-214, 238-245.

### A8. Section 8, open risk 1 (lines 185-188)

Current: "Managed runs may execute a project's own hooks and MCP servers, and `--bare` ... does not use subscription
login. If Spike S1 finds no mode that does both, the choice is an API key, or accepting the risk for projects
the owner trusts."

Proposed: "Spike S1: a headless run executes a project's `SessionStart` hook by default; `--bare` skips hooks but
fails on the subscription login. `--setting-sources user` kept the login and skipped the hook (one run per
condition); `--safe-mode` and `--restricted` also did; per the help text, not tested, `--safe-mode` also disables agents and
`CLAUDE.md` and `--restricted` removes Bash. The managed
launch mode is `--setting-sources user`, provisional until it is shown that project agents (or roles passed with
`--agents`) and `CLAUDE.md` still load under it. If they do not, the choice returns to an API key or trusted
projects only. Only a `SessionStart` hook was tested; MCP servers and other hook events were not."

Evidence: S1 lines 47-55, 83-111, 133-168.

### A9. Section 8, open risk 2 (lines 189-192)

Current: "Whether a subscription-login dashboard is permitted is the owner's call..."

Proposed: "Owner decision recorded 2026-10-26: subscription login for dashboard-run Claude sessions, for the owner's
personal, local use. The SDK overview note was read, not interpreted; whether it applies remains the owner's own
judgement and is not resolved by Phase 0. Fallback if reversed: an API key supplied outside the project
through an environment variable."

Evidence: S1 lines 113-131.

### A10. Section 1, "Stated by the owner", auth bullet (line 26)

Current: "Sign-in is the owner's Claude subscription. No keys in the project."

Proposed: "Sign-in is the owner's Claude subscription, for personal, local use (recorded 2026-10-26). If that is
reversed, an API key supplied outside the project by environment variable. No keys in the project."

Evidence: S1 lines 123-131.

### Where no amendment is proposed

- Section 3, "Read-only roles" row (line 64): S4 agrees (Bash gave a write route gated only by session
  permissions). No amendment needed; it could add "confirmed in S4" if the owner wants it.
- Section 3, "Models" row (lines 62-63): the alias list is from docs; opus and fable are untested but the row
  makes no claim about tests. No amendment. The gap is handled in Task 15 and open question 5.
- Section 3, "Cost" and "Project hooks" rows (lines 69, 71): S3 and S1 are consistent. The "Project hooks" row also
  mentions MCP servers, which S1 did not test.
- Section 4.2, "Spike S2/S3 decide which" (line 117): the spikes show both routes can work (SDK callback for
  approvals, S2 Step 1; stream-json for events, S3; hook answers in `-p` mode, S2 Step 2) and did not compare
  them. This is a Phase 2 plan decision, not a spec edit (open question 7).
- Section 4.2, "Allow means one call. No session grants." (lines 119-121): matches the managed-callback result (one
  run). No amendment.
- Section 6 and the rest of 4.1: no change.

## 7. Open questions for the owner

1. **Accept this report and start Phase 1?** Task 5 Step 3 says Phase 1 does not start until you accept it.
2. **Which of A1 to A10 do you want applied to the spec?** Say yes or no per amendment.
3. **Phase 3 approval strategy given Auto mode.** In Auto mode the dashboard never sees calls that Auto mode
   approves (S2 lines 184-199). Options the evidence allows: require manual mode for observed sessions; accept
   partial coverage and label it clearly in the UI; or drop approvals for observed sessions. This needs your
   decision before Phase 3 planning.
4. **Repeat the S3 flag test with `run_in_background` pinned, before Phase 2?** It would use a few more
   subscription runs (S3 lines 158-160). Without it, Phase 2 should not rely on `--forward-subagent-text`.
5. **Should `opus` and `fable` be checked before Task 9, or first at Task 15?** No spike used either (section 2,
   row 1d). A small pre-check (one short run per alias) would find a rejected alias or effort pairing before
   the 14 files are generated; otherwise the first test is Task 15, after generation. Either costs subscription
   usage and needs your yes.
6. **Is the recorded subscription-login decision still your decision?** Recorded in S1 with the terms
   question left to your judgement. No action is needed unless you want to revisit it.
7. **Phase 2: Agent SDK callback or `claude -p` with a hook for managed approvals?** Both worked in S2 and S3.
   The SDK adds a dependency (spec lines 117-118). Under the provisional `--setting-sources user` mode, a
   project-level hook would not load (S2 line 139-140), which is relevant to this choice. This can be settled in
   the Phase 2 plan; it is listed because of the dependency.

## 8. Not tested in Phase 0

**Team loading (S4, lines 124-129)**
- Interactive mode and interactive permission prompts.
- More than one run per condition.
- Effect of `effort` on reasoning depth; any `effort` other than `low` and the default `medium`; per-model
  availability of effort levels.
- Aliases `opus` and `fable` (no spike run used them).
- `disallowedTools`, `permissionMode` and other frontmatter fields; a Bash-allowed role with deny rules or a
  `PreToolUse` hook as a second layer.
- Reviewer read-only check on a model other than `haiku`; the stream method for subagents that call tools was
  not tested further (S4 lines 74-77).
- A real `CLAUDE.md` (the test one was one line) and whether its differences section overrides `AGENTS.md`.

**Auth and launch mode (S1, lines 152-181)**
- Under `--setting-sources user`: whether project agents, `CLAUDE.md` and its import, skills, `.mcp.json` servers,
  project plugins and `--agents` roles load; whether `--strict-mcp-config` helps.
- That the dashboard must supply its own permission rules (project deny rules are dropped).
- Whether the owner's own user-level hooks run under it.
- Hook events other than `SessionStart`; repeat runs.
- That no API key was set (inferred from `--bare` failing, environment not inspected); `--bare` with an API key.
- Legal reading of the subscription terms (read, not interpreted).

**Approvals (S2, lines 249-271)**
- Managed waits longer than 5 s; hook waits between 8 and 20 s, and longer than 20 s with a larger timeout.
- Interactive: a silent dashboard or hook timeout; the owner answering in the terminal while the hook is pending
  (and the reverse); how a prompt and an allowing hook interact on screen; a hook deny answer, which was
  exercised in neither headless nor interactive mode (the stub only answered allow); Auto mode escalating some
  calls to prompts.
- A callback that raises or never returns; `--permission-prompts none`; hook `onFailure: "block"`;
  `updated_permissions` ("remember this").
- Tools other than `Bash`; whether a hook allow is per call; the `permission_mode` value in the payload.
- The owner's user-level settings and hooks were not read and could change results.
- The 20 s cut-off is inferred from run duration. The prompt in the "dashboard down" interactive check rests on the
  owner's report.
- The Agent SDK's bundled CLI version (`2.1.310`) with the managed path.

**Event stream (S3, lines 309-324)**
- `--forward-subagent-text` in isolation (confounded); the `CLAUDE_CODE_FORWARD_SUBAGENT_TEXT` variable; the
  thinking half of the flag.
- `--input-format stream-json`, `--replay-user-messages`, hook events (`--include-hook-events`), resumed
  sessions, interactive sessions.
- Failure kinds other than invalid model and headless tool denial (rate limit, network, max turns, budget,
  subagent failure).
- Interrupt during a tool call or a subagent; SIGTERM and SIGKILL. Run 5 (interrupt attempt) was inconclusive.
- A task-list tool as a source for plan-like events.
- The scope of `result.usage`; the claim that `modelUsage` includes subagent tokens is an inference.
- Models other than `haiku`; tiny prompts; no docs page was fetched in S3, so "untested" rows have no source.
- The user's own `SessionStart` hook produced `hook_*` events in every S3 run; a clean install may not emit them
  (S3 lines 15-16).
- The identity of the run 1 and run 2 prompts is reported, not proven (S3 lines 70-75).

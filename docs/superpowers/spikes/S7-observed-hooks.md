# S7: hooks in an interactive Claude Code session (spike findings)

Dates: 2026-10-27 (first session) and 2026-10-28 (second session); all times below are UTC (the log times equal the
transcripts' `Z` timestamps). Model alias `haiku`.
Claude Code version, read from the `version` field of each session transcript: first session `2.1.310` (steps a1,
a2, b, c1 and the stray prompts), second session `2.1.312` (steps c2, d and e). The version changed between the
sessions (verified from the transcripts); the Terminal panel text the controller read showed "Update installed ·
Restart to apply" in the footer. The version is not recorded per step beyond that.
Hook type used: **`http`**, in the scratch project's `.claude/settings.json`, one entry per event, each
`{"type":"http","url":"http://127.0.0.1:<port>/hook","timeout":N}` with port 53400, timeout 10 s for
`SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop` and 60 s for `PermissionRequest`. The `command`
hook type was not tested.
Permission mode: the owner started `claude --model haiku --permission-mode manual` (OWNER-REPORTED command; the
footer text "manual mode on" was read by the controller in the Terminal panel). The hook payload said
`permission_mode` = `default` on every request in that mode (log, `pmode=default`). In the second session the
transcript shows the mode changing `default` to `auto` at 08:54:39, inside the same session id, so Auto was
reached by switching mode in the running session, not by a restart; the footer "auto mode on" was read by the
controller.

Tags: **OWNER-REPORTED** marks a fact that rests on what the owner saw or said and that the log, files,
transcripts or Terminal panel text the controller read itself do not show. Untagged facts come from the receiver
log, the files in the scratch project, the session transcripts, or Terminal panel text the controller read.

## Method

A throwaway stub receiver (`s7/stub_receiver.py`, outside the repository, loopback only, no authentication)
answered `PermissionRequest` from a mode file: `allow`, `deny`, `silent` (never answer), `delay-allow` (hold
30 s, then allow). Other events were answered `{}`. In `allow` and `delay-allow` only three call shapes were
allowed (an `echo s7-... >> s7-....txt` line, a `README.md` read inside the scratch project, the `s7-reader`
agent) and anything else was denied "off-list"; in `deny` every call was denied, in `silent` every call was held.
The log holds event names, field **names**, tool names, redacted 200-character `tool_input` summaries,
`permission_mode` strings and timings, and no header or other value. Plan Task 7 allowed field names only; the stub also logged redacted `tool_input` summaries because its allow-list matching needed the tool input. The owner ran Claude in the scratch folder
`s7/project` and answered prompts; the controller changed the mode file only while no request was held, and
recorded in its ledger that no `.claude/settings.local.json` existed at the checks before steps c2, d and e and
after c1 (end state also confirmed absent). Raw log: `s7/receiver-final.log` (37 lines, outside the repository).
Two of its `PermissionRequest` lines at 08:53:15 are the controller's own `curl` replays (see D).

## Verdict table

| Step | Question | Result | Evidence |
| --- | --- | --- | --- |
| Setup | Do project `http` hooks load in an interactive session? | Yes for `PermissionRequest`, `SubagentStart`, `SubagentStop`, `SessionEnd`. **`SessionStart` never arrived** in either session. | Log: the first `PermissionRequest` at 17:13:47 (an unplanned prompt) answered `deny`; no `event=SessionStart` line in 37 log lines. The plan's rule "stop if no `SessionStart` within about 15 s" was deliberately overridden, because that rule meant "hooks not loaded", which the logged `PermissionRequest` disproved. |
| a1 `allow` | Does a hook `allow` run the call with no terminal prompt? | Yes. | Log `REQUEST ... mode=allow ... echo s7-a >> s7-a.txt` then `RESPONDED allow in 0.001s`; Terminal text read by the controller: "Ran 1 shell command / Allowed by PermissionRequest hook"; `s7-a.txt` has 1 line. |
| a2 `deny` | Does a hook `deny` stop the call with no prompt? | Yes. | Log `RESPONDED deny in 0.000s`; Terminal text read by the controller: "Denied by PermissionRequest hook"; the model quoted "S7 stub receiver denied this call" (transcript, 17:18:02); `s7-a2.txt` does not exist. |
| b `silent` | What happens when the hook never answers? | Claude Code's own prompt was on screen while the hook request was still open (read by the controller at 17:21:09, 24 s in), and still on screen at 17:23:17, after the hook connection closed. The hook connection closed at the 60 s hook timeout. Nothing was auto-allowed. OWNER-REPORTED: the prompt appeared right away. | Log `REQUEST mode=silent` 17:20:45, `SILENT client gave up after 60.0s` 17:21:45. OWNER-REPORTED: nothing changed on screen at or after the 60 s mark (the controller's reads at 17:21:09 and 17:23:17 are identical, so a transient between them would have been missed). The owner chose No at about 17:23:20 (transcript), about 2.5 minutes in, later than the planned 75 s; Terminal text: "Interrupted · What should Claude do instead?"; `s7-b.txt` does not exist. |
| c1 terminal first | If the owner answers Yes in the terminal, what happens to the pending hook request? | The command ran once, from the terminal answer. The hook request was still open at the stub's 30 s mark, and the stub's late `allow` did not re-run the command. | Log `REQUEST mode=delay-allow` 17:24:09, `RESPONDED delay-allow:allow in 30.441s` 17:24:39, with no "client gave up" or "client gone" line (the stub polls for a closed connection while it waits), so the connection stayed open for at least 30.4 s; the data does not show how long Claude Code would have kept it. `s7-c1.txt` mtime 17:24:18 and the transcript `tool_result` at 17:24:18 show the terminal answer ran the command 21 s before the late allow; the file has exactly 1 line. Terminal text: "Ran 1 shell command … DONE". |
| c2 stub first | If the hook allows while the prompt is on screen and the owner does nothing, what happens? | The command ran once about 1 s after the stub's allow, and Claude said DONE. OWNER-REPORTED: the prompt disappeared by itself at about 30 s. | Log `REQUEST` 08:50:00, `RESPONDED delay-allow:allow in 30.491s` 08:50:30; `s7-c2.txt` mtime 08:50:31 and the transcript `tool_result` at 08:50:31, 1 line. |
| d subagent | Which lifecycle events and permission requests does a subagent produce? | `SubagentStart` and `SubagentStop` arrive; the subagent's own permission request reaches the hook with `agent_id` and `agent_type`; launching the agent raised **no** `PermissionRequest`. | Log (fields below). The subagent's `Read` of `README.md` was answered `deny (off-list)` (see D), so the first line was not obtained. OWNER-REPORTED (pasted screen text; also in the session transcript at 08:51:34): Claude said the read failed with "S7 stub: off-list". |
| e Auto | Do Auto-mode calls reach the hook? | **Not for two benign calls.** `echo >> file` and `rm -f file` ran with no prompt and no `PermissionRequest`, with the stub set to `deny`. Whether Auto escalates riskier calls to a prompt, and so to the hook, was not tested. | Between the switch to Auto and the `SessionEnd` the log has only `SubagentStop` lines (two). The transcript `tool_result`s came 1 to 2 s after each `tool_use` (08:54:41.9 to 08:54:43.1; 08:55:09.8 to 08:55:10.4), `is_error` false, so no human prompt held them and the `echo` succeeded; `s7-e1.txt` is absent after the `rm`. The `permission_mode` value hooks saw in Auto was not obtained (the two `SubagentStop` payloads carried the field, the value was not logged); the transcript string is `auto`. |
| Exit | Does `SessionEnd` arrive? | Yes, once (second session). The first session's `SessionEnd` was not logged, and how that session ended is not established. | Log `event=SessionEnd fields=[cwd,hook_event_name,prompt_id,reason,scratchpad_dir,session_id,transcript_path]` 08:55:56. The last record of the first session's transcript is a system `away_summary` at 17:27:22. OWNER-REPORTED: the owner was away and the first session had closed when they came back. |

## Payloads (field names from the log; `tool_input` appears in the log only as a redacted summary)

- `PermissionRequest`: `cwd, effort, hook_event_name, permission_mode, permission_suggestions, prompt_id,
  scratchpad_dir, session_id, tool_input, tool_name, transcript_path`. A subagent's request adds `agent_id,
  agent_type`. There is **no tool call id**, which matches design section 4.3 (match on `session_id`, `prompt_id`
  and tool input).
- `SubagentStart`: `agent_id, agent_type, cwd, hook_event_name, prompt_id, scratchpad_dir, session_id,
  transcript_path`.
- `SubagentStop`: `agent_id, agent_transcript_path, agent_type, background_tasks, cwd, effort, hook_event_name,
  last_assistant_message (absent on the two Auto-period stops), permission_mode, prompt_id, scratchpad_dir,
  session_crons, session_id, stop_hook_active, transcript_path`.
- `SessionEnd`: `cwd, hook_event_name, prompt_id, reason, scratchpad_dir, session_id, transcript_path` (the value
  of `reason` was not logged).
- Counts in the 37-line log: 11 `PermissionRequest` (9 from Claude Code, 2 controller replays), 1 `SubagentStart`,
  10 `SubagentStop`, 1 `SessionEnd`, 0 `SessionStart`.

## What this means for the design

These are inferences from the evidence above; the untested cases are named, not assumed.

1. **Interactive hooks work as the design assumes for the cases tested.** An `http` `PermissionRequest` hook can
   allow or deny in an interactive manual-mode session. The terminal prompt and the hook request were open at the
   same time, so a silent hook did not block the owner's prompt and allowed nothing (extends section 4.3's
   "dashboard is down" line to a reachable-but-silent dashboard).
2. **The dashboard cannot tell that the owner already answered in the terminal.** In c1 the hook request was
   still open 30.4 s after the request, about 21 s after the owner's terminal answer, so a dashboard would be expected to keep showing a pending
   request until its own expiry. The UI needs a "may already be answered elsewhere" state and an expiry. **Untested
   and security-relevant:** terminal No followed by a late dashboard allow, and terminal Yes followed by a late
   dashboard deny. If a late allow after a terminal No could run the call, a dashboard could override the owner;
   this must be tested before Phase 3. A signal that closes the request early (`PostToolUse` or similar) was not
   tested.
3. **A stub allow that arrives while the prompt is open resolved the prompt and the command ran once** (c2). A
   deny was tested only as an immediate answer (a2). Not tested: a deny arriving while the prompt is open, a
   repeat of the same call after an allow (whether another prompt appears), a genuinely simultaneous answer from
   the owner and the hook (in c2 the owner kept hands off), and any of this through the real dashboard
   (token, Host and Origin guard, UI).
4. **Auto-mode approvals were not visible to the hook for two benign calls** (e). Section 4.3's UI limit stands as a
   caution; the Auto classifier's behaviour for riskier calls was not tested.
5. **Do not rely on `SessionStart` over `http`.** It did not arrive in two sessions; the cause is not established (a
   hook-type limit, a trust or ordering issue, or something else). Candidates to test for a session-start input:
   a `command` hook, the first `PermissionRequest` (which a session that never prompts, or runs in Auto, may never
   send), or `SubagentStart`. `SessionEnd` arrived once and is not shown to be reliable; no abrupt exit was tested.
6. **`SubagentStop` cannot be read as "the subagent finished" on its own.** There were 10 stops for 1
   `SubagentStart`; the first of three stops near the subagent (08:51:29) precedes the subagent's own last
   transcript record (08:51:31.8). Nine of the ten stops cannot be paired with a `SubagentStart`; the first session had four stops and
   no start. Some fall 2 to 3 s after a main-turn final message, which suggests internal helper agents, not
   established. Whether the extra stops carry different `agent_id` values from the start was not tested (ids were
   not logged); matching on `agent_id` is a recommendation, not a tested method.
7. **A deny without `interrupt: true` is not a stop.** After the stub denied a Bash call in the second stray
   prompt, the model tried a different tool for the same intent (`Read`, 17:14:44) and then explained the denial.
   In the other two denied prompts (the first stray prompt and a2) it only reported the denial. `interrupt: true`
   was never sent.
8. **Subagent requests are attributable** by the `agent_id` and `agent_type` fields, which the dashboard needs to
   show who is asking. Matching a subagent's read by path is untested (D).
9. **Spec section 4.3's three "untested, to be tested" items:** reachable-but-silent (rows b), hook timeout in an
   interactive session (row b: the hook connection closed at the configured 60 s, the prompt stayed), both
   answering (rows c1 and c2; covers allow only, see item 2).

## Anything unexpected, and what remains unresolved

- **D. The stub denied the subagent's `Read` of `README.md` as "off-list"** although the transcript shows the
  subagent asked for exactly `…/s7/project/README.md`, and a `curl` replay of that absolute path (with and
  without `agent_id`/`agent_type`; the replays are in the log, where both paths show as `<REDACTED>.md`, so the
  path used rests on the controller's command history) was allowed. The stub's long-token redaction hides the live
  path, so the cause is **not established**; a stub defect and a payload difference are both possible. It does not
  change the verdicts above, which concern events and fields.
- Unplanned prompts: the owner typed `cd /hooks` as a prompt (twice, once with a typo), which produced two `Bash`
  and one `Read` `PermissionRequest`, all denied (stub in `deny`).
- Not tested: the `command` hook type interactively; `SessionStart` with a `command` hook; two sessions at once; a
  session started by the dashboard; a remote or non-loopback host; `PostToolUse`; concurrent requests from several
  subagents; the owner's global settings were not read.
- Side effects: no `.claude/settings.local.json` existed at the controller's checks or at the end. OWNER-REPORTED:
  the owner accepted Claude Code's folder-trust dialog for the scratch folder (the start commands said it writes one
  entry to `~/.claude.json`; that file was not inspected). The stub was stopped and its generated `settings.json`
  removed; scratch files remain outside the repository (`s7-a.txt`, `s7-c1.txt`, `s7-c2.txt`, 1 line each).

# S7: hooks in an interactive Claude Code session (spike findings)

Dates: 2026-10-27 (first session) and 2026-10-28 (second session). Model alias `haiku`.
Claude Code version, read from the `version` field of each session transcript: first session
`2.1.310` (steps a1, a2, b, c1 and the two stray prompts), second session `2.1.312` (steps c2, d and e). The
CLI updated between the sessions ("Update installed" showed in the footer). The version is not recorded per step
beyond that.
Hook type used: **`http`** (`{"type":"http","url":"http://127.0.0.1:53400/hook","timeout":N}`), in the scratch
project's `.claude/settings.json`, for `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop` and
`PermissionRequest` (timeout 10 s, 60 s for `PermissionRequest`). The `command` hook type was not tested.
Permission mode: the owner started `claude --model haiku --permission-mode manual`; the footer read
"manual mode on" and the hook payload said `permission_mode` = `default` (`pmode=default` on every request in
that mode). The second session was later in Auto mode (footer "auto mode on", read by the controller).

Tags: **OWNER-REPORTED** marks a fact that rests on what the owner saw or said and that the log, files or
Terminal panel text the controller read itself do not show. Untagged facts come from the receiver log, the
files in the scratch project, or Terminal panel text the controller read.

## Method

A throwaway stub receiver (`s7/stub_receiver.py`, outside the repository, loopback only, no authentication)
answered `PermissionRequest` from a mode file: `allow`, `deny`, `silent` (never answer), `delay-allow` (hold
30 s, then allow). Other events were answered `{}`. Only three call shapes were ever allowed (an
`echo s7-... >> s7-....txt` line, a `README.md` read inside the scratch project, and the `s7-reader` agent);
everything else was denied "off-list". The log holds event names, field **names**, tool names, redacted
200-character input summaries, `permission_mode` strings and timings, no values. The owner ran Claude in the
scratch folder `s7/project` and answered prompts; the controller changed the mode file only while no request was
held, and checked that no `.claude/settings.local.json` existed (it never did, at any check).
Raw log: `s7/receiver-final.log` (37 lines, kept outside the repository). Two of its `PermissionRequest`
lines at 08:53:15 are the controller's own `curl` replays (see D), not Claude Code traffic.

## Verdict table

| Step | Question | Result | Evidence |
| --- | --- | --- | --- |
| Setup | Do project `http` hooks load in an interactive session? | Yes for `PermissionRequest`, `SubagentStart`, `SubagentStop`, `SessionEnd`. **`SessionStart` never arrived** in either session. | Log: the first `PermissionRequest` at 17:13:47 (an unplanned prompt) answered `deny`; no `event=SessionStart` line in 37 log lines. |
| a1 `allow` | Does a hook `allow` run the call with no terminal prompt? | Yes. | Log `REQUEST ... mode=allow ... echo s7-a >> s7-a.txt` then `RESPONDED allow in 0.001s`; terminal text "Ran 1 shell command / Allowed by PermissionRequest hook"; `s7-a.txt` has 1 line. |
| a2 `deny` | Does a hook `deny` stop the call with no prompt? | Yes. | Log `RESPONDED deny in 0.000s`; terminal text "Denied by PermissionRequest hook"; the model quoted "S7 stub receiver denied this call"; `s7-a2.txt` does not exist. |
| b `silent` | What happens when the hook never answers? | Claude Code showed its own prompt **immediately**, at the same time as the hook request, and kept it while the hook was open. The hook connection closed at the 60 s hook timeout. Nothing was auto-allowed. | Log `REQUEST mode=silent` 17:20:45, `SILENT client gave up after 60.0s` 17:21:45. Terminal text read at 17:21:09 and 17:23:17 showed the same prompt, unchanged. OWNER-REPORTED: the prompt appeared right away and nothing changed on screen after 17:23 (the controller's own read at 17:23:17 agrees). Owner chose No: terminal text "Interrupted · What should Claude do instead?"; `s7-b.txt` does not exist. |
| c1 terminal first | If the owner answers in the terminal, what happens to the pending hook request? | The command ran once. The hook request stayed **open** until the stub's own 30 s wait ended, and the late `allow` was written without error and **did nothing visible**. | Log `REQUEST mode=delay-allow` 17:24:09, `RESPONDED delay-allow:allow in 30.441s` 17:24:39; terminal text "Ran 1 shell command … DONE … Cogitated for 4s"; `s7-c1.txt` has exactly 1 line. |
| c2 stub first | If the hook answers while the prompt is on screen, what happens? | The prompt closed by itself, the command ran once, and Claude said DONE. | Log `REQUEST` 08:50:00, `RESPONDED delay-allow:allow in 30.491s` 08:50:30; `s7-c2.txt` 1 line. OWNER-REPORTED: the prompt disappeared by itself at about 30 s, then DONE. |
| d subagent | Which lifecycle events and permission requests does a subagent produce? | `SubagentStart` and `SubagentStop` arrive; the subagent's own permission request reaches the hook with `agent_id` and `agent_type`; launching the agent raised **no** `PermissionRequest`. | Log (fields below). The subagent's `Read` of `README.md` was answered `deny (off-list)` (see D), so the first line was not obtained: OWNER-REPORTED (pasted screen text): Claude said the read failed with "S7 stub: off-list". |
| e Auto | Do Auto-mode calls reach the hook? | **No.** Two Bash calls ran with no prompt and no `PermissionRequest`, with the stub set to `deny`. | Log lines for 08:54 to 08:55: only `SubagentStop`. Terminal text "Ran 1 shell command … DONE" twice; footer "auto mode on"; `s7-e1.txt` absent after the `rm` (the controller cannot show from the end state that the `echo` created it first). How Auto was reached (`shift+tab` or restart) and the labels passed through were not reported. |
| Exit | Does `SessionEnd` arrive? | Yes, once (second session). The first session's end was not logged. | Log `event=SessionEnd fields=[cwd,hook_event_name,prompt_id,reason,scratchpad_dir,session_id,transcript_path]` 08:55:56. The first session was closed while the owner was away; whether it ended cleanly is unknown. |

## Payloads (field names from the log; values were never logged)

- `PermissionRequest`: `cwd, effort, hook_event_name, permission_mode, permission_suggestions, prompt_id,
  scratchpad_dir, session_id, tool_input, tool_name, transcript_path`. A subagent's request adds `agent_id,
  agent_type`. There is **no tool call id**, which matches design section 4.3 (match on `session_id`, `prompt_id`
  and tool input).
- `SubagentStart`: `agent_id, agent_type, cwd, hook_event_name, prompt_id, scratchpad_dir, session_id,
  transcript_path`.
- `SubagentStop`: `agent_id, agent_transcript_path, agent_type, background_tasks, cwd, effort, hook_event_name,
  last_assistant_message (absent on some), permission_mode, prompt_id, scratchpad_dir, session_crons, session_id,
  stop_hook_active, transcript_path`.
- `SessionEnd`: fields above; `reason` is present (its value was not logged).
- Counts in the 37-line log: 11 `PermissionRequest` (9 from Claude Code, 2 controller replays), 1 `SubagentStart`,
  10 `SubagentStop`, 1 `SessionEnd`, 0 `SessionStart`.

## What this means for the design

1. **Interactive hooks work as the design assumes.** An `http` `PermissionRequest` hook can allow or deny in an
   interactive manual-mode session. The terminal prompt and the hook run **at the same time**, so a silent or
   unreachable dashboard never blocks the owner's own prompt and never allows anything (confirms and extends
   section 4.3's "if the dashboard is down" line to a reachable-but-silent dashboard).
2. **The dashboard cannot see that the owner already answered in the terminal.** In c1 the hook request stayed
   open for 30 s after the answer and a late `allow` did no harm, but the dashboard would keep showing a
   pending request until its own timeout. The UI needs a "may already be answered elsewhere" state and an
   expiry. A `PostToolUse` or `PermissionDenied`-style signal that could close the request earlier was **not**
   tested.
3. **A dashboard answer wins while the prompt is open** (c2), and the prompt closes itself. This is the
   Phase 3 approval path working end to end for a single-use allow and a deny, in manual mode.
4. **Auto mode approvals are not visible to the dashboard** (e). Section 4.3's UI limit stands; the Auto
   classifier's behaviour beyond `echo` and `rm -f` of a scratch file was not tested.
5. **Do not rely on `SessionStart` over `http`.** It did not arrive in two sessions. The cause is not
   established (a hook-type limitation, a trust or ordering issue, or something else). Section 4.3's "session
   start" input should come from a `command` hook, the first `PermissionRequest` or `SubagentStart`, or a later
   spike. `SessionEnd` arrived once and is not guaranteed on abrupt exit.
6. **`SubagentStop` is not a reliable "the subagent finished" signal on its own.** There were 10 stops for 1
   start (several arrived within seconds after the one subagent finished and after plain turns). The stop events
   carry `agent_id`/`agent_type`; matching on those against `SubagentStart` is needed, and what the extra stops
   were is not established (agent types were not logged).
7. **A hook deny is not a stop.** After the stub denied a Bash call, the model tried a different tool for the
   same intent (a `Read`), and then explained the denial. The dashboard's "deny" is a per-call answer only.
8. **Subagent requests are attributable** (`agent_id`, `agent_type` on the request), which the dashboard needs
   to show who is asking.

## Anything unexpected, and what remains unresolved

- **D. The stub denied the subagent's `Read` of `README.md` as "off-list"** although the transcript shows the
  subagent asked for exactly `…/s7/project/README.md`, and a `curl` replay of that absolute path (with and
  without `agent_id`/`agent_type`) was allowed. The live payload's path is redacted in the log, so the cause is
  **not established**; a stub defect and a payload difference are both possible. This does not change the
  verdicts above, which concern the events and fields, but it means "a subagent's read request is matched and
  answerable by path" is **untested**.
- Unplanned prompts: the owner typed `cd /hooks` as a prompt (twice, with a typo variant), which produced two
  `Bash` and one `Read` `PermissionRequest`, all denied (stub in `deny`).
- Not tested: the `command` hook type interactively; `SessionStart` with a `command` hook; two sessions at once;
  a session started by the dashboard; a remote or non-loopback host; `PostToolUse`; concurrent requests from
  several subagents; the owner's global settings were not read.
- Side effects: no `.claude/settings.local.json` was created at any check. The first run in the scratch folder
  asked for folder trust; the owner accepted it, which writes one entry to `~/.claude.json` (the entry itself was
  not inspected). The stub was stopped and its generated `settings.json` removed; scratch files remain outside
  the repository (`s7-a.txt`, `s7-c1.txt`, `s7-c2.txt`, 1 line each).

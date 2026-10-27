# S6: managed launch with a `PermissionRequest` hook (spike findings)

Date: 2026-10-27. Claude Code version: `2.1.310 (Claude Code)` (`claude --version`, saved per run; identical in all seven runs).
Model alias: `haiku` (the `init` event reported `model=claude-haiku-5-5`).
Hook type used: **`http`** (`{"type":"http","url":"http://127.0.0.1:<port>/hook","timeout":20}`) in every run.
The optional run **R1c** (the spec's `command` hook form) was **not run**, so only the `http` type is proven.
Permission mode observed: **`default`**, with no mode flag. Exact string in `init.permissionMode`
(all seven runs) and in `pmode=` on every stub `REQUEST` line: `default`. The harness's fallback
(`S6_PERMISSION_MODE=manual`, one extra run) was therefore not needed and not used.

Owner approval for R1 to R7 (not R1c): 2026-10-27. Seven runs, one per condition, no repeats. After review the owner
approved one further control run, R5c (same prompt as R5 with `--setting-sources user,project`), also on 2026-10-27.
It needed one change to the throwaway harness: `run.sh` accepts an optional `S6_SETTING_SOURCES` (`user`, the
default, or `user,project`; recorded in `out/<run>.cmd`). Nothing else changed.
`<scratch>` below means the scratch folder
`/private/tmp/claude-501/.../scratchpad/s6` (outside the repo). Raw streams stay there and are not committed.
The scratch project there holds a `CLAUDE.md` (one sentence with a codeword) and a `README.md`; no `.claude/` folder.
Harness: a loopback stub receiver (no authentication, no token), `run.sh`, `launch.py`, `summarize.py`.
No credential, token, header or environment variable was used, printed or recorded.

A user-level `SessionStart` hook that injects additional context ran at the start of every run except R6, the
resumed run (6 of the 7 R1 to R7 streams, and R5c, have one `hook_started` / `hook_response` pair of
system events; R6 has none). Its source is not identified: it could be the owner's settings file or an enabled
user plugin. The only hint toward a plugin is that the hook's output text refers to a plugin-style name
(`hook_name` itself is only `SessionStart:startup`); no name is recorded here. The `init` event of every run listed 4 plugins and 12 MCP servers (counts only; 8 or 9 servers
were `connected`, 3 `needs-auth`, and in R1, R2 and R7 one was still `pending`).
No names are recorded here. So `--setting-sources user` loads the owner's global user-level
configuration (consistent with S3). The owner's user settings were not read, so a user-level rule
contributing to any result cannot be excluded; none of the verdicts below depend on one except as
noted in R2.

The `project/s6-*.txt` evidence files were observed live (existence, line counts) and
were not retained afterwards, because `run.sh` clears them at the start of each run (R2's 2 lines and
R7's 5 lines were read at run time). For R1 to R4 the file claims are corroborated by the stream
(`tool_result` and `permission_denials` entries). The receiver log lines quoted below were read from
`receiver.log` after each run.

## Verdict table

| Run | Question | Verdict | Reason (criteria from the run list) |
|-----|----------|---------|-------------------------------------|
| R1 | Hook from `--settings` loads under `--setting-sources user`; fires; `deny` | **PASS** | Mode `default`. `REQUEST ... tool=Bash` for `echo r1 >> s6-r1.txt`, followed by `RESPONDED deny`. `s6-r1.txt` absent. `result`: `success`, `is_error: false`, `terminal_reason: completed`; `permission_denials` has 1 entry (that command); exit 0. |
| R2 | `allow` is one call | **PASS** (one run) | Two `REQUEST` lines for the identical command, each `RESPONDED allow`; `s6-r2.txt` has exactly 2 lines; `permission_denials` empty; final text `DONE`. The two lines differ only in the model-written `description` field. |
| R3 | Stub never answers (`silent`) | **PASS** | Stub logged `SILENT client gave up after 20.0s`. Run ended by itself in 32.3 s (well under the 240 s watchdog). `s6-r3.txt` absent. `permission_denials` lists the call. Nothing auto-allowed. |
| R4 | Stub stopped (connection refused) | **PASS** | Preconditions met (R1 and R2 passed with the identical settings file and the same port number, 52828 in each `.cmd` file; the stub had been stopped, not moved). No `REQUEST` line between the R4 markers. Call denied (`permission_denials` has it). `s6-r4.txt` absent. Run took 10.0 s, no hang, `result` present. |
| R5 | `--agents` role and project `CLAUDE.md` under `--setting-sources user` | **(a) PASS, (b) FAIL** | (a) `s6-reader` is in the `init` agent list. (b) The answer to "what is the codeword in your project instructions (CLAUDE.md)?" was `NOT VISIBLE`, not `marmalade-lighthouse-7431`. Recorded as FAIL under the run list's criterion: one run on `haiku`, and the prompt offered `NOT VISIBLE` as an exit. The control run R5c (below) saw the codeword with `--setting-sources user,project`, so the cause is consistent with the project setting source being excluded by `--setting-sources user` (one run each). |
| R5c | Control for R5b: same prompt as R5, `--setting-sources user,project` | **Positive control** (one run) | Answer: `Noted, 4417 is remembered. The S6 scratch project codeword is marmalade-lighthouse-7431.` Mode `default`, `--agents` role listed in `init`, no tools, exit 0. So the codeword was visible with `user,project` and not visible with `user` (R5b): one run each, `haiku` only. |
| R6 | `--resume <session id>` continues the conversation | **PASS** | Answer was `4417`, a number that existed only in R5's conversation. `init` session id was the same as R5's (`53cb66dd-...`), not a copy. |
| R7 | SIGINT to the `claude` PID mid-run | **PASS** (precondition met) | `r7_precondition_met: true` (6 descendants and 5 `tick` lines at the signal). Exit 0, 1.09 s after SIGINT; no snapshotted descendant alive 3 s after exit; `s6-busy.txt` stayed at 5 lines (at signal, at exit, and 3 s later). The stream ended with a `result` (`error_during_execution`, `aborted_tools`). |
| extra re-run | Flagless R1 re-run with `--permission-mode manual` | **Not made** | Flagless R1 showed `default`, so the documented branch did not trigger. |

Each run is one run of one condition on one model alias. Nothing here was repeated.

## Runs

### R1: hook loads and fires; stub `deny`

Command (stub mode `deny`, no mode flag):

```
claude -p "<prompts/R1.txt>" --output-format stream-json --verbose --setting-sources user \
  --settings <scratch>/settings.json --model haiku \
  --agents '{"s6-reader":{"description":"Read-only helper that reads files in the project and reports what they say.","prompt":"You are a read-only helper. You may only read files. Never modify anything.","tools":["Read","Grep","Glob"],"model":"haiku"}}'
```
(cwd `<scratch>/project`, stdin `/dev/null`; prompt: run `echo r1 >> s6-r1.txt` with Bash, answer `DONE`, or quote the refusal and answer `REFUSED`.)
`settings.json` held exactly one hook: `PermissionRequest` with the `http` hook above (timeout 20).

Observed: the hook fired once, the stub denied, the command did not run, the model quoted the denial
and answered `REFUSED`. 10.8 s, exit 0, no stderr.

Proof (chosen lines):
- `receiver.log`: `REQUEST path=/hook mode=deny pmode=default event=PermissionRequest tool=Bash input={"command": "echo r1 >> s6-r1.txt", ...}`
- `receiver.log`: `RESPONDED deny in 0.001s path=/hook tool=Bash`
- stream, `system`/`permission_denied`: `"decision_reason_type": "hook", "decision_reason": "S6 stub receiver denied this call"`
- stream, final assistant text: `S6 stub receiver denied this call\n\nREFUSED`
- evidence files: `project/s6-r1.txt` does not exist.

Informational: the hook's deny `message` reached the model as the tool result and the model quoted it
verbatim. (S2 had seen this only for the SDK callback, not a hook.) The `permission_denied` event carries
`decision_reason_type: "hook"`, which tells a hook deny apart from the generic denial seen in R3 and R4.

Does not prove: that a deny with `interrupt: true` works (not sent); that the hook fires for tools other
than `Bash`; that the `command` hook form works (R1c not run); behaviour on another model or another try.

### R2: stub `allow`, allow is one call

Command: as R1 with stub mode `allow` and `prompts/R2.txt` (run `echo r2 >> s6-r2.txt`, then the exact
same command again, answer `DONE`).

Observed: both calls reached the hook, both were allowed, both ran. 13.3 s, exit 0.

Proof:
- `receiver.log`: `REQUEST ... pmode=default ... tool=Bash input={"command": "echo r2 >> s6-r2.txt", "description": "Append r2 to s6-r2.txt (first run)"}`
- `receiver.log`: `REQUEST ... pmode=default ... tool=Bash input={"command": "echo r2 >> s6-r2.txt", "description": "Append r2 to s6-r2.txt (second run)"}`
- both followed by `RESPONDED allow in 0.00Xs`
- evidence file: `project/s6-r2.txt` had 2 lines (`r2`, `r2`); stream: `permission_denials: 0`; final text `DONE`.

Does not prove: that allowing one call can never create a grant for a differently worded or different
command (only the identical command string was repeated, and the `description` differed); that allow
works with `updatedInput` or `updatedPermissions` (not sent; the spec says there are no session
grants, and this run only shows the plain allow does not create one for this case). A user-level allow
rule cannot be fully excluded, but the fact that both calls hit the hook, and R1's call too, makes one unlikely.

### R3: stub `silent` (never answers)

Command: as R1 with stub mode `silent` and `prompts/R3.txt` (`echo r3 >> s6-r3.txt`).

Observed: the hook request was received and never answered. After the 20 s hook timeout, Claude Code
denied the call itself (the headless fallback), the model quoted that message, and the run finished
normally. 32.3 s total, `duration_ms` 29364, exit 0. Nothing was auto-allowed and the file was not created.

Proof:
- `receiver.log` (times `12:56:05` then `12:56:25`): `REQUEST ... mode=silent pmode=default ... "command": "echo r3 >> s6-r3.txt"` then `SILENT client gave up after 20.0s (no answer sent)`
- stream, `permission_denied` message starts: `Output redirection to '<scratch>/project/s6-r3.txt' needs approval. The path is inside the working directories for this session ...`
- result: `subtype=success is_error=False terminal_reason=completed`, `permission_denials: 1`.
- evidence: `project/s6-r3.txt` does not exist.

The denial message is Claude Code's own "needs approval" text, with no `decision_reason_type: hook` marker,
so a hook timeout is distinguishable from a hook deny in the stream (R1). The model also did not retry
after the denial.

Does not prove: behaviour of a hook with a much longer timeout (a real dashboard needs minutes to hours);
what happens in an interactive session; that 20 s is the default (it was the configured value).

### R4: stub stopped (connection refused)

Setup: `stop_stub.sh` (port file kept, nothing listening), then command as R1 with mode `down` and
`prompts/R4.txt` (`echo r4 >> s6-r4.txt`).

Observed: no request could reach any listener; Claude Code denied the call, the run finished with a
`result` in 10.0 s, exit 0. The conclusion "nothing reachable means deny" is meaningful here because R1
and R2 used the identical settings file and the same port number and did produce requests.

Proof:
- `receiver.log`: only the two run markers between R4 start and end, no `REQUEST` line.
- stream, `permission_denied` message starts with: `Output redirection to '<scratch>/project/s6-r4.txt' needs approval.`
- result: `subtype=success`, `terminal_reason=completed`, `permission_denials: 1`.
- evidence: `project/s6-r4.txt` does not exist.

Does not prove: that a non-refusal network failure (DNS, TLS, a hung accept, a non-2xx reply from a
live server) also denies. Only "connection refused" on loopback was tested. Two separate facts: `.err` was empty, and the
stream has one `hook_started` / `hook_response` pair, which is the user-level `SessionStart` hook; no event
for the failed `PermissionRequest` hook appears in the stream.

### R5: `--agents` role and project `CLAUDE.md` under `--setting-sources user`

Command: as R1 with stub mode `allow` and `prompts/R5.txt` (remember 4417; what is the S6 codeword in your
project instructions (CLAUDE.md); answer `NOT VISIBLE` if none; no tools). Run with `S6_ABORT_ON_AUTO=0`
(the harness's abort switch, irrelevant since the mode was `default`).

Observed (read (b) with the caveat in the next sentence): (b) is one run on `haiku`, the prompt offered
`NOT VISIBLE` as an answer, and `init.memory_paths` cannot settle it (it listed only an `auto` key in every
run here). R5c, run afterwards as a control, answered with the codeword (next section).
(a) the `init` event's agent list was `claude, claude-code-guide, Explore, general-purpose, Plan, s6-reader, statusline-setup`, so
the `--agents` role is available. (b) The model could not see the project `CLAUDE.md` sentence. 7.5 s, no tools used.

Proof:
- stream: `init[0] agents: [..., "s6-reader", ...]`
- final text: `4417 noted. NOT VISIBLE`
- the file `<scratch>/project/CLAUDE.md` does contain the codeword `marmalade-lighthouse-7431`.

Does not prove: that `CLAUDE.md` content would load via any other mechanism (e.g. `--add-dir`,
`--append-system-prompt`, a user-level `CLAUDE.md`) since none was tried; that `NOT VISIBLE` is the
model's fault-free reading (the model had been told it could answer that way; one run on `haiku`).
It also does not prove the `s6-reader` role can be invoked and its tool limit enforced (S4 covers
role loading; this run only shows the name is listed).

### R5c: control for R5b, `--setting-sources user,project`

Command: exactly as R5 (stub mode `allow`, `prompts/R5.txt`, no permission-mode flag, `S6_ABORT_ON_AUTO=0`,
same scratch project) except `--setting-sources user,project` in place of `--setting-sources user`:

```
claude -p "<prompts/R5.txt>" --output-format stream-json --verbose --setting-sources user,project \
  --settings <scratch>/settings.json --model haiku --agents '<same s6-reader JSON as R1>'
```
Version `2.1.310 (Claude Code)`. Observed `init.permissionMode`: `default`. 9.4 s, exit 0, `.err` empty,
no tools used, no `REQUEST` (none expected).

Proof:
- final text: `Noted, 4417 is remembered. The S6 scratch project codeword is marmalade-lighthouse-7431.`
- stream: `init[0] ... permissionMode=default`, agent list contains `s6-reader`.

Reading: with the project setting source included the codeword was visible; with `--setting-sources user` (R5) it was
not. This is one run of each, on `haiku`, with a prompt that allowed `NOT VISIBLE`. The only intended difference
between R5 and R5c is the setting-sources value, but the runs are separate sessions and a chance difference in
model behaviour cannot be excluded.

Does not prove: that a project `CLAUDE.md` is the only thing the `project` source adds (it also loads
project settings, hooks and `.claude/` content; the scratch project had none besides `CLAUDE.md`); behaviour on a
real project with an `@import` such as this repo's `CLAUDE.md` importing `AGENTS.md` (the scratch file had no import).

### R6: `--resume <session id>`

Command: as R1 with stub mode `allow`, `prompts/R6.txt` (what number did I ask you to remember; no tools)
and `--resume 53cb66dd-900d-4707-afd3-bc92fcede990` (R5's session id) appended.

Observed: the resumed session answered with the number from R5. 6.0 s, exit 0, `init` session id unchanged.

Proof: final text `4417`; `init` session id `53cb66dd-900d-4707-afd3-bc92fcede990` (same as R5).

Does not prove: resume after a run that was interrupted or denied; resume across a different working
directory; that guidance can be sent into a running turn (the spec does not promise it).

### R7: SIGINT mid-run

Command: as R1 with stub mode `allow` and `prompts/R7.txt` (a Python one-liner appending a `tick` line
per second for 60 s inside one Bash call), launched through `launch.py` with `--interrupt-after 5`:
SIGINT is sent to the captured `claude` PID only, 5 s after the first Bash `tool_use` appeared.

Observed: the hook allowed the command (one `REQUEST`/`RESPONDED allow`), the loop started, SIGINT was
sent at 9.35 s, the process exited by itself 1.09 s later with exit code 0. The stream ended with a
`task_notification` with status `stopped`, a tool result saying the tool use was rejected, a
`[Request interrupted by user for tool use]` text event, and a `result` with `subtype: error_during_execution`,
`is_error: true`, `terminal_reason: aborted_tools`, `permission_denials: 0`. Six descendants of the `claude`
PID existed at the signal (names `uv`, `bash`, `java`, `python`, `zsh`, `Python`); none was alive 3 s after exit. `s6-busy.txt` had
5 lines before the signal, at exit, and 3 s after exit.

Proof:
- `out/R7.meta.json`: `"r7_precondition_met": true`, `"exit_code": 0`, `"seconds_from_sigint_to_exit": 1.09`, `"descendants_still_alive_3s_after_exit": {}`, `"r7_file_stopped_growing": true`
- stream: `{"type": "text", "text": "[Request interrupted by user for tool use]"}` (user event)
- stream, `system`/`task_notification`: `"status": "stopped"`
- stream, result: `subtype=error_during_execution is_error=True terminal_reason=aborted_tools`; `errors: ["[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use"]`

Notes: SIGINT during a tool call gives a `result` (S3 had not tested this case; S3's SIGINT during text
streaming gave `aborted_streaming`; here the reason string is `aborted_tools`), and the exit code was 0 both
times, so the exit code cannot distinguish an interrupt from a normal end; the dashboard must record
"interrupted" itself (it knows it sent the signal) and not infer it from the exit code.
Of the six descendants, only the `zsh` and `Python` pair is plausibly the busy command (not verified); the others
(`uv`, `bash`, `java`, `python`) were not identified. They are likely the user-level MCP servers
that `claude` started (an inference, not checked). They are all gone, but this means "descendants" is not a list of tool children
only.

Does not prove: stopping a run that has spawned a background process or a detached child (this one ran
in the foreground); behaviour on a second SIGINT or SIGTERM; interrupt while the hook is waiting (the
stub had already answered).

## Cost (list-price estimate, not a charge)

`total_cost_usd` from each `result` event. This is a client-side list-price figure; the runs used the
subscription login and were not billed per call.

| Run | Duration | `total_cost_usd` |
|-----|---------:|-----------------:|
| R1 | 10.8 s | 0.00465 |
| R2 | 13.3 s | 0.00458 |
| R3 | 32.3 s | 0.00426 |
| R4 | 10.0 s | 0.00419 |
| R5 | 7.5 s | 0.00356 |
| R6 | 6.0 s | 0.00403 |
| R7 | 10.4 s (interrupted) | 0.00324 |
| R5c (control) | 9.4 s | 0.00345 |
| **Total, R1 to R7 plus R5c** | | **about 0.032 USD** (R1 to R7 alone: about 0.029) |

The seven planned runs cost about 25 to 35 times less than the 0.70 to 1.05 USD estimate in the run list; the earlier
estimate (about 0.11 USD per run) came from older spikes. The `result` events reported about 0.3k to 19k cache-creation
tokens (R6: 324; R1: 19,330) and about 24k to 104k cache-read tokens (R5, R5c and R7: 24,164; R2: 104,432), so the
figure depends on prompt caching and may not be repeatable.

## Implications for the design (section 4.2 of the 2026-10-27 spec)

Facts first. No recommendation is made here; the owner decisions are named as such.

**Supported (one run each unless noted):**
- "Approvals: ... `--settings` ... adds one `PermissionRequest` hook ... posts the request ... and waits."
  A hook supplied through `--settings` fired under `--setting-sources user` (R1, R2, R7). This was proven for
  the **`http`** hook type. The spec says "a small fixed command". The `command` form was not run (R1c), so that
  wording is unproven; `http` is proven.
- "Allow means one call; there are no session grants." The second identical command prompted again (R2).
  Proven for the plain `{"behavior":"allow"}` answer and one identical repeat only.
- "No answer within the wait ... means deny." (Spec section 4.3 lists "a reachable but silent dashboard" as
  untested: R3 now covers it for `-p` mode only; the interactive case stays untested and belongs to S7.) With a 20 s hook timeout and a silent receiver, the call was
  denied by Claude Code after 20.0 s and the file was not created (R3). The denial comes from Claude Code's
  headless fallback ("needs approval" text, no hook marker), not from the dashboard. In this run the wait
  ended at the hook's configured `timeout`; whether a dashboard's approval window is bounded by that
  timeout in general, and longer waits, were not tested.
- "... an unreachable dashboard means deny." Connection refused on loopback gave a denial, no hang (R4).
  Only that failure kind.
- A hook `deny` stops the command, the run still finishes with `success` / `completed`, and the denial is
  recorded in `permission_denials` and as a `permission_denied` event whose `decision_reason_type` is `hook` (R1).
- "Stop interrupts the process and records 'interrupted'." SIGINT to the process exited it in about 1 s,
  produced a `result`, and no descendant of those snapshotted at the signal remained 3 s after exit (R7). The record "interrupted" is the dashboard's own
  decision; the stream gives `error_during_execution` / `aborted_tools` and exit code 0.
- "`--resume <session id>`" continues the conversation, same session id (R6).
- "Roles are passed per run with `--agents`." The role name appeared in `init` (R5a).

**Failed under the specified argv, with a positive control (one run each, `haiku` only):**
- The spec's section 5 (order of work), item 2, expects "`--agents` and `CLAUDE.md` still load". `--agents`
  loaded (R5a). Under `--setting-sources user` the codeword from the project `CLAUDE.md` was not visible (R5b); under
  `--setting-sources user,project` it was (R5c). (Section 4.2 itself does not state the `CLAUDE.md` expectation; the section 5 line does.)
  Stated plainly: under the specified argv, a managed run would not carry the project `CLAUDE.md`, on this evidence.
- Consequence (a): spec section 5 says "If S6 fails, work stops and the owner decides", and R5b is a failed
  expectation under that rule, so Task 8's gate must treat it as an owner decision. The control run shows one
  flag change (`user,project`) loads it, but that also loads the project's own settings, hooks and `.claude/`
  content, which the spec's use of `--setting-sources user` was meant to keep out; that trade-off is the owner's call
  and was not examined here.
- Consequence (b): in this repo `CLAUDE.md` is what imports `@AGENTS.md`, and with it the security rules (no
  secrets, no reading credential stores, no push or publish without authorization). Under the specified argv a
  managed run in a project would therefore not carry the project `CLAUDE.md` and so not the `@AGENTS.md` text, and
  only the hook and the permission layer would constrain it. This rests on one run each; R5c used a scratch
  `CLAUDE.md` without an `@import`, so the import itself was not exercised.
- Related fact: managed runs under `--setting-sources user` inherit the owner's global plugins, hooks, injected
  context and MCP servers (4 plugins and 12 MCP servers in `init`, counts only), but not, on this evidence, the
  project's `CLAUDE.md`. The `uv`, `bash`, `java` and `python` descendants seen in R7 are probably those MCP
  servers (an inference; they were not identified).

**Left unproven:**
- "Managed runs use the default permission mode, not Auto": a flagless run reported `permissionMode`
  `default` in all seven runs, and the hook payload said `pmode=default`. So **with the specified argv and this
  owner's user settings, "default permission mode" is what you get with no flag**; the concrete name is the
  absence of `--permission-mode`, and the string is `default`. The CLI's help lists `manual` as a
  choice and has no `default` choice (run list, from `claude --help`); `--permission-mode manual` was **not
  run**, so whether it is equivalent to the flagless `default` is unproven. Because the mode may depend on the owner's
  user settings (not read), another machine or a changed user setting could produce `auto`; the dashboard
  should check `init.permissionMode` (or the hook payload's `permission_mode`) and treat anything other
  than `default` as a failure to start safely. That check is a suggestion for design; this spike only
  observed `default` once per run.
- The per-run token and `headers` / `allowedEnvVars` mechanism (the stub had no authentication).
- The `command` hook form and any `onFailure` field (not used).
- Behaviour when the wait must be minutes or hours (the dashboard's real approval wait).

**Hook timeout / silent / refused behaviour, as observed:** timeout 20 s configured; silent stub, the
call was denied after 20.0 s and the run finished in 32.3 s total with exit 0; refused connection, denial
immediately with the run finishing in 10 s; in neither case did the hook layer allow anything. In both runs `.err` was empty and the
stream had no event for the failed `PermissionRequest` hook (see R4).

## Not tested

- R1c (`command` hook form) and any `curl`-based variant; hook `onFailure`.
- `--permission-mode manual` (and `acceptEdits`, `plan`, Auto). `bypassPermissions` and `dontAsk` are never to be used.
- Deny with `interrupt: true`; allow with `updatedInput` / `updatedPermissions`.
- Tools other than `Bash`; subagent tool calls reaching the hook; MCP tool calls.
- Hook waits longer than 20 s; a hook that answers late (S2 saw a 30 s answer cut by the 20 s timeout, for allow).
- Non-refusal network failures; a non-2xx or malformed hook reply from a live server.
- Authentication on the receiver (token, headers, allowed env vars).
- Interactive sessions (S7); Auto mode; other models than `haiku`.
- A second SIGINT, SIGTERM, a background or detached child, interrupt while the hook is waiting.
- Whether `--setting-sources user,project` loads an `@import` in `CLAUDE.md` (the scratch file had none); a repeat of R5 or R5c; loading the project `CLAUDE.md` by any other route (e.g. `--add-dir`, `--append-system-prompt`).
- Any other effect of the `project` setting source (project hooks, permission rules, `.claude/` agents) on the managed launch.
- Repeats of any run: each result rests on one run (R5 and R5c are one run each).

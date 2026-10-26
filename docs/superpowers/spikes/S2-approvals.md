# S2: Approval round trip (spike findings)

Date: 2026-10-26. Claude Code version: `2.1.296 (Claude Code)`. Agent SDK: `claude-agent-sdk 0.2.174`
(Python), installed into a virtualenv at `<scratchpad>/s2/venv` (nothing added to the repo or to the
global Python). The SDK installed and imported under the system `python3` 3.15.0, so `python3.14` was
not needed. The SDK ships its own bundled CLI (`2.1.310`); it was not used. `managed.py` pointed the SDK
at the system `claude` (`cli_path`) so that every run used the same CLI version.
Scratch project (outside the repo): `<scratchpad>/s2`, holding `managed.py`, `stub_dashboard.py` and
`.claude/settings.json`. All `claude` commands ran from inside that directory, with `--model haiku`
(SDK: `model="haiku"`) and stdin redirected from `/dev/null`. Seven short real runs on the owner's
subscription login were used (2 managed, 5 `claude -p`; one of the five was an accident, see Step 3).
No credential, token or environment variable was printed or recorded.

## Summary

| # | Spec claim | Verdict |
|---|------------|---------|
| 1 | Allow means this one call and not a session grant | PASS for the managed callback (one run); not tested separately for the hook |
| 2 | A managed run's permission callback may wait for a human | PASS at 5 s (only duration tested); longer waits NOT tested |
| 3 | A `PermissionRequest` hook fires in interactive sessions the owner starts, and an HTTP hook can wait for the dashboard | PENDING OWNER CHECK for interactive sessions. Observed in `-p` mode only: hook fires, and a delayed (8 s) HTTP answer is applied |
| 4 | Dashboard down or silent: managed run denies, observed session falls back to Claude Code's own prompt, nothing auto-allowed | PASS for the "denies, nothing auto-allowed" half in `-p` runs. The "falls back to Claude Code's own prompt" half is PENDING OWNER CHECK |

Findings that change the design assumptions are in "Implications".

## Step 1: Managed path (Agent SDK `can_use_tool`)

`managed.py` uses `ClaudeSDKClient` with `can_use_tool=...`, `setting_sources=["user"]` (as in the
planned managed launch mode from S1), no `permission_mode` (so the default mode), `max_turns=12`. The
callback prints the tool name and input, sleeps 5 seconds, returns `PermissionResultAllow()` (no
`updated_permissions`) for a `Bash` command starting with `echo`, and otherwise returns
`PermissionResultDeny(message="S2-DENY-MARKER: ...", interrupt=False)`.

### Baseline: the brief's literal commands never reached the callback

Prompt: run `echo one`, run `echo one` again, run `ls`. Result: all three ran, the callback fired 0 times,
`permission_denials: []`. In the default mode Claude Code treats plain `echo` and `ls` as read-only and
runs them without asking, so there is nothing for the callback or a dashboard to answer. (I did not read
the owner's user settings, so I cannot rule out that a user-level allow rule contributed; the
read-only classification is an inference, supported by the next run, where adding `>>` made the same
command prompt.) The dashboard therefore only sees commands that Claude Code would have prompted for.

### Main run (commands changed so that they prompt)

Prompt: run `echo one >> s2-out.txt`, run `echo one >> s2-out.txt` again, then run `touch s2-denied.txt`,
and quote any denial message verbatim.

| Call | Callback fired | Waited | Returned | Outcome |
|---|---|---|---|---|
| 1 `echo one >> s2-out.txt` | yes | 5.0 s | allow | ran; file got a line |
| 2 `echo one >> s2-out.txt` (identical) | yes (again) | 5.0 s | allow | ran; file has 2 lines |
| 3 `touch s2-denied.txt` | yes | 5.0 s | deny with message | not run; `s2-denied.txt` does not exist |

- The callback fired for BOTH identical `echo` calls: an allow with no `updated_permissions` covers that
  one call only. PASS on allow-once for the callback path.
- Wait tolerated: three consecutive 5 s waits (run took 20.6 s in total) with no timeout, no error and
  no retry. Waits longer than 5 s were not tried on the managed path.
- After the deny: the tool result was an error (`is_error=True`) whose content was exactly the message
  returned by the callback (`S2-DENY-MARKER: dashboard owner declined this command`). Claude did not try
  another route; its final answer quoted the message verbatim ("`touch s2-denied.txt` failed with this
  error, quoted verbatim: ..."). The result message's `permission_denials` listed the denied call with its
  `tool_use_id`. So a deny message round-trips to the model and to the host.
- The callback received a `tool_use_id` (visible in the `permission_denials` entry; not separately
  printed from the callback context).
- `--permission-prompts none` (CLI semantics, from `claude --help`: "nobody: anything that would prompt is
  denied automatically") was not run: it is not the SDK path and the `-p` runs in Step 3 already show the
  deny-when-unanswered behaviour.

## Step 2: Hook payload (HTTP `PermissionRequest` hook)

Stub: `stub_dashboard.py` binds `127.0.0.1` on a random port, requires `Authorization: Bearer $S2_TOKEN`
(401 otherwise; checked by a curl test with no token, a wrong token and the right token, giving 401, 401
and 200), logs only a timestamp, the event, the tool name, the payload field names and the redacted tool
input (never headers), and answers a `PermissionRequest` with
`{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}` after
`--delay` seconds. The token was generated per run with `openssl rand -hex 16` into `S2_TOKEN`; it was
not written to any file, log or this report (a grep of the stub log and output for it found 0 matches).
Redaction (bearer tokens, `sk-` keys, `KEY=value`, long hex and base64 strings) was checked with a fake
payload.

Hook config (`<scratchpad>/s2/.claude/settings.json`, written by `stub_dashboard.py --write-settings`):

```
{"hooks":{"PermissionRequest":[{"hooks":[{"type":"http","url":"http://127.0.0.1:<port>/hook",
  "timeout":20,"headers":{"Authorization":"Bearer $S2_TOKEN"},"allowedEnvVars":["S2_TOKEN"]}]}]}}
```

Command (stub running, delay 0, allow):

```
claude -p "Use the Bash tool to run exactly: echo one >> s2-hook.txt  Then reply DONE." --model haiku --output-format json < /dev/null
```

Result: the stub received one request; the file `s2-hook.txt` was created; `permission_denials: []`,
`result: DONE`. So the `PermissionRequest` hook fires in `-p` mode, the HTTP hook with a bearer header
from `allowedEnvVars` works, and its allow answer was applied. The no-hook behaviour (deny in `-p`) is
shown by the "down" runs in Step 3, which makes this a controlled comparison.

Exact payload field names received (top level, sorted):

`cwd`, `effort`, `hook_event_name`, `permission_mode`, `permission_suggestions`, `prompt_id`,
`scratchpad_dir`, `session_id`, `tool_input`, `tool_name`, `transcript_path`.

- `tool_use_id` is NOT present (matches the docs: PermissionRequest hooks receive `tool_name` and
  `tool_input` "but without `tool_use_id`"). The dashboard cannot correlate a hook request to a tool call
  by id; it has `session_id`, `prompt_id` and the tool input.
- `tool_input` for Bash had `command` and `description`.
- `scratchpad_dir` and `transcript_path` are local paths, so treat the body as sensitive and keep it out
  of logs beyond what is needed.
- `permission_suggestions` is present (docs: suggested permission updates the prompt would offer, for
  example an "always allow" rule). An allow answer without `updatedPermissions` did not create any rule
  in this run (not checked beyond the single run).

## Step 3: Timeout and down behaviour

### Hook timeout: stub delay 30 s, hook `timeout: 20`

Same command and settings as Step 2, stub started with `--delay 30`. Stub log: request received at
14:30:36; at 14:31:06 (30 s later) the stub found the client had gone (`CLIENT GONE before response could
be written`), so Claude Code had closed the connection. The whole `claude -p` run took 25.6 s
(`duration_ms: 25570`; the Step 2 run took under 7 s). That is roughly 20 s of hook wait plus the
normal run cost, so Claude Code did not wait the full 30 s and cut off at about the configured 20 s (the
exact cut-off instant was not observed; this is inferred from the run duration). What it did at the
timeout: it did not hang and did not allow. The tool call was NOT run (no `s2-hook.txt`),
`permission_denials` listed the call, and the model reported that the command "was not run" because
"Output redirection ... needs approval", i.e. the headless run fell through to the normal flow, which in
`-p` mode with no one to ask is a denial. The deny message the model saw is the generic approval message,
not anything from the hook, so a dashboard cannot tell the model why.

### Delayed answer inside the timeout: stub delay 8 s, hook `timeout: 20`

Stub log: request 14:32:13, answered allow 14:32:21. Result: the call ran (file created),
`permission_denials: []`, `DONE`. So a human-speed delay of 8 s is tolerated and applied. This is the only
successful delayed hook answer tested. Longer waits up to the configured timeout were not tried (docs
state the default `http` hook timeout is 600 s; the cut-off at a configured value was shown above).

### Dashboard down (stub stopped, hook still configured and pointing at the closed port)

Command: the Step 2 command with `--setting-sources user,project` (the `project` source is needed for the
hook to load; the managed launch mode `--setting-sources user` would not load this project hook at all).
Result: exit 0 in 11 s, `permission_denials` listed the call, the file was not created, the model said
the command was not run and quoted the approval message. Nothing was auto-allowed and nothing hung. A
second, accidental run behaved the same way: the first Step 3 attempt ran while the stub process was
alive but had not started listening (its startup hung in `http.server`'s hostname lookup, which I then
bypassed in the stub), so the hook got a refused connection; that run also ended in a denial in about
12 s. Because the stub never received a request in either run, the "hook was attempted" part is inferred
from the identical configuration having fired in the Step 2 run.

### Was anything ever auto-allowed when nothing answered?

No. In every run where the hook timed out or could not connect (3 runs), and in the managed callback
deny, the command did not execute and the file was not created. The only allows were explicit allow
answers.

### What the docs add (not re-tested)

From https://code.claude.com/docs/en/hooks (fetched 2026-10-26; the page text was 282268 characters and
only the first 200000 were read, which included these parts):

- HTTP hook failures (non-2xx, connection failure, timeout) are non-blocking by default, so "the action
  goes ahead", meaning the normal permission flow continues. An `onFailure` field (v2.1.295 and later)
  accepts `"continue"` (default) or `"block"`. For `PermissionRequest` the hook only decides allow or
  deny, and the table is written for the general case; what `onFailure: "block"` does on a
  `PermissionRequest` hook was NOT tested.
- "A hook that exits 2 without a `decision` object leaves the permission flow unchanged."
- In sessions that cannot show a prompt, "if no hook returns a decision, it denies the tool call". This
  matches the `-p` observations above.
- For a call that reaches the SDK's `canUseTool`, PermissionRequest hooks "run alongside your host, and
  whichever decides first applies". Not tested. If both are used, the first answer wins, so a hook that
  answers quickly can override the managed callback.

## Owner interactive check (pending)

Why this is needed: everything above ran non-interactively. The spec claim that a `PermissionRequest`
hook fires in a session the owner starts, and that Claude Code's own prompt appears when the dashboard is
down, can only be checked in an interactive `claude` session.

Use a command that prompts. A plain `echo from-interactive` is auto-approved by Claude Code (Step 1
baseline), so no permission request would fire. Appending `>> file` makes it prompt.

Two terminals, both started from the scratch directory. Type any made-up string at the `read` prompt, the
SAME string in both terminals (it is only a shared test token for this check; do not use a real
password). It is never written to a file.

Terminal A (the stub; it prints every request here and also to `stub.log`):

```
cd <scratchpad>/s2 && rm -f stub.log s2-interactive*.txt && read -rs S2_TOKEN && export S2_TOKEN && ./venv/bin/python stub_dashboard.py --port 8765 --delay 3 --decision allow --write-settings
```

Terminal B (start only after A prints `stub listening`; Claude Code may ask you to trust the folder and to
approve the project hook, accept for this scratch folder only):

```
cd <scratchpad>/s2 && read -rs S2_TOKEN && export S2_TOKEN && claude --model haiku
```

In Terminal B ask:

```
Use the Bash tool to run exactly: echo from-interactive >> s2-interactive.txt
```

What to look for:

1. Terminal A shows a `REQUEST ... event=PermissionRequest tool=Bash ...` line, then about 3 s later
   `RESPONDED allow`.
2. In Terminal B: does Claude Code show its own permission prompt at all, and when? Does the command then
   run without you pressing anything (the stub's answer was applied)? Check `cat <scratchpad>/s2/s2-interactive.txt`
   contains `from-interactive`.
3. Variant "dashboard down": press Ctrl-C in Terminal A, then in Terminal B ask the same thing with a new
   file name: `Use the Bash tool to run exactly: echo again >> s2-interactive2.txt`. Expected: Claude Code
   shows its own permission prompt. Answer `No` (deny) and note what it did.
4. Optional variant "stub says deny": restart A with `--decision deny` in place of `--decision allow` and
   ask for `s2-interactive3.txt`; note whether the denial is applied without a prompt.

Report back: (a) did Terminal A show the request, (b) was the stub's allow applied without you answering
a prompt, (c) with the stub stopped did Claude Code show its own prompt, (d) anything surprising (for
example a startup trust or hook-approval dialog and what it said). Do not paste the token or environment
variables.

Result: Not yet recorded: owner to report.

## Implications

- A managed run's dashboard only receives requests that Claude Code would prompt for. Plain read-only
  commands (`echo`, `ls`) are never sent. Do not demonstrate or test approval flows with them.
- Allow is per call on the managed path. A "remember this" feature would need to be built deliberately
  (for example by returning `updated_permissions`, not tested here).
- The hook payload has no `tool_use_id`. Correlate on `session_id` plus `prompt_id` and tool input, and
  never treat two identical commands as one request.
- The hook's timeout is the dashboard's maximum wait for an observed session: set `timeout` well above a
  human response time (docs default 600 s for `http`), because at the timeout the request falls through to
  Claude Code's own flow (a prompt interactively, a denial headless).
- The dashboard must not rely on an unanswered or unreachable hook being denied in interactive sessions: it
  falls through to Claude Code's own prompt (pending the owner check), which is safe but means the
  owner sees two prompts or answers in the terminal instead. `onFailure: "block"` exists but was not tested.
- For managed runs, fail closed has to be implemented in the callback itself: wait with a timeout and
  return `PermissionResultDeny` when no human answers. What the CLI does if the callback raises an
  exception or never returns was not tested.
- Python 3.15's `http.server` can hang at startup in `server_bind` (reverse hostname lookup via
  `socket.getfqdn()`) on this machine. The dashboard server should avoid that call (the stub does).

## Limits of this spike

- Seven real runs, one per condition; model and CLI behaviour could vary. The interactive path is untested
  (pending owner).
- Only a `Bash` tool and only `-p` mode for the hook. The `permission_mode` value in the hook payload was
  not recorded, though the runs used the default mode.
- Managed callback waits: 5 s only. Hook waits: 8 s allowed and applied, 30 s cut off at the 20 s timeout.
  Nothing between 8 s and 20 s, and nothing longer than 20 s with a larger timeout, was tried.
- Allow-once was shown for the managed callback only. Whether a hook allow is also per call was not
  tested (docs and the absence of rule changes suggest so; not verified).
- Fail-closed on the managed path was shown through the `deny` return and the `-p` unanswered cases, not
  with a callback that crashes or hangs, and not with `--permission-prompts none`.
- The owner's user-level settings and hooks were not read; `--setting-sources user` still loads them and
  could change results (for example by shadowing the callback with an allow rule).
- The `-p` "down" conclusion for the hook relies on the identical configuration firing in the Step 2 run;
  the stub saw no request in the down runs by construction.

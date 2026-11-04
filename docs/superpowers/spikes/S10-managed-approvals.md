# S10: hook behaviour that Plan 4 depends on (spike findings)

Date: 2026-11-01. Claude Code version: `2.1.312 (Claude Code)` (`claude --version`, saved per run in
`out/<run>.version`; identical in all eight runs).
Model alias: `haiku` (the `init` event reported `model=claude-haiku-5-5` in every run).
Hook type used: **`http`**, one `PermissionRequest` hook in a `--settings` file, in every run.
Permission mode observed: `init.permissionMode` = `default` in all eight runs (no mode flag), and `pmode=default`
on every stub `REQUEST` line. The launcher was set to interrupt any run whose `init` mode was not `default`; it never fired.

Owner approval: 2026-11-01, recorded in the Plan 4 ledger ("Run all thank you." after the plan was presented):
up to 8 live runs, alias `haiku`, one run per condition R10a to R10h, list-price estimate about 0.01 USD.
**Runs used: 8 of 8**, one per condition, none repeated, no harness failure. The actual list-price total was
about 0.036 USD, above the 0.01 USD estimate (see Cost).

`<scratch>` below means `/private/tmp/claude-501/.../scratchpad/s10` (outside the repo). Raw streams, the receiver
log and per-run files stay there and are not committed. The S6 harness files were no longer in the S6 scratch folder
(only empty directories remained), so the S10 harness was rebuilt: `launch.py` and `summarize.py` were copied from the
S9 scratch folder (they are the S6 launcher and summarizer) and extended; `stub.py`, `run.sh` and `inspect_run.py`
are new. The S6 folder was not modified.

Fixed in every run: `claude -p "<prompts/<run>.txt>" --output-format stream-json --verbose --include-hook-events
--setting-sources user --settings <scratch>/settings.json --model haiku`, stdin `/dev/null`, cwd `<scratch>/project`
(a scratch project holding only `README.md`, no `CLAUDE.md`, no `.claude/`). `--include-hook-events` is new
relative to S6; it adds `hook_started` / `hook_response` system events to the stream. R10g also passed
`--agents` with one role, `s10-worker` (tools `["Bash"]`, model `haiku`).

As in S6, the owner's user-level configuration loaded under `--setting-sources user` (`init`: 4 plugins, 12 MCP
servers, counts only; one user-level `SessionStart` hook ran at the start of every run). It was not read, so a
user-level rule contributing to a result cannot be excluded.

Harness (loopback only): `stub.py` is a `ThreadingHTTPServer` on `127.0.0.1` with an ephemeral port, started by
`run.sh` before each run and stopped by its own PID after it (`stub stopped` recorded for all eight runs; no
`stub.py` or `claude -p` process was left afterwards). While it holds a request it polls the socket every 0.2 s
and logs `CLIENT CLOSED` on EOF. It logs the tool input (data, not instructions) and, for the auth header, only
`absent`, `match` or `mismatch`. Its modes were self-tested with `curl` on loopback before the live runs.
No credential, header value, token or environment variable value was printed or recorded. The R10b token was
generated per run inside `run.sh` (`secrets.token_urlsafe(32)`) and exported to the stub and `claude` only;
the settings file held the placeholder `$S10_TOKEN`, and a search of all scratch outputs for a bearer value found none.

## Ceiling on hook `timeout` (documentation check, no run)

- `claude --help` (2.1.312) says nothing about hook timeouts.
- The installed package (`@anthropic-ai/claude-code`, `README.md`, `sdk-tools.d.ts`) documents none.
- The settings schema embedded in the installed binary (strings, read-only) describes the `http` hook as
  `timeout: number, positive, optional` "Timeout in seconds for this specific request", with **no maximum**.
  `headers` ("Values may reference environment variables using $VAR_NAME or ${VAR_NAME} syntax ... Only variables
  listed in allowedEnvVars will be interpolated") and `allowedEnvVars` are the field names (matching S2).
- So no ceiling is documented, and none was found in the schema. That is not proof that a long timeout is honoured at
  run time: the longest hook timeout run is 120 s (R10a). The dashboard's 3600 s upper bound is not supported by any run.

## Verdict table

| Run | Question | Verdict | Reason |
|-----|----------|---------|--------|
| R10a | Hook `timeout` 120, stub allows after 75 s: does the run wait, does the call run? | **PASS** (one run) | `REQUEST` at +4.04 s, `HOLD DONE ... after 75.13s, client still connected`, `RESPONDED allow(late)`. Stream: `hook_started` 3.96 s, `hook_response` (`success`) 79.19 s, tool result 79.61 s. `s10-a.txt` = `a`. `result` `success`, `permission_denials` 0, text `DONE`, 84.4 s. |
| R10b | `headers` + `allowedEnvVars` token: is the header sent; is a rejected request a deny? | **Sent: yes. Rejected = deny: yes, but the 401 was forced by the stub whatever the header** (one run) | Both requests logged `auth=match`. Request 1 allowed, `s10-b1.txt` = `b1`. Request 2 got a forced HTTP 401: `hook_response` `outcome=error`, `exit_code=401`; call denied, `s10-b2.txt` absent, `permission_denials` 1. |
| R10c | Stub replies 500 once: deny or hang? | **Deny, no hang** (one run) | One `REQUEST`, `RESPONDED 500`. `hook_response` `outcome=error`, `exit_code=500`, output `HTTP 500 from http://127.0.0.1:<port>/hook`, 0.2 s after `hook_started`; `permission_denied` at the same moment. No second request. `s10-c.txt` absent. |
| R10d | Stub replies 200 with malformed JSON: deny or hang? | **Deny, no hang** (one run) | One `REQUEST`, `RESPONDED malformed status=200`. `hook_response` `outcome=error`, `exit_code=200`, within the same 0.2 s poll as `hook_started`; `permission_denied` follows. No second request. `s10-d.txt` absent. |
| R10e | Allow `echo a >> f`, then `printf b >> f`: does the second prompt again? | **Prompts again** (one run) | Two `REQUEST` lines: n=1 `echo a >> s10-e.txt` allowed, n=2 `printf b >> s10-e.txt` denied by the stub (`decision_reason_type: hook`). `s10-e.txt` = `a` only. |
| R10f | A `Write` and a `Read` outside the project reach the hook | **Both reach it** (one run) | `REQUEST ... tool=Write` (path in `<scratch>/outside/`) and `REQUEST ... tool=Read` (`<scratch>/outside/readme.txt`), both allowed; file written (`f`), read returned the codeword. `hook_name`s `PermissionRequest:Write` and `PermissionRequest:Read`. |
| R10g | Two Bash calls in one turn: concurrent delivery? Subagent call: `agent_type` present? | **Serial in this run (one message, two calls); `agent_type` present** (one run) | Both Bash `tool_use` blocks were in one assistant message (same message id). Request 2 arrived at +8.84 s, after request 1 was answered (+8.17 s) and its tool result appeared (8.74 s). Subagent request n=3 carried `agent_type=s10-worker` and an `agent_id` (main-session requests had neither key). All three files written. |
| R10h | SIGINT while the hook waits | **Exits in about 1 s with a `result`; connection closed; no snapshotted descendant alive 3 s after exit** (one run) | Stub holding (mode `hold:90`, hook `timeout` 120). SIGINT about 5 s after holding began. Exit code 0, 1.07 s after SIGINT. Stream ends with `hook_response` `outcome=cancelled` ("Hook cancelled"), `permission_denied`, a tool result rejecting the call, `[Request interrupted by user for tool use]`, and `result` `error_during_execution` / `aborted_tools`, `permission_denials` 1. Stub: `CLIENT CLOSED n=1 after 5.38s of holding`. 4 descendants at the signal, none alive 3 s after exit. `s10-h.txt` absent. |

Each verdict is one observation: one run of one condition on `haiku`. Nothing was repeated.

## Runs

Commands: `run.sh <run>` from `<scratch>` with the stub mode, hook timeout and options below (each run's exact argv,
settings with the port and placeholder only, and version are in `out/<run>.cmd`). Default hook `timeout` 30 s.

| Run | Stub mode | Hook `timeout` | Extra | Exit | Wall time | `duration_ms` | `total_cost_usd` |
|-----|-----------|---------------:|-------|-----:|----------:|--------------:|-----------------:|
| R10a | `late:75` (allow after 75 s) | 120 | | 0 | 84.39 s | 81336 | 0.00407 |
| R10b | `token` (n=1 allow if header matches else 401; n>=2 forced 401) | 30 | `headers` + `allowedEnvVars` | 0 | 10.78 s | 7739 | 0.00472 |
| R10c | `s500once` (n=1 HTTP 500; then deny) | 30 | | 0 | 11.43 s | 8016 | 0.00476 |
| R10d | `malformed1` (n=1 HTTP 200, truncated JSON; then deny) | 30 | | 0 | 10.81 s | 7814 | 0.00426 |
| R10e | `allow1` (n=1 allow; then deny) | 30 | | 0 | 9.59 s | 6451 | 0.00459 |
| R10f | `allow` | 30 | | 0 | 9.17 s | 6207 | 0.00484 |
| R10g | `late:3` (allow after 3 s) | 30 | `--agents` `s10-worker` | 0 | 26.59 s | 23827 | 0.00567 |
| R10h | `hold:90` (never allows) | 120 | SIGINT 5 s after holding starts | 0 | 10.63 s | 7441 | 0.00340 |

R10b hook entry (the only form difference): `{"type":"http","url":"http://127.0.0.1:<port>/hook","timeout":30,
"headers":{"Authorization":"Bearer $S10_TOKEN"},"allowedEnvVars":["S10_TOKEN"]}`. Every other run used
`{"type":"http","url":"http://127.0.0.1:<port>/hook","timeout":<t>}`.

### R10a: long wait

Prompt: run `echo a >> s10-a.txt` once, it may take a while to be approved, wait; `DONE` or `REFUSED`.
Observed: the hook request stayed open 75.1 s and the allow then applied; the run took 84.4 s.

Does not prove: any hook timeout above 120 s, or a wait longer than 75 s; that the 120 s timeout is honoured to its
end (the stub answered at 75 s); behaviour of a request still open when the timeout expires at that length (S6 R3
showed it only at 20 s).

### R10b: header token and a rejected request

Prompt: two separate Bash calls `echo b1 >> s10-b1.txt` then `echo b2 >> s10-b2.txt`, report each.
Observed: the `Authorization` header arrived with the expected value on both requests (`auth=match`); the 401 on
request 2 became a denial. The denial text was Claude Code's own "Output redirection ... needs approval" fallback,
without the `decision_reason_type: hook` marker, so a rejected request looks like S6's timeout or unreachable case,
not like a hook deny.

Does not prove: what happens when the variable is missing or the header is wrong from Claude Code's side (the run
did not vary the token; the second request's 401 was forced by the stub regardless of the header); any status other
than 401; whether the variable named in `allowedEnvVars` is visible to tool subprocesses (Bash children inherit the
`claude` environment by default; not tested). The token was in the `claude` process environment for the whole run.

### R10c and R10d: non-2xx and malformed replies

Prompt: run `echo c >> s10-c.txt` (R10d: `echo d >> s10-d.txt`) once, `DONE` or `REFUSED`.
Observed: both were denied at once by Claude Code's fallback ("needs approval" text, no hook marker); both
`hook_response` events had `outcome=error` with the HTTP status as `exit_code`. The hook was not retried (one
request each), and the model did not retry the call.

Does not prove: other 5xx or 4xx codes, a slow non-2xx, an empty body, valid JSON of the wrong shape, or a
`decision` with an unknown `behavior`; behaviour when more than one hook is configured.

### R10e: allow is one call, also for a differently worded command

Prompt: two separate Bash calls `echo a >> s10-e.txt` then `printf b >> s10-e.txt`.
Observed: the second, differently worded command reached the hook and was denied by the stub; the file held only `a`.
So the plain allow of the first call did not create a grant covering the second.

Does not prove: that no allow ever creates a grant (only one pair of commands, on the same file); behaviour with
`updatedPermissions` (not sent).

### R10f: Write and Read outside the project

Prompt: `Write` `<scratch>/outside/s10-f.txt` with `f`, then `Read` `<scratch>/outside/readme.txt`.
Observed: each tool produced one hook request with its own `tool_name` and `tool_input` (`file_path`, plus
`content` for Write), and the allow answers applied.

Does not prove: that a `Read` inside the project reaches the hook (it was not tried, and it probably does not need
permission); `Edit`, `NotebookEdit`, web or MCP tools; that a user-level allow rule could not skip the hook for other
paths.

### R10g: two calls in one turn, and a subagent

Prompt: one assistant message with two parallel Bash calls (`echo g1 ...`, `echo g2 ...`), then the `Agent` tool
with `subagent_type` `s10-worker` running `echo g3 >> s10-g3.txt`. The stub held each request 3 s.
Observed: the two Bash calls from one message were delivered to the hook one at a time: the second request was sent
only after the first was answered and its command had run. The subagent's request carried `agent_type`
(`s10-worker`) and `agent_id`; the main-session requests had neither field. Payload keys otherwise as in S2
(`cwd`, `effort`, `hook_event_name`, `permission_mode`, `permission_suggestions`, `prompt_id`, `scratchpad_dir`,
`session_id`, `tool_input`, `tool_name`, `transcript_path`; no `tool_use_id`).

Does not prove: that requests are never concurrent. Two subagents running in parallel, or a background agent, could
still produce overlapping requests; that was not tested. The dashboard should keep handling concurrent requests
(plan Review Focus 2). It also does not prove the serial order holds on another model or version.

### R10h: SIGINT while the hook waits

Prompt: run `echo h >> s10-h.txt` once and wait for approval. `launch.py` sent SIGINT to the `claude` PID only,
5 s after the stub created its "holding" flag file (the meta key `first_bash_tool_use_at_s`, 4.37 s, records when
that trigger was seen; with the file trigger it is the flag time, not a tool_use time).
Observed: exit 1.07 s after SIGINT, exit code 0, a `result` event (`error_during_execution`, `aborted_tools`,
`is_error: true`, `permission_denials` 1 with that call). The hook was reported `cancelled`. The stub saw the
connection close 5.38 s into the hold, about 0.3 s after the signal (both times measured from the start of the hold,
with 0.2 s polling), and sent no answer. Descendants at the signal were `uv`, `bash`, `java`, `python` (probably the
user-level MCP servers, as in S6 R7; not identified; the Bash command had not started); none was alive 3 s after exit.

Does not prove: SIGTERM or a second SIGINT; a kill of `claude` with no chance to clean up (whether the connection then
closes is up to the OS, which closes sockets of a dead process, but this was not run); that a late answer after the
close would be ignored (none was sent).

## Cost (list-price estimate, not a charge)

`total_cost_usd` from each `result` event; the runs used the subscription login (`init.apiKeySource` `none`) and were
not billed per call. Total for R10a to R10h: **about 0.036 USD** (0.00407 + 0.00472 + 0.00476 + 0.00426 + 0.00459 +
0.00484 + 0.00567 + 0.00340). This is about 3.6 times the 0.01 USD estimate given at approval. The estimate came from
S9 (about 0.001 USD per run, no tools); runs with tool calls and hooks cost about as much as S6's (0.003 to 0.005 USD).

## Implications for Plan 4 and the spec

Facts first; one run each.

- **Fail closed holds for every failure kind tried.** Silent and refused (S6), HTTP 500 (R10c), HTTP 200 with
  malformed JSON (R10d), HTTP 401 (R10b) and an interrupted run (R10h) all ended in a denial, never an allow, and
  none hung. The denial in these cases is Claude Code's own fallback; only an explicit hook deny carries
  `decision_reason_type: hook` (R10e, S6 R1).
- **Longest wait shown to work: 75 s under a hook `timeout` of 120 s (R10a).** No ceiling is documented, but nothing
  longer was run. With plan decision 4's rule (hook `timeout` = wait + 60), the only wait that keeps the hook timeout
  at the tested 120 s is 60 s. Under the brief's rule that the upper bound must not exceed what is shown to work, the
  setting's default and upper bound become 60 s until a longer live run is approved and passes.
- **Token placement.** `headers` + `allowedEnvVars` carries a token (R10b), so decision 2's condition is met. It
  moves the token from the settings file into the `claude` process environment, which tool subprocesses inherit by
  default (not tested whether Claude Code strips it). The path token stays in a 0600 file in a 0700 folder; a `Read`
  of a file outside the project reaches the hook (R10f), so the owner would see such a read. Either way a bad or
  missing token answered with a non-2xx is a deny.
- **One call per allow** also holds for a differently worded command (R10e).
- **Tools reaching the hook:** `Bash`, `Write`, `Read` outside the project (R10f), a subagent's `Bash` with
  `agent_type` and `agent_id` (R10g).
- **Concurrency:** two calls from one message were delivered serially (R10g); parallel subagents untested.
- **Stop during a held request:** about 1 s to exit, `result` present, held connection closed by Claude Code, no
  descendant left (R10h). The dashboard sees the close and must mark the approval unavailable; it records
  "interrupted" itself (exit code 0, as in S6 R7).
- Spec section 4.2 is not contradicted by these results ("a small fixed command" was already corrected to `http` by
  S6; "no answer within the wait, a crash, or an unreachable dashboard means deny" now also covers non-2xx and
  malformed replies). It is not changed.

**Recommendation for Tasks 2 to 6:** keep the per-run token in the URL path (decision 2) and treat any non-2xx,
malformed or closed connection as deny; set `claude_approval_wait_seconds` default and maximum to 60 with hook
`timeout` 120 (wait + 60) until a live run proves a longer hook timeout; handle concurrent requests anyway.

## Not tested

- Hook timeouts above 120 s and waits above 75 s; expiry of a long timeout with the request still open.
- A missing `allowedEnvVars` variable or a wrong token from Claude Code's side; whether the token variable reaches tool
  subprocesses.
- Status codes other than 401 and 500; valid JSON of the wrong shape; an empty body; a slow error reply.
- `Edit`, `NotebookEdit`, web, MCP and other tools; `Read` inside the project.
- Parallel subagents or background agents producing overlapping requests.
- SIGTERM, a second SIGINT, a hard kill during a held request; a late answer after the close.
- Interactive sessions, Auto mode, other models than `haiku`, other Claude Code versions.
- Repeats of any run: each result rests on one run.

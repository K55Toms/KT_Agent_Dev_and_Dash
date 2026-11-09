# S11: no-decision reply and the untested cases listed below (attended spike kit)

Status: kit written, **pending owner run**. Nothing below has been run against a real Claude Code session.
Feeds: the constant `NO_DECISION_MODE` in `dashboard/observed_receiver.py` (Task 5), spec sections 5.1 and 5.2.
Builds on S7 (`S7-observed-hooks.md`): S7 verified only that a held connection leaves Claude Code's terminal prompt
in charge until the hook timeout; it did not test any reply that ends the request.

## Questions

1. Which "no decision" reply leaves the terminal prompt open and auto-allows nothing: `empty_object` (HTTP 200,
   `{}`), `status_204`, `close` (drop the connection), or `hold` (S7-verified)?
2. What do the real `PostToolUse` and `Stop` payloads contain? The two-way decision record (spec 5.2) infers the
   terminal's answer from later events, so it depends on: is `tool_input` present in `PostToolUse`, is there a
   `tool_use_id` (S7 found none on `PermissionRequest`), and what a terminal No produces (which events follow).

Only event names and **field names** are recorded, never values. The stub log holds no `tool_input` value, no
path, no token. Do not paste prompts or file contents into the results.

## Kit

`scripts/spike_s11_stub.py`, stdlib only, binds `127.0.0.1` only, no authentication, throwaway, outside the dashboard.

```
python3 scripts/spike_s11_stub.py --mode MODE --port 53411 --log LOGFILE [--other-mode MODE] [--script allow|deny --after SECONDS]
```

- `--mode empty_object | status_204 | close | hold`: the candidate no-decision reply for `PermissionRequest` only.
- `--other-mode` (default `empty_object`): the reply for every other event (`PostToolUse`, `Stop`, `SessionEnd`), so
  they are never held and the real next events and their order are observed. Keep the default in every case.
- `--script allow|deny --after N`: answer `PermissionRequest` with that decision after N seconds (instead of the
  mode reply), to create late and simultaneous answers.
- Log line: UTC time, `event=<name>`, `mode`, `fields=[sorted field names]`; plus `answered=` / `hold_ended` markers.

Owner setup (interactive terminal, scratch project outside the repository, project `.claude/settings.json`):
one `http` hook per event (`PermissionRequest`, `PostToolUse`, `Stop`, `SessionEnd`) with
`{"type":"http","url":"http://127.0.0.1:53411/hook","timeout":60}`. Start `claude --permission-mode manual` (a real mode name in `claude --help`; hooks report it as `permission_mode` = `default`, per S7) there,
use a harmless call (`echo s11 >> s11.txt`). Restart the stub between cases; keep the log per case.

## Cases

| Case | Owner action | Stub action | Expected evidence | Result |
| --- | --- | --- | --- | --- |
| A1 empty_object | Trigger a prompt; do not answer for 10 s; then answer Yes | `--mode empty_object` | Prompt stays on screen after the `{}` reply; nothing auto-allowed (file not written before Yes) | pending owner run |
| A2 status_204 | As A1 | `--mode status_204` | As A1 | pending owner run |
| A3 close | As A1 | `--mode close` | As A1; note any error text in the terminal | pending owner run |
| A4 hold | As A1 | `--mode hold` | As A1 (S7 verified); hook gives up at its timeout | pending owner run |
| B1 terminal Yes, then PostToolUse | Answer Yes in the terminal | `--mode hold --other-mode empty_object` | Log: `PermissionRequest` then `PostToolUse` fields; is `tool_input` present, is there `tool_use_id` | pending owner run |
| B2 terminal No, next events | Answer No in the terminal, then let Claude finish | `--mode hold --other-mode empty_object` | Which events follow (`PostToolUse`? `Stop`? none?) and their field names | pending owner run |
| B3 dashboard Allow, then PostToolUse | Do not answer | `--mode hold --script allow --after 5 --other-mode empty_object` | `PostToolUse` arrives; fields as B1; file written once | pending owner run |
| B4 dashboard Deny, then any PostToolUse | Do not answer | `--mode hold --script deny --after 5 --other-mode empty_object` | No `PostToolUse` for the call (a `PostToolUse` here would be the "ran although denied" warning case) | pending owner run |
| C1 terminal No, then late allow | Answer No within 10 s | `--script allow --after 30 --other-mode empty_object` | Late allow does not run the call | pending owner run |
| C2 terminal Yes, then late deny | Answer Yes within 10 s | `--script deny --after 30 --other-mode empty_object` | Call runs once; late deny does not undo it | pending owner run |
| C3 deny while prompt open | Leave the prompt open | `--script deny --after 5 --other-mode empty_object` | Prompt closes by itself, call refused | pending owner run |
| C4 simultaneous answer | Answer Yes at about the 5 s mark | `--script allow --after 5 --other-mode empty_object` | Call runs once, no duplicate, no error | pending owner run |
| D1 connection drop | Trigger a prompt; do not answer | `--mode close` (the listener drops the held connection with no reply, as on a crash or a read-deadline cut) | Prompt stays on screen; nothing auto-allowed; note any error text | pending owner run |
| D2 413 / 415 reply | Trigger a prompt; do not answer | Stub variant answering `PermissionRequest` with HTTP 413 (oversize) or 415 (wrong content type), empty body | Prompt stays on screen; nothing auto-allowed; note any error text | pending owner run |
| D3 two PermissionRequest hooks | Trigger a prompt with two `http` `PermissionRequest` hooks configured (as when the observed snippet is in user settings and a dashboard-managed run adds its own via `--settings`) | One stub answers `allow`, the other `{}`; then `deny` and `{}`; then `allow` and `deny` | How Claude Code merges the two decisions (which wins, any wait for the slower hook); whether `{}` from one hook defers to the other | pending owner run |
| D4 dashboard down: connection refused | Stop the dashboard (or stub), then trigger a prompt | Nothing listens on the port | Prompt appears and nothing is auto-allowed; note any error text. The documentation says a connection error is a non-blocking error, so Claude Code's own prompt stays in charge; this is the basis of the "nothing is allowed automatically while the dashboard is down" statement and it is **not tested** | pending owner run |
| D5 local settings file | Put the hook block in `.claude/settings.local.json` (not `.claude/settings.json`) of the scratch project and start a NEW session | Any stub mode | The hooks fire from the local settings file (S7 tested a project settings file only); whether an already-running session picks up newly pasted hooks; that the file is kept out of git (documentation says so, not verified here) | pending owner run |

`Stop` field names come from the end of any turn in these cases; record them once.

## Recorded payload field names (fill from the log)

| Event | Field names seen | `tool_input` present | `tool_use_id` present |
| --- | --- | --- | --- |
| `PostToolUse` | pending owner run | pending owner run | pending owner run |
| `Stop` | pending owner run | n/a | n/a |
| Terminal No (B2) | pending owner run | | |

## Decision rule

The shipped default is `NO_DECISION_MODE = "empty_object"` (HTTP 200 with `{}`). Its basis is docs-sourced only:
the hooks reference says a 2xx reply with no decision is success with no action and the normal permission dialog
appears. It is not live-tested. It was chosen because the owner asked that terminal sessions are never blocked by
the dashboard, and `{}` ends every no-decision request at once instead of holding it.

If the owner's run (A1) shows that `{}` disturbs the terminal prompt (closes it, auto-allows, or shows an error),
switch to `NO_DECISION_MODE = "hold"` (one line in `dashboard/observed_receiver.py`; A4 is the behaviour S7
verified). `status_204` and `close` stay candidates only if A2 or A3 pass. Record the result and the Claude Code
version here and in `docs/claude-code-setup.md` (Task 9). D1 to D3 are recorded the same way; D3 decides whether
the observed snippet may share a settings file with dashboard-managed runs (until then the dashboard answers a
managed run's session `{}` at once and the snippet note says managed runs are ignored by the page). If B1 or B2 show that `tool_input` or an identifying field is missing, spec 5.2 matching must fall back to
`tool_name` plus event order, and the card outcome stays `unknown` more often.

## Decision

Shipped default: `empty_object` (docs-sourced, not live-tested). Owner run pending.

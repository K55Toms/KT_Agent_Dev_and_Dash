# S11: no-decision reply and the four untested terminal cases (attended spike kit)

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
python3 scripts/spike_s11_stub.py --mode MODE --port 53411 --log LOGFILE [--script allow|deny --after SECONDS]
```

- `--mode empty_object | status_204 | close | hold`: the candidate no-decision reply, given to every event.
- `--script allow|deny --after N`: answer `PermissionRequest` with that decision after N seconds (instead of the
  mode reply), to create late and simultaneous answers.
- Log line: UTC time, `event=<name>`, `mode`, `fields=[sorted field names]`; plus `answered=` / `hold_ended` markers.

Owner setup (interactive terminal, scratch project outside the repository, project `.claude/settings.json`):
one `http` hook per event (`PermissionRequest`, `PostToolUse`, `Stop`, `SessionEnd`) with
`{"type":"http","url":"http://127.0.0.1:53411/hook","timeout":60}`. Start `claude --permission-mode manual` there,
use a harmless call (`echo s11 >> s11.txt`). Restart the stub between cases; keep the log per case.

## Cases

| Case | Owner action | Stub action | Expected evidence | Result |
| --- | --- | --- | --- | --- |
| A1 empty_object | Trigger a prompt; do not answer for 10 s; then answer Yes | `--mode empty_object` | Prompt stays on screen after the `{}` reply; nothing auto-allowed (file not written before Yes) | pending owner run |
| A2 status_204 | As A1 | `--mode status_204` | As A1 | pending owner run |
| A3 close | As A1 | `--mode close` | As A1; note any error text in the terminal | pending owner run |
| A4 hold | As A1 | `--mode hold` | As A1 (S7 verified); hook gives up at its timeout | pending owner run |
| B1 terminal Yes, then PostToolUse | Answer Yes in the terminal | `--mode hold` | Log: `PermissionRequest` then `PostToolUse` fields; is `tool_input` present, is there `tool_use_id` | pending owner run |
| B2 terminal No, next events | Answer No in the terminal, then let Claude finish | `--mode hold` | Which events follow (`PostToolUse`? `Stop`? none?) and their field names | pending owner run |
| B3 dashboard Allow, then PostToolUse | Do not answer | `--mode hold --script allow --after 5` | `PostToolUse` arrives; fields as B1; file written once | pending owner run |
| B4 dashboard Deny, then any PostToolUse | Do not answer | `--mode hold --script deny --after 5` | No `PostToolUse` for the call (a `PostToolUse` here would be the "ran although denied" warning case) | pending owner run |
| C1 terminal No, then late allow | Answer No within 10 s | `--script allow --after 30` | Late allow does not run the call | pending owner run |
| C2 terminal Yes, then late deny | Answer Yes within 10 s | `--script deny --after 30` | Call runs once; late deny does not undo it | pending owner run |
| C3 deny while prompt open | Leave the prompt open | `--script deny --after 5` | Prompt closes by itself, call refused | pending owner run |
| C4 simultaneous answer | Answer Yes at about the 5 s mark | `--script allow --after 5` | Call runs once, no duplicate, no error | pending owner run |

`Stop` field names come from the end of any turn in these cases; record them once.

## Recorded payload field names (fill from the log)

| Event | Field names seen | `tool_input` present | `tool_use_id` present |
| --- | --- | --- | --- |
| `PostToolUse` | pending owner run | pending owner run | pending owner run |
| `Stop` | pending owner run | n/a | n/a |
| Terminal No (B2) | pending owner run | | |

## Decision rule

Choose the first mode, in the order `empty_object`, `status_204`, `close`, that leaves Claude Code's terminal
prompt open with nothing auto-allowed (A1 to A3). If none is verified, keep `NO_DECISION_MODE = "hold"` (A4, the
only behaviour S7 verified). Record the choice and the Claude Code version here and in `docs/claude-code-setup.md`
(Task 9). If B1 or B2 show that `tool_input` or an identifying field is missing, spec 5.2 matching must fall back to
`tool_name` plus event order, and the card outcome stays `unknown` more often.

## Decision

Pending owner run.

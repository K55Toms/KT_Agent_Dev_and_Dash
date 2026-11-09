# Claude observed sessions (Phase 3) design

Status: draft for owner review, 2026-11-06. Implements Phase 3 of
`docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (section 4.3); that spec stays the
parent. Hook behaviour comes from spike S7 (`docs/superpowers/spikes/S7-observed-hooks.md`).

## 1. Intent

The owner can see their own Claude Code terminal sessions in the dashboard and answer those sessions'
permission prompts there. Owner choices (2026-11-06): the first version lists sessions with status and handles
approvals (not approvals only, and not transcripts); the sessions reach the dashboard on a fixed port.

Applies only to a deployment whose provider is Claude. A Codex deployment shows no observed-session page and opens
no listener. One provider per deployment is unchanged.

## 2. Non-goals (first version)

Transcripts, reply text, guidance, stop buttons, replay or recovery of observed sessions, Automatic approval for
observed sessions, editing the owner's Claude settings, counting subagents, any claim about Auto mode completeness.

## 3. Architecture

- A second listener on `127.0.0.1` only, on a fixed default port, 47615 (setting `observed_port`, changeable in the
  dashboard settings). If the port is in use, the listener stays off, the sessions page says "observed sessions off:
  port in use", and the rest of the dashboard runs normally. No fallback port is ever chosen.
- Path `/hook/observed/<install token>` only. The managed receiver (`/hook/managed/<run token>`, random port) and
  the observed listener keep separate token tables and separate handlers, so a managed token cannot reach observed
  data or answer an observed approval, and the reverse.
- Shared parts are split out of `dashboard/hook_receiver.py` into a base used by both: body-size limit, Host and
  Origin guard, constant-time token comparison, held-request handling (`HeldRequest`, closed-connection detection,
  expiry), and the rule that no log line, error body or exception text carries a token, path or request text.
  Managed behaviour and its tests must not change.
- Install token: `secrets.token_urlsafe(32)`, generated on first use, stored in one file in the owner's user config
  directory (outside the repository, mode 0600, directory 0700). A rotate action replaces it and invalidates the old
  one at once. An unreadable or wrongly permissioned file turns observed sessions off with a plain reason; it is never
  recreated silently over a file the dashboard did not write.
- Hook snippet: a page (behind the dashboard key) shows the exact hook configuration to paste into the owner's own
  Claude settings: the listener URL with the token, the events `PermissionRequest`, `PostToolUse`, `Stop`, `SessionEnd`, `SubagentStart`,
  `SubagentStop` (and `SessionStart`, harmless if undelivered), and a hook timeout that is longer than the
  dashboard's wait. The token is shown only on that page and never in lists, logs, errors or other API responses.

## 4. Sessions

- A session record is created on the first event of any kind for a `session_id` (`SessionStart` over `http` was not
  delivered in S7 and is not relied on).
- Stored in SQLite (ids and status only): `session_id`, project name (the final path segment of `cwd`, after the
  secret scan; the full path is not stored), first seen, last seen, status. Status is `active`, `ended` (on
  `SessionEnd`), or `quiet` (no event for a configured time; default 30 minutes). A quiet session returns to active on
  any event.
- Subagents: the page says "subagent activity seen" with the last time; it never shows a count (`SubagentStop` fires
  more often than subagents start).
- Caps: 256 stored sessions (the oldest `ended`, then `quiet`, are evicted first) and 32 pending approvals. A request
  beyond the pending cap is answered with no decision, so Claude's own prompt stays in charge, and the page shows how
  many were refused.

## 5. Approvals

- A `PermissionRequest` becomes a held request and an approval card labelled "Your terminal session", with tool name,
  a bounded summary of the tool input (secret-scanned before display; a refused scan shows "withheld", the input is
  never shown), `agent_type` when raised by a subagent, an expiry, and the note "may already be answered in the
  terminal".
- Answer Allow or Deny from the dashboard returns the decision on the held connection. If the terminal answered first,
  the hook timed out or the connection closed, the card closes ("closed: answered elsewhere or timed out") and cannot
  be answered.
- Matching uses `session_id`, `prompt_id` and tool input (no tool call id exists). Identical requests remain separate
  held connections.
- Never automatic: observed approvals are excluded from every approval mode including Automatic.
- Dashboard down or listener off: Claude's own prompt appears and nothing is auto-allowed.
- The page states: only calls that reach a permission prompt are sent, so in Auto mode the list is not a complete
  record.

### 5.1 Never block the terminal

The terminal session is never held up or overruled by the dashboard. Every ending that is not an owner's Allow or
Deny from the dashboard (expiry, a closed connection, the pending cap, the listener stopping, a parse failure, a
dashboard error) replies with **no decision**: HTTP 200 with the body `{}`, so Claude Code's own permission dialog
stays in charge. The observed listener never replies "deny" on its own. Basis: the hooks reference says that with no
hook decision an interactive session goes to the normal permission dialog and that a 2xx reply with no decision is
success with no action (docs-sourced, not yet live-tested; spike S11 tests it, and the fallback is to hold the
connection until the hook's own timeout, the one behaviour S7 verified). Non-interactive sessions (`-p`) have no
dialog, so no decision there means the call is denied by Claude Code itself.

### 5.2 Two-way record of decisions

Each card records who decided and what happened, so the dashboard and the terminal agree:

- Dashboard to terminal: Allow or Deny is returned on the held connection (the terminal then proceeds or refuses).
- Terminal to dashboard (inferred, labelled as such): the hook does not tell the dashboard that the owner answered in
  the terminal (S7). The dashboard infers it from later events of the same session and the same agent (`agent_id`
  absent for the main session): a `PostToolUse` for the same `tool_name` and equal `tool_input` means the call ran;
  `Stop` or `SessionEnd` means the session moved on (a `PostToolUse` for a different call proves nothing: parallel tool calls can finish while another prompt is still open, so it never closes a card). The card then closes
  with `decided_by = "terminal (inferred)"` and `outcome` = `ran` or `not run`.
- Cross-check: a `PostToolUse` after the owner pressed Allow records `outcome = ran` ("ran after your Allow"). A match
  after the owner pressed Deny records `outcome = ran` and raises a visible warning ("ran although denied here"),
  because that would mean the dashboard's decision was not honoured.
- Fields per card: `decided_by` (`dashboard`, `terminal (inferred)`, `timed out`, `unknown`), `decision`
  (`allow`, `deny`, none), `outcome` (`ran`, `not run`, `unknown`), `decided_at`. Stored with ids and status only.
- Limits stated on the page: it is inference from events, not a receipt; a call without a matching event stays
  `unknown`; Auto mode and calls that never prompt are not covered.

## 6. Failure handling

Wrong token, unknown path or method: bare 404, no detail. Oversize body: 413. Host or Origin guard failure: refused as
the managed receiver does. Malformed JSON or unknown event: accepted with no effect where the hook protocol requires a
reply, otherwise refused; nothing from the body is logged.

## 7. Security review focus

Token class separation (both directions), token file handling, no token in any response, log or error, secret scan of
every displayed field including `cwd` and tool input, loopback-only binding and DNS-rebinding guard, resource caps,
and that no observed path can reach managed-run state, project files or the owner's Claude settings.

## 8. Testing and evidence (each labelled)

- Unit / fake-binary / raw-socket HTTP tests in the style of `tests/test_hook_receiver.py`: cross-token refusal both
  ways, caps and eviction, secret scanning, expiry and closed states, token file permissions, rotation, port in use,
  Codex deployment opens no listener, managed receiver tests unchanged.
- Browser check on a scratch copy: sessions list, approval card, snippet page.
- Live (headless `claude -p` against the listener, owner-approved alias, count and estimate beforehand): allow, deny,
  hook timeout. Terminal-attended cases that need the owner at an interactive terminal: terminal No then a late allow,
  terminal Yes then a late deny, a deny while the prompt is open, a simultaneous answer. Until run, the docs say they
  are untested.
- Documentation impact: `docs/dashboard-operations.md`, `docs/dashboard-api.md`, `docs/claude-code-setup.md`,
  `docs/decisions.md`, `docs/task-board.md`; writers assigned (technical_writer, user_documentation_writer).

## 9. Open points

None blocking. Defaults chosen here, changeable at plan review: default port 47615, 30-minute quiet time, caps 256 and
32.

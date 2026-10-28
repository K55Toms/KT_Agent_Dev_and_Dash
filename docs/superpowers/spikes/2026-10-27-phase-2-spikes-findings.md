# Phase 2 spikes S6 and S7: findings and go/no-go

Dates: 2026-10-27 and 2026-10-28. Written from [S6](S6-managed-hook.md) (managed `claude -p` with a `PermissionRequest`
hook, 8 live runs, `claude 2.1.310`) and [S7](S7-observed-hooks.md) (interactive session with hooks, `2.1.310` and
`2.1.312`). Baseline and characterization evidence: `docs/superpowers/evidence/2026-10-27-phase-2-baseline.md`.
Spec: [Phase 2 and 3 design](../specs/2026-10-27-claude-dashboard-phase-2-3-design.md). Every run was one run of one
condition on the `haiku` alias; nothing was repeated, and the owner's user-level Claude settings were not read.
No spec text has been changed except its status line: the changes below wait for the owner's go.

## 1. Recommendation

**Proceed with `claude -p` plus a `PermissionRequest` hook for managed runs and an `http` hook receiver for
observed sessions.** The plan's stop condition (R1, R2 or R4 failing) did not trigger: all three passed, as did R3, R6
and R7. Returning to the Agent SDK is not needed on this evidence. Two things need the owner's decision before Plan 2
is written (section 3): how managed runs get the project's `CLAUDE.md`/`AGENTS.md` text, and whether managed runs may
inherit the owner's user-level configuration.

## 2. Per-claim verdicts

| Claim from the spec | Verdict | Source |
| --- | --- | --- |
| A hook given through `--settings` loads under `--setting-sources user` and fires | **Proven** (`http` type only) | S6 R1 |
| Hook `deny` blocks the call, the model sees the reason, and the stream marks it `decision_reason_type: "hook"` | **Proven** | S6 R1 |
| Hook `allow` is one call, no session grant | **Proven for an identical command repeated once** (not for differently worded commands, `updatedInput` or `updatedPermissions`) | S6 R2 |
| A silent hook ends in a deny by Claude Code itself, nothing auto-allowed | **Proven headless (20 s hook timeout)**. Not proven for the minutes-to-hours wait a dashboard needs | S6 R3 |
| An unreachable dashboard (connection refused) means deny | **Proven for connection refused only** | S6 R4 |
| `--agents` roles load under `--setting-sources user` | **Proven** (role listed in `init`; invocation and tool limits not exercised) | S6 R5a |
| The project `CLAUDE.md` loads under `--setting-sources user` | **Not shown** (the model could not see it); it was visible with `user,project` (one run each) | S6 R5b, R5c |
| `--resume <session id>` continues the same conversation | **Proven** | S6 R6 |
| SIGINT stops a run cleanly | **Proven**: exit 0 in 1.09 s, children gone, stream ends with a `result` (`error_during_execution`, `aborted_tools`) | S6 R7 |
| Managed runs use the `default` permission mode with no flag | **Proven** (`init.permissionMode`, `pmode=default`) | S6 |
| In an interactive session an `http` `PermissionRequest` hook can allow or deny | **Proven** (manual mode; single-use allow and deny) | S7 a1, a2 |
| A silent or unreachable dashboard never blocks or allows the owner's own prompt | **Proven for a silent one** (prompt appears at once, hook closes at its timeout) | S7 b |
| A terminal answer and a dashboard answer can both occur without a double run | **Proven only for two cases**: terminal Yes then a late stub allow (command ran once); a stub allow while the prompt was open (prompt closed, command ran once). **Untested and security-relevant:** terminal No then a late allow, terminal Yes then a late deny, a deny while the prompt is open, a true simultaneous answer | S7 c1, c2 |
| Auto mode approvals do not reach the hook | **Confirmed for two benign calls** (`echo >> file`, `rm -f file`); riskier calls untested | S7 e |
| Observed sessions can be tracked from lifecycle hooks | **Partly**: `SessionStart` over `http` never arrived; `SessionEnd`, `SubagentStart`, `SubagentStop` did | S7 |
| A subagent's approval request can be attributed | **Proven** for the field (`agent_id`, `agent_type`); matching a subagent read by path is untested (stub off-list issue, S7 D) | S7 d |

## 3. Owner decisions needed (before Plan 2)

1. **Project instructions in managed runs.** Under `--setting-sources user`, the project's `CLAUDE.md` (which imports
   `AGENTS.md` and carries the security rules) was not visible to the model; with `user,project` it was. Spec section
   5 says work stops and the owner decides. Options: (a) `--setting-sources user,project`: loads the registered
   project's own settings too. Inference, not tested: a project-level allow rule would then skip the hook, because
   `PermissionRequest` only fires for calls that reach a prompt; (b) keep `user` and pass the project's text with
   `--append-system-prompt` or `--add-dir` (not tried); (c) accept managed runs without project instructions.
   **Recommendation: (b), tried first as the opening step of Plan 2 with a test that the codeword is visible, with (a)
   as fallback only if the project's rules are reviewed.**
2. **User-level configuration in managed runs.** `--setting-sources user` still loaded the owner's user-level
   `SessionStart` hook, plugins (4) and MCP servers (12) in every S6 run. A dashboard-started run therefore inherits
   whatever the owner has installed. Accept, or require a documented clean profile.
3. **Spec section 1 assumptions** (already approved): Claude runs are manual-only; Ponytail "not applicable";
   cost as list-price estimate. Nothing in the spikes contradicts them.

## 4. Changes to make to the spec if the owner agrees

- 4.2: state that a hook that is silent, unreachable or timed out is denied by Claude Code itself; the hook timeout
  must be set far above the 20 s used in S6 (a real wait is minutes), and the interactive spike shows the terminal
  prompt stays open meanwhile. Replace "confirmed once" wording for the dashboard-down case with the S6/S7 evidence.
- 4.2: record the `--resume` and SIGINT results as proven, and the `CLAUDE.md` decision once made.
- 4.3: replace the "to be tested" sentence with the S7 results: reachable but silent (terminal prompt stays; hook closes
  at its timeout), both answering (tested only for terminal Yes then a late allow, and a stub allow while the prompt is
  open; the late-allow-after-terminal-No case must be tested before Phase 3), no auto-allow in any case.
- 4.3: do not use `SessionStart` over `http` as an input (not delivered in two sessions, cause unestablished);
  candidates to test for a session-start input are a `command` hook, the first `PermissionRequest` (not sent in Auto
  or by a session that never prompts) and `SubagentStart`; treat `SessionEnd` as not shown to be reliable.
- 4.3: add a "may already be answered in the terminal" state and an expiry to pending approvals, because the hook
  request stays open after the owner answers (30.4 s in c1) and the dashboard has no signal that closes it (a
  `PostToolUse` or similar signal is untested).
- 4.3: `SubagentStop` fired 10 times for 1 `SubagentStart`; never count stops. Matching on `agent_id` is a
  recommendation, not a tested method (ids were not logged).
- 4.3: payload field lists (S7) replace the generic wording; there is still no tool call id.
- Section 8: add risks for items 1 and 2 above and for the version drift (the CLI updated between S7 sessions).

## 5. Still untested

- The `command` hook type (S6 R1c not run; S7 `http` only); `SessionStart` with a `command` hook.
- Hook behaviour with long timeouts; non-refusal network failures (DNS, TLS, non-2xx); concurrent requests from several
  subagents or sessions; a dashboard-started run observed by a second hook source.
- `updatedInput`, `updatedPermissions`, `interrupt: true` on deny, hooks for tools other than `Bash` and `Read`.
- Auto mode beyond one `echo` and one `rm -f` of a scratch file; other models than `haiku`; plan events (still
  unconfirmed); `PostToolUse`/`PermissionDenied`-style signals.
- Late or conflicting dashboard answers: terminal No then a late allow, terminal Yes then a late deny, a deny while
  the prompt is open, a repeat of the same call after an allow, and a true simultaneous answer (S7 item 2 and 3).
- Matching a subagent's `Read` by path (S7 D unresolved: the stub refused a path that a replay accepted).
- Terms-of-service position of subscription use through the dashboard (owner's judgement, spec section 1).

## 6. Evidence labels

Live Claude runs and hook traffic (S6, S7) are native-integration evidence for this machine and these two CLI
versions. The Codex characterization tests (758 Python and 126 Node tests after Task 4) are mock-based and pin
current behaviour only. Nothing here establishes a dashboard Claude backend, which does not exist yet.

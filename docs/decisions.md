# Decisions

## 2026-11-06 — Claude dashboard Plan 6 (observed terminal sessions): decisions and rulings

Spec: docs/superpowers/specs/2026-11-06-claude-observed-sessions-design.md (where the built behaviour differs from the
spec, the built behaviour and this entry win); user docs: docs/dashboard-operations.md "Terminal sessions", API:
docs/dashboard-api.md "Observed sessions"; spike: docs/superpowers/spikes/S11-observed-replies.md (pending the owner's
attended run). The code is on the local, unpushed branch `observed-sessions`; the pull request waits for the owner's
authorisation. Evidence is unit, fake-binary and journey tests plus one controller browser check on a scratch copy; no
live run with a real interactive terminal session.

Owner choices (made while the spec was written):
- **Fixed port 47615 plus a per-install token file.** The listener uses a fixed default loopback port (setting
  `observed_port`, 1024 to 65535, applied at restart) so hooks the owner pasted keep working across restarts. The token
  is a separate 32-byte value in a 0600 file in a 0700 folder in the user config directory, outside the repository,
  never in logs, rotatable from the page. Port in use means the listener stays off with the reason shown; no fallback
  port is tried, because a different port would silently invalidate pasted hooks.
- **Session list scope, option 2.** The page lists sessions (status active, quiet after 30 minutes without an event, or
  ended; project name; last seen; the time "subagent activity seen", never a count) and shows permission requests from
  them as cards with Allow and Deny. It does not record transcripts, prompts or tool results.
- **The terminal is never blocked.** Every ending other than the owner's Allow or Deny (expiry, closed connection, cap
  refusal, stop, parse failure) replies HTTP 200 `{}`, so Claude Code's own prompt stays in charge. Observed approvals are
  never automatic. Caps: 256 sessions, 32 pending, 64 finished cards, 256 KiB body.

Rulings made while building (cost if wrong in brackets):
- **No-decision reply defaults to `empty_object` (HTTP 200 `{}`)**, constant `NO_DECISION_MODE` in
  `dashboard/observed_receiver.py`. Basis: Claude Code's documentation says a 2xx reply with no decision is success with
  no action and the normal dialog appears; it is **not live-tested**. It beats holding the connection because it frees
  the thread and the slot at once and matches "never block". The S11 decision rule: if the owner's run shows `{}`
  disturbs the prompt, switch the constant to `hold` (a one-line change; hold was the behaviour S7 verified). [A
  disturbed prompt on a real session until the run is done.] The connection-drop, 413/415 and two-hook-merge endings
  are also untested.
- **Inference rules for the two-way record.** The terminal's answer is inferred, labelled "Inferred from later events,
  not a receipt". A `PostToolUse` of the same session and agent with the same tool name and equal tool input means the
  call ran. `Stop`, or `SessionEnd` (which closes every card of that session), without a match shows **no run seen**, not
  "not run", because a dropped or oversize `PostToolUse` gives the same record. A `PostToolUse` without tool input
  leaves the outcome unknown. A `PostToolUse` for a different call never closes a card (parallel tool calls would
  otherwise give a false "not run" and remove the dashboard's chance to answer). A matching `PostToolUse` after the
  owner's Deny shows "ran although denied here". When inference settles a card whose hold is still open, the hold ends
  with `{}` at once. [A terminal "No" stays pending until the turn's `Stop`; rework if S11 shows an earlier signal.]
- **Managed sessions are ignored.** Dashboard-managed runs use `--setting-sources user`, so a snippet in user-level
  settings fires for them too (double hooks, a card on a managed call, a possible stall of the managed pipeline). The
  listener replies `{}` at once for a known managed session, with no card and no record, and the docs say to paste the
  snippet only into `.claude/settings.local.json` (never a committed or shared file: the URL carries the private token;
  that Claude Code keeps that file out of git is documentation-sourced, and that hooks in it fire is untested, S11 D5).
  [A managed run's first hook can arrive before its session id is registered, so
  a card may briefly appear; a managed session resumed in a terminal is ignored.]
- **Opaque ids.** A session id the secret scan refuses is shown and stored as `~` plus 12 hex digits of its SHA-256; the
  leading `~` is refused by the id pattern, so it cannot collide with a real id.
- **Defaults changeable in code, not settings:** 30 minute quiet time and the caps above. [A rebuild to change them.]

**OPEN owner decision: fixed-port exposure while the dashboard is down.** The fixed port is inherent to the owner's
choice. While the dashboard is not running, another local program could bind the port and would receive hook payloads
(commands, file contents and the token in the URL) and could reply allow. Accepted for now with warnings: the page and
the snippet note say to remove or disable the hooks when the dashboard is not in use, and the port-in-use phrase says
hooks installed earlier may be sending to another program. Alternative if the owner wants it closed: a `command` hook
wrapper that checks the listener's uid before sending (out of scope; not built). Cost if left: residual exposure to
another local user on a shared Mac while the dashboard is down.

**Release note (upgrade and rollback).** `observed_port` is a new key in `config.toml`. Older code, including `main` before
this branch merges, refuses a `config.toml` that contains `observed_port`, the same precedent as
`claude_approval_wait_seconds`. Remove the key (or restore the old file) before running older code.

**Fail-closed managed check (decided, built).** The check that a session belongs to a dashboard-managed run fails
closed: an error in it, or the dashboard's lock staying busy for over a second, counts as managed, so that event gets
`{}` with no record, card or hold. Reason: a card on a managed call would have an unverified interaction with the
managed hook; a missing card is the safe cost, and the terminal prompt stays in charge either way.

Open items:
1. **S11 owner-attended run** (pending): the `{}` reply, the real `PostToolUse`, `Stop` and `SessionEnd` payloads (field
   names only), the connection-drop and 413/415 endings, how Claude Code merges two `PermissionRequest` hooks, the
   dashboard-down case (D4: the claim that Claude Code's own prompt appears and nothing is allowed is documentation-sourced,
   not tested) and hooks in `.claude/settings.local.json` (D5).
2. Pull request and push: waiting for the owner's authorisation. Writers' review and the agent-evaluation checkpoint are
   recorded in docs/model-evaluation.md when done.

## 2026-11-01 — Claude dashboard Plan 4 (managed approvals): decisions and rulings

Evidence: docs/superpowers/evidence/2026-11-01-managed-approvals.md; spike: docs/superpowers/spikes/S10-managed-approvals.md;
status: docs/task-board.md. The code is on the local, unpushed branch `managed-approvals`. The owner has not yet
reviewed the results and has not approved the live acceptance run.

Owner requests (2026-11-01, made when the plan was presented; the owner then said "Run all thank you." and the plan
defaults were read as confirmed):
- The wait for an approval is configurable: a dashboard setting `claude_approval_wait_seconds`, default 300 seconds (owner ruling 2026-11-02, was 900),
  range 60 to 3600, applied to runs launched afterwards.
- Automatic approval is an option for Claude projects. This replaces the manual-only decision of the Plan 2 entry below
  (managed Claude runs are manual-only) for approvals. Scope: the existing per-project `manual`/`automatic` mode and its
  confirmation checkbox; only the tools `Bash`, `Write`, `Edit` and `NotebookEdit`; one call each, recorded as
  `project_policy`; never for secret-shaped input; every other tool always manual. Claude's own Auto mode stays excluded
  (a run whose permission mode is not `default` is stopped). The part of the Plan 2 entry about inheriting the owner's
  user-level Claude configuration is unchanged.

Controller rulings (the owner may overturn these):
1. The per-run token stays in the URL path of the hook (`/hook/managed/<token>`), with the settings file at 0600 in a 0700
   folder. S10 showed the `headers` plus `allowedEnvVars` form works, but it would put the token in `claude`'s environment,
   which tool subprocesses inherit by default (not tested whether Claude Code strips it). Cost if wrong: the token is
   readable in the settings file by the same user.
2. The wait defaults were restored to 900 seconds and 60 to 3600 over the S10 note's narrowing to 60 seconds, which would
   make approvals unusable for a person. They were marked unverified above 120 seconds (the Settings help text and the docs); the live run of 2026-11-02 verified about 305 seconds under a 960 second hook timeout, and longer waits stay unverified.
   The longest hold shown live is an answer after about 305 seconds under a 960 second hook timeout (2026-11-02, one run; S10 R10a showed 75 seconds under 120). It fails closed:
   if Claude Code ends the hook earlier than the dashboard's wait, the connection closes, the approval becomes unavailable
   and the call is denied. The further live run (hook timeout 960, answer after 300 seconds) needs the owner's separate approval
   and has not been run. Cost if wrong: waits above the real ceiling expire early.
3. The hook timeout is the wait plus 60 seconds, fixed at launch; a live run's effective wait is the smaller of the current
   setting and its launch value.
4. A request that arrives before the dashboard knows the run's session is denied, not queued (it cannot be bound to a live
   turn), and recorded as the notice `claude_hook_session_unknown`.
5. Deleting a task with a pending approval keeps the answer 409 "stop the run first" (as for Codex); stopping denies the
   request and marks the approval unavailable, after which the delete succeeds.
6. A request with a `permission_mode` other than `default` (or none), or a `session_id` that contradicts the run's, is denied,
   and the run is stopped and marked failed (`claude_permission_mode`, `claude_session_rejected`).
7. The approval display escapes control and bidirectional-format characters as `\uXXXX` for Claude requests only; Codex
   display was left unchanged (carried on the task board).
8. The settings key is optional on save (absent keeps the stored value) because the previous page payload lacks it.
9. Live acceptance is part of the plan within the owner's recorded approval; if the owner declines it, Plan 4 stays
   fake-binary only and the docs say so.

Not decided: pushing, merging or publishing; the live acceptance run; the R10i run.

## 2026-10-28 and 2026-10-29 — Claude dashboard Plan 3 (managed run loop): decisions, rulings and deviations

Evidence: docs/superpowers/evidence/2026-10-28-managed-run-loop.md; status: docs/task-board.md. The code
is on the local, unpushed branch `managed-run-loop`; the owner has not yet reviewed the results. The owner
confirmed on 2026-10-28 that the ten plan defaults stand (listed first); the rulings after them were made by
the controller during review.

Plan decisions (owner-confirmed defaults):
1. 2026-10-28: the role becomes the main session through `--agents` plus `--agent` (proven by spike S9,
   run R9a); the `--model` plus appended-body fallback was not needed.
2. 2026-10-28: the child environment is an allow-list (`PATH`, `HOME`, `USER`, `LANG`, `LC_*`, `TMPDIR`,
   `SHELL`, `TERM`); all else, including `ANTHROPIC_*`, `CLAUDE_CODE_*` and cloud-provider variables, is not
   passed. S9 R9c: a run with this allow-list logged in; no widening was needed.
3. 2026-10-28: token mapping sums input, cache read and cache creation into `input_tokens`; cost is
   `total_cost_usd` shown as an estimate at list price, never a billed amount (`cost.unit` `usd-estimate`).
4. 2026-10-28: denied calls are surfaced as a bounded list of tool names and a count, with a fixed notice;
   never `tool_input` or message text.
5. 2026-10-28: a run that ends without a `result` is `unknown`, not `recovery_hold`, and resumable with
   `--resume` because its session id is known.
6. 2026-10-28: the dashboard passes its security baseline plus the project's expanded instructions
   through `--append-system-prompt` (S8); it expands the `@AGENTS.md` import (one level, inside the
   project, regular files only, size capped).
7. 2026-10-28: stop ladder SIGINT, 10 s, SIGTERM to the process group, 5 s, SIGKILL; the child starts in
   its own session; `interrupted` comes from the dashboard's own signal, not the exit code. On restart a
   possibly-still-running child is only warned about; the dashboard never signals an old pid.
8. 2026-10-28: a run whose `init.permissionMode` is not `default` is stopped immediately and marked
   `failed`; nothing it asks for is answered.
9. 2026-10-28: `claude` is looked up on `PATH`; `scripts/run_dashboard.sh claude` checks it exists.
10. 2026-10-28: readiness is `claude --version` only; the UI says "login not verified"; no account data is read.

Rulings and results during the plan:
- 2026-10-29: an overflow (an output line over the size limit) after a terminal `result` keeps the
  status and adds the `claude_output_too_large` notice; without a terminal status it ends `unknown`.
- 2026-10-29: an unknown Claude task holds its project only while its latest diagnostic is
  `claude_possibly_running` (a process may still exist). Other unknown Claude tasks hold nothing, so a
  restart no longer blocks the project. A guard in `_init_recovery` stops the Codex-style recovery hold
  from being applied to Claude tasks. Claude records saved with `recovery_hold` before that guard are not
  cleared (development data only).
- 2026-10-29: the snapshot exposes only `claude.denied_count` and `claude.denied_tools` for a Claude task.
  The first Task 10 build sent the whole internal `claude` record (process id, session id, pid start marker);
  a review found it and that record was reduced. The session id still appears as the task's `thread_id`, the
  same way Codex thread ids do.
- 2026-10-29: new diagnostics codes `claude_session_rejected` and `claude_restart_unknown` (plus
  `claude_possibly_running`, used for the pid warning).
- Test fact: all fixtures share one session id. A Dashboard registers each session once, so a second
  fresh run on the same Dashboard is refused as `claude_session_rejected` (correct, fail-closed);
  journey tests use a new Dashboard or rewrite the session id in the run factory.

- Owner decision restated (2026-10-28, Plan 2 entry below): managed Claude runs inherit the owner's user-level
  Claude configuration (`--setting-sources user`). Consequence for Plan 3: user-level allow rules and hooks
  apply, so "denied by Claude Code itself" holds only when no such rule exists; this is untested.
- 2026-11-01 (controller ruling, final review): the instruction and each follow-up are passed to `claude -p` as
  the positional argument, so other local users of the Mac can read them with `ps` while the run lasts. Kept
  because the spec fixes stdin to `/dev/null` and stdin delivery is untested. Disclosed in
  docs/dashboard-operations.md and docs/claude-code-setup.md ("do not put secrets in instructions"). Revisit
  with stdin input in a later plan, after a live check.

- 2026-11-01 (controller rulings, Task 9 fix round after the final and security reviews):
  1. Automatic mode confines file tools: `Write`, `Edit`, `NotebookEdit` are auto-accepted only for a path inside the
     project's real path (symlinks followed, relative paths against the project) with no `.git`, `.claude` or `.local`
     component; anything else, including a missing path or a resolution error, falls back to manual review, never deny.
     `Bash` stays name-only and is documented as unrestricted same-user execution. Manual mode unchanged (F1, M2).
  2. The tool-call automatic accept repeats the final `recovery_manual` check as the Codex path does (F6).
  3. An accept that loses the race with expiry records `unavailable_reason` so the card says Expired (L1).
  4. A hook request with a differing `session_id` and an `agent_id` is denied for that call only, with the new code
     `claude_hook_subagent_session`; without `agent_id` the run is still stopped and failed. Reason: not verified live
     whether subagent requests carry the parent's session id (M1).

Plan 2 carry-forward items, disposition at the end of Plan 3:
- Codex wording flash before `/api/provider` answers (static page text): unchanged by design, still open.
- Codex wording reachable under Claude: closed for the empty task list, plan and usage empty texts, stage
  labels (including "Create Codex thread"), and the delete and interrupt announcements (Task 10); "Checks run
  through Codex" (delivery check plan, unreachable for Claude) and the approval, guidance and delivery strings
  remain, unreachable.
- One source for the duplicated refusal strings: deferred again, still open.
- Assessment routes under `/recovery` should require both capabilities for a future provider: still open.
- `GET /api/tasks/{id}/recovery` for another provider's run creating a recovery row: still open.
- `ProviderUnavailable` before any state change: closed (Task 7 and 8 tests).
- `turn/completed` with a list or object status raising `TypeError` in `conversation.py`: still open (pre-existing).
- Untested provider exemption in `Capabilities` validation: still open.

Accepted deviations and disclosures:
- Deviation: there is no `ClaudeBackend.start_run`. The Dashboard takes a `claude_run_factory` seam
  (default `ClaudeRun`) and `ClaudeBackend` only supplies the probe and the binary path. Controller design
  ruling in Task 8.
- Disclosure: during Task 7 the implementer ran the real `claude --version` once by mistake (an existing
  test reached the default runner). No model call was made and the output was not kept; the test now
  injects a runner. A reviewer mutation check also briefly ran a scratch `dashboard.server`.
- Existing tests edited outside the Task 7 exception: two (`test_claude_readiness.py` and
  `test_provider_routes.py`), because they pinned the refusal that Task 8 removed.
- Not decided here: Plan 4 (hook receiver and approvals) needs the owner's go; the optional live smoke
  run needs a separate approval.

## 2026-10-28 — Claude dashboard Plan 2 (provider seam): decisions, accepted deviations and known residuals

Recorded by who decided. Evidence: docs/superpowers/evidence/2026-10-28-provider-seam.md; status:
docs/task-board.md. The code is on the local, unpushed branch `provider-seam`; the owner has not
yet reviewed the results.

Owner decisions:
- One provider per deployment (decided 2026-10-27, restated here because Plan 2 implements it).
- Managed Claude runs are manual-only (owner, 2026-10-28): the per-project Automatic approval mode
  does not extend to them, and neither does Claude's own Auto mode.
- Managed Claude runs inherit the owner's user-level Claude configuration (settings, hooks,
  plugins, MCP servers) as it is at each launch, including additions made later (owner, accepted
  2026-10-28). A user-level allow rule or hook could change which calls reach the dashboard; that
  is untested.

Plan and controller decisions (the owner may overturn these; the owner pre-approved executing
Plan 2 without a prior plan review):
- The provider is chosen by a start-up argument and fails closed. `sh scripts/run_dashboard.sh
  codex|claude` requires exactly one argument; with none, or any other value, it prints its usage
  and exits with status 2. There is no default to Codex, and there is no environment variable or
  `config.toml` setting. User-visible consequence: the previous command `sh
  scripts/run_dashboard.sh` no longer starts the dashboard; existing Codex users must add `codex`.
  A server started directly without a valid `--provider` runs with no provider, starts no backend
  and refuses to start runs.
- The project-instructions mechanism for managed Claude runs, chosen by spike S8: pass the
  project's `CLAUDE.md` with `--append-system-prompt`, the dashboard expanding the `@AGENTS.md`
  import itself; the file form (`--append-system-prompt-file`) is the fallback; `--add-dir` alone
  did not make the instructions visible. Evidence: docs/superpowers/spikes/S8-project-instructions.md
  (one live spike, four `haiku` runs, one run per condition, under `--setting-sources user`). It shows
  the appended text reaches the model, not that Claude Code resolves `@AGENTS.md` itself (the harness
  pre-expanded it). The file form is not listed as its own option in `claude --help`; it was inferred
  from the `--bare` description and worked in version 2.1.312. The CLI records the system prompt once
  per conversation, so a resumed run keeps the original appended text (design, section 4.2; not
  run). The decision lands in Plan 3; Plan 2 does not implement it.
- A project registered while no provider is configured is recorded under the legacy default
  `codex`, never `none`.

Accepted deviation (controller ruling in Task 6): a `turn/started` or `turn/completed` notification
whose `turn.id` is not a string now changes nothing; the earlier code stored whatever value it was
given. Codex goldens are unchanged.

Three further accepted deviations (Review Focus 5, final whole-branch review): a `turn/plan/updated`
step whose `status` is a list or object now reads as `pending` (it raised `TypeError`); a
`thread/tokenUsage/updated` with a non-object `tokenUsage` or `total` now leaves usage unchanged but
still stamps `updated_at` and saves (it raised `AttributeError`), as the invalid-counters path does;
a `thread/settings/updated` with a non-object `threadSettings` now changes nothing (it raised
`AttributeError`). All three are pinned by the translator tests; Codex goldens are unchanged.

Final-review fixes (2026-10-28): the approval review routes (GET review, sensitive review, and the
alternative route before its text check) and `delivery_review_decision` now refuse a run recorded
under another provider with "recorded under a different provider", and `record_review_failure`
writes nothing onto another provider's approval, so a refused request changes nothing, as the API
page states. An explicit `client=None` to a `CodexBackend` method now raises `ProtocolError`
instead of using the current client. Deferred to Plan 3: one source for the duplicated refusal
strings ("Claude backend is not implemented yet." and "No provider configured." exist with and
without the final period in `server.py`, `backends/claude.py` and `backends/base.py`), and real
offered decisions in `ApprovalRequest.available_decisions` (documented as carried for later
providers and not read by `CodexBackend`).

Known residual, not fixed: a `turn/completed` notification whose `turn.status` is a list or an
object still raises `TypeError` in `dashboard/conversation.py` (an unhashable dictionary lookup in
a module that Plan 2 did not change), as it did before. Review Focus 5 (a malformed notification
never raises on the reader thread) is therefore met except for that one shape.

Pre-existing oddity, preserved: when the human sends guidance on a pending permissions or
elicitation request, the dashboard answers it with `{"decision": <mode>}` whatever the request kind;
that is probably not a valid Codex response shape for those kinds. Separately, an approval-question
decline or cancel cannot be reached over HTTP (a validation error now answers 400 where the old
code dropped the connection). The behaviour was kept and flagged for the owner.

## 2026-10-27 — One provider per dashboard deployment

Recorded by who decided. Owner decision (in chat, 2026-10-27): the dashboard is deployed with
ChatGPT (Codex) OR with Claude, never both at the same time.

Consequences:
- One build supports both providers. A deployment setting selects exactly one at start-up; the
  other provider stays disabled.
- No mixed-provider runs, no showing Codex and Claude work side by side, and no shared approvals
  across providers.
- The Claude backend adapter ("Phase 2") must be built for this release. It is not designed or
  started yet and is being specified separately.
- The team layer is unaffected: the 14 roles (`team_source/`, `.codex/agents`, `.claude/agents`)
  keep supporting both Codex and Claude Code side by side.

Open: which settings mechanism selects the provider, and whether observing the owner's own Claude
sessions is in this release, are decided in the Phase 2 design.

## 2026-10-27 — Claude Code adaptation: security review dispositions

Recorded by who decided. The review, the reproduction results and the per-finding dispositions are
in docs/superpowers/evidence/security-review-claude-code-adaptation.md; the status is in
docs/task-board.md.

Owner decisions (in chat):
- Fix F1, F5, F10, the cheap part of F2 (a test pinning the generated files' front-matter keys),
  F6, F8 and F7 ("Yes, all of these").
- Fix F3 and F4 in the security automation ("F3 and F4, you review them"): the owner reads that
  diff before merging. The `.claude` path rule only adds blocks; a future `.claude/settings.json`
  or `.mcp.json` needs a reviewed policy change first.
- Not in this wave, kept open: F2's CI, branch protection and CODEOWNERS; F9 (tool profiles for
  non-implementer roles, the `advisor` question); a path rule against stdlib-named `.py` files; a
  policy on nested CLAUDE.md files.

Owner decision, ACCEPTED 2026-10-27 ("Accept"; dashboard side effect of F3): the dashboard shares `forbidden()`, so it now refuses
  project roots under `.claude/worktrees/`, hides `.claude`, `.mcp.json` and `CLAUDE.local.md` paths, and
  refuses Git publish of any registered project whose history contains them (as it already does for
  `.codex`). Fails closed; may block publishing other Claude Code projects that commit
  `.claude/settings.json` or `.mcp.json`. Accepted as is; a dashboard-specific rule can be requested later.

Controller decisions (the owner may overturn these):
- CLAUDE.md, not AGENTS.md, carries the F6 and F8 wording: it never relaxes AGENTS.md's security
  rules or SECURITY.md, and skill instructions never authorize pushing, publishing or merging.
- Process note (I1): future live runs do not list environment variable names without the owner's
  explicit approval.

## 2026-10-26 — Claude Code adaptation: closeout dispositions and the owner's decisions

Recorded by who decided. The findings are in docs/model-evaluation.md (EVAL-2026-10-26-05 and its
addendum) and the status is in docs/task-board.md.

Owner decisions (in chat, 2026-10-26):
- Merge back to main locally, chosen from the finishing menu. The work was merged into local `main`
  by fast-forward and not pushed. This is the authorization the evaluator could not see in the
  earlier records.
- Apply the documentation and records fixes from the three closeouts ("Yes, all of it").
- Change Claude's Chief of Staff so that it is not told to follow the Codex-only
  docs/model-policy.md; it points at `team_source/models.toml`. Claude only; Codex unchanged.
- Run an independent security review before anything is pushed. It is APPROVED and PENDING; it has
  not been done, and nothing here says it passed. (Superseded: it was RUN on 2026-10-26; see the
  2026-10-27 entry above.)

Controller decisions (the owner may overturn these):
- The three closeouts were run after completion, read-only, and a follow-up wave acts on them,
  limited to documentation, records, one role-prompt line and the tests that pin them. Code
  findings outside that scope (the hard-coded "28 files" message in `sync_roles.py`, symlink
  handling) stay on the deferred list.
- Substitution, recorded: implementers and reviewers during development were general workers, not
  the 14 project roles, because the Claude role files did not exist until Task 11 and loading them
  in the running session was not established. QA acceptance was run by the controller, not by the
  qa_engineer role. The mid-development evaluation checkpoints were not run and cannot be run
  retroactively: a permanent process gap.
- Phase 2 briefs carry all the AGENTS.md task fields, including an explicit list of questions to
  stop and ask the owner.

Not decided or not done: the independent security review (pending); owner confirmation of the
commit attribution trailer and the local git identity before any push; whether to authorize the
paid native checks (an interactive Claude Code session delegating one real task to a project role,
and one native Codex load of the regenerated role files); retention of the local evidence folder.

## 2026-10-26 — Claude Code adaptation: Phase 0 and Phase 1 decisions

Status: merged into local `main` by fast-forward on 2026-10-26 at the owner's choice (see the entry
above); not pushed. The closeouts were run afterwards; the security review is pending.

Recorded by who decided. The evidence is in docs/superpowers/spikes/ and
docs/superpowers/evidence/2026-10-26-phase-1-live.md; the design is
docs/superpowers/specs/2026-10-26-claude-code-adaptation-design.md.

Owner decisions (in chat, 2026-10-26):
- Keep both Codex and Claude Code. The team and the dashboard both move; the dashboard follows in
  later phases. The dashboard is to start and own Claude runs and later also observe the owner's
  own sessions, including approvals (confirmed as a later phase whose feasibility Phase 0 was to
  test).
- One shared model policy file with a column per tool. Keep the 14 roles and add superpowers as
  process discipline. Consolidate in one repo on a branch.
- Claude sign-in is the owner's subscription login, for personal local use. The terms question
  (the Anthropic SDK note about third-party use of a claude.ai login) is left to the owner's own
  judgement and is NOT resolved.
- Ponytail is not used on the Claude side. Dashboard approach: backend adapter, phased.
- The Phase 0 report was accepted and spec amendments A1-A10 applied.
- Claude model column: opus/medium for chief_of_staff, product_manager, ui_designer,
  frontend_developer, qa_engineer; opus/high for technical_architect, backend_developer,
  platform_reliability_engineer, security_reviewer, code_quality_reviewer,
  agent_evaluation_engineer; sonnet/high technical_writer; sonnet/medium
  user_documentation_writer; opus/low expert_escalation (the `fable` alias is credit-gated off at
  the owner's organisation, S5).
- General guidance lost in translation is restored for Claude through claude-only lines in the
  roles' own words. expert_escalation's shared description is made neutral (this changes the Codex
  description too). The Chief of Staff's pre-existing broken sentence is presented whole for
  Claude only; Codex is unchanged.

Plan and controller decisions (the owner may overturn these):
- Reviewer roles get only Read, Grep and Glob, because a role with Bash gains a write route once
  Bash is approved (S4). Every role except chief_of_staff has `disallowedTools: Agent`. The live
  runs observed the Agent tool removed; the setting removes only that tool.
- Ponytail and ui-skills-root text is codex-only. AGENTS.md is not split: CLAUDE.md imports it and
  its differences section scopes the exclusion to the first paragraph under `### Ponytail pilot`.
  Subagents receive CLAUDE.md and AGENTS.md as context, so the paragraph is switched off, not
  removed.
- Sync never deletes files and renders everything before writing. The Codex dashboard files and
  docs outside the new sections were left untouched.
- The project's Codex-style workflow gates were NOT followed for this work: no technical_writer or
  user_documentation_writer closeout and no agent_evaluation_engineer checkpoint. The Claude-side
  superpowers process with independent task reviews was used instead. Per AGENTS.md this is a
  recorded gap, not a passed gate. The closeouts were run afterwards (2026-10-26, see the entry
  above); the mid-development evaluation checkpoints cannot be run retroactively.

Open items: Phases 2 and 3 not started; launch mode `--setting-sources user` provisional (S1);
hook-based approvals do not reach Auto-mode calls (S2) and the hook payload has no tool_use_id;
the S3 `--forward-subagent-text` effect is inconclusive; `fable` untested; interactive mode and
Auto-mode behaviour untested; the `CLAUDE_EFFORT` variable (observed set when checked at run R9; assumed for the first eight
runs, same shell) was not investigated;
AskUserQuestion-in-subagents is docs-sourced; "Astra" wording remains in dashboard/team.py,
README.md, docs/team.md, docs/decisions.md and docs/model-policy.md; deferred minor review
findings (team_source test polish, sync_roles.py CLI polish, docs gaps) are in a local, untracked
working ledger, not in the repo. The final whole-branch review has since been done (see the
task board entry of the same date); its outcome is recorded there.

## 2026-10-26 — Native approval parity and human verification steps

After another unsupported-request screenshot, the human requires actual native Codex requests
and approve/reject choices in the dashboard. The installed App Server schema and current official
documentation distinguish command/file approval, turn-scoped permission requests, native input
approval choices and MCP elicitation. Preserve each native response shape and actual scope;
new kinds remain manual. Do not label a turn-wide permission grant as one-command approval.
The human clarified: “Human steps are good.” External sign-in and device verification may require
an explicit human step; the dashboard must explain and expose that path and native negative
choices without manufacturing verification proof or automatically navigating external links.
This does not authorize granting any currently pending request or changing project policy.

## 2026-10-26 — Execute the reviewed UI improvements

The human authorized team review, planning and efficient implementation of the UI review.
The UI Designer and Technical Architect reviewed both reports. Implementation order is reading
stability and unsupported-request exits, safe completed-task Outputs, full decision accounting,
then secondary delivery summaries. Keep existing themes, polling, exact-request authority and
the separate execution/delivery/release states.

Routine implementation contract: explicit output registration binds a project-relative path to
the server-owned task and current turn, using existing scanned text preview controls and a
recorded content digest. Historical completed tasks have an explicit human attach path.
Never infer artifact associations from model prose. Changed, missing and blocked content remain
distinct. State polling exposes output metadata and historical delivery summaries without
per-row project snapshots; only existing fresh detail validation can authorize delivery actions.
The full-queue action explicitly says it clears filters and does so only on the user's click.
Security reviews new file/identity boundaries; independent QA and reviews remain required.
No release, publication, new upstream request support or application redesign is authorized.

### 2026-10-25: conversation reading-position review

The human reported refresh repeatedly resetting conversation reading position. Lina's source
review identifies full log replacement without scroll restoration when the render signature
changes. Preserve reading position and conditionally follow the bottom as a prioritized repair
proposal; no app change is made by this review. Root in-chat browser verified only that an
unchanged completed conversation retained its bottom position after refresh. Changed-data
browser reproduction/retest remains assigned to QA; no native work was started to force it.

### 2026-10-25: UI review follow-up and completed-task outputs

The human requested Lina Cass's UI Designer review of the recommendations and an assessment
of visual improvements. The human also explicitly required completed-task outputs, using a link
to the generated Markdown review as the example. Record this as requested product behavior;
the current task updates review artifacts, not application code. Safe task/project association,
direct checked preview and honest missing/changed output states remain implementation design
work. Do not treat an accessible output as delivery acceptance or release authorization.

## 2026-10-25: Direct dashboard run deletion

The human requested a way to delete a run after unresolved recovery state blocked a new UI
review. Add direct confirmed local-history deletion for terminal/Unknown runs and release
their holds without assessment, continuation planning or boot checks. Preserve honest native
uncertainty: deletion does not stop execution or undo files. Known live roots/children and
in-flight operations require Stop first. Use existing same-origin boundaries, a current
confirmation fingerprint and one storage transaction before in-memory removal. Test the
positive delete/unblock journey, persistence failure, stale confirmation and late callbacks.
This authorizes a capability; no particular live record is deleted during development.
Development closeout: 551 project-environment Python tests and 109 UI tests passed; independent
QA/security/code review and both documentation writers closed. Retry after uncertain requests
and focus restoration after Recovery polling were fixed and retested. Disposable browser
evidence covers both entry points, acknowledgement gating and cancellation; actual deletion
and same-project relaunch are verified through synthetic HTTP/DOM tests, not real native work.
The human approved restarting the idle dashboard with the current combined working tree.
Graceful restart and App Server reconnection were verified; exact ID/status comparison retained
all 10 runs and both projects. All tasks now expose deletion eligibility/version, including both
eligible Unknown runs. Live browser verification opened and cancelled the blocking run's
confirmation, restoring focus and preserving the record. No live run deletion, model work or
publication was performed. This restart also loaded other current local changes in the shared tree.

## 2026-10-25: UI Skills guidance for design and implementation

The human requested ui-skills-root reinforcement for the UI Developer and clarified that
UI Designer should receive it too. Add maintained-skill routing to frontend_developer and
ui_designer, scoped to each role's ownership. Keep Ponytail Full in Frontend and retain
existing permissions, accessibility and independent review requirements. Reference the
installed root skill rather than duplicating its full contents. This changes future role
instructions; existing invocations are not refreshed and CLI/runtime behavior is unverified.
The human also requested portability documentation for Ponytail and confirmed the UI skill is
ui-skills-root. Document per-machine external installs and environment checks in
docs/skill-setup.md, linked from README and team guidance; resolve skill paths through the
catalogue instead of a developer's username. Preserve the existing approved Ponytail runtime
version/hash. UI CLI version locking and clean-machine installation remain unverified;
documentation does not install or update dependencies automatically.

## 2026-10-25: Fix all nine Ponytail audit findings

The human requested all reported fixes using Ponytail when useful. Keep the current local
Python/SQLite/browser design and dependencies; repair shared causes, preserve safety gates
and remove unreachable native-assessment branches. Read-only metadata timeouts must not
terminate unrelated work. Descendant checking must cover the observed 25-child case with
bounded complete checks, not clear incomplete evidence or weaken ownership/boot fences.
Writers and independent quality reviews remain part of development and delivery.

## 2026-10-25: Implement assessment handoff as a feature

The human approved a checked evidence handoff for assessment in an existing approved chat,
returning the assessment for explicit local review before separate continuation-plan approval.
Present it as a general recovery feature. Corporate sign-in limitations belong in dated
development history, not the feature rationale or UI. Keep uncertain outcomes, project holds,
fresh activity checks and native permission boundaries; handoff never starts native work or
automatically transmits evidence. Architecture and security review preceded implementation. Independent QA and reviews
verified the handoff source and fixes, and the full Python/UI suites passed. The update was
applied locally under the earlier human approval to restart and begin live recovery validation.
Existing tasks were preserved, and no model work or continuation was started.

## 2026-10-25: Corporate account blocks the assessment sign-in route

The human attempted sign-in and reports that corporate account policy prohibits Sign in
with ChatGPT. The current assessment integration is therefore unusable for this account;
real assessment and native continuation remain uncompleted. Preserve the existing-Codex-only
and no-separate-API-billing direction. No policy bypass, personal-account substitution or
credential reuse is authorized. Technical Architect will review existing native capabilities
and safe alternatives. Source review confirms native assessment is explicitly disabled,
with no verified enforced tool-isolation or credential bridge. A previewable scanner-checked
evidence handoff and human-reviewed returned assessment is a proposed alternative only; its
export/import and acceptance workflow needs a product decision and reviewed implementation.
The existing assessment annotation cannot satisfy the assessment gate or unlock continuation.

## 2026-10-25: Human approved local application and live validation

The human approved restarting the dashboard with the recovery update and beginning live
validation. The service reconnected without replaying work; existing unknown records remain
unknown. The human completes ChatGPT sign-in directly, with only bounded status inspected
afterward. This approval does not authorize an OS reboot or native development continuation.
Live metadata exposed incomplete descendant coverage, which remains a development blocker
alongside the existing recovery gates. Reboot alone is not sufficient evidence to clear it.

## 2026-10-25: Recovery candidate review closeout; release validation pending

The implemented candidate preserves the human's assess-first, separately-approved-continuation
choice and ChatGPT-sign-in-only direction. Independent security/correctness findings were
remediated and retested. Documentation owners closed their source reviews; the test board
separates synthetic protocol/browser/pipe evidence from native startup observations. Two
scanner findings were synthetic authentication test construction, now corrected and rescanned;
no real credential incident or scanner-rule change occurred.

At this pre-restart checkpoint, the running dashboard had not been updated; application
was awaiting the human release decision subsequently recorded above.
Real account eligibility, sign-in, useful repeated inference, any separately chosen OS reboot
and native recovery continuation still need live validation. No outcome of an uncertain old
operation is inferred from these checks, and no production task is resumed or replayed.

## 2026-10-23: Recovery keeps ChatGPT sign-in and plan usage

The human rejected a separate API-key/billing integration and requested Codex/ChatGPT sign-in,
including an in-dashboard sign-in flow if reauthentication is needed. The installed App Server
has no verified complete tool-free assessment boundary. Official public Sign in with ChatGPT
documentation provides a direct ChatGPT-plan OAuth route without a partner API key or client
secret. Implement that explicit sign-in and a separate text-only assessment transport; actual
development continues through the existing dashboard-managed App Server.

Never read or copy Codex credential stores. Keep this assessment session's OAuth tokens,
authorization codes and PKCE transaction material in process memory only; persist only
nonsecret host/client registration and validated identity fingerprint. Reauthentication never
replays work. Token signature verification uses maintained pinned JWT/cryptography dependencies.
Account/workspace eligibility and completed live inference remain unverified until the human
completes consent and an isolated assessment succeeds. No API-key or separately billed fallback,
model substitution, or automatic account switch is authorized.

## 2026-10-19: Implement the reviewed recovery design

After receiving the reviewed proposal and its remaining proof requirements, the human requested
implementation of that design. Proceed with mandatory assessment first, a separately approved
versioned fresh continuation plan, same-thread restoration only where verified safe with a
linked fallback, and Manual native approvals during recovered execution without changing the
saved project preference. This authorizes implementation, not weakening capability gates or
claiming unexecuted native proof. A legacy OS restart is offered only as an optional separately
chosen human operation; never initiate it automatically. Do not resume/replay production work
for tests. Prepare reviewable isolated probes before requesting any required native execution
authorization. Keep the current dashboard live while developing and reviewing changes.

## 2026-10-19: Design unknown-task recovery (proposal work authorized)

The human requested a safe recovery workflow design after finding that unknown tasks cannot
accept conversation follow-ups after restart. Prepare a reviewed proposal covering evidence
inspection, restoration where supported, a usable conversation alternative, fresh explicit
guidance, approval boundaries, uncertainty and failure recovery. This authorizes design work;
product and architecture choices remain proposed until human agreement. Existing no-replay,
secret-handling and request-scoped authorization requirements remain binding. No production
thread is resumed or altered as part of the design investigation.

The human subsequently chose: assess first, then human approval of continuation. The proposal
must enforce that sequence, while allowing questions and evidence discussion before write
authority is restored. Same-thread restoration details and other architecture choices remain
proposed pending design review and human agreement.

## 2026-10-18: Documentation and ongoing agent quality review

The human requested documentation throughout development and continuing agent quality review.
Require Technical Writer involvement for each development task, with User Documentation Writer
for changed user behaviour. Record documentation impact at intake, supply verified evidence
during implementation, and obtain writer closeout before declaring completion. Keep shared
status and decisions current, including failed checks, blockers and interruption handoffs.

Invoke Agent Evaluation at development checkpoints and before completion, independently from
product QA. Record sources, observed outcomes, corrections, handoff quality, documentation
coverage, findings, owners and retest evidence in docs/model-evaluation.md. Historical records
do not establish fresh verification; unavailable model/runtime usage and costs remain unknown.
Missing specialist review is a recorded gap, not a passed gate. This establishes task-triggered
delegation, not a scheduled or continuously running service. No paid comparative benchmarks,
model-policy changes, dashboard restart, deployment or publication are included.

## 2026-10-18: Team activity and delegation drill-in

The human requested per-member work on Team, including Chief of Staff delegation, and drill-in
from Overview Task activity to delegated activities and status. Reuse observed native activity
records, expose a field allowlist, and keep them separate from root-run counts and cost estimates.
Show direct/delegated history per role with project filtering and coordinating-task navigation;
show nested native parentage in task details only where recorded. Unknown historical parentage
must not be attributed to the Chief of Staff by inference. Child pending requests affect that
child's status; completion, interruption and connection loss remain event-derived.

Delegated labels remain generated role titles with coordinating-task context: native metadata
has no separate checked assignment-description field in this implementation. Raw delegated
prompts, reasoning and tool transcripts remain excluded under the existing retention policy.

## 2026-10-18: Inspect personal agent prompts

The human requested personal prompts in the Team view via a Details button. Display the exact
role instructions loaded by the dashboard in a read-only plain-text dialog. Retrieve only the
selected known role on demand after sensitive-content checks; withhold text if checking fails.
Keep prompts out of polled state and roster payloads. Explain that shared security and task
instructions are additional context, so the display is not a complete run transcript.

## 2026-10-16: Run the team in Codex

The human selected Codex and requested a new Git repository that keeps secrets out of Git
and documentation. The workspace already contained an empty repository without commits or
remotes, so initialise the team there rather than nesting another repository.

Initially use project-scoped custom agent definitions with inherited model selection and bound
concurrency to three child agents; actual session limits take precedence.

Use Gitleaks with complete staged-file scanning and pre-push history checks. Reject common
credential paths even if force-added. Keep secrets outside the project. Remote hosting,
server push protection, and product technology choices remain unresolved.

The human subsequently selected GitHub and will supply the account and repository name.
Keep this repository local until the destination and remote controls are configured.

An independent security review identified gaps in explicit-object pushes, tag annotations,
and unquoted credential assignments. The implementation was corrected and regression tests
added before the initial commit.

## 2026-10-16: Expand ownership and assign models

The human approved adding Technical Architect, Platform & Reliability Engineer and Agent
Evaluation Engineer. PM/UI explicitly own usability research; QA includes relevant accessibility,
performance and recovery checks.

Pin core engineering roles to GPT-6.1 Sol with Medium or High reasoning, documentation roles
to GPT-6 Luna, and an on-demand expert escalation profile to GPT-6 Astra / Low. Configure the
primary chat and otherwise unspecified subagents to Sol / Medium, retaining the concurrency cap.
The separate Astra profile is required because custom role model settings take precedence
over explicit spawn settings. This policy supersedes the initial inherited-model choice.

The human uses a Business or Enterprise workspace; the exact agreement is not confirmed.
Cost savings and task quality must be measured rather than assumed. Record evaluations using
docs/model-evaluation.md. No comparative model trials have been run yet.

## 2026-10-16: Build a live local development dashboard

The human selected multiple projects, local operation on this Mac, Python/SQLite/browser UI,
and live Codex integration. A manual ledger alone does not satisfy the requested first version.
After a supported-existing-session connection was not demonstrated, the human selected
dashboard-managed runs via a dedicated Codex App Server. Existing desktop chats are outside v1.

The app initializes the server without starting a model turn. A human Start run action supplies
the project, role and instruction. App Server events drive sanitized persistent projections.
No secret-store access, transcript-file reads or raw event logs are needed. Costs are unknown
until suitable observed usage/model/tier evidence allows a clearly labelled credit estimate;
estimates are never presented as verified Business/Enterprise charges.

V1 displays pending native approvals and allows decline or interruption. It does not grant
permissions from a generic sanitized summary. A future acceptance flow needs sufficient exact
review context and independent security review. Disconnect invalidates pending controls and
marks active work unknown, without replaying inference or approvals.

## 2026-10-16: Add manual file review and controlled Git publishing

The human requested read-only project-file inspection, Git status and a publish option, then
specified the public GitHub repository K55Toms/KT_Agent_Dev_and_Dash. The repository was created
empty and connected as origin. Repository metadata confirmed public visibility, secret scanning
and push protection enabled. No source code was pushed during repository creation.

File access is confined to registered Git working trees, nonignored safe text, no symlinks or
credential/runtime paths, and a successful fixed-policy secret scan before any preview. Git
publication uses explicit destination/branch/commit confirmation, rejects dirty or changed
snapshots, runs full secret checks and preserves normal hooks. No implicit stage/commit or force
push is included. Native Git authentication remains outside the dashboard.

## Personal identity and design exploration

The dashboard uses the supplied original silver-on-navy logo and the name Kristian’s Rebellion Builders. Three isolated browser previews at /designs explore Terminal Ops, Rebel Command and Hybrid Night Shift. Their tasks, usage and approvals are illustrative. Theme selection changes only the preview; the production theme awaits the human’s choice. Rebellion-inspired colors are a design interpretation.

The human selected Hybrid Night Shift for the live dashboard. Terminal Ops and Rebel Command
remain available through the appearance-only dashboard/config.toml setting, applied on page reload.

Graceful server shutdown drains bounded HTTP handlers before process exit so explicit publication
helpers retain timeout and cleanup guarantees. Independent synthetic success/timeout checks passed.

## Dashboard settings and repository creation

The human requested in-dashboard configuration for all supported config.toml preferences,
including name/logo/theme and GitHub account/visibility defaults. Private is the initial default
for new repositories; existing repositories retain their visibility and origin. Repository
creation is explicitly confirmed and separate from publishing commits. Uploaded logos remain
local runtime files outside Git; configuration contains only a validated local reference.

The human requested agent conversation after Settings: answer agent questions and send follow-up
guidance from dashboard-managed runs. Existing desktop session sync remains outside current scope.

## Managed conversations and Rebel crew

After Settings, the human requested agent question replies/follow-up guidance, a fictional named
team with themed portraits, observed last work and agent-to-agent logs. The human chose automatic
Chief of Staff recognition rather than human approval for each internal, nonmonetary award.
Visible complete messages are checked before display/persistence in private ignored SQLite;
reasoning and raw tool content remain excluded. Existing desktop-session sync remains unavailable.
Recognition has bounded evidence-backed issuance and no invented initial history or scheduler.

## Failed launches and CLI compatibility

The first human-started dashboard run failed before a native thread was registered. Its original
raw error was discarded, so its precise historical server response cannot be recovered. A fresh
thread-only reproduction isolated a project configuration parser rejection: desktop-specific
scalar entries under `[agents]` were interpreted as CLI agent definitions. The outdated CLI
catalogue advertised GPT-5 models that real execution rejected. Official current model docs
confirm GPT-5.5 and GPT-5.4 retirements for ChatGPT sign-in and the original GPT-6 IDs as valid
CLI choices. Retain the original approved profiles; the diagnostic fallback trials did not
establish a working replacement or comparative quality/cost result.

Failed activity must open task details with bounded, fixed-vocabulary launch checkpoints,
failure reason and next action. Raw protocol errors, stderr, tool output and reasoning remain
withheld. Historical missing diagnostics are labelled unavailable rather than reconstructed.
Ambiguous execution outcomes remain unknown and are never automatically replayed.

On 2026-10-18, the updated CLI 0.163.0 completed an isolated GPT-6.1 Sol health-check turn,
reported usage and created no project files. The named profile retains the original broad-read,
project-write boundary, explicitly disables command networking and routes approvals to the user.
The stronger restricted-read helper failed on this Mac; credential-read prohibitions remain
agent policy, not filesystem isolation. The original human instruction was not replayed.
Latest regression suite: 167 tests passed; independent targeted review: 56 tests passed.

## 2026-10-18: Human approval from the dashboard

The human requested an approval action after encountering the decline-only implementation.
Add a separate, complete-context review step for supported native command and file-change
requests. Acceptance must bind to the exact live request and reviewed contents, not a generic
summary or historical record. Review contents are ephemeral and checked before display and
acceptance; they are not stored in the runtime database, logs or conversation history.
No session-wide grants, remembered command rules or automatic decisions are included.
Applying backend changes requires a restart; an existing ephemeral pending request cannot be
transferred to a new App Server. Do not approve, replay or interrupt the human's pending work
as part of synthetic tests or the upgrade without the human's explicit choice.

Verification included an isolated native GPT-6.1 Sol request to run only `/usr/bin/true`:
complete-context review, one-request acceptance, native command execution and turn completion
all succeeded; no project files were created. The live pending human request remained untouched.
The installed native client marks local command requests with `environmentId: "local"` and
explicitly offers `accept`; the review preserves both values. Other environments, managed-network
batch prompts, interactive stdin, file-root/session grants and missing native acceptance choices
remain unavailable for grants. Independent review fixes cover uncertain-delivery replay,
conflicting RPC IDs, incomplete item context and approval expiry for child agents.

## Delivery lesson: incomplete approval journey

The first dashboard brief explicitly deferred acceptance and shipped decline/stop controls.
This was a scope and acceptance failure, not evidence that a particular named agent forgot
a button. The Chief of Staff owns the delivery decision. Strengthen Product Manager journey
definition, independent QA's positive end-to-end checks and the Chief of Staff's completion gate.
Compare the agreed brief with the original human outcome; do not silently substitute a narrower
implementation contract. The three role prompts and AGENTS.md now state this requirement.

The human authorized stopping the existing waiting run and restarting the dashboard. The
interrupt was acknowledged, active runs reached zero, and the updated dashboard reconnected.
The interrupted task's file edits were preserved and its instruction was not replayed. Final
checks: 191 Python tests, 12 UI tests, 14 TOML profiles parsed and 7 prompt endpoint tests passed.

## 2026-10-18: Resolve blocked approvals and choose project approval mode

The human requested a resolution path directly from a blocked approval, including chat guidance,
and a choice between approving once and accepting risk for future runs in the selected project.
Use an approval-scoped guidance action: queue checked guidance for the exact live turn before
declining the captured request. Guidance never grants permission by itself. Ambiguous delivery
must not cause automatic retries or execution replay.

Project approval modes belong in Settings and nonsecret `config.toml`, defaulting to manual.
Explicit automatic mode applies to eligible future callbacks from that project, with complete
context validation and scanning. It does not change sandbox defaults or replace separate release
authorization rules. Originating-project association does not confine command effects to project
files. Revoke through Settings; already-delivered decisions cannot be recalled.

Compatibility inspection confirmed native subcommand callbacks may differ from their cached
parent command and that some optional text and file diffs may legally be empty. The live waiting
request's exact rejection cause remains unverified. An isolated native compound-command approval
round trip completed without creating files; this run did not emit a subcommand callback, so
subcommand compatibility also requires schema-based regression coverage.

The native recovery probe exposed a separate protocol constraint: its offered decisions included
Cancel but omitted a decline that continues the turn. The explicit cancel flow therefore sends
checked guidance, cancels only the captured request, waits for observed interruption and requires
a separate human follow-up action. A live isolated test verified this full cancel/interruption/
follow-up/new approval/completion sequence without creating project files. It does not establish
the original production review failure's exact cause.

Use verified team-role mappings for conversation names. Keep runtime identifiers as secondary
details and show unknown agents honestly rather than guessing a team member.

## 2026-10-18: Native delegation and explicit sensitive-request review

The human authorized correcting missing dashboard delegation. A no-inference isolated check
reproduced a missing-history failure when forking an ephemeral source. Managed parents now use
verified persistent native history. All 14 configured roles are explicitly registered for every
managed project with checked private snapshots that repeat the shared security instructions.
The installed runtime emits modern `subAgentActivity` items; ignoring them prevented child
ownership and approval routing. Track lineage from owned-parent native events, then resolve known
role metadata with bounded metadata-only requests. Never read stored native conversations.

A real isolated run started the configured Backend Developer from the Chief of Staff, routed
and accepted the child's exact harmless command, observed child and parent completion, and
created no project files. This verifies the native delegation and child-approval path; mocked
event tests remain separate evidence. Native history is a separate CLI-managed retention store,
outside dashboard scanning. No old task is automatically resumed, migrated or replayed.

The human explicitly selected revealing exact sensitive requests locally and approving once.
Keep the scanner and Git controls intact. Permit only an explicit local reveal followed by a
separate human decision on unchanged complete live context; never extend this exception to
automatic project policies. Distinguish findings using a dedicated scanner findings exit code;
scanner failures cannot authorize reveal or acceptance. Keep revealed bytes out of dashboard
logs, SQLite, documentation and screenshots. Codex may retain underlying native history.
The local dashboard trusts same-user processes; this feature does not add administrator login.

### 2026-10-25: local commit of reviewed recovery and audit changes

The human requested a local commit of the cumulative development changes. Final integrated
verification passed 487 Python and 86 UI tests. The audit update was applied locally with
existing task counts preserved and no active work or decisions. The metadata-only check
of an existing unknown task returned unavailable coverage; execution remains blocked.
Commit records the reviewed source and this unresolved live-validation item, without
asserting complete recovery, authorizing native continuation or authorizing a push.
Backend and Platform retain ownership of metadata diagnosis and a bounded live retest.

### 2026-10-25: resolve unloaded-thread recovery metadata

The human requested a Ponytail code fix. A reviewed diagnostic-only update confirmed that
the loaded-thread-only background-terminal RPC rejected the unloaded historical root.
Recovery now reads fresh root/descendant identities and goals and validates a complete current
loaded inventory on the same observed startup connection. It does not resume a thread to
inspect it. Unsupported or failed reads preserve validated partial evidence and fixed error
labels; no raw upstream error strings are recorded. Existing boot-fence, exclusive-owner,
external-activity and separate human continuation approval checks remain mandatory.

After application, the original task's live metadata-only check returned complete coverage
for 38 descendants with no unresolved current children. Historical child/turn uncertainty and
the required boot fence still block continuation. This resolves the metadata compatibility
failure, not historical outcomes or native continuation. No OS restart or inference occurred.

### 2026-10-25: pilot Ponytail Full in implementation roles

The human approved Ponytail Full defaults for Backend and Frontend, with independent Code
Quality Review, explicit Chief of Staff handoffs and Agent Evaluation follow-up. AGENTS.md
identifies the maintained installed skill; profiles reference the pilot rather than copy its
full text or hardcode a cache version. The pilot preserves complete user journeys, security,
accessibility, required checks, documentation and approval boundaries. No new role, model,
dependency, automatic execution or benchmark batch is introduced. Static propagation will be
verified; future behaviour, savings and broader rollout require observed task evidence.

Pilot application evidence: the idle dashboard was reloaded and its five checked role-prompt
endpoints matched the new profiles. Existing task/decision counts were preserved. This verifies
configuration propagation, not future model behaviour or measured savings.

### 2026-10-25: enforce Ponytail inclusion and delivery evidence in code

The human approved both proposed controls. Before managed dispatch the dashboard validates
the installed Ponytail Full 5.3.2 skill against the reviewed SHA-256 pin, scans its bounded
bytes, injects it into Backend/Frontend parent and registered delegated profiles, and records
policy/role fingerprints. Missing or altered sources/profiles block new work. Browser callers
cannot enroll a policy path or digest. Unknown native roles block delivery verification; the
dashboard does not claim it can intercept every native internal spawn before execution.

Delivery readiness is separate from native turn completion. The owner approves exact project
check commands, explicitly starts a QA task through the existing native sandbox/approval flow,
and receives evidence only from that owned task's current successful command lifecycle. A
separate registered reviewer produces a complete checked report; a fresh owner decision binds
that report to current code, policy, plan and check evidence. No host shell test runner, automatic
native approval, publication or model-judgment guarantee is introduced.

Snapshots cover bounded safe Git-visible paths and bytes, including file modes, opaque assets,
HEAD and root identity, with post-scan revalidation. Tracked files cannot disappear through an
ignore rule. Ignored untracked/runtime files and execution environments are outside that code
snapshot; hashing an image is not a visual or complete secret review. Old tasks remain explicitly
unverified/unenforced. A coordinating task with registered implementation children is eligible;
unattributed children cannot earn readiness.

A reviewed policy update invalidates old delivery evidence. New checks and independent review
may qualify the existing code under the new policy without replaying implementation; original
execution policy metadata remains historical. Lost acknowledgements reconcile durable identities
separately from current readiness. Explicit retries retain the original request/UUID, version or
single-use receipt; no retry is automatic. A consumed failed decision receipt requires a fresh
review after repair, rather than reviving old acceptance authority.

## 2026-11-02: owner rulings after Plan 4 live acceptance

- **Default wait is 5 minutes (300 s), hook timeout 360 s.** The owner chose this over the 900 s built earlier; the live
  run showed about 305 s under a 960 s hook timeout. Range 60 to 3600 is unchanged; anything above about 5 minutes is
  unverified.
- **Bash in Automatic mode is accepted unconfined.** Automatic mode accepts any `Bash` command that passes the secret scan;
  only Write, Edit and NotebookEdit are confined to the project folder (never `.git`, `.claude`, `.local`). Cost if wrong:
  an automatic project can run any command the model chooses, and a command could change user settings that later runs load.
- **API secret.** The owner asked for the dashboard API's missing per-client secret (finding F2) to be addressed; it is a
  separate piece of work from Plan 4 and is designed before it is built.
- **Plan 4 is pushed and opened as a pull request against `main`** at the owner's instruction.

## 2026-11-02: dashboard key (finding F2), design A

The owner chose design A for finding F2 (the dashboard API had no per-client secret, so any local
process, including an approved Bash call from a managed Claude or Codex run, could call review,
respond or accept). It covers both providers.

- `dashboard.server.main()` makes a key with `secrets.token_urlsafe(32)` at each start and keeps it
  in memory only. It is printed once, as the launch URL `http://127.0.0.1:<port>/#key=<key>`.
- Every request except GET of the page shell needs header `X-Dashboard-Key` (compared with
  `hmac.compare_digest`); otherwise 403 `Dashboard key required`, before the body is read or state
  is touched. Host and Origin checks stay. The hook receiver keeps its own token.
- The page reads the key from the URL fragment, keeps it in `sessionStorage` for the tab, strips it
  from the address bar and sends it on every API call, including the uploaded logo (blob URL).
- Fail closed: `make_server` has no default key; `None` (off) is used only by the test harness.
- Why the alternative (here called design B: the server hands the key to the page itself, as a
  cookie or embedded in the served HTML, as the security review suggested) was rejected: the page
  shell is served to any local process that can reach the port, so the same processes F2 is about
  could load the page and read the key. With design A the key exists only in the launch terminal
  and the owner's tab. The brief did not describe design B in detail; this reading is recorded
  for the owner to confirm.
- Cost: bookmarks and old URLs stop working after each restart; whoever holds the printed URL
  (terminal scrollback) can act as the owner; a same-user process that can read the terminal, the
  browser profile or the dashboard's memory, and code running inside the page, are out of scope.

## 2026-11-04: Claude dashboard Plan 5, conversations, team, outputs, deletion and delivery readiness

Plan 5 (slice 2b) is built on branch `slice-2b` (local, unpushed). Everything below is backed by fake-binary and unit
tests; no browser check or live run is recorded in this entry.

**Owner answers (2026-11-04).**
1. Subagent lineage: yes. A subagent whose type matches a registered role is a delegate under that role; any other is
   shown as an unnamed delegate under its parent task's role.
2. Outputs: owner-attached only, unless a safe workaround exists. No workaround ships (see rulings).
3. Rewards: removed for now. Read as Claude deployment only: a Claude team view has no coins, Agent of the Week or
   commendations; Codex rewards and `issue_award` are unchanged.
4. Ponytail: a Claude run can reach `ready` when every other gate passes. The Ponytail row reads "Not applicable for
   Claude" and is never counted as passed.
5. Live acceptance: one live run, alias `haiku`, count 1, on a scratch project, after a final go in chat. Not run yet.

**Rulings made while building** (cost if wrong in brackets).
- A route-level delivery refusal for a task with no policy stamp is 409 `delivery_not_started`; "not available for this
  provider" comes only from the start path. [Tests would assert the wrong layer.]
- A finished delegate with no role (a built-in subagent type) does not block delivery; an active or unknown one does, and
  any omitted delegate (more than 64) makes delivery unverified. [A run that used a built-in subagent would never be
  deliverable, or an omitted named-role child such as `qa_engineer` would be missed.]
- Unnamed delegates are listed under the parent task's role in the team view, not left out.
- Claude checks are stricter than Codex: only a plain foreground `Bash` call with exactly the approved command and a
  non-error result passes; any other Bash call in the run, a background call or a background result fails the checks,
  because Claude reports no working directory per command. [A model that runs another command first gets
  `checks_failed`.]
- A review that lost a reply cannot be accepted. A dropped reply (cut at a bound, over the line cap or 1 MiB, runner
  overflow, missing counter) gives `unverified` with `complete_review_messages_required`; a withheld reply (refused by
  the sensitive-content scan) fails the operation and gives `changes_requested` with `independent_review_required`.
  No decision action is offered either way.
- Final review rulings (commit 61be10f): a delegate's stop must have been reported in the stream (`stop_observed`);
  this fails closed until the live run shows how the real CLI reports a stop. Delivery runs are never eligible for
  automatic approval. A checks run fails on any main-session tool other than `Bash`, `Read`, `Grep` or `Glob`, on any
  child, and on any project change after it exits. The `Write`, `Edit` and `NotebookEdit` tools were not removed from a checks runner at that time (since 2026-11-11 they are: see the entry at the end of this file).
- The outputs suggestion workaround (offer `Write`/`Edit` paths from the stream in the Outputs dialog, owner still
  confirms) was deferred until a live `Write`/`Edit` event shape was captured; it ships since 2026-11-11 (see the entry at the end of this file). Owner-attached outputs stay the only way to attach.
- A Claude deployment ignores an injected non-Claude policy so Claude never loads Ponytail.

**Owner decision 2026-11-11 (was open): deleting a `claude_possibly_running` task: warning only, no tombstone.** A task flagged "may still be running" after a dashboard
restart holds its project. Deleting it (explicit confirmation and current version required) drops that hold and the
dashboard sends no signal to the old process, so a new run can start in the project while the old process is still
working. Options: (a) add a warning to the delete dialog for a possibly-running task; (b) keep a tombstone hold on the
project after the delete until the old process is gone. The behaviour is pinned by `tests/test_claude_task_deletion.py`. Resolved on 2026-11-11: option (a) as built, the delete dialog warns, nothing else changes. Cost accepted by the owner: two processes can work in one project after a deliberate delete.

## 2026-11-11 Claude independent review: task text passed as data

Live proof (docs/superpowers/evidence/2026-11-10-live-proof.md, finding 2): the Claude review prompt ended with
"Task objective:" and the raw last-turn instruction. The reviewer read those steps as its own and reported that it would not
perform them, so no review was produced, yet the dashboard offered **Accept review**. Decided and built (bounded change,
Claude deployments only): the instruction now says the text between `<<<TASK STATEMENT` and `TASK STATEMENT>>>` is a
statement given to a different agent, to be judged and not carried out; task text containing a marker is refused (409,
the existing "guidance unavailable" message). The checks prompt, the Codex prompts and the choice of which messages count as
the task text are unchanged. Evidence: fake-binary tests (`tests/test_claude_delivery.py`) and one live direct `haiku` review run on the same task text (reviewed correctly; not through the dashboard). Open
follow-ups: the dashboard cannot tell a real review from a refusal to review (no verdict line is checked); the Codex review
prompt has the same pasted-text shape and was not touched or tested live.

## 2026-11-11 Terminal sessions: S11 partly run (owner-attended)

Evidence: docs/superpowers/spikes/S11-observed-replies.md and docs/superpowers/evidence/2026-11-10-live-proof.md (Part 3). Claude Code
2.1.322, `haiku`, manual permission mode, one run per case; terminal text pasted by the owner, page driven by the AI controller.
This entry supersedes the "not live-tested" wording of the 2026-11-06 entry for the items below; that entry is kept as history.

- **`NO_DECISION_MODE` stays `empty_object`.** Case A1: after the `{}` reply the terminal prompt stayed up 18 s and nothing ran
  before the owner's Yes. The `hold` fallback is not needed. (The owner's earlier ruling was to keep `{}` until S11.)
- **Dashboard down:** with a stub switched off, Claude Code's own prompt stayed until the owner answered (owner-reported, case D4).
  Each hook event shows a visible, non-blocking `ECONNREFUSED` error line. The fixed-port exposure decision is unchanged.
- **`settings.local.json`:** hooks in it fired, including in a session already running (case D5). Git ignored the file only through
  the owner's global ignore file.
- **Allow and Deny:** from the real page both closed the terminal prompt and were honoured; the Deny reason text reaches the terminal.
  The card showed "ran after your Allow" and "no run seen"; a Yes in the terminal showed "Answered in the terminal (inferred): ran".
- **A terminal No sends no later event.** The card stays "closed: answered elsewhere or timed out" until `SessionEnd`, then reads "no run
  seen". The bracketed rework note about the turn's `Stop` in the 2026-11-06 entry is answered: no `Stop` follows a No.
- **New fact:** `PermissionRequest` and `PostToolUse` both carry a `prompt_id`; `PostToolUse` carries `tool_use_id` and `tool_input`.
  The matching rule was not changed.
- **Still open:** cases A2, A3, A4, C1, C2, C4, D1, D2, D3 not run; the page's prompt behaviour with the dashboard down not reported;
  "subagent activity seen" shown for a session where no subagent was asked for, unexplained.

## 2026-11-11 Plan 5 leftovers: output suggestions, checks runner without write tools, subtitle, deletion decision

Owner answers (2026-11-09): deleting a possibly-running task stays a warning only; suggest outputs from `Write` and `Edit`; start the
checks runner without the write tools; drop the "celebrate" part of the Team subtitle where rewards are off. Plan:
docs/superpowers/plans/2026-11-09-plan5-leftovers.md (Task 0 security review and rulings at its end).

- **Deleting a `claude_possibly_running` task:** closed as warning only (see the 2026-11-04 entry). No code change.
- **Output suggestions (Claude only):** the stream parser keeps the tool name and `file_path` of main-session `Write` and `Edit` calls in
  its state only (at most 32, never contents, never in an event). After the run ends, outside the dashboard lock, the paths become
  project-relative by string logic, are checked as an attach would be (descriptors without symlinks, regular single-link file, size,
  Git-visible, path-only secret scan in one batch, 15 s budget, at most 8) and are stored under the task's `claude` record; the snapshot
  shows `output_suggestions`. The owner still confirms each attach; nothing is attached automatically. `Write` and `Edit` shapes were seen
  live (one run each, 2.1.322).
- **Checks runner:** a delivery checks run starts with `--disallowedTools Write,Edit,NotebookEdit` (last in argv, a fixed set, checks runs
  only). The guard that fails the checks on any other tool and the project-change check after exit stay. Seen live once in a direct CLI run
  (the tools were absent from the tool list); not tested inside a dashboard-managed run.
- **Team subtitle:** "Meet the agents and review their latest recorded work." when rewards are off (a Claude deployment, known from the
  provider before the team answer arrives); the Codex text is unchanged.
- Evidence: unit, fake-binary and node tests; a live run of the new code through the dashboard was not made.

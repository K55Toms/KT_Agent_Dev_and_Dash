# Local dashboard operations

This first version runs on this Mac with Python 3.11 or newer, SQLite from Python's standard
library, and the installed Codex CLI. No cloud deployment or Windows support is provided.
The dashboard starts and manages its own Codex App Server process. It does not watch existing
Codex desktop chats, discover projects by scanning the machine, or run agents continuously.
The App Server handshake and an isolated GPT-6.1 Sol inference turn have been verified on CLI
0.163.0. The turn completed with observed usage and no project files created. This does not
verify account access to every configured model, acceptance of development work or billed cost.

## Start and sign in

1. Ensure `python3` and `codex` are available on your terminal's PATH. Install or update these
   through your organisation's approved process; the launcher does not install software.
2. If Codex requires sign-in, run `codex login` separately and complete the browser sign-in.
   Use the intended Business or Enterprise workspace and follow its access policies. Codex
   manages its authentication outside this repository. Never copy authentication files,
   paste credentials into this dashboard, or save credentials in project files or documentation.
3. From this repository, run:

   ```sh
   sh scripts/run_dashboard.sh codex
   ```

   The single argument chooses the provider for this deployment and must be exactly `codex` or
   `claude`. Any other value, including none, prints
   `Usage: sh scripts/run_dashboard.sh codex|claude` and exits with status 2 before any other
   check. Nothing defaults to Codex.

   **Changed start-up command.** Earlier versions took no argument (`sh scripts/run_dashboard.sh`).
   That command now exits with status 2 and starts nothing. Add `codex` to get the previous
   behaviour. A bookmark, alias or script that ran the launcher without an argument must be
   updated.

   Only `codex` requires the Codex CLI on PATH; only `claude` requires Claude Code (`claude`) on
   PATH, else the launcher prints "Claude Code CLI is required on PATH." and exits 1. A `claude`
   deployment starts no Codex process. See [Claude Code setup](claude-code-setup.md). A server started directly
   (`python3 -m dashboard.server`) without a valid `--provider` runs with no provider: the
   indicator reads "No provider configured" and **Start run** is disabled. The provider cannot be
   changed while the dashboard runs; stop it and start it again with the other argument.

   **What a `claude` deployment does today.** A `claude` deployment runs your tasks with Claude Code
   (the `claude` CLI) instead of Codex. Checked by unit tests and a fake-binary journey test
   (`tests/test_claude_journey.py`) that replays recorded stream fixtures through the real HTTP
   handler; the approve, decline and stop journeys were also run live once each through the dashboard with the real `claude` (see
   [the evidence](superpowers/evidence/2026-10-28-managed-run-loop.md) and, for approvals,
   [the approvals evidence](superpowers/evidence/2026-11-01-managed-approvals.md)).

   - Readiness: the dashboard runs `claude --version` once at start. A version shows "Claude
     connected" with "Claude Code <version> (login not verified)"; the login is not checked. A
     missing binary or no version disables **Start run** with a fixed reason; restart to probe again.
   - Start run: starts a `claude -p` process in the project directory with the chosen role as the
     main session and the project's instructions appended through `--append-system-prompt` (the
     dashboard's security baseline plus the project's `CLAUDE.md`, with its `@AGENTS.md` import
     expanded by the dashboard). The prompt cannot start with `-` or contain NUL. The usual limits
     (three runs at once, project overlap checks) apply. Delivery checks and readiness work for Claude runs without the Ponytail gate (see [Delivery checks and readiness](#delivery-checks-and-readiness)).
   - Environment: the child process receives only `PATH`, `HOME`, `USER`, `LANG`, `TMPDIR`, `SHELL`,
     `TERM` and `LC_*` variables. Everything else, including `ANTHROPIC_*`, `CLAUDE_CODE_*` and cloud
     provider variables, is not passed, so runs use the subscription login (spike S9: a run with
     this allow-list logged in).
   - Status, usage and cost: the run goes queued, running, then completed, failed, interrupted or
     unknown. Usage shows five token counters. Cost is "Estimated USD (list price)" taken from
     Claude Code's own result, not a billed amount.
   - Approvals and denied calls: every run gets its own approval hook, so a tool call that needs
     permission appears on the Approvals page and waits for your answer (see
     [Claude tool-call approvals](#claude-tool-call-approvals) below). A call you decline, or that is
     not answered in time, is denied and the run continues without it; the task shows a count, up to
     20 tool names and the notice "Some tool calls were denied because they were not approved: by you, by the approval wait running out, or because the run was stopped." Caveat: runs use
     `--setting-sources user`, so your own user-level Claude Code allow rules and hooks apply (an
     accepted design decision, see
     [decisions](decisions.md#2026-10-28-and-2026-10-29--claude-dashboard-plan-3-managed-run-loop-decisions-rulings-and-deviations);
     not tested); a call such an allow rule covers can run without reaching the dashboard. There are no
     question prompts and no guidance into a running turn.
   - Stop: **Stop** sends SIGINT to the process group, waits 10 s, then SIGTERM, waits 5 s, then
     SIGKILL. The run is recorded `interrupted` from the dashboard's own signal, whatever the exit
     code. Closing the dashboard stops live runs the same way (waiting up to 20 s) and records them
     `interrupted`.
   - Follow-up: sending a message to a finished (completed, failed, interrupted or unknown) run
     that has a session resumes it with `--resume`; usage and cost totals add. A running run refuses
     it (the dashboard answers a generic "request rejected" 400). Limits: 50 invocations and 200 turns per
     run, prompts up to 16000 characters; a run stopped for its permission mode cannot be continued.
   - A run whose first event reports a permission mode other than `default` is stopped and marked
     failed; the requests it made are denied. A hook request that reports a mode other than `default`, or a
     different session than the run's own, is denied and stops the run the same way.
   - Restart: a run that was active when the dashboard stopped becomes `unknown`, keeps its session
     (so a follow-up can continue it) and gets no recovery hold. If the stored process id still
     shows the same start time, the task is flagged "may still be running", follow-ups are refused
     while that process exists, and only while flagged does the task hold its project against new
     runs. The dashboard never signals an old process.
   - Instructions and follow-ups are passed to Claude Code as a command-line argument and can be seen by
     other users of this Mac with `ps` while a run lasts. Do not put secrets in instructions.
   - Login: readiness does not check the login; a run can fail after it starts with `claude_not_logged_in`.
     Sign in through the Claude Code CLI outside the dashboard.
   - Deleting a run removes the dashboard record with its messages, outputs, delegate rows, approvals and
    delivery operations, and frees its session id and its project hold; Claude Code keeps its own local session
    history. A run that is live, waiting for approval or has an active delegate cannot be deleted until it is
    stopped. Caution (open owner decision, see [decisions](decisions.md)): a task flagged "may still be running"
    after a dashboard restart holds its project; deleting it drops that hold and the dashboard never signals the
    old process, so a new run in the project can start while the old process is still working.
  - Conversation view (fake-binary tests only): the conversation panel shows your instruction and follow-ups
    and, in order, the run's own replies (the model's text blocks of the main session). Reply text is checked
    like other conversation text: control characters other than newline and tab are removed, a reply over 32,000
    characters is cut with a "[Reply truncated]" marker, and a reply that fails the sensitive-content checks is
    replaced by the fixed notice "Reply withheld: sensitive-content checks did not pass". The dashboard copies no
    thinking, tool input or results, hook output or subagent text (the model's own reply may quote them). Control
    characters, including hidden direction overrides, are removed.
  - Delegates (fake-binary tests only): when the run launches a subagent, the dashboard records one delegated
    row per subagent (up to 64 per run; further ones are counted as omitted and not listed). A subagent whose
    type matches a registered role is listed under that role; any other is an "Unnamed delegate": a helper whose type is not one of your configured roles,
    shown under the role of the run that started it. Its own text is never recorded. Whether the real CLI marks subagent
    requests with the parent's session id is not checked live.
  - Team view (fake-binary tests only): the team panel lists Claude tasks under their roles with the last
    reply of the latest turn as a model-reported summary (up to 500 characters; it is the model's own words,
    not verified). A Claude deployment has no coins, Agent of the Week or commendations area.
  - Outputs (fake-binary tests only): to attach an output, open the completed Claude run, choose **Attach output**,
    pick a project file and confirm. The dashboard checks the path and content as for Codex. The run cannot attach files
    itself, and no list of files the run wrote is offered. If the run is not completed (running, failed,
    interrupted or unknown) the attach control is not offered and a request is refused; an output belongs to the
    turn it was attached to, so after a follow-up starts a new turn it is not listed and must be attached again.
  - Delivery readiness works for Claude runs without the Ponytail gate (fake-binary tests only; see
    [Delivery checks and readiness](#delivery-checks-and-readiness)). The Ponytail row reads "Not applicable
    for Claude" and is never counted as passed.
  - Not available for Claude runs: plan steps, recovery and approval alternatives (Codex-only routes answer
    HTTP 409 "not available for this provider"). Some Codex wording remains in guidance text that a Claude run
    cannot reach. The Claude conversation, team, outputs and delivery panels have not been checked in a
    browser or in a live run.

   One deployment serves one provider. Runs recorded under the other provider stay in the
   database, but acting on them (message, interrupt, approvals and their reviews, questions, delivery checks,
   reviews and review decisions, recovery actions) is refused with HTTP 409 "recorded under a different provider" and
   changes nothing. Projects stay visible and usable in either deployment.

4. When the server is ready it prints one line, `Dashboard: http://127.0.0.1:8765/#key=<key>`.
   Open that exact URL (see [Dashboard key](#dashboard-key)). Opening `http://127.0.0.1:8765/`
   without the key shows "Open the dashboard with the URL printed when it started." Check the
   connection indicator before starting work. A reachable page alone does not prove that the
   App Server handshake succeeded or that your account can access a selected model.
5. Register each existing local project directory explicitly. Review its instructions, files,
   and intended changes before selecting a role and starting a run.

The launcher uses a fixed local port, checks Python's version and (for `codex` only) the Codex CLI's availability, and sets
restrictive permissions for newly created files. It does not change user configuration,
sign in, start an inference turn, or automatically open a browser. Opening the dashboard and
connecting App Server do not themselves start a model run. **Start run** explicitly starts
work that can consume workspace usage and modify files in the selected project, subject to
Codex sandbox and approval controls.

The managed profile permits writes only within the selected project, with command networking
disabled and approval requests routed to the human. Filesystem reads outside the project remain permitted,
matching the original workspace-write read boundary. Instructions prohibit
credential reads; this is not filesystem isolation of secret stores. The restricted-read helper
failed to initialize on this Mac, so this version does not claim that stronger read boundary.

There are no dashboard environment variables to configure. The provider is chosen only by the
launcher argument, which the launcher passes to the server as `--provider`; a server started
without exactly `codex` or `claude` there runs with no provider. The listener is fixed to
`127.0.0.1:8765`; the SQLite database is created under `.local/` at startup with owner-only
permissions. Keep the launch terminal open. A connection failure is retried by the dashboard;
check the connection indicator before starting a run. Starting a run requires the App Server
connection and a registered project. At most three runs can be active at once, and active runs
cannot use registered project directories whose paths overlap (including parent and child
directories).

The default browser sign-in is documented in [OpenAI's CLI reference](https://learn.chatgpt.com/docs/cli/reference)
and was checked against the installed `codex login --help` on 16 October 2026. CLI behaviour
and workspace access policies can change; recheck the installed help after upgrades. No
credential-store contents are required to operate or diagnose this dashboard.

### Dashboard key

Each start of the dashboard makes a new random key and prints it once, inside the launch URL
`http://127.0.0.1:8765/#key=<key>`. The key is kept in the server's memory only; it is not saved
anywhere. Every API request must carry it, so a local program that can reach the port but does not
have the URL (for example a command run by a managed Claude or Codex run) gets HTTP 403
`Dashboard key required` and changes nothing.

- Open the printed URL. The page keeps the key for that browser tab and removes it from the
  address bar (the page replaces the current history entry; the original entry in your browser's history
  may still contain it, which was not tested). Reloading the
  tab keeps working. The Design previews link in the same tab keeps working too.
- A new tab, a bookmark or a typed `http://127.0.0.1:8765/` has no key: the page shows "Open
  the dashboard with the URL printed when it started." Copy the URL from the launch terminal.
- Bookmarks of the dashboard no longer open a working dashboard on their own, and URLs from an
  earlier start stop working after a restart, because each start makes a new key.
- If the browser blocks site storage, the key lives only in the open page; a reload then needs
  the printed URL again.

Residual risk: whoever holds the printed URL can act as you, and it stays in the launch
terminal's scrollback. A process running as your user that can read the terminal, the browser
profile or the dashboard's memory is outside what the key protects against. That includes an unsandboxed `Bash`
command you approved for a managed run, or one that Automatic mode approved: the key stops a run from calling the API
directly, not from reading those places, and the key is no
defence against code running inside the dashboard page. Clear the terminal scrollback if
others can see it.

## Assessment handoff

Assessment handoff uses the dashboard to prepare a checked text packet and record a human-reviewed
reply. The user carries the packet to an existing approved chat and brings the reply back. The
dashboard does not sign in to that chat, send or observe messages, or verify which account, model,
tools or usage produced the reply. This path needs no OAuth sign-in, API key or API billing. It
does not create a Codex task or turn.

1. Open the origin task's **Recovery** view. Preparation and reply review can use checked stored
evidence even when Codex is offline or the registered project folder is missing or replaced. The UI
records those gaps; it does not inspect replacement files or clear activity holds.
2. Select up to 20 available messages and enter a fresh question (up to 12,000 characters). Choose
**Prepare checked handoff packet**. Read the complete preview and confirm it contains only relevant
checked evidence and coverage gaps.
3. Choose **Copy checked packet** and paste it yourself into an existing approved chat. If clipboard
access fails, select and copy the displayed plain text manually. The dashboard does not open the
chat, send the packet or know whether it was delivered.
4. Paste the returned assessment into **Preview returned assessment**. The dashboard scans the
complete text before storing or displaying it and binds the preview to the packet. Review its
content and the label **Human-supplied external assessment; source, model, tools and usage
unverified.** Script-looking text and links remain plain text; they are not executed or followed.
5. Choose **Accept reviewed assessment** only after reviewing the exact packet and reply. This
records your local decision that the reply may satisfy the assessment prerequisite. It does not
accept a proposed development plan, clear activity, grant native permissions or continue work.
6. If a plan becomes available, inspect it and use the separate **Review continuation** and
**Approve and continue development** decisions only when all native, project identity, ownership,
activity and role gates pass. The old task is never resumed or replayed.

If an action's delivery is uncertain, the dashboard retains its exact request and edited drafts.
Choose **Reconcile previous handoff action** to check that same request. Do not resubmit it or
start another handoff action until its outcome is known; a conflicting or stale request must be
reviewed against refreshed recovery state.

The packet is limited to 49,152 UTF-8 bytes and is rejected without truncation if it is too large.
The pasted question is limited to 12,000 characters and each returned response to 16,000. Scanner
failure blocks preview or acceptance and retains existing history. A material change to task,
message, project binding or checked activity marks a packet stale. Refreshing the view, restarting
the dashboard or transferring a checked hold alone does not. A stale reply can be read as history
but cannot be newly imported or accepted; prepare a new round to assess changed evidence.

The GET preview's acceptance receipt is single-use and lasts 60 seconds; re-open the preview to
renew it. A dashboard restart clears receipts but retains packet, response and acceptance records.
An accepted current response may remain reviewable after restart; continuation still requires fresh
native checks and a new explicit decision. A new packet round or replacement response revokes any
older acceptance and plan. Limits are 8 rounds per origin, 128 handoffs total, 16 responses per
handoff and 64 idempotency operations per handoff. Records are retained without silent eviction;
when capacity is reached, the dashboard returns a safe error instead of discarding a record.
Recovery polling restores focus to the previously focused control and preserves text selection.
When a check, receipt or snapshot is stale, its actions stay disabled until the current state is
refreshed; focus restoration never preserves old authority.

The optional direct ChatGPT OAuth assessment route is separate. It is not required for handoff and
does not read, copy or alter Codex CLI credentials. It supports one saved OAuth registration, with
reauthorization for the same account and client; there is no account switching or add-account UI.
Its access and refresh tokens are held in process memory and lost when the dashboard exits. Sign-out
attempts provider revocation, but an unconfirmed result does not prove provider-side revocation.
The user's account/workspace eligibility has not been established here. No API-key fallback is
implemented.

If the optional OAuth feature is needed, provision its pinned dependency from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: -r requirements.txt
```

The launcher selects `.venv/bin/python` when present, otherwise `python3`; it does not install
dependencies. Missing PyJWT reports `dependency_unavailable`; install the pinned requirements in
`.venv` and restart through the normal launcher. Current pins are PyJWT 2.15.1, cryptography
50.0.2, cffi 2.1.1 and pycparser 3.12. No dashboard environment variables are defined for either
assessment route.

Real external-chat source/model/tool/usage provenance and real native continuation have not been
verified. An earlier live recovery inspection found 20 descendants against that implementation's
16-descendant bound; an old `interrupted` status did not prove process or external activity had
stopped. The 16-descendant bound is historical, not the current source limit. Current source pages
metadata up to 8 pages of 100 rows (512 total rows), deduplicates at most 256 descendants, caps
cursors at 4,096 characters and shares a 12-second deadline across root and child checks. Reaching
a limit, missing a page, or failing identity/status/goal/background checks leaves coverage
incomplete and execution clearance unverified. The earlier observation remains evidence about that
task; the larger scan bound alone does not establish it is safe. A sampled empty startup inventory
also does not prove that descendants or remote effects stopped.

The App Server documents `thread/backgroundTerminals/list` as a loaded-thread-only method. When a
recovery check finds a thread in `notLoaded` status, it checks that thread's goal and uses a fresh,
complete loaded-thread inventory from the same connection to verify that the thread is currently
not loaded. The recovery record labels this `current_loaded_inventory: current_not_loaded`. This
is a current-session observation only; it does not prove the absence of remote activity or satisfy
the separate boot-fence, ownership, external-activity and historical-turn checks. If the loaded
inventory is incomplete, stale or conflicting, or another metadata request fails, the check keeps
any already collected root/child observations, records fixed diagnostic codes and leaves execution
clearance unverified. See the [App Server method contract](https://learn.chatgpt.com/docs/app-server)
for the loaded-thread restriction on background-terminal listing.

Earlier handoff validation reported 458 passing Python tests, 78 UI tests and 14 independent QA
acceptance checks with the real scanner and synthetic native fixtures. Those results cover the
handoff implementation at that time. The earlier audit-remediation stage reported 114 passing
security checks, 487 passing Python tests and 86 passing UI tests; those counts predate the current
loaded-thread metadata fix. For the current fix, the author reported 82 passing tests, security
reported 126 passing checks plus 7 probes, and code review reported 104 passing checks plus 2 probes.
QA first reported 45 checks including 10 new cases; after correcting an old root-read fixture to
assert exact root identity and the expected 25 children, an independent QA retest passed 21 checks.
The initial 503-test full-suite run failed because that fixture lacked root-read data. After the
fixture correction, the full Python suite passed 504 tests in 109.912 seconds. The fixture now checks
exact root identity and the expected child count; negative checks were retained. These test scopes
overlap and are not additive. A synthetic browser fixture verified a completed parent remains completed with one
unresolved child and recovery available, and restored focus after a 4.1-second poll. These checks do
not establish live native continuation. No external chat or model call was made. The remediation
source was applied locally by graceful restart on 25 October 2026; the service reconnected with 10
tasks, including two unknown, zero active runs and zero pending decisions. An earlier live check
failed when background-terminal listing was attempted on an unloaded thread, preserving partial
child evidence. After the fix, a live metadata-only check completed in about 0.2 seconds with
coverage complete, 38 children, zero unresolved children, and current-not-loaded inventory
observations. It still reported `boot_fence_required`, `historical_descendant_unresolved` and
`unreconciled_turn`, so execution clearance remains unverified and continuation unavailable. No
task was resumed, no inference was run, and no OS restart was performed for this check. Keep
execution clearance unverified until every required gate is established. See
[the API contract](dashboard-api.md#recovery-and-assessment-api) for exact routes and request fields.

## Status, costs, and approvals

On **Team**, each member's Recorded activity lists direct runs and observed delegated work,
including Chief of Staff assignments. Use the project filter to narrow the history; select an
activity to open its coordinating task. On **Overview**, select a task title or **View details**
to see **Delegated activity**, statuses and nested agents, then open the coordinating conversation.
Generated delegated labels identify the role; assignment prompts are withheld. Older records
without parent-thread metadata show that the parent agent was not recorded. Child records do
not add to root-task counts or execution estimates. Only dashboard-managed activity is covered.

The dashboard shows live sanitized projections for its own managed runs. A completed model
turn is not a reviewed, accepted, or released development task. Use independent QA and review
before accepting changes. This version does not automatically execute the complete engineering
team workflow simply because a role was selected.

Task details show the reported plan as ordinal step labels and statuses only; model-authored
plan text is withheld. The dashboard records usage counters when Codex reports them. Those
counters and plan status are execution evidence, not proof that code passed checks or met the
task's acceptance criteria.

Credit figures are **estimates**, not bills or verified charges under your workspace agreement.
The dashboard estimates only when it has observed usage, a supported actual model, and an
explicit supported Standard-speed tier. Unknown or mixed model/tier cost stays unknown; unknown
does not mean zero. Model and reasoning settings come from the approved GPT-6 role profiles.
Use a current CLI; older catalogues can advertise retired models. Actual routing can differ.
No cost estimate proves the account's billing
arrangement. Browser polling and SQLite storage run locally; explicit Codex work uses the
account's workspace allowance or billing arrangement. No paid infrastructure is provisioned
by the launcher.

Approval cards show a safe summary. Choose **Review request** to inspect the complete checked
native context before deciding. Command and file-change approvals retain **Approve once** for
that exact request. A native permission request uses **Approve for this turn**: review the full
requested filesystem/network overlay and reason first. The server grants only that displayed
overlay for the current turn, never session-wide, and project Automatic mode does not decide
permission requests. Declining sends an empty permission overlay.

Permission-related connected-tool questions show their exact checked questions and choices.
Choose an answer and submit it explicitly; the dashboard sends the selected labels against the
native question IDs. Secret questions and unsupported question shapes remain blocked, with the
human step completed in Codex when required. Ordinary advisory questions remain in Conversations.

For supported MCP elicitation forms (`mode: form`), the dashboard displays the checked form and
validates typed primitive values before sending them. The implemented subset supports boolean,
integer, number and string fields, required fields, numeric/string bounds and string choices.
Arrays, nested objects, secret/write-only fields, semantic formats and unrecognized schema
details stay blocked. Extended form modes can be reviewed as context but cannot be accepted in
the dashboard.

For a URL elicitation, inspect its message and URL, complete the external step yourself, then
explicitly confirm that completion in the dashboard. The dashboard does not open the URL or
perform sign-in for you. Device verification remains in Codex because the dashboard cannot
produce its proof. Decline or cancel remains available where the native request offers it.

Every accepted decision uses the exact live request and a short-lived review receipt; stale,
disconnected, changed, scanner-blocked or malformed context cannot be approved. Dashboard review
contents are kept in memory, outside dashboard history and SQLite. Codex native history may
separately retain underlying requests and tool output. Reconnecting or restarting does not
restore an actionable request. Managed-network requests that can release multiple queued
operations, remote environments, broader/session file-root grants, terminal-input approvals,
extended elicitation forms and unknown protocol shapes remain blocked pending a separately
reviewed complete flow. No automatic retry occurs after uncertain response delivery.

When review is blocked, use the resolution controls within the approval panel to send guidance
and ask for a reviewable alternative. Sending this guidance declines the captured request only
after Codex acknowledges queuing the guidance. Sending guidance does not itself approve a replacement;
new requests follow the project's manual or automatic mode. A stale request or uncertain delivery
is not retried automatically.

Some native requests offer Cancel rather than a decline that continues the turn. The panel labels
this explicitly: sending guidance and cancelling the attempt stops that turn. Queued guidance may
be discarded when Codex stops. After the native interruption is confirmed, explicitly continue
with the retained guidance in a new turn. Cancellation never starts a replacement turn on its own.

For an explicit sensitive-content finding, the local owner can choose **Reveal sensitive request
locally**, confirm the reveal, inspect the full request, then separately confirm **Approve once**.
This is a request-specific exception, not a project automatic grant. Scanner errors, unavailable
policy, incomplete context and unsupported native permissions cannot be bypassed this way.
The revealed bytes remain in the browser and server memory rather than dashboard records or logs.
Codex native history may already retain the underlying request. Do not copy revealed content into
chat, screenshots, documentation or Git. This local dashboard trusts same-user processes; the
feature does not create an authenticated administrator account. Disable it through Settings or
`sensitive_review_enabled = false` in config.toml to revoke sensitive-review authority.

Independent pending requests can be reviewed in any order. An agent remains paused where its
own action needs approval, and dependent operations remain sequential. Revealing and approving
a sensitive request are intentionally separate actions for that same request.

Automatic approvals are an explicit per-project preference, initially off. Settings stores
`project_approval_modes`, mapping local project IDs to `manual` or `automatic`. Automatic mode
applies to future supported requests originating from that project, including future runs;
it does not limit a command's effects to that project's files. A command approval can permit
effects beyond baseline sandbox restrictions. Full context validation and secret checks still
apply. Incomplete, sensitive, unsupported and grouped network requests need manual resolution.
Switch the project back to Manual in Settings to revoke future automatic approvals. A request
already delivered to Codex cannot be recalled by changing this preference.

On Overview, **Dismiss notice** acknowledges an old inactive failed/unknown warning without
deleting the task or changing its status. Task history remains available. A later update or new
diagnostic brings attention back. Pending decisions and active child work cannot be dismissed.

Use the task details **Delete run** action when you want to remove an inactive run from the
dashboard, including an unknown run whose recovery status remains unresolved. The confirmation
states that this deletes the dashboard record and releases its recovery hold, but cannot stop
native work already delivered to Codex or undo changes already made in the project. Review that
warning before confirming. Active roots or children, live ownership, pending native requests,
and in-flight launch/message/recovery operations must be stopped or resolved first; historical
unknown child activity alone does not block deletion. A stale confirmation requires refreshing
and reviewing the current state again.

Deletion removes the selected run's dashboard history, including its visible conversation,
approval and recovery projections, associated child activity and related operation records.
Linked assessment references on an origin recovery record are cleared if the assessment task is
deleted. Other linked task records, project check plans, recognition records and project files
remain. Codex's native history remains outside the dashboard and is not deleted. Because the
run is removed, its previous dashboard details are no longer available; save only non-sensitive
information you need before confirming.

### Claude tool-call approvals

This applies to a `claude` deployment. It is checked by unit tests and fake-binary tests (a fake
`claude` that posts to the real receiver), and by one live spike of the hook itself (S10: eight `haiku`
runs outside the dashboard), and by four live `haiku` runs through the dashboard on 2026-11-02 (approve once,
decline, stop while a request was held, and a 5 minute wait), driven in the built-in browser on a scratch project
(`claude` 2.1.312). Each was run once; Linux, other tools than `Write`, and parallel subagent calls were not tried. See
[the evidence](superpowers/evidence/2026-11-01-managed-approvals.md).

**Why the approval is in the dashboard.** A dashboard-started run is headless (`claude -p`): there is no
terminal prompt to answer, so approving "in Claude" is not possible. Each run is started with a
settings file that holds one `PermissionRequest` hook. The hook sends the request to the dashboard and
Claude Code waits for the reply.

**The approve-once journey.**

1. Start a run. When Claude Code needs permission for a tool call, the task changes to waiting for approval
   and a card "A tool call requires approval" appears on **Approvals**, with the requester ("<role> via
   Claude Code"), the scope "This one tool call only" and the longest time the run will wait.
2. Choose **Review request**. The dialog shows the tool name, the complete tool input and, for a
   subagent, its agent type (marked "not verified", because Claude Code supplies it). Control and
   direction-changing characters (for example U+202E) are shown as `\uXXXX` so the text cannot hide
   what it does; newlines and tabs stay as they are. Codex requests are not shown this way.
3. Choose **Accept** to allow this one call, or **Decline** to refuse it. The list card also has
   **Decline**. Accept needs the review you just opened (a receipt valid for 10 minutes); nothing is
   accepted from the summary alone. Two identical requests are two approvals, and accepting one never
   allows the other. Claude Code asks again for a differently worded call (S10 R10e, one run).
4. If the tool input contains secret-shaped text, the normal review is blocked. You can use the same
   explicit sensitive review as for Codex, if it is enabled in Settings, and then accept once.
5. The run continues, or is refused that one call. Check the task for observed progress; an
   acknowledgement alone does not prove the work went on.

**The receiver.** The dashboard starts a small receiver on the first Claude launch. It listens on
`127.0.0.1` only, on an ephemeral port, and serves one path, `POST /hook/managed/<token>`, where the
token is 32 random bytes made for that launch. The token is valid only while the process lives, is
never shown in the page, the state, the logs or the store, and lives only in the settings file below. The receiver refuses a wrong
method, content type, size (over 256 KiB), malformed or unexpected fields, and an unknown or finished
token, without passing anything to the dashboard. It holds at most 16 requests per run and 64 in all; a
request over a limit is denied at once and not queued. The dashboard itself holds at most 128
pending requests; a request over that is denied and noted as `claude_hook_limit`. The dashboard's own
port, API, page and Host/Origin rules are unchanged, and none of them is served on the receiver's port.

**The per-run settings file.** It sits in the private state folder (the same folder as the database,
`.local/` by default) under `claude-runs/`, as `run-<random>.json`. The folder is mode 0700 and the file
0600. It is written before the process starts, passed with `--settings`, removed when the run ends
(and when the dashboard closes), and any file left by a crash is deleted when the dashboard starts. It holds one hook and
nothing else. The token is in its URL, so treat the folder as private like the database.

**The wait.** Settings has a field "Claude approval wait" (`claude_approval_wait_seconds`): how long a
run waits for your answer to one tool call. The default is 300 seconds (5 minutes); the range is 60 to
3600 and anything else is refused, never rounded. The hook timeout written into a run's settings file is the wait
plus 60 seconds, fixed when the run starts, because Claude Code reads the file once. A new setting
applies to runs started afterwards. A run that is already live keeps its own timeout, and its effective
wait is the smaller of the current setting and the value it started with, so raising the setting never lengthens a live run's wait.
**Live-checked to about 5 minutes only:** the longest wait shown to work live is an answer after about 305 seconds under a
960 second hook timeout (2026-11-02, one run; earlier 75 seconds under 120 seconds in S10). No ceiling is documented, but nothing longer, and
no wait above that, including the 3600 second maximum, was run. The 300 second default (hook timeout 360) is the value those runs came closest to. If Claude Code ends the hook
earlier than the dashboard's wait, the connection closes, the card shows as unavailable and Claude denies the
call, so a too-long setting fails closed.

**What ends a request, and what Claude does.** The call is allowed only by your explicit Accept. Every other
end is a denial, never an allow:

| What happens | The card | The call |
| --- | --- | --- |
| The wait runs out | "Expired" | denied |
| The hook connection closes (timeout inside Claude Code, process killed) | Unavailable | denied |
| You stop the run | Unavailable (run ended) | denied; the held request is released before the process is signalled |
| You close the dashboard | Unavailable (run ended) | denied; live runs are stopped as for Stop |
| The dashboard crashes or restarts | Unavailable (dashboard restarted); the task becomes `unknown` | the old process cannot reach the dashboard; a refused, unanswered or error reply was a denial in the live spikes (S6, S10) |
| You answer after the request ended | Accept refused as unavailable; nothing is sent | denied |
| The request has no known session, arrives after the turn ended, comes from a subagent with a different session id, or the dashboard is over its limit | no card | denied, with the notice `claude_hook_session_unknown`, `claude_hook_turn_inactive`, `claude_hook_subagent_session` or `claude_hook_limit` and the tool name in the denied-calls line |

Pending approvals are never restored after a restart. Deleting a run that is waiting is refused with
409 until you stop it; after the stop, delete works as for any finished run.

**Automatic mode for Claude projects.** The per-project setting (Manual by default, same confirmation
checkbox as for Codex) applies to Claude projects. In Automatic mode the dashboard accepts a request itself
only after it has built and checked the complete context, only if the input has no secret-shaped text, and only for the tools
`Bash`, `Write`, `Edit` and `NotebookEdit`. Each automatic accept covers that one call and is recorded and shown as "Accepted
automatically by project policy (one call)". Every other tool (web, MCP, agent launch, any unknown name) always waits for you,
as does every request in a Manual project. Changing the mode affects only requests that arrive afterwards, and a request being
checked when you switch to Manual is left for you. This is not Claude Code's own Auto mode: a run
whose permission mode is not `default` is stopped (Auto mode skips the hook, S2 and S7), and the
dashboard does not set one.

Automatic mode is confined for file tools only. `Write`, `Edit` and `NotebookEdit` are accepted automatically only when
the call's path (`file_path` or `notebook_path`; symlinks followed, relative paths read against the project folder)
lies inside the project's real path and no part of it below the project is `.git`, `.claude` or `.local`. Any other
path, a missing or non-text path, or a path that cannot be resolved leaves the request waiting for you, as in Manual
mode; it is never denied for that reason. `Bash` cannot be confined: Automatic mode accepts any `Bash` call that has no
secret-shaped text, and that is the same as unrestricted code execution as your user, including outside the project.
Use Automatic only for projects where you accept that.

Subagents: a request from a subagent that names a session other than the run's is denied for that call only (notice
`claude_hook_subagent_session`); the run is not stopped. Without a subagent marker the same mismatch still stops the
run and marks it failed. Whether real subagent requests carry the run's session id has not been checked live.

### Terminal sessions (observed Claude Code sessions)

This applies to a `claude` deployment only. Codex deployments have no Terminal sessions page, start no listener, and
answer the four observed routes with 409 `not available for this provider`.

**Evidence, stated plainly.** Unit tests, fake-binary tests and journey tests that send synthetic hook events through
the real HTTP listener and API (196 focused tests passed on Python 3.15 and 3.12, 213 Node tests passed, at commit
`da9f291`); and one **browser** check by the controller on a scratch copy with an isolated home, a fake `claude` and
fake hook events sent over HTTP. That check saw: the navigation entry and the page; the status line, the port and the
Auto-mode sentence; active and ended sessions with "subagent activity seen" and no count; two pending cards with Allow
and Deny; focus on a card's Allow button surviving a refresh; Enter on Allow producing the card "Allowed here: outcome
not known" and the held hook receiving the allow reply; a matching `PostToolUse` turning the card to "Allowed here:
ran"; and the hook snippet showing the token only after it was opened (43 characters, all seven events), with the token
absent outside the panel and from browser storage, and cleared after leaving the page and coming back.
**Not checked in a browser:** a true page reload with the snippet open (back/forward cache), a Codex deployment, the
Deny path, the quiet state, other browsers, screen readers. **Live: none.** This feature has not run against a real
interactive terminal session. The earlier spike S7 and the Plan 5 headless live run are not this feature. **Owner-reported:
none.** The spike that would check the open points, S11, is pending the owner's attended run (see
[the S11 note](superpowers/spikes/S11-observed-replies.md)).

**What it does.** Your own Claude Code sessions in a terminal appear on the **Terminal sessions** page. Each session
shows a status, the project name, when it was last seen and, if a subagent event arrived, the time "subagent activity
seen" (never a count):

- `active`: an event arrived in the last 30 minutes. `quiet`: no event for 30 minutes. `ended`: Claude Code reported the
  session end.
- The project name is the final path segment of the session's working directory, after the secret and control-character
  scan; `unknown` if the scan refuses it.
- A permission request from one of these sessions appears as a card "Your terminal session" with the tool name, the
  project, a summary, the time it expires and **Allow** and **Deny**. The card says "This request may already be
  answered in the terminal", because your terminal prompt is still open: whichever of you answers first wins. Observed
  approvals are never automatic.

**Setup (one time).**

1. Start the dashboard with `sh scripts/run_dashboard.sh claude`. A second listener starts on `127.0.0.1` only, on the
   fixed default port **47615**. The setting `observed_port` (Settings API, 1024 to 65535) changes it, and applies when
   the dashboard restarts. If the port is in use the listener stays off with the reason shown on the page, the dashboard
   itself keeps running, and **no other port is tried**.
2. Open the page and choose **Show hook snippet**. The snippet is a `hooks` block with one `http` hook for each of seven
   events: `PermissionRequest`, `PostToolUse`, `Stop`, `SessionEnd`, `SubagentStart`, `SubagentStop` and `SessionStart`
   (`SessionStart` over `http` was not delivered in spike S7, so a session may first appear at its next event). It has
   this shape, with the token only inside the panel after you open it:

   ```json
   {"hooks": {"PermissionRequest": [{"hooks": [{"type": "http", "url": "http://127.0.0.1:47615/hook/observed/<REDACTED>", "timeout": 360}]}]}}
   ```

   The snippet's `timeout` is the approval wait plus 60 seconds (default wait 300 seconds). The dashboard never edits
   your Claude settings: you paste the block yourself.
3. Paste it into your **PROJECT or LOCAL Claude settings** (`.claude/settings.json` or `.claude/settings.local.json` of
   the project you work in), not into your user-level settings. Dashboard-managed runs use `--setting-sources user`, so
   project and local settings files are not loaded by managed runs. If you paste the block into user-level settings,
   managed runs fire the hooks too; the listener then ignores events from dashboard-managed sessions (it replies `{}` at
   once, with no card and no record), so nothing breaks, but you get no page entry for those runs. A managed run's very
   first hook can arrive before the dashboard has registered its session id, so a card may appear briefly; a managed run
   resumed in your own terminal is also ignored. The check fails closed: if it errors, or the dashboard's internal lock
   stays busy for more than a second, the session is treated as managed, so that event gets `{}` and no card. A card
   can be missing in that rare case; your terminal prompt stays in charge either way. See [decisions](decisions.md).
4. Start Claude Code in your terminal as usual. Only tool calls that reach a permission prompt send a request.

**The token.** Each install has one token. It is in its own file in your user config directory, outside the repository:
`~/Library/Application Support/KT Agent Dashboard` on macOS, otherwise `$XDG_CONFIG_HOME` or `~/.config` followed by
`kt-agent-dashboard`. The file is mode 0600 in a folder of mode 0700; the dashboard refuses a token file or folder with
other permissions (reason `token_permissions`) or one it cannot read (`token_unreadable`). The token is never written
to the logs, the database, the settings or the page, except inside the snippet panel while you hold it open (it is
fetched when you open the panel, not when the page loads, and cleared when you close it, rotate or leave the page).
**Rotate token** makes the old token stop working for new requests; requests already waiting finish. After rotating,
paste the snippet again. After changing the port, rotate the token and paste the snippet again. After changing the
approval wait, paste the snippet again (the new wait applies after a dashboard restart). Only paste the token's snippet
into settings you control; anyone who has the token and can reach `127.0.0.1:47615` can send events.

**It never blocks your terminal.** The dashboard never makes Claude Code wait for it. When a request expires, the
connection closes, the listener is over a limit, the dashboard is stopped or the payload cannot be read, the listener
replies HTTP 200 with `{}` (no decision), and Claude Code's own prompt stays in charge. Only your **Allow** or
**Deny** produces an allow or deny reply. Limits: 256 sessions, 32 pending approvals, 64 finished cards and a 256 KiB
request body; the page shows how many requests were left to the terminal because too many were waiting. If the
dashboard is not running and no other program listens on the port, nothing is allowed automatically and Claude Code's
own prompt appears.

**`{}` is not live-tested.** That a 200 reply with `{}` leaves the terminal prompt open comes from Claude Code's
documentation, not from a live run. Spike S11 (an owner-attended run) is pending; the decision rule is recorded there:
the shipped default is `{}`, and if the run shows it disturbs the prompt, the default is switched to holding the
connection (a one-line change). Also untested: what Claude Code does when the connection drops or the listener answers
413 or 415, and how it merges the decisions of two `PermissionRequest` hooks.

**The two-way record (inferred).** The card is closed in one of two ways. A decision you make here goes back on the held
connection. An answer you give in the terminal is not sent to the dashboard, so it is inferred from later events of the
same session and the same agent, and labelled "Inferred from later events, not a receipt":

- A later `PostToolUse` with the same tool name and equal tool input: the call **ran**.
- `Stop` (the turn ended) or `SessionEnd` (which closes all cards of that session) with no matching `PostToolUse`: the
  card shows **no run seen**. A `PostToolUse` that was dropped, or was over the size limit, gives the same result, so
  this wording does not say the call did not run. If a `PostToolUse` arrived without a tool input, the outcome stays
  "outcome not known".
- A `PostToolUse` for a **different** call never closes a card, because Claude Code can run tool calls in parallel and a
  sibling's result is not an answer to this card. A terminal "No" therefore shows no change until the turn's `Stop`.
- If a matching `PostToolUse` arrives after you pressed **Deny** here, the card shows the warning "ran although denied
  here".
- When these rules settle a card whose connection is still held, the connection ends with `{}` at once, which frees the
  slot; the terminal stays in charge.

The real `PostToolUse` and `Stop` payloads have not been seen (S11 pending). The match assumes `tool_input` comes back
exactly as it was in the `PermissionRequest`; if it does not, cards end as "outcome not known" or "no run seen".

**What is stored.** In the local database: session id (or an opaque id), project name, first and last seen, status and the
subagent time. Nothing else. Request payloads (tool name and input, summary) are kept in memory only, are scanned for
secret-shaped text before they are shown, and disappear when the dashboard stops. A session id that the scan refuses is
shown and stored as an opaque `~` followed by 12 hex digits.

**Limits to know.**

- Only tool calls that reach a permission prompt are sent, so in Auto permission mode (and for any call your own
  settings allow) the list is not a complete record.
- **Security limit (an owner decision, recorded in [decisions](decisions.md)):** the port is fixed so that hooks you pasted
  keep working. The token lets the dashboard check who is calling it, but Claude Code cannot check who is listening: while
  the dashboard is not running, another local program could bind the port and would then receive hook payloads (commands, file contents and
  the token in the URL) and could reply allow, so remove or disable the hooks when you are not using the dashboard. If the
  port is in use when the dashboard starts, the page says that hooks installed earlier may be sending to another program.
  A wrapper command hook that checks who is listening is out of scope.
- Pending cards are never restored after a dashboard restart.
- Defaults such as the 30 minute quiet time and the caps are set in code and are not settings.

**Not verified.** Everything marked above as S11 pending; a real interactive session end to end; the page in a browser
for the Deny path and the quiet state; that Claude Code sends the same `session_id` to every hook of one session; and
that `SessionStart` arrives over `http`.

## Review files and publish commits

Select a registered project in the dashboard and open **Files**. The list includes eligible
tracked and nonignored untracked files from that Git working tree. The preview is plain text,
read-only, bounded in size and scanned before it is returned. Credential/runtime paths, ignored
files even if force-tracked, links, binary files and possible secrets are blocked. A missing,
wrong-version or failed Gitleaks check blocks preview. File contents are not saved in SQLite.

Open **Git** to refresh local status. Ahead/behind information uses existing local references;
the status view does not fetch from the network. Git status and file review can work while Codex
is disconnected, but still require the local dashboard server.

Commit reviewed changes using normal repository controls before publishing. The dashboard will
not stage or commit automatically. **Publish commits** displays the exact approved GitHub remote,
branch and captured commit, then requires an explicit confirmation. Changes to that snapshot,
dirty files, an unsafe destination, failing secret checks or overlapping active managed work
block publication. Publishing requires an HTTPS GitHub origin; SSH origins are visible but cannot publish from the dashboard. Configured Git clean/process filters also block status review. The push is not forced and ordinary push hooks remain enabled. Only use
registered projects whose Git installation, configuration and hooks you trust.

Git uses its normal existing authentication setup. Never enter tokens or passwords into this
dashboard, embed them in remote URLs, or copy credential files into the project. A failed push
does not justify bypassing hooks, weakening scanning or force-pushing. Resolve the cause outside
the dashboard and refresh the reviewed status before trying again.

The human requested public repository K55Toms/KT_Agent_Dev_and_Dash. Creation and origin setup
completed; repository metadata confirmed secret scanning and push protection enabled. Source
publication remains a separate explicit action. Server-side branch/required-CI rules have not
been configured by this feature.

## Stop, disconnect, and recovery

Click an activity row or **View failure** to open its details. New runs record safe diagnostic
checkpoints and a suggested next action; failures after submission also show a notification.
A launch that fails before the first turn has no conversation messages. Older failures retain
their original generic error because detailed upstream responses were not recorded. Diagnostics
use fixed categories, not raw protocol text, stderr, tool output or reasoning. A category helps
troubleshooting but does not establish that every downstream issue has been resolved.

Usage and estimates cover the dashboard-owned main thread. Child-agent usage is not rolled up,
so a delegated run's displayed estimate is incomplete execution-cost coverage. Use the workspace
billing surface for account totals; do not infer them by summing these estimates.

Keep the launch terminal open while using the dashboard. Interrupt active work deliberately
and inspect its resulting status before a planned shutdown. Use Ctrl-C in the launch terminal
to stop the dashboard. Graceful shutdown waits for bounded in-flight HTTP work, including any
explicit publication, to finish or time out. Closing a browser tab does not stop the backend or its work. A requested
interrupt or shutdown cannot undo file changes or external actions already performed.

After a connection loss, active tasks become unknown and pending approvals become unavailable.
An ambiguous transport failure while starting work can also leave the outcome unknown if Codex
may already have received the request. Restarting does not replay prompts, resume inference, or
resend approvals. Inspect the project's working tree and verify what completed before explicitly
starting new work. Never interpret an unknown run as successful or immediately repeat a potentially
non-idempotent instruction.

Open **Recover task** from task details or Conversations to investigate an unknown outcome or
prepare a separately approved continuation. If you do not need that history and the run is
inactive, **Delete run** is the direct way to remove it and release its dashboard hold. Recovery
remains available for a terminal parent with an unresolved child; the parent's recorded
completed/failed/interrupted status is preserved.
An unknown-role child remains labelled **Unattributed delegated task** and its persisted unresolved
state can keep the parent recoverable after disconnect or restart. Recovery checks must be complete
before any separate continuation decision; an available button is not activity clearance.

If port 8765 is already in use, stop the earlier dashboard instance using its launch terminal
and retry. Do not kill an unidentified process or change the listener to a public network
address. If the page opens but Codex is disconnected, check CLI availability and the CLI's
normal sign-in flow. Report only sanitized symptoms; do not collect raw RPC traffic, environment
dumps, credential files, or Codex transcripts for troubleshooting.

## Private state and backups

Runtime state belongs in the ignored `.local/` directory with owner-only permissions. It
contains project/task/approval projections, scanner-checked visible conversation messages,
recognition records and uploaded logos. Project names, paths, titles and visible messages
can still reveal business information: keep them free of secrets
and unnecessary personal data. Git ignores do not encrypt files or protect them from other
processes running as your user. Use the Mac's approved disk protection and account controls.

For a consistent backup, first interrupt work and stop the server. Confirm the process has
exited before copying the complete `.local/` directory into an approved private backup
location outside any Git repository. Preserve owner-only access. Do not copy Codex authentication
or transcript stores. Do not copy only an open SQLite database file; journal files may be needed
for consistency. An online backup would need SQLite's backup API and is not implemented here.

To recover, keep the server stopped, preserve the current `.local/` directory separately, then
restore a known good complete backup with owner-only permissions before relaunching. Restored
records are historical observations; reconnect cannot recreate a live native approval request
or establish the outcome of a disconnected run. Inspect project changes before creating new
runs. Dashboard state backups do not back up project source or undo agent changes: manage each
registered repository's source and recovery separately without committing secrets.

No automatic backup, age-based retention, schema downgrade, unattended startup, or automatic
recovery of model turns is provided. Test backup/restore against synthetic local state before
relying on it for important work. Keep an application revision paired with its backup; do not
run an older revision against newer state without a reviewed migration or recovery procedure.

## Delivery checks and readiness

The steps below describe a Codex deployment. A Claude deployment differs in the Ponytail gate and in how checks and review are run; see [Delivery for Claude runs](#delivery-for-claude-runs) at the end of this section.

The dashboard's Ponytail policy and delivery gate are separate from a task's native execution
status. A `completed` task stays `completed` while checks, review and human acceptance are recorded
in a separate readiness projection. A **Ready for delivery** status does not publish or deploy
changes, approve a Codex native request, or grant release approval. Historical tasks without the
policy metadata are reported as **Not enforced for this run**; they are not retroactively stamped.

For new managed tasks, the dashboard pins the installed `ponytail:ponytail` Full policy to version
`5.3.2` and SHA-256
`9badd22a32e19cb884e46dfa8d3aae82bb81dfa5484105b8b4f0262df823a509`. It resolves only this
approved file from the current user's Codex plugin cache, requires an owned regular file within
the 32 KiB size limit, without following symbolic links, verifies stable bytes and the digest, and
runs the reviewed secret scanner. It adds the approved text to Backend/Frontend root and registered
child roles, fingerprints the registered role snapshots, and rechecks that policy before native
dispatch. A missing or changed pin/profile blocks native dispatch and may leave a recorded failed
task if discovered after task creation. After a reviewed policy/profile update, wait until the
dashboard is idle, repair the approved installation if needed, then reload the dashboard so it
builds a fresh role snapshot. Do not supply a browser path, new digest or alternate skill source.

Use this sequence for an eligible completed Backend/Frontend implementation or its coordinating
task with an observed direct implementation child:

1. Check the task details and delegated activity. Stop or resolve active work first. An unknown,
   unattributed, or unresolved child, a recovery hold, an unavailable current policy, or an
   incomplete project snapshot keeps delivery unverified.
2. Review the project's saved **Approved project checks**. Enter one exact command per line, up to
   eight; each can be up to 2,000 characters and all commands together up to 8,000 characters.
   Select **I approve these exact checks for this project** and choose **Save approved checks**.
   Saving stores the scanned plan; it does not run it. The plan cannot be changed while project
   work is active.
3. Review the current project snapshot and choose **Run approved checks** after selecting the
   separate confirmation that checks/review may consume workspace usage or request native
   approvals. The dashboard creates a separate `qa_engineer` task. Commands run through Codex from
   the registered project root with its normal sandbox and approval controls, not a host-side
   runner. A command counts only when the current owned turn reports the exact approved command
   in that working directory and a completed exit code of zero. A supported shell `-lc` wrapper
   may carry the exact approved command; other command text does not count. Every approved command
   must pass.
4. After checks pass, choose **Start independent review**. This creates a separate
   `code_quality_reviewer` task to inspect the current project changes and agreed outcome without
   editing or delegating. Open its conversation to inspect its full response.
5. Choose **Read independent review** to load the scanner-checked current report. Review the entire
   text. Choose **Accept review and mark delivery ready** only if the report accepts the current
   work; otherwise choose **Request changes** and route findings to the implementer. The review
   receipt lasts 60 seconds and is single-use.

The code fingerprint covers the registered directory identity, HEAD, Git-visible tracked files
(even tracked ignored files), non-ignored untracked files and modes. It also hashes opaque binary
assets; that fingerprint does not assess their visual content or whether they carry sensitive
meaning. The scan covers up to 5,000 candidates and 1,000 files, 256 KiB per file and 16 MiB total.
All file witnesses and HEAD are checked again after scanning. A file, plan, role/policy, task or
connection change makes earlier evidence stale. Refresh and repeat checks and review against the
current snapshot.

For checks or review, `not_started:true` means preflight failed before the new task and operation
were published. Correct the reported issue, refresh, then make a new explicit attempt with a fresh
operation ID. If dispatch may have started but its response was lost, refresh to reconcile. The
**Retry original request** control resends only the frozen request and same operation ID; the server
returns an existing operation or rejects a stale request. It never creates a different request or
retries automatically.

Review-decision receipts are single-use. If the decision save succeeds, refresh can reconcile its
durable acknowledgement. If storage fails after the receipt is consumed, readiness remains
unverified and the old receipt cannot authorize a repeat. Repair storage, refresh checks if needed,
read the current review again for a new receipt, then make a fresh explicit decision.

An earlier integrated browser validation used the real HTTP/UI path, local storage and scanner, with
synthetic native events driving check and reviewer results. That fixture completed plan setup,
one of one approved checks, separate review, literal report preview and explicit acceptance while
leaving the original parent task `completed`. It verifies that candidate's browser and delivery-
record path. A later isolated test used actual Codex execution with the approved installed policy
and existing sign-in: a Backend assessment completed, the exact approved unittest command was
observed passing, a separate native reviewer completed, and explicit fixture acceptance reached
`ready` through the browser. Only disposable synthetic source files were supplied; no existing
task was resumed or native permission automatically approved. This proves that tested integration,
not model judgment or release readiness for other projects. Native child isolation remains subject
to the documented App Server limits. Final regression/review status is recorded on the task board.

The routine local checks do not require model execution:

```sh
sh -n scripts/run_dashboard.sh
python3 -m unittest discover -s tests
```

Before a commit, stage the intended reviewed changes and run
`python3 scripts/security_check.py staged`; before any authorised push, run
`python3 scripts/security_check.py history`. An unstaged file is not covered by the staged scan. No
remote or deployment destination has been authorised. Review changes to security controls,
the CLI protocol, dependencies, and runtime file handling before release.

Automated protocol and failure-path tests should use fake App Server events. A real handshake
checks connectivity only; paid model execution and recovery of in-flight external actions
require separate explicit exercise and must not be inferred from passing offline tests.

### Delivery for Claude runs

Evidence kind: fake-binary and unit tests only (`tests/test_claude_delivery.py` and the journey test
`tests/test_claude_slice2b_journey.py` replay synthetic stream fixtures through the real HTTP handler). No delivery
run has been made with the real `claude`. One live run (2026-11-05, `haiku`, CLI 2.1.312) confirmed the shapes of a failing
command (`is_error` true, "Exit code" first line), a backgrounded command (`backgroundTaskId` and "Command running in
background") and a subagent; the full delivery path is still not run live.

- **Ponytail is not used on Claude.** The panel shows "Ponytail policy: Not applicable for Claude". That row is not
  counted as passed; **Ready for delivery** still needs the approved checks, a complete independent review and your
  explicit acceptance. A Claude run started before delivery readiness was available for Claude reads **Not enforced
  for this run** with the notice that it cannot earn it.
- **Who gets the panel.** Delivery applies to Backend and Frontend runs and to any Claude run that has an unnamed
  delegate, so a run of another role that used a built-in helper can show **Delivery not verified**; this fails safe.
- **Unnamed delegate.** A helper whose type is not one of your configured roles, shown under the role of the run that
  started it. A finished one whose stop was reported does not block delivery; one whose end was never reported does.

**Delivery not verified: what to do.** The panel lists the reasons in words. Then:
1. Reasons about helpers or unfinished work: wait for the helpers and the run to finish, then refresh.
2. "Policy binding changed": the role setup or deployment no longer matches the run. Start a new run.
3. "Complete review messages required": the review was cut short. Start a new independent review.
4. Reasons about a changed snapshot or stale evidence: refresh, then run the checks and review again.

**Checks.** They run as a separate QA Engineer Claude run in the project root. A check fails if the model ran the
command in the background, added anything before or after it, ran any other command, used any tool other than the
read-only ones (read, search) and the shell, used a helper, or if project files changed while the checks ran, even if
they were restored, or if any part of the run's output was too long to read in full (even a very long report fails the checks). The change check cannot see ignored files, so it is not a complete guarantee. Remedy: approve only the exact commands you want, then run the checks again. Each approved
command is expected to go through the normal tool-call approval unless your own Claude settings allow it (not
exercised with the approval hook in the tests); delivery runs are never approved automatically, even in Automatic
mode. The failing-command and background markers were confirmed in one live run (CLI 2.1.312); the full delivery path has not run live.

**Review.** It runs as a separate Code Quality Reviewer Claude run. A review cannot be accepted if any reply was cut
short, was too long, or was withheld by the sensitive-content checks. Start a new review.

A delivery run takes no follow-up; use the delivery controls.

## Settings and branding

Open **Settings** to edit every supported field in `dashboard/config.toml`: dashboard name,
theme, logo reference, GitHub account/organisation, default new-repository visibility and
per-project approval modes and local sensitive-request review availability.
Save applies the name, logo and theme immediately. Manual file edits apply after a browser
reload. The supported themes are `hybrid`, `terminal` and `rebel`. Unknown or malformed
configuration is rejected rather than silently overwritten. Loading an existing config and saving
changes require the reviewed secret scanner; scanner errors block the operation and preserve the
previous file. Never put credentials here.

Upload a plain, noninterlaced PNG up to 1 MiB and 2048 pixels per side, without metadata.
Uploads stay in ignored, owner-only `.local/branding`; only a content-addressed local URL
is stored in config. Uploading does not activate it until Save. Choose Original logo to
restore the supplied logo. A clone with an uploaded-logo reference also needs that local
image uploaded again, or the original-logo setting restored.

GitHub account and visibility prefill **Create GitHub repository** in the Git view for a
project without origin. Private is the default for new repositories. Existing destinations
and visibility never change when you save preferences. Review owner/name/visibility and
confirm creation explicitly; it creates an empty repository and attaches HTTPS origin.
It does not push files or commits. Publishing remains a separate reviewed action. The
installed GitHub CLI must already be authenticated outside this dashboard; never paste
credentials into Settings. An uncertain result or partial origin attachment requires checking
GitHub and local status before retrying; the dashboard never retries creation automatically.

## Talk to a dashboard-managed run

There is no one-message quota. Pending approvals pause ordinary chat until their scoped decision
is resolved; Conversations shows the actual reason and **Review request** controls directly.
After resolution, further guidance and follow-ups remain available. Polling failures preserve
unsent drafts, focus and caret; reconnect with a fresh conversation read before deliberately retrying.

Start a run explicitly, then open **Conversations**, choose its task, or use the conversation
button in task details. New visible user instructions and completed agent messages are checked
before they enter the local conversation log. Messages appear after a complete-item scan rather
than token by token. Reasoning, raw tool commands/output and existing desktop chats are excluded.
If checks fail, content is withheld. A processing or tracking limit is reported as incomplete
coverage rather than a complete interaction record. Never include secrets in a message or answer.

For a running turn use **Send guidance**; for a finished turn in the current server session use
**Send follow-up**. Both send input to Codex and may consume workspace usage or change project
files. Guidance cannot undo earlier actions. Stale turn IDs, disconnected sessions and overlapping
project work block sending. Verified active delegated agents also keep their project reserved
after the parent turn ends. Task details show active children and **Stop active agents** sends
interrupt requests to the bound live child turns; completion events confirm when work stops. An uncertain delivery is not retried automatically.

Supported advisory agent questions show their checked questions/options with an explicit answer
action. Permission-related native choices instead open the scoped approval review described
above; they do not pass through the ordinary conversation answer form. The checked choices are
sent against their native question IDs. Secret fields or unsupported shapes remain blocked and
require the protected native human step. Wording checks are a conservative heuristic and cannot
establish a question's purpose. The dashboard never submits an answer automatically on timeout.
Expired questions are historical.
Questions from verified live child turns remain actionable after the parent turn finishes.
They expire when the child stops, its request resolves or the runtime disconnects. Child
lifecycle behavior still needs a live App Server roundtrip test.

The log includes observed native agent-to-agent prompts and returned messages only. It does not
claim to capture every internal exchange or anything from this desktop session. Visible records
stay in the private ignored dashboard database, bounded to the latest 200 messages per task and
2000 overall. After server restart/reconnection, past dashboard-run history is read-only; start
a fresh run when needed. No model turn is resumed or replayed on startup.

Managed runs now use persistent Codex parent sessions to support native delegation. All 14 team
roles are registered for every project, including projects without this repository's role files.
Each registered role preserves its model, effort and shared security instructions. Codex keeps
native history locally outside the repository; that history may contain prompts, commands,
approval details and tool output and is not covered by dashboard scanning. Never include secrets.
The dashboard does not read native histories or migrate old ephemeral runs. Private static role
snapshots are removed when the dashboard closes; persisted history does not add task resumption.

## Your Rebel crew and recognition

**Team** shows fictional human identities and original illustrated Rebel-crew portraits for the
configured roles. Names and art are presentation; the configured role/model still govern execution.
Latest work uses dashboard role runs and child activity whose role is explicitly identified by
the native runtime under a verified owned parent. Unknown child roles stay unattributed; names or
message text are never used to guess a role. The child activity record persists with the
**Unattributed delegated task** label; unresolved status is preserved for parent recovery. A
model-reported result is labelled as such; a
finished turn does not establish independent acceptance, quality or release readiness. No history
from this chat is backfilled and empty records remain empty.

When a dashboard-managed Chief of Staff runs, it can use its dedicated recognition tool to issue
Rebel coins and Agent of the Week without another human approval. A recipient must have recorded
completed work. The tool cannot award the Chief of Staff itself. Each award is 1–20 symbolic
coins, with at most 100 coins per recipient per UTC ISO week and one award per recipient/source
task. There is at most one Agent of the Week across the team each UTC ISO week. Duplicate calls
are idempotent. Reasons and source-task evidence are recorded; no starter balances are invented.
These are internal thank-you points with no monetary value. There is no automatic weekly paid
run or background award scheduler.

### Local trust boundary

The dashboard assumes a trusted local user and trusted local processes. Role checks govern
normal application/tool requests; they are not OS isolation or a tamper-proof audit system.
Managed agents inherit their parent’s filesystem permissions, and an agent working on this
repository can potentially modify its local runtime files directly. Owner-only permissions
protect against other OS users, not processes running as this user. Recognition points and
conversation records are workflow information, not proof against a malicious local operator.

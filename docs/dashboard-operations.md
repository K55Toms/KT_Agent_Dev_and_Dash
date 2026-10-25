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
   sh scripts/run_dashboard.sh
   ```

4. Open [the local dashboard](http://127.0.0.1:8765/) after the server is ready. Check the
   connection indicator before starting work. A reachable page alone does not prove that the
   App Server handshake succeeded or that your account can access a selected model.
5. Register each existing local project directory explicitly. Review its instructions, files,
   and intended changes before selecting a role and starting a run.

The launcher uses a fixed local port, checks Python's version and CLI availability, and sets
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

There are no dashboard environment variables to configure. The listener is fixed to
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

Earlier handoff validation reported 458 passing Python tests, 78 UI tests and 14 independent QA
acceptance checks with the real scanner and synthetic native fixtures. Those results cover the
handoff implementation at that time, not the nine audit-remediation changes. For the remediation
source, independent security review reported 114 passing checks, the 487-test Python suite passed,
and the 86-test UI suite passed. A synthetic browser fixture verified a completed parent remains
completed with one unresolved child and recovery available, and restored focus after a 4.1-second
poll. These checks do not establish live native continuation. No external chat or model call was
made. The remediation source was applied locally by graceful restart on 25 October 2026; the service
reconnected with 10 tasks, including two unknown, zero active runs and zero pending decisions. A
subsequent live recovery check returned `coverage: unavailable`, `activity_unverified` and
`metadata_unavailable` within 0.2 seconds, reporting zero children. This incomplete result does not
establish that no children exist; diagnosis remains open, and live descendant coverage and native
continuation are unverified. Keep execution clearance unverified until complete native checks
establish every required gate. See
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
command and working directory or proposed file paths and diffs, then **Approve once**.
Review includes supported requested permissions and the reason. Approval applies only to the
native request being reviewed; it does not create session-wide grants or remembered rules.
Unsafe, incomplete, unsupported or stale context cannot be approved. Decline and Stop remain
available. Dashboard review contents are kept in memory, outside dashboard history and SQLite.
Codex native local history may separately retain underlying requests and tool output. Reconnecting or
restarting does not restore an actionable approval request. Broader file-root grants, interactive
stdin approvals, managed-network prompts covering queued requests, remote execution environments,
and commands without an explicit native one-request acceptance choice require a separate supported
review flow. Command-specific permission overlays are displayed in full before approval.

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

Open **Recover task** from task details or Conversations when a task outcome is unknown, a recovery
hold exists, or delegated activity remains unresolved. This remains available for a terminal parent
with an unresolved child; the parent's recorded completed/failed/interrupted status is preserved.
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

## Delivery checks

The safe local checks do not require model execution:

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

Supported advisory agent questions show their full checked questions/options with an explicit
answer action. Wording-based checks are a conservative heuristic and cannot verify a question’s
purpose. Review the full context and never use the question form to grant access. Sensitive or permission-related questions require an appropriate review flow;
stop the run if they cannot be answered here. Command/file permission grants remain unsupported.
The dashboard never submits an answer automatically on timeout. Expired questions are historical.
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

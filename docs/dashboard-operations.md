# Local dashboard operations

This first version runs on this Mac with Python 3.11 or newer, SQLite from Python's standard
library, and the installed Codex CLI. No cloud deployment or Windows support is provided.
The dashboard starts and manages its own Codex App Server process. It does not watch existing
Codex desktop chats, discover projects by scanning the machine, or run agents continuously.
The App Server handshake has been verified. No real model inference has been run, so this does
not verify account access to every configured model, successful task execution, or billed cost.

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

## Status, costs, and approvals

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
does not mean zero. Configured model and reasoning values come from this project's role profiles,
but actual routing can differ. No cost estimate is proof of a charge or of the account's billing
arrangement. Browser polling and SQLite storage run locally; explicit Codex work uses the
account's workspace allowance or billing arrangement. No paid infrastructure is provisioned
by the launcher.

Approval cards show generic sanitized summaries and a safe explanation, not the actual command,
patch, or requested input. In v1 the dashboard can decline supported command/file approval
requests or stop the active run. Approval grants and session-wide decisions are not available.
Unsupported input requests cannot be answered here and require stopping the run. Reconnecting
does not restore an actionable approval request.

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

If port 8765 is already in use, stop the earlier dashboard instance using its launch terminal
and retry. Do not kill an unidentified process or change the listener to a public network
address. If the page opens but Codex is disconnected, check CLI availability and the CLI's
normal sign-in flow. Report only sanitized symptoms; do not collect raw RPC traffic, environment
dumps, credential files, or Codex transcripts for troubleshooting.

## Private state and backups

Runtime state belongs in the ignored `.local/` directory with owner-only permissions. It
contains sanitized project/task/approval projections, not a prompt archive. Project names,
paths, titles, and plan text can still reveal business information: keep them free of secrets
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

No automatic backup, retention policy, schema downgrade, unattended startup, or automatic
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
theme, logo reference, GitHub account/organisation and default new-repository visibility.
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

# Kristian’s Rebellion Builders

A Codex project with a Chief of Staff and on-demand product, design, architecture,
implementation, platform, independent review, QA, evaluation and documentation roles. It
also contains a local multi-project dashboard for observing runs started by that dashboard.
The dashboard uses Python, SQLite and a browser UI, and connects to its own Codex App Server.
It does not observe existing desktop chats or run the complete team workflow automatically.

The team has thirteen core roles plus an on-demand Astra escalation profile. Engineering
roles use GPT-6.1 Sol, writers use GPT-6 Luna, and the primary chat defaults to Sol / Medium.
See docs/team.md, docs/model-policy.md and docs/model-evaluation.md for ownership, exact
assignments and the evaluation protocol. These choices have not been benchmarked on a product.

## Start

Open this directory as your Codex project and read AGENTS.md. Project agents are defined in
`.codex/agents/`. They run on demand; saving their definitions does not start background agents.
Select a role for a dashboard-managed run to invoke that role's configured instructions and
model. This does not automatically call other team roles or run QA/review/documentation stages.

The primary chat coordinates the team. Example first request:

> Act as Chief of Staff. Have the Product Manager help me define our first product.
> Ask about users, their problem, constraints, and success criteria before choosing a stack.
> Record the agreed brief and delegate specialist work when it is ready.

To use the dashboard, follow [Local dashboard operations](docs/dashboard-operations.md).
In brief, sign in to the local Codex CLI if needed, run `sh scripts/run_dashboard.sh`, wait for
the connection indicator to report Codex connected, then add existing project directories.
Choose **Start run** only when you intend to send instructions to Codex; a run can consume
workspace usage and modify the selected project's files under the configured Codex controls.
The App Server handshake was verified, but a real inference turn, model access for every role,
and billed cost reporting have not been verified.

## Design previews

The dashboard uses Kristian’s Rebellion Builders and the supplied personal logo. Open
**Design previews** to compare Terminal Ops, Rebel Command and Hybrid Night Shift. Example
records are illustrative. Hybrid Night Shift is the selected live theme. To change it, set
`theme` in `dashboard/config.toml` to `"hybrid"`, `"terminal"` or `"rebel"`, then reload the browser.
Use **Settings** to edit all supported configuration, rename the dashboard, upload a PNG logo
and set GitHub account/new-repository visibility defaults. Saving applies branding immediately.
New repositories can be explicitly created from Git; creation does not publish commits.

## Review project files and Git

Use **Files** to choose a registered Git project, search its visible source paths and read text
with line numbers. This is read-only. Ignored/credential/runtime paths, links, binary/oversized
files and scanner-flagged content are unavailable; previews require the reviewed Gitleaks version.

Use **Git** to inspect the branch, current commit and local changes. Status does not fetch remote
updates. **Publish commits** requires a clean working tree, passing secret checks and confirmation
of the exact GitHub destination, branch and commit. It never stages, commits, force-pushes or
copies credentials. Use your normal Git authentication setup outside the dashboard.

The requested public repository is [K55Toms/KT_Agent_Dev_and_Dash](https://github.com/K55Toms/KT_Agent_Dev_and_Dash).
It was created empty and connected as origin; secret scanning and push protection are enabled.
No source was pushed as part of creating it. Creating the repository and publishing commits are
separate actions.

## Local setup

Requires Git, Python 3.11+, and Gitleaks 8.30.1. On macOS Gitleaks can be installed using
Homebrew (`brew install gitleaks`); verify the installed version. Upgrades require reviewing
the version pin and rerunning the security tests.

```sh
sh scripts/bootstrap.sh
python3 -m unittest discover -s tests -v
python3 scripts/security_check.py staged
python3 scripts/security_check.py history
```

Bootstrap must run in every clone: Git does not install repository hooks automatically.
The commit hook scans a snapshot of the complete Git index, so partial staging cannot hide
a staged secret behind a clean working copy. The push hook checks all reachable history,
historical sensitive filenames, commit messages, annotated tag messages, and explicit
outgoing object IDs as well as the index.
Scanner output is suppressed to avoid copying sensitive excerpts into logs. A failed scan
needs local investigation with redaction; it must not be bypassed.

## Security boundaries

- No credentials are required to use this harness. Keep real secrets outside this project.
- Documentation uses empty fields or `<REDACTED>` / `<VARIABLE_NAME>` placeholders only.
- `.gitignore` excludes common credential files and local runtime artifacts.
- Commit checks also reject force-added sensitive paths and scan documentation.
- Pre-push checks block detected secrets in history, including subsequently deleted ones.
- Security reviewers are instructed not to edit; that instruction is not a separate sandbox.
  Subagents inherit the parent's permissions. Use the appropriate parent permission mode.

These controls reduce risk; secret detection cannot guarantee that every possible secret
will be recognized. Hooks can be bypassed by a user or software with sufficient access.
Git ignore rules do not encrypt files or prevent filesystem/cloud backup tools syncing them.
The public GitHub origin is configured and its secret scanning and push protection were verified
enabled. Branch protection and required CI checks are not configured yet. CI alone detects
exposure after a push, so it cannot prevent the first upload.

See SECURITY.md and docs/team.md for policy and operating details.

## Sources

- [Building an AI-Native Engineering Team](https://learn.chatgpt.com/guides/build-ai-native-engineering-team)
- [Codex custom subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Gitleaks documentation](https://github.com/gitleaks/gitleaks/blob/master/README.md)

Agent definitions follow the official documentation checked on 2026-10-16.

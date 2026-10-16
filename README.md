# AI-native engineering team

A Codex project with a Chief of Staff, product, design, implementation, independent review,
QA, and documentation roles. This repository currently contains the team harness and
security controls. It does not contain a product application yet.

## Start

Open this directory as your Codex project. Read AGENTS.md. Project agents are defined in
`.codex/agents/`. They run on demand; saving their definitions does not start background agents.
Use a new session if the current one has not discovered the definitions. Loading these
definitions in the installed Codex client still needs to be confirmed in a fresh session.

The primary chat coordinates the team. Example first request:

> Act as Chief of Staff. Have the Product Manager help me define our first product.
> Ask about users, their problem, constraints, and success criteria before choosing a stack.
> Record the agreed brief and delegate specialist work when it is ready.

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
Before using the planned GitHub remote, add server-side push protection and required CI checks
available to the account. CI alone detects exposure after a push, so it cannot prevent the first
upload. No remote hosting, branch protection, or server-side scanning is configured here yet.

See SECURITY.md and docs/team.md for policy and operating details.

## Sources

- [Building an AI-Native Engineering Team](https://learn.chatgpt.com/guides/build-ai-native-engineering-team)
- [Codex custom subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Gitleaks documentation](https://github.com/gitleaks/gitleaks/blob/master/README.md)

Agent definitions follow the official documentation checked on 2026-10-16.

# Security and secrets

## Handling credentials

Store credentials in an approved external secret manager. Applications should receive them
at runtime with least privilege. Prefer short-lived credentials where supported.
Never store real credentials in this repository, including ignored files, documentation,
diagrams, screenshots, test fixtures, commit messages, review reports, or agent transcripts.
Record variable names and provisioning steps, never values. No real credentials are needed
for the team harness or its tests. Tests construct synthetic, nonfunctional values at runtime.

Do not run environment dumps, shell tracing around secrets, or commands that print tokens.
Do not paste secret-bearing scanner reports into Codex. Even redacted scan output needs
review before sharing. Test a product's logging and error paths for accidental disclosure.

## Checks

Run `sh scripts/bootstrap.sh` in each checkout to install hooks. Commits fail closed when
Gitleaks is missing or at an unreviewed version. All indexed files, including docs, are scanned.
Common credential paths, scanner ignore files, archives, symlinks, and submodules are blocked
by policy. Generated binary assets need separate review; scanners do not reliably read
screenshots or every binary format. Never use images to document credential values.

Inline scanner allow comments and local Gitleaks ignore files cannot suppress these scans.
Do not add global allowlists or blanket doc/test exemptions. Only explicit angle-bracket
placeholders or environment variable references are exempted from the extra literal-credential
rule; built-in Gitleaks rules still apply.

The human explicitly selected public visibility for K55Toms/KT_Agent_Dev_and_Dash. The empty
repository and origin are configured; secret scanning and push protection were verified enabled.
Branch protection and required CI checks remain unconfigured. Review changes to hooks, scanner
config, agent instructions, dependencies and CI as security-sensitive changes. Restrict
collaborator access and review the exact commit/destination before publication. Local hooks
are not an enforcement boundary against an actor who can change repository/Git configuration.

## If a credential is exposed

1. Stop the commit, push, or publication. Do not quote the credential in an issue or chat.
2. Tell the responsible human the file location and credential type only.
3. Revoke or rotate the credential at its issuer; deleting text does not invalidate it.
4. Determine exposure across Git history, remote copies, logs, transcripts, and artifacts.
5. Coordinate any history cleanup with repository owners. Do not rewrite shared history
   or force-push without authorization.
6. Rerun scans and add a regression check using a synthetic value. Record a sanitized incident
   summary and remediation evidence.

Report vulnerabilities privately using an agreed channel. No public reporting destination
has been selected for this local project.

## Local dashboard recognition and logs

Runtime SQLite and branding use owner-only files under ignored `.local/`. The application
checks content and native role/task authority on normal ingestion. This is a single-user
trusted-local-process boundary, not a sandbox between agent roles or a tamper-proof ledger.
Agents inherit parent permissions; work on this repository can include access to its runtime
files. A malicious same-user process can bypass normal endpoints by editing local state.
Rebel coins have no monetary value and are not a security attestation. Keep all real secrets
out of prompts, configuration, logs and runtime records regardless of scanner results.

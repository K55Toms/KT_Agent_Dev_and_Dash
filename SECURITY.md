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

Before publishing to a chosen Git host, configure private visibility unless agreed otherwise,
restricted collaborator access, server-side secret push protection where available, and
required security checks with branch protection. Review changes to hooks, scanner config,
agent instructions, dependencies, and CI as security-sensitive changes.
Those remote controls are pending host selection; local hooks are not an enforcement boundary
against an actor who can change the repository or its Git configuration.

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

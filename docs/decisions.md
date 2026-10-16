# Decisions

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

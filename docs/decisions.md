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

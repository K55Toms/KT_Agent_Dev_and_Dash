# Development dashboard design proposal

Status: discovery proposal, not usability-tested. User confirmed multiple projects, local
operation on this Mac, Python/SQLite/browser stack, and live Codex integration in the first
version. A manual activity ledger alone does not meet the requirement.

Use a light, warm-neutral interface with slate text, teal actions and amber attention states.
Keep project selection consistent across Overview, Tasks, Approvals and Costs navigation.
Show source update time separately from the page refresh time; refreshing the page does not
mean the underlying work was updated.

Overview: task-count progress, recorded costs, separate estimates, and pending human decisions.
The main area lists projects and tasks; an attention panel surfaces blocked tasks and approvals.
Never invent progress percentages from agent messages or display missing cost as zero.

Tasks: searchable and filterable by project, status and role. Each task shows title, project,
owner, status and update time. Detail includes the live plan, usage and required decisions.
States follow the runtime contract: queued, running, waiting approval, completed, failed,
interrupted or unknown. Completed means a finished model turn, not independently accepted work.

Costs: each execution shows amount when known, unit, classification, source, observation time
and model when actually observed. Configured role models are not proof of the model used.
Sum reported and estimated values separately and keep different units separate. Explicitly
show incomplete coverage; unknown execution costs are counted, never added as zero charges.

Approvals: pending requests show action, reason, scope, requester, project/task and request time.
The human selected dashboard-managed App Server runs. Show native approval requests from that
runtime with available request-scoped actions only. V1 can decline requests or stop runs;
approval grants need a full-context review flow. Never tell the user to resolve these in an
unrelated desktop chat. A local record alone must never authorize an operation.

Forms use product terms: Add project and Start run. Explain that Start run consumes workspace
usage and may change the explicitly registered project within Codex permissions. Usage and
approval records come from the live runtime, not manual entry or imports in v1. Avoid storage
and implementation details in normal workflows. Never request credentials or raw transcripts.

Empty views invite project/task creation rather than showing fabricated examples. On failure,
retain previously loaded data with a visible error and retry action. Use semantic tables,
labelled controls, text with status colours, keyboard focus, responsive stacking and reduced
motion support. Modal focus returns to the opener; Escape closes dismissible overlays.

## Verified integration boundary

The available Codex chat tools can provide status to agents, but are not automatically callable
from a standalone web application. App Server documentation describes status, plan, usage and
approval events; subscribing to the already-running desktop session has not been demonstrated.
Account-level allowance is not per-task cost. A ledger MVP must be labelled as such and must
not imply a verified live billing or native approval integration.

## Local connection spike, 2026-10-16

The installed CLI (0.141.0) exposes App Server, daemon management and a stdio-to-control-socket
proxy. The Technical Architect checked the default control socket and local socket metadata.
The default control socket was absent and daemon version lookup returned ENOENT. Internal IPC
sockets do not establish supported App Server access and were not connected to. No daemon
was started, no chats were created, and no credentials,
session databases or transcript files were opened during this investigation.

The human chose a dashboard-managed App Server as the v1 integration target. This does not
include pre-existing desktop runtime activity. Observational hooks were investigated but
are outside v1 because they do not establish exact pending-approval resolution or usage.

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Workspace Analytics API](https://learn.chatgpt.com/docs/enterprise/analytics-api)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)

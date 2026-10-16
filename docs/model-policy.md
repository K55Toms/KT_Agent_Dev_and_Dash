# Model routing and cost policy

Status: starting configuration approved by the human on 2026-10-16.
These assignments are recommendations, not benchmark results or measured cost savings.
Workspace administrator controls, available models and session limits take precedence.

## Default assignments

| Role | Model | Reasoning |
| --- | --- | --- |
| chief_of_staff | gpt-6.1-sol | medium |
| product_manager | gpt-6.1-sol | medium |
| technical_architect | gpt-6.1-sol | high |
| backend_developer | gpt-6.1-sol | high |
| ui_designer | gpt-6.1-sol | medium |
| frontend_developer | gpt-6.1-sol | medium |
| platform_reliability_engineer | gpt-6.1-sol | high |
| security_reviewer | gpt-6.1-sol | high |
| code_quality_reviewer | gpt-6.1-sol | high |
| qa_engineer | gpt-6.1-sol | medium |
| agent_evaluation_engineer | gpt-6.1-sol | high |
| technical_writer | gpt-6-luna | high |
| user_documentation_writer | gpt-6-luna | medium |
| expert_escalation (on demand) | gpt-6-astra | low |

The primary chat acts as Chief of Staff and defaults to Sol / Medium. A separate coordinator
is only needed when coordination itself is delegated. Project configuration supplies Sol /
Medium defaults for otherwise unspecified subagents; each custom role pins both settings.
All fourteen profiles were discovered in the active Codex session and specialist roles were
used during dashboard delivery. Availability for dashboard-launched inference and comparative
quality/cost remain unverified; a handshake alone does not establish either.

## Routing

Invoke only roles required for the task. Keep the configured cap of three concurrent children;
the actual session limit takes precedence. Give each agent relevant sources and concise
handoffs, avoiding repeated full-chat context and unnecessary tool output.

Use Standard speed in the session UI where supported. This policy does not force a speed
setting or change administrator permissions. Faster modes need an explicit cost/latency tradeoff.

Luna is appropriate for bounded documentation tasks grounded in verified evidence. For more
complex technical explanations, involve the relevant Sol specialist and return the checked
facts to the writer. Narrow summaries or mechanical edits can be assigned to a general Luna
worker with an explicit model/effort request if that tool supports it. Never mislabel that
worker as a loaded custom role. Do not downgrade independent security review to save credits.

When consequential ambiguity, failed verification or an unresolved defect exceeds a role's
scope, stop blind retries. Give the coordinator evidence and the precise unresolved question.
The coordinator may invoke expert_escalation in the needed specialist capacity. Start Astra
at Low reasoning; any increase should be deliberate and supported by the task.

A custom file's model and effort take precedence over explicit spawn settings. Therefore
route a Sol-to-Astra escalation to expert_escalation, rather than assuming that a spawn
override will change a Sol-pinned role. Runtime selection must be verified from available
session/tool metadata. If unavailable or denied, report it and seek a supported alternative;
never claim the requested model ran without evidence.

Security and code reviewers remain separate from authors regardless of model choice.
An expert reviewing a change must not also implement its fixes without a different reviewer.
Deterministic checks and human judgment establish correctness; model agreement is insufficient.

## Billing and evaluation

The human identified Business or Enterprise workspace billing. The exact agreement and
model access remain unconfirmed. Do not equate API prices, credit rates and included limits.
Use workspace usage evidence when available; mark absent costs as unknown. Do not invent
monthly estimates, savings percentages or token budgets.

Evaluate cost per accepted result, including retries, independent review and human correction.
Use docs/model-evaluation.md before proposing routing changes. No paid batch benchmark or
unbounded workload is authorized by this configuration change.

Official sources checked on 2026-10-16; availability and pricing can change:

- [Model selection](https://learn.chatgpt.com/docs/model-selection)
- [Pricing and credit billing](https://learn.chatgpt.com/docs/pricing)
- [Custom agent configuration and precedence](https://learn.chatgpt.com/docs/agent-configuration/subagents)

# Operating the team in Codex

The primary chat is the Chief of Staff. `chief_of_staff` is available if coordination is
explicitly delegated. All agents inherit the parent model and permission settings.
Custom definitions are project-scoped TOML files, not separate permanently running services.

| Agent | Owns | Output |
| --- | --- | --- |
| chief_of_staff | Sequencing, bounded assignments, dependencies, integration | Task board, decision requests, release evidence |
| product_manager | Users, problem, scope, priorities, acceptance | Agreed product brief and acceptance criteria |
| backend_developer | Data models, APIs, business logic, integrations | Implementation, API contract, relevant tests |
| ui_designer | User journeys, components, visual and accessible interaction | Design spec, states, prototype when useful |
| frontend_developer | Implementing the agreed UI and API integration | Working UI, interaction tests, visual verification |
| security_reviewer | Threat model and independent security review | Evidence, impact, severity, remediation and retest |
| code_quality_reviewer | Correctness, maintainability, error handling | Actionable findings with locations and evidence |
| qa_engineer | Acceptance and adversarial behavioural testing | Criteria-to-test evidence and failures |
| technical_writer | Developer setup, APIs, architecture, runbooks | Verified technical documentation |
| user_documentation_writer | User guidance and release notes | Instructions matching delivered behaviour |

Use only the roles a task needs. Queue tasks within the session's available concurrency.
Writers can share the documentation workload sequentially or own separate files.
Reviewers never approve their own implementation. If a reviewer helps implement a fix,
use a different reviewer for that change. Agent agreement alone is not test evidence.

## Task handoff

Each assignment contains: objective; authoritative inputs; file ownership; dependencies;
acceptance criteria; required checks; expected outputs; unresolved questions.
Responses contain: result; files changed; checks run and outcomes; findings; limitations;
next owner. Use sanitized excerpts, never credential-bearing command output.

## Delivery gates

1. PM resolves product ambiguities with the human; record scope and measurable acceptance.
2. Design and engineering agree on interactions, API contracts, and architecture. Involve
   security early for authentication, sensitive data, integrations, and trust boundaries.
3. Implementers own disjoint changes and meaningful tests. Chief of Staff integrates them.
4. QA checks acceptance independently. Reviewers inspect current changes and report findings.
5. Implementers fix issues; reviewers verify fixes. Run repository security checks.
6. Writers verify docs against actual behaviour and use placeholders only.
7. Chief of Staff reports delivered behaviour, checks, open risks, and release readiness.
   The human owns release approval; no deployment or remote publication is implied.

Project status and decisions must survive a chat ending. Keep docs/task-board.md and
docs/decisions.md current. Do not choose product features or a technology stack until agreed.

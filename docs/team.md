# Operating the team in Codex

The primary chat is the Chief of Staff. `chief_of_staff` is available if coordination is
explicitly delegated. Roles pin their model and reasoning; permissions follow the parent session.
Custom definitions are project-scoped TOML files, not separate permanently running services.
In the dashboard, open **Team** and click **Details** on an agent's card to read its configured
personal prompt. This read-only display preserves formatting and checks content before showing
it. Shared security instructions and task-specific guidance are additional run context.
The primary chat defaults to GPT-6.1 Sol / Medium in project configuration. Existing sessions
may keep their selected model; confirm the active model in Codex. See docs/model-policy.md.

| Agent | Owns | Output |
| --- | --- | --- |
| chief_of_staff | Sequencing, bounded assignments, dependencies, integration | Task board, decision requests, release evidence |
| product_manager | Users, problem, scope, priorities, acceptance | Agreed product brief and acceptance criteria |
| technical_architect | Cross-system architecture, contracts, migrations | Design decisions and bounded implementation handoffs |
| backend_developer | Data models, APIs, business logic, integrations | Implementation, API contract, relevant tests |
| ui_designer | User journeys, components, visual and accessible interaction | Design spec, states, prototype when useful |
| frontend_developer | Implementing the agreed UI and API integration | Working UI, interaction tests, visual verification |
| platform_reliability_engineer | Secure delivery, environments, monitoring, recovery | Validated pipelines, operational and rollback evidence |
| security_reviewer | Threat model and independent security review | Evidence, impact, severity, remediation and retest |
| code_quality_reviewer | Correctness, maintainability, error handling | Actionable findings with locations and evidence |
| qa_engineer | Acceptance and adversarial behavioural testing | Criteria-to-test evidence and failures |
| agent_evaluation_engineer | Agent routing, handoffs, quality and cost evaluation | Comparable trials, regression evidence and recommendations |
| technical_writer | Documentation impact review for every task; developer setup, APIs, architecture, runbooks | Verified technical documentation and task closeout |
| user_documentation_writer | User guidance and release notes | Instructions matching delivered behaviour |

There are thirteen core roles. An additional expert_escalation profile provides bounded
Astra assistance when the coordinator explicitly escalates a difficult problem.
PM and UI jointly own usability research. QA includes relevant accessibility, performance
and recovery checks. Add data, privacy/compliance or ML specialists when product scope requires.

Use roles in proportion to the change, within the session's available concurrency. For every
development task, involve `technical_writer` at intake, during verified changes, and before
completion. A small task may use a bounded impact review and brief closeout. Record the
documentation impact, owner and expected evidence in the handoff or task board. When no
document needs changing, the writer records the reviewed rationale and guidance checked.
Missing writer review is an open gap, never a passed gate or silent waiver.

`technical_writer` reviews documentation impact for every task and owns developer-facing
changes to setup, configuration, APIs, architecture, operations, recovery, or limitations.
Assign `user_documentation_writer` when delivered behaviour changes user tasks, visible
controls, recovery guidance, or release notes. Coordinate file ownership and sequence the
work where both writers are needed. The Chief of Staff owns docs/task-board.md and
docs/decisions.md, including sanitized delivery evidence, decisions, open gaps and follow-up
owners. Writers own only the documentation files assigned to them. Engage writers during
implementation when behaviour or contracts are changing, then verify their documentation
against the integrated result before completion.

Agent quality is an ongoing, independent workstream owned by `agent_evaluation_engineer`.
Assign the evaluator at intake and invoke them at development checkpoints and before every
task completion. Focus evaluation on routing, handoffs, original user journeys, review and
retest evidence, documentation coverage, and any affected agent roles, prompts, tools,
permissions, or evaluation controls. Retain sanitized assessments in docs/model-evaluation.md
and route findings to named owners for fixes and retests. Small tasks may use bounded
checkpoint and closeout reviews; they do not skip evaluator involvement. If the evaluator is
unavailable or a review is unrun, record the gap and next owner. Missing evaluation is never
a passed gate or silent waiver. These task-triggered reviews are not background jobs or
scheduled work. Agent Evaluation assesses workflow quality separately from product QA, which
tests product acceptance and behaviour.

Writers can share the documentation workload sequentially or own separate files.
Reviewers never approve their own implementation. If a reviewer helps implement a fix,
use a different reviewer for that change. Agent agreement alone is not test evidence.

## Task handoff

Each assignment contains: objective; authoritative inputs; file ownership; dependencies;
acceptance criteria; required checks; expected outputs; unresolved questions; documentation
impact, technical-writer checkpoints and evidence expected; whether user documentation applies;
and evaluator checkpoints. Responses contain: result; files changed; checks run and outcomes;
findings; documentation sources and validation; unverified documentation gaps; evaluation
evidence or explicit unrun status and gap owner; limitations; next owner. Use sanitized
excerpts, never credential-bearing command output.

## Delivery gates

1. PM resolves product ambiguities with the human; record scope and measurable acceptance.
2. Technical Architect, design and engineering agree on interactions, API contracts, and architecture. Involve
   security early for authentication, sensitive data, integrations, and trust boundaries.
3. Implementers own disjoint changes and meaningful tests. Technical Writer joins every task
   at intake, during verified changes and at closeout; User Documentation Writer joins when
   user behaviour changes. Chief of Staff integrates them.
4. QA checks product acceptance independently. Reviewers inspect current changes and report
   findings. Agent Evaluation checks agent workflow quality at development checkpoints and
   before completion under docs/model-evaluation.md; it does not substitute for product QA or
   review. Missing or unrun review remains an open gap.
5. Route findings to the responsible implementer, record the owner and disposition, then
   obtain reviewer, QA or evaluator retest evidence for the affected criteria. Run repository
   security checks.
6. Writers verify assigned docs against the integrated behaviour, authoritative sources and
   executed evidence, using placeholders only. Record sources, checks actually run, limitations
   and unverified instructions. The Chief of Staff records the docs impact and closure or
   follow-up in shared project records. Platform & Reliability supplies operational readiness
   and recovery evidence for releases.
7. Before completion, the Chief of Staff obtains Technical Writer closeout, applicable User
   Documentation Writer closeout, and Agent Evaluation closeout. Each records evidence,
   limitations and open gaps with owners. Missing or unrun documentation or evaluation review
   stays an open gap; it cannot be treated as a passed gate or waived silently. Report
   delivered behaviour, checks, risks and review status. The human owns release approval; no
   deployment or remote publication is implied.

Agent Evaluation uses docs/model-evaluation.md to keep a continuing record of representative
trials, regressions, findings, fixes and retests across task checkpoints. Recommendations
remain provisional until representative tasks have been evaluated; report gaps rather than
presenting planned or unexecuted evaluation as evidence.

Project status and decisions must survive a chat ending. Keep docs/task-board.md and
docs/decisions.md current. Do not choose product features or a technology stack until agreed.

# Agent model evaluation

Status: evaluation protocol prepared; no comparative model trials have been run.
Owner: agent_evaluation_engineer. Coordinator: Chief of Staff.

## Method

Use representative, bounded tasks after the product is defined. Agree the rubric before
running candidates. Keep task inputs, available tools, permissions and acceptance criteria
equivalent. Record the exact model, reasoning effort and speed actually observed.

Candidate tasks:

| Task | Ground truth / acceptance |
| --- | --- |
| Define a feature from an incomplete brief | Explicit uncertainties, agreed scope, testable criteria; human product review |
| Implement a backend change | Functional and negative-path tests, API contract, independent review |
| Implement a UI interaction | Behaviour and accessibility checks, visual verification where available |
| Review a change containing seeded defects | Known synthetic defects found, false positives recorded, reproducible evidence |
| Assess secret-handling controls | Synthetic leaks blocked without disclosure; existing security regression suite |
| Write setup documentation | Instructions independently executed in a clean test environment |
| Coordinate a multi-role task | Correct routing, bounded ownership, no lost handoffs, verified deliverables |

Do not use real credentials, customer records or production incidents as raw fixtures.
Store only sanitized evidence. Discard sensitive tool output rather than copying it here.
Keep assessor separate from author; do not let an LLM-generated score alone determine success.

## Trial record

For each trial record:

- Task/version and acceptance rubric.
- Candidate role, observed model, reasoning, speed and environment.
- Relevant input sources and checks.
- Acceptance outcome and specific defects/missed defects.
- Retries, human corrections and independent review effort.
- Elapsed time and observed usage/cost, or unknown if unavailable.
- Limitations, confounders and decision.

Do not infer reliability or savings from a single success. Repeat across representative
tasks as warranted, without inventing statistical confidence. Keep security gates intact.
Only recommend a cheaper route when it meets the agreed quality baseline. Escalate unresolved
quality/cost tradeoffs to the human; do not silently rewrite the model policy.

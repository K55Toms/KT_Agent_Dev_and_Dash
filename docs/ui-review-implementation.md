# UI review implementation ledger

## Independent validation — 2026-10-26

The agreed P0–P3 functional paths are present in source, but validation is partial and
the implementation is not an unconditional completion of every review recommendation.
Independent QA freshly ran 113 focused Python tests (Outputs, UI HTTP acceptance, approvals,
native-shaped acceptance, delivery backend and conversation acceptance) and all 126 Node
tests; all passed without skips. These are synthetic HTTP/protocol/DOM checks. No application
source or production records were changed during this validation.

Open findings and owners:

- Backend/Frontend: `dashboard/task_outputs.py` retains an old same-path association when its
  digest changes, then appends the replacement. `app.js` recommends reassociation and removes
  old entries only optimistically. Refresh restores duplicates; eight registrations exhaust
  capacity and block the recommended recovery. This is source-traced, not a fresh executed
  reproduction. Retest changed-file reassociation, reload and replacement at capacity.
- Frontend/UI Designer: task details show title/path and an intermediate **Open task outputs**
  action; the original direct **Open report** proposal is not implemented there. Resolve whether
  this extra navigation satisfies the intended journey. Broader modal hierarchy proposals
  and the refresh measurement task remain unvalidated.
- Technical Writer: document the implemented Outputs attach/preview endpoints and operator
  limits in API/operations guidance. User Documentation Writer: reconcile approval-guide URL
  instructions with the supported explicit external-completion acknowledgement in source/API.

Earlier writer/evaluator closeout receipts were received, as recorded in the task board and
EVAL-2026-10-26-03 addendum; this pass identifies new documentation gaps rather than reopening
those receipts silently. Chief of Staff owns follow-up and QA owns independent retest.

Fresh browser validation could not run: no browser surfaces were available and Computer Use
did not approve Safari access. Changed-data scroll with real wrapping/selection, live native
approval continuation/completion, responsive/modal inspection, accessibility and performance
remain unverified. Fixed-height DOM fixtures cannot establish those browser outcomes.

## Approval parity steering — 2026-10-26

The human supplied another unsupported-request screenshot and requires native Codex requests
to show their actual context and approve/reject choices in the dashboard. The P0 stop/close
repair remains appropriate only for methods the installed server genuinely does not support.
Technical Architect verified the installed CLI 0.163.0 generated experimental schemas and
[official App Server documentation](https://learn.chatgpt.com/docs/app-server): native
permission approvals, permission-related `item/tool/requestUserInput`, and
`mcpServer/elicitation/request` have distinct payload and response contracts. The screenshot
alone does not reveal which method fired or where the request was ultimately resolved.

The human accepted that external sign-in and device verification may require an explicit human
step (“Human steps are good”). The dashboard shows the request context and native negative
choices, does not auto-open external URLs, and does not manufacture verification proof.
Permission grants are manual and turn-scoped; the UI labels them **Approve for this turn**.
The screenshot itself cannot identify the original method or show where it was resolved.

Status: implementation and synthetic verification complete; a live native App Server
continuation was not run. This ledger records delivered behavior and the evidence boundaries
for [the UI outcomes review](../design-plans/ui-outcomes-review.md) and
[Lina's follow-up](../design-plans/lina-ui-review.md).

## Agreed plan

| Priority | Scope and acceptance | Owners | Evidence still required |
| --- | --- | --- | --- |
| P0 | Preserve conversation reading position through changed-message/metadata refreshes; support scoped reviews for command/file, turn permissions, permission-related tool questions, and supported MCP form/URL requests. Keep unknown schemas and device proof blocked with a human path. | Frontend, Backend, Architect, Security and QA. | 83 focused Python tests after schema hardening, 126 Node UI tests, and Safari synthetic native-shaped request/response exercise passed. **No live native continuation was run.** Device verification remains in Codex. |
| P1 | Explicit, persistent task/turn Outputs with scanner-checked preview and distinct missing/changed/blocked states. | Backend, Frontend, Security, QA. | Positive association/open, reload persistence, changed/missing/scanner/path-race and cross-task checks passed synthetically. No output establishes delivery acceptance. |
| P2 | Complete decision accounting, explicit filter-clearing action, filtered counts and question-specific wording. | Frontend and QA. | UI suite passed; no separate live run was used to force a decision update. |
| P3 | Historical delivery readiness shown as supporting evidence without per-row snapshots; detail action remains freshly validated. | Backend, Frontend and QA. | Backend/UI checks passed; no performance gain is claimed. |
| Measure | Measure refresh cost and focus/read-position effects before further optimization. | Frontend, QA, Agent Evaluation. | General request/render performance benchmark remains unmeasured; no target or savings claim. |

## Intake evidence and limits

- The two review reports document source analysis, a supplied approval-modal screenshot, and a coordinator-observed narrow-viewport browser session. The browser session verified unchanged-conversation refresh position only; changed-message behavior was not reproduced live.
- The reports identify the unsupported approval loop from current source and screenshot evidence. The exact originating method remains unknown. Genuinely unknown or malformed methods must remain unapprovable, while schema-supported request families receive their native review and response flow.
- Output registration and task/project association are implemented with explicit association and scanner-checked preview. A plain-text path in a conversation is not verified artifact association.
- Broader visual hierarchy proposals remain proposals until rendered states are inspected. The reviews establish no accessibility conformance, performance gain, human-efficiency result, or full-dashboard visual sign-off.
- Final reported verification: the Python suite discovered 584 tests (548 passed and 36 skipped); 83 focused Python tests passed after schema hardening; 126 Node UI tests passed with no skips. A Safari exercise used synthetic native-shaped requests and verified the expected response payloads and human-step UI. This is rendered synthetic evidence, not a live App Server round trip.
- Independent Security's earlier four synthetic Outputs authorization, path-race and persistence checks passed. These were separate from product QA and did not test live native continuation.
- The 2026-10-25 browser receipt remains historical: it verified unchanged-message scroll position only. Changed-message behavior is covered by the later reported UI suite, but no real active run was used to force a live update. No full accessibility audit, general performance benchmark, paid model run or native continuation was performed.

## Documentation impact

Technical Writer updated this ledger and the API/operations references against the delivered
handlers and recorded verification. User Documentation Writer owns user-facing instructions for
Outputs and the new approval choices. The Chief of Staff owns shared task-board and decision
records. Earlier closeouts were received; the independent validation above records newly
identified documentation gaps and their owners.

## Handoff and closeout record

The agreed order was P0 reading position/native request parity, P1 safe persistent Outputs,
P2 complete decisions, P3 non-authoritative readiness, then measurement. Stop/close remains the
available path for unknown or malformed methods. API and operations documentation now describe
the implemented request kinds and limits. Remaining evidence limits are live native
continuation, broad accessibility review and performance measurement; none is represented as
passed.

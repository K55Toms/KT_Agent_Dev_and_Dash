# Lina Cass: UI review follow-up

Date: 2026-10-25. Reviewer: the project UI Designer role, whose crew identity is Lina Cass. Recommendation-only review; no application changes.

## Evidence

I read the existing [UI/outcomes review](ui-outcomes-review.md), the installed UI Skills root and improve-ui guidance, relevant project security instructions and the current approval rendering source. The coordinator reported that offline catalogue routing failed with `ENOTCACHED`; I did not repeat that attempt, install anything or claim CLI-selected skill loading.

I visually inspected the user-supplied `Screenshot 2026-10-25 at 17.54.18.png`. Its image dimensions are 1962 × 770 pixels; the browser viewport, zoom, route and capture conditions are unverified. It shows the actual approval modal for UI Review/Lina Cass. Its dark blue palette is consistent with the project's selected theme, but the configured runtime theme was not independently read. No secret reveal or native action was performed.

The earlier browser attempt was blocked. This screenshot establishes rendered evidence for this modal only. Overview, task rows, output cards and responsive layouts remain source-only proposals. It does not establish current request liveness, the exact originating native method, accessibility conformance, performance or human task completion.

## Verdict on the recommendations

| Recommendation | Verdict | Refinement |
| --- | --- | --- |
| Completed-task Outputs | Put first as the explicit human requirement. | Present the actual deliverable title/path with one direct safe Open report action. A completed report-writing task is not useful until the human can inspect its result. Preserve missing/blocked/changed states and distinguish output availability from accepted delivery. |
| Complete decision queue and question wording | Keep, and include correct request-type presentation. | A complete queue also needs an honest action for each type. Unsupported requests must not invite an approval review that can never succeed. Filter scope and remaining counts still matter. |
| Delivery readiness in task triage | Keep as secondary evidence. | Do not give execution status, readiness and report-opening three competing primary treatments. Task/result first, one output action, then supporting execution/readiness facts. This hierarchy is a proposal until task rows are rendered. |
| Refresh efficiency | Keep as a measurement task after completing the journeys. | Measure focus behavior and request/render costs. A screenshot cannot justify a polling rewrite or an efficiency claim. |

The screenshot's approval dead end deserves correction before polishing the decision modal. Outputs remains the highest requested outcome addition; the dead end is an existing workflow defect, not a substitute for Outputs.

## Urgent follow-up: conversation refresh loses the reading position

The human now directly reports being unable to read the conversation because scrolling to the bottom is followed by a refresh returning the view to the start. This is user-reported usability evidence, not an invented visual hypothesis. Reading-position stability should be addressed before cosmetic improvements or speculative refresh optimization. The root agent is checking the live browser; I have not personally reproduced the reset in this child context.

**Source explanation:** [app.js](../dashboard/static/app.js), `renderConversation()` at line 587, removes all children of `#conversation-content`. Line 589 then creates a new `.conversation-log`; [styles.css](../dashboard/static/styles.css), line 1327, makes that log a separate scroll container with `max-height:520px` and `overflow-y:auto`. The renderer saves and restores drafts, focused form fields and caret position, but does not capture or restore the old log's scroll position or visible message anchor (line 609). Replacing the scrolled element therefore loses its reading-position state.

`loadConversation()` at line 562 includes the whole selected task, approvals and connection state in its render signature, as well as the conversation result. A task metadata update can therefore rebuild the log even when the message list is unchanged. The visible-page loop polls every three seconds (line 1287). Counterevidence: a genuinely unchanged full signature skips rendering; the source does not establish that every poll resets the reader.

**Proposed behavior:** keep the current reading position on unchanged-message polls and on updates while reading older content. Follow new content only if the reader was already at the bottom; otherwise retain the visible message and show an explicit “Jump to latest” action. Preserve page scroll as well as the inner log position. Switching to another task is a separate intentional navigation state; it must not accidentally inherit an unrelated task's scroll position.

**Smallest complete design direction:** preserve the existing message-log element when only controls or task metadata change. When messages must change, retain a stable visible-message anchor and offset; use bottom-follow only for a reader already following the latest messages. Retain existing draft/caret safeguards and safety-disabled actions. Do not disable polling or drop required approval/freshness updates merely to conceal the reset.

**Required acceptance:** a long conversation stays at the same message while polls return unchanged messages, a new message, or a task-status/usage update. At the bottom, new content follows only under the agreed follow-latest behavior. Away from the bottom, new messages do not pull the reader elsewhere and “Jump to latest” works. Test page and log scrolling, selection/copy, draft/focus retention, task switching, and failure/recovery without sending duplicate messages. [test_conversation_ui.js](../tests/test_conversation_ui.js), lines 113–119, checks draft/focus/caret preservation but does not assert scroll stability; it must not be cited as coverage of this problem.

**Owners:** Frontend implements the reading-state correction; Lina specifies the follow-latest behavior; independent QA verifies actual browser scroll plus regression checks. This report does not implement the fix. The later root-browser receipt below checks unchanged refresh; changed-message live reproduction remains unexecuted.

### Later root-browser receipt — 2026-10-25

The coordinator successfully inspected `http://127.0.0.1:8765/` in the root chat's browser. This child context still could not access either `iab` or the root-observed browser ID, so the following is explicitly **root-observed browser evidence supplied to Lina**, not my personal live browser inspection. The coordinator viewed the actual screenshots; I received the verified observations and DOM measurements.

- Browser viewport was 692 × 900 CSS pixels, read from `window.innerWidth`/`innerHeight`. The footer explicitly displayed Hybrid Night Shift. This was the production dashboard with existing records, not a synthetic fixture; Codex was connected, with nine tasks and no active runs or pending decisions.
- Overview displayed horizontally overflowing navigation and a two-by-two metric grid. At this viewport the metrics occupied most of the initial view before Task activity, which began around vertical position 805 pixels. The completed UI Review row had no output action.
- The selected UI Review conversation contained 75 messages in `.conversation-log`, whose `clientHeight` was 520 and `scrollHeight` was 16039. It initially had `scrollTop:0`. The coordinator scrolled to the bottom (`scrollTop:15518.5`, page scroll position `771.5`), then used Refresh conversation on the unchanged completed transcript. The log remained at `scrollTop:15518.5`.
- This live check is important counterevidence: **unchanged refresh preserved the reading position**. No new message or active-task metadata update was provoked, and no run or message was started to manufacture the reported reset. The changed-signature issue remains user-reported and source-explained rather than freshly reproduced live.
- The root screenshot showed a fixed-height message log within a separately scrolling page. The latest message contained the Markdown report path as plain text rather than an actionable report link. This supports the requested direct Outputs action; it does not prove that every recorded path is a verified artifact association.

**Lina's interpretation of the coordinator's observations:** prioritize preserving the current message/anchor and page position; follow new content only if the reader was already following the bottom, otherwise offer Jump to latest. The nested scrolling layout makes reading-state protection especially important. At the inspected narrow viewport, a compact summary or earlier task/decision content is a visual proposal worth testing, because the metric grid precedes the working content; no desktop-wide density claim follows from this one viewport. The plain-text report path reinforces the need for a clear Open report affordance. Keep these proposals distinct from the observed measurements and from implemented behavior.

No application code, settings, approvals, tasks or conversation messages were changed during this review. No performance target, accessibility result or efficiency gain is inferred from the browser receipt.

## Design language

- Audited surface: the supplied production approval modal; broader task/decision recommendations reviewed from source.
- Design sources: [index.html](../dashboard/static/index.html), [app.js](../dashboard/static/app.js), [styles.css](../dashboard/static/styles.css), supplied screenshot and [accepted appearance decisions](../docs/decisions.md).
- Documented decisions: preserve the selected dark visual identity, exact-request authority, distinct stop/decline behavior, and separate execution/delivery states.
- Governing owners and consumers: `openApprovalReview()`, `checkApprovalReview()`, `#approval-review-dialog`, existing banner/button/dialog styles and theme variables.
- Explicit exceptions: None documented.

## Findings

| # | Problem | Evidence | Proposed change | Scope | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | The modal tells the human to use Approve once although this request type cannot use approval. | The screenshot shows the unsupported-flow heading, the instruction to use Approve once and disabled approval. [app.js](../dashboard/static/app.js), lines 313–321, supplies the same generic mode guidance for every kind, while line 267 accepts only command/file-change kinds. [server.py](../dashboard/server.py), lines 923–936, classifies other kinds as unsupported input. | For unsupported kinds, replace the approval-mode instruction with a direct explanation that this request cannot be approved here and identify the available stop/close path. | State-specific copy in the existing modal. Functional routing repair is separate. | High for the visible contradiction; effect on comprehension has not been measured. |

## Improve first

Correct the unsupported-state explanation. Reopening or changing future approval mode cannot make that request approvable, so the interface must not prescribe those actions as the solution.

## Visual proposals

These are professional design recommendations based on the screenshot, not newly established binding design rules.

1. **Put the current blocker and next usable action first.** The screenshot's largest colored region is a generic warning, while the actual unsupported-state explanation is lower down and says the review is no longer live. Use the current-state explanation as the leading status block. Keep the task/agent association visible. Proposal owner: UI Designer/Frontend; source owners: `#approval-review-status` and the existing banner style. Acceptance: an unsupported example clearly states why approval is unavailable and which action is usable before generic policy context.

2. **Move future settings and detailed disclosure into supporting hierarchy.** The future-approval configuration button currently sits above the current decision content and competes with resolving the blocker. Keep required risk information available and visible where relevant; present future-policy controls as secondary settings, separate from this request's resolution. Use existing typography and controls rather than another panel system. Acceptance: the current request's state/action leads the reading order; future settings are clearly labeled as future-only and do not suggest they can resolve the current unsupported request. Security should review any disclosure rearrangement; this proposal does not remove required information.

3. **Make the footer match the request state.** An unsupported request has no usable Approve once path. Present Close and the supported explicit stop action with their consequences; do not leave an approval affordance implying that refresh will eventually enable it. In supported review states, preserve the existing full-context review and one-time approval flow. Acceptance: compare supported, unsupported, loading, stale and disconnected examples; each presents only its correct decisions and explains blocked actions without prescribing an impossible retry. Preserve focus return and keyboard operation during implementation.

Keep the dark palette, brand, existing type family and button vocabulary. There is no evidence here for a new theme, framework, decorative layer or wholesale redesign. Do not infer contrast compliance or mobile usability from this screenshot.

## Loop explanation: evidence boundary

Current source corroborates the coordinator's diagnosis: Overview's `renderAttention()` routes every non-question decision into `openApprovalReview()` (app.js line 217), but `approvalStillLive()` excludes unsupported kinds (line 267). The state check consequently invalidates the review and prescribes refresh/reopen (line 282); opening it again repeats the condition. Automatic policy also skips unsupported requests (server.py lines 322–334).

The UI should distinguish unsupported capability from an expired request. This source path explains the repeatable dead end; I did not reproduce it in a live browser or identify the exact upstream method in this historical request. No assertion is made that Lina's request was caused by browser discovery or a particular command.

The initial screenshot pass skipped live browser/native execution, responsive checks and performance measurement. The later root-browser receipt covers one live narrow viewport and unchanged conversation refresh only. Modal proposals still need rendered state comparison and independent journey QA after implementation; changed-message reading-position behavior remains unverified live.

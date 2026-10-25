# Assessment handoff contract

Status: implemented contract, locally applied 2026-10-25. The human approved a first-class recovery feature:
prepare checked evidence, assess it in an existing approved chat, return and review the assessment,
then separately approve development continuation. This document defines that route. Source tests, independent reviews and local browser checks
are recorded in the task board; external-chat provenance and real native continuation remain
unverified.

## Journey and authority

1. **Prepare evidence** uses explicitly selected checked local messages, normalized recovery
   observations and a fresh question. It performs no authentication, native call or inference.
2. Preview the exact plain-text **Assessment packet**. **Copy checked packet** explicitly copies
   those checked bytes; offer manual selection when clipboard access fails. Copy does not send
   messages, open a destination, prove delivery or mark an assessment complete.
3. The human pastes it into their existing approved chat and discusses recovery there. The packet
   requests assessment only, distinguishes quoted historical instructions from current guidance,
   and asks for facts, uncertainties and a proposed fresh plan. The dashboard neither controls nor
   attests that chat's account, model, tools or behavior. It does not observe the external discussion.
4. **Check and preview returned assessment** accepts a pasted plain-text response, scans the entire raw value
   before normalization/persistence/display, and shows it bound to the original packet. State:
   **Human-supplied external assessment; source, model, tools and usage unverified.**
5. **Accept reviewed assessment** is a separate explicit local human decision about the exact
   packet and response. It satisfies the assessment prerequisite, never activity clearance,
   native permissions, task completion or approval of a development plan.
6. Existing **Review continuation** and **Approve and continue development** remain distinct,
   with all current directory, boot, ownership, activity, overlap, role/profile, exact-plan and
   Manual native request gates. Same-thread restoration stays disabled.

This is a general assessment handoff feature. Corporate policy history belongs in dated project
records, not its product rationale or permanent UI. Keep the optional existing OAuth assessment
route available; handoff does not authenticate it or impersonate its transport/epoch.

## Records and projection

No native/model task or turn is fabricated. The implementation stores private local
`recovery_handoff` records with bounded immutable logical response and acceptance records
embedded as audit arrays; these are not separate database kinds:

- `recovery_handoff`: server ID, origin task/project IDs, version, creation time, status, immutable
  packet bytes/digest, semantic snapshot/digest, selected message IDs/content digests, current
  response ID/version and accepted-result reference. Packet bytes never change under an ID.
- Embedded response: server ID, response version, checked exact text,
  full-text digest, packet digest, creation time, fixed human-supplied provenance. Each paste
  creates an immutable response; older replies remain historical and cannot regain acceptance.
- Embedded acceptance: exact handoff/packet/response/digests/versions/snapshot, local
  human-review source and time. It is a decision about evidence, not an external attestation.
- A bounded local idempotency ledger binds operation ID, origin and exact request digest/result.
  These synchronous local operations never enter the native pending-dispatch state machine.

Creation starts handoff `version:1`; every response replacement and acceptance increments
handoff version and recovery revision atomically. Response version increments only on paste.
`awaiting_return` -> `needs_review` -> `accepted`; material evidence change projects `stale`.
A new packet round supersedes prior acceptance and invalidates any existing continuation plan
atomically. Replacing a response likewise revokes acceptance and the plan before returning.
There is no fallback to an earlier accepted response when the current round is incomplete.

GET recovery adds the following bounded metadata, excluding packet/response bodies:

```text
handoff: null | {
  id, version, status, packet_digest, snapshot_digest, stale,
  response: null | {response_id, response_version, response_digest, status}, accepted_at
}
capabilities.assessment_handoff: boolean
actions.handoff_prepare, actions.handoff_response, actions.handoff_accept: boolean
```

`status` is `awaiting_return|needs_review|accepted|stale`; response status is
`unreviewed|accepted|superseded`. Action booleans describe current availability, not authority.
All endpoints independently enforce their conditions and content checks.

The normalized assessment summary supports `source:"handoff"`, `assessment_id`, `task_id`,
`status`, `result_revision` and provenance. For compatibility, `task_id` is an opaque alias of
the handoff assessment ID; **no task exists under that ID**. Existing `assessment_task_id`
request fields remain aliases of this canonical assessment reference. Resolve by source,
never by assuming every assessment ID can be looked up in `tasks` or `/conversation`.
Handoff `status:"reviewable"` requires the current accepted response and matching snapshot.
Its `result_revision` hashes accepted packet/response versions+digests and snapshot. A pending
handoff is not reviewable. Never attribute handoff text to a verified agent, award it recognition,
or report observed tokens/cost. Historical original outcomes remain unchanged.

## Exact API

Routes are relative to `/api/tasks/{origin_id}/recovery`. Existing loopback/Host/Origin guards,
JSON Content-Type, 65,536-byte HTTP request limit, fixed safe errors and no-store responses apply.
IDs are server-assigned lowercase 32-hex; digests are lowercase SHA-256 hex. Strict booleans and
nonnegative bounded versions reject bool-as-int and unknown fields. `expected_revision` means
the current recovery revision; `expected_handoff_version` means the current handoff version.

| Route | Exact input / result |
| --- | --- |
| `POST /handoffs` | `{expected_revision,operation_id,selected_message_ids,text,confirmed:true}`. Prepare a new round from checked local evidence. Returns authoritative recovery projection. |
| `GET /handoffs/{id}` | Returns the exact rescanned preview shape below. This is the preview/copy and response re-review path; it never accepts anything. |
| `POST /handoffs/{id}/responses` | `{expected_revision,operation_id,packet_digest,expected_handoff_version,text,confirmed:true}`. Scan raw paste, persist a new response, revoke prior acceptance/plan. Returns authoritative recovery projection. |
| `POST /handoffs/{id}/accept` | `{expected_revision,operation_id,packet_digest,expected_handoff_version,response_id,response_digest,response_version,review_id,confirmed:true}`. Require the exact current preview receipt and explicit human review; atomically persist acceptance and invalidate any older plan. Returns authoritative recovery projection. |

Preview response:

```text
{
  task_id, handoff_id, version, packet_text, packet_digest, snapshot_digest, stale,
  response: null | {
    response_id, response_version, response_digest, text, status, review_id
  }
}
```

Every POST returns current recovery projection; the browser then GETs the preview for exact
body/review fields and uses the new authoritative recovery revision and handoff version on the
next mutation. A Copy click obtains a fresh GET preview before writing exactly `packet_text`
to the clipboard. The packet digest hashes those complete UTF-8 bytes; show digest separately
instead of recursively embedding a digest in its own hashed body. Browser DOM uses plain text,
never Markdown/HTML execution, model-supplied URLs or auto-navigation.

The same operation ID and exact payload return the saved/current result without another mutation;
the same ID with any changed payload or origin returns 409. Check idempotency before stale-revision
rejection so a successful request with lost HTTP acknowledgement can be reconciled. Conflicting
tabs/versions return 409 and retain drafts. No automatic resubmission after uncertainty.

Limits: at most 20 unique selected available messages from the origin task; question 12,000
characters; returned response 16,000 characters. Validate raw sizes/control characters and scan
before trimming. Final rendered packet is limited to 49,152 UTF-8 bytes and scanned as a whole;
oversize returns a safe request to select fewer messages, with no truncation. Exclude credentials,
raw native transcripts/errors/tools/reasoning, local absolute paths, role prompts, unrelated
task messages and sensitive-reveal content. Use safe project display name/opaque IDs, task
status, normalized checked observations and explicit coverage gaps. Native thread IDs are not
needed in the exported packet. Every preview rescans packet and response under current scanner
policy; scanner absence/failure withholds bodies and blocks acceptance without deleting history.

Storage caps are 8 retained rounds per origin, 128 globally, 16 returned responses and
64 durable operation bindings per round. The current round counts toward these limits. Never silently evict the active round, accepted result supporting a plan, or current
idempotency binding. At the cap, return a safe capacity error rather than discard authority or
substitute another result. Historical pruning must atomically revoke related review receipts
and cannot make an old operation ID reusable. No unbounded retention is part of this contract.

## Snapshot validity, offline operation and restart

Handoff is a long human round trip. Its packet has no short time-based expiry. Its semantic
snapshot contains origin task outcome/identity/lineage, registered project identity and safe
binding availability, relevant known message contents, normalized activity findings/coverage/
reasons and relevant observed child identities/statuses. Explicit selected text is scanned again;
changes to known evidence must not be hidden by selecting a smaller subset of old messages.

Exclude observation timestamps, check/recovery bookkeeping revision, client object identity,
connection/assessment epoch, review receipts and internal recovery hold-transfer fields. A pure
refresh, backend restart or final transfer of a checked hold therefore does not invalidate a
reviewed assessment. Fresh native execution authority is a separate existing short-lived gate.
Normalize fixed reasons/findings and sorted child sets so ordering changes are not material.
Meaningful task/message/activity/project changes do make the result stale. The implementation
must enumerate these fields explicitly rather than hashing the whole mutable recovery record.

Compare the current local semantic digest on response import, accept, plan creation and final
dispatch. Old text remains previewable and discussable if stale, clearly labelled historical;
it cannot satisfy the plan/dispatch gate. Import rejects a stale returned response without saving it. A previously stored stale response
remains historical and cannot issue acceptance authority. A fresh packet round lets the
human ask the existing chat to reconsider changed evidence. No model-generated marker, JSON,
quoted digest or instruction in the returned text can control these bindings.

The GET response review receipt is random, in memory, single-use and expires after 60 seconds.
Bind it to origin, current handoff/response versions+digests, current semantic snapshot and
scanner policy. Recheck under the dashboard lock after scanning and before the accept transaction.
Use current `expected_revision` for mutation races independently of semantic snapshot validity.
GET re-preview refreshes an expired receipt. Restart removes receipts; it retains scanned packet,
response and explicit accepted provenance. Previously accepted, semantically current evidence
can remain reviewable across restart; final execution still needs new native checks and a fresh
human continuation decision. Nothing autoaccepts, autoexports, authenticates or executes on load.

Preparation/import/review work with native Codex offline and a missing/replaced project folder.
They use checked stored dashboard evidence and safe local registry/binding metadata, never read
replacement contents or call `_recovery_project` to require an existing folder. Show unavailable
binding/transport and evidence age. Existing strict project identity validation remains mandatory
for development plan creation/continuation. Recovery holds and unrelated native operations stay
intact; local handoff does not cancel or obscure them and consumes no active native-run slot.

## Integration and checks

- Backend: add bounded local handoff methods/records alongside `RecoveryMixin`; reuse
  `safe_text`, exact-field validation, `digest`, `Store.put_many` and `_recovery_save` rollback
  behavior. Extend `_assessment_summary` and recovery projection/source resolution; preserve
  `_fresh_dispatch_clearance`, `recovery_plan`, `recovery_continue`, `_recovery_dispatch_context`
  and `_recovery_before_dispatch` safety checks. Add only explicit handoff route regexes to
  `Handler.do_GET/do_POST` in `dashboard/server.py`; do not expose arbitrary RPC or file access.
- Frontend: `recoveryDraft`, `loadRecovery`, `renderRecovery` and `recoveryAction` in
  `dashboard/static/app.js`. Add first-class handoff controls alongside optional direct assessment.
  Branch on `assessment.source === "handoff"`; do not request a task conversation or offer native
  Send/Stop for that source. Keep message selection editable for repeated handoff rounds. Preserve
  drafts/caret, announce preview/accept/stale states accessibly and require explicit Copy/Accept.
- Security: independent review of raw scans, immutable bindings, no forged agent identity,
  exact operation deduplication, scanner races, untrusted imported instructions and unchanged
  final execution gates. Documentation writers describe actual delivered routes and evidence;
  Agent Evaluation traces the whole handoff/return/approval journey independently of product QA.

Acceptance needs a successful prepare -> explicit copy -> returned response preview -> explicit
accept -> versioned plan -> separate approval journey, plus a second question/packet round.
Exercise offline and missing/replaced folders, restart between every stage, unchanged refresh,
semantic changes, oversized/scanner-blocked content, cross-origin/cross-task bindings, duplicate
requests, conflicting versions, expiry, forged reply markers, storage rollback and no-auth/native
call assertions. Browser evidence must show clipboard/manual-copy behavior, safe plain-text
rendering, repeated rounds and retained drafts. Mock native continuation cannot establish real
native execution. Human-mediated external-chat provenance remains unverified even after acceptance.

Executed for this contract: current repository/code inspection and coordinated architecture /
security contract review. No account browsing, authentication, native startup/inference or
external messaging occurred; no application tests are claimed for this design document.

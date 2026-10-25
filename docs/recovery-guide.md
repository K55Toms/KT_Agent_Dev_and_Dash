# Recover an unknown task safely

Use this guide when a dashboard-managed development task is marked **unknown** after a disconnect, restart, or uncertain request delivery. Unknown means the dashboard cannot establish the outcome. It does not mean the work failed, stopped, or completed. Recovery keeps the original outcome unresolved; it does not restore the old turn, replay its instruction, or restore previous approvals.

## Current status

The assessment handoff and parent/child recovery updates are implemented in source. The latest source was applied locally on 25 October 2026 with a graceful dashboard-server restart. The dashboard reconnected with 10 tasks preserved, including two unknown tasks, zero active tasks, and zero pending tasks. The reported final full Python suite passed 487 checks in 107.243 seconds, and 86 UI checks passed. A metadata-only check of an existing task then returned `activity_unverified` and `metadata_unavailable`; live coverage therefore remains unverified and continuation is blocked while this is diagnosed. No native continuation or inference was performed. External-chat provenance and native recovery continuation remain unverified.

## Assessment handoff

The handoff lets you carry a checked evidence packet to an existing chat you are authorized to use, then review the response locally. Packet preparation and response review can use stored checked evidence while Codex is offline or the registered folder is unavailable; they do not inspect a replacement folder or clear native activity holds. The dashboard never sends the packet for you. It cannot verify the other chat's account, model, tools, policy, actions, or usage, or prove that a returned response came from that chat. Treat the response as human-supplied text, not verified agent work or evidence that native actions occurred.

## When a finished parent has unresolved child work

An agent run can finish while delegated child activity is still unknown. Open **Recover task** on the coordinating parent to inspect that child activity; opening Recovery does not change the parent's completed, failed, or interrupted outcome. Unknown-role child activity remains unattributed instead of being guessed from its title or message. The unresolved child keeps recovery available for the parent across disconnect or restart. Do not treat missing attribution as proof that the child stopped.

The updated check covers both archived and unarchived descendants, bounded to 256 unique child threads, at most eight pages and 512 rows, with a shared 12-second deadline for the parent and child metadata. If pagination, coverage, identity, or time limits prevent a complete check, execution clearance remains unverified and continuation stays blocked. A refresh observes metadata only; it does not resume any child, turn, or external action. Polling retains drafts and restores the field and caret you were using. The live metadata check is currently incomplete, so do not treat the successful synthetic checks as clearance for a live task.

1. Open the unknown task and refresh its recovery checks. Review coverage, activity findings, unresolved items, and the messages available for selection. If native activity or the registered directory is unavailable, the packet may still support discussion, but that does not clear the missing evidence or authorize development.

2. Select only the checked messages you want to include, enter a fresh question, and choose **Prepare checked handoff packet**. Review the complete plain-text preview before copying it. The packet and response are scanned, but scanning may not detect every sensitive value. Do not include secrets or information you are not permitted to share with the destination chat.

3. Choose **Copy checked packet**. If clipboard access fails, select and copy the preview using your browser's keyboard controls. Copying does not send anything, open a chat, or record that delivery happened. Open your existing approved chat yourself and paste the packet there. Read it before sending and follow that chat's rules. The packet asks for assessment of the evidence, its uncertainties, and possible next steps; it does not authorize continuation or actions on the project.

4. Discuss the evidence in that chat as needed. When ready, copy the response text yourself and return to Recovery. Paste it into **Paste assessment reply**, then choose **Check and preview returned assessment**. The dashboard scans the full response before saving or displaying it, then previews it alongside the packet it answers. It labels this as a human-supplied assessment; the source, model, tools, and usage are unverified. If the packet is already stale when you check the reply, the dashboard rejects the import and does not save it. If evidence changes after a response is saved, that response remains historical and cannot satisfy current recovery gates.

5. Read the packet and response together. If the preview is current and acceptable, choose **Accept reviewed assessment** as a separate explicit decision. Acceptance records your review of that exact packet and response. It does not certify the external chat, clear activity or directory checks, grant native permissions, complete the old task, or approve development.

6. To ask another question, prepare a new packet from the current checked evidence and copy it to the chat yourself. A new round supersedes the prior acceptance and invalidates any continuation plan. Replacing a returned response also invalidates its acceptance and plan; review and accept the current response again.

   Handoff storage is bounded: at most eight rounds per task and 128 across the dashboard are retained, with up to 16 returned responses and 64 recorded actions per round. When a limit is reached, the dashboard blocks more handoff work rather than silently deleting earlier records.

If a handoff action's delivery is uncertain, keep your drafts and choose **Reconcile previous handoff action**. That explicit action repeats the exact saved request so the dashboard can return its recorded result. New handoff actions stay blocked until the request is resolved; nothing retries automatically. If the server definitively rejects it, read the error and refreshed checks before making a corrected decision.

The optional direct ChatGPT sign-in assessment route is separate and is not required for this handoff. The handoff does not use API credentials or create an alternate sign-in. For endpoint and content limits, see [recovery and assessment API](dashboard-api.md#recovery-and-assessment-api).

## Approve new development separately

After you accept a current assessment, write the exact fresh development instruction, choose a role, and review the selected project directory and plan. Save or revise the plan, then refresh recovery checks. Assessment acceptance never substitutes for this plan review.

Choose **Approve and continue development** only when the current checks allow it and you have reviewed the exact plan. This starts a new linked development conversation. It does not resume or replay the old turn. Same-thread continuation is disabled. Recovery runs use Manual approval handling for native permission requests; inspect each request and approve only the specific action you understand. Earlier approvals and project-wide automatic preferences are not restored.

The development plan and dispatch require fresh native activity checks, verified ownership, a changed trusted boot identity when required, and an unchanged registered directory identity. A restart plan only prepares manual steps; recording it does not authorize a reboot. Any restart is your independent choice and action. A boot change alone does not prove that prior external work stopped or resolve incomplete descendant activity. If evidence, directory identity, ownership, or a current response is missing or stale, continuation stays blocked.

If the dashboard reports its active-run limit is full, wait until a slot is available and explicitly retry the action. It is not queued automatically. If dispatch or a stop has an uncertain result, refresh and reconcile the observed status; never resend the same operation automatically. A stop request does not prove the work stopped.

## Validation status

Reported verification includes 18 backend unit checks, 3 HTTP checks, 14 independent QA acceptance checks, 49 Python and 25 UI security checks, 78 UI checks after the handoff reconciliation fix, 458 full Python checks from an earlier revision, and the final 487-check Python suite (107.243 seconds). The root-run 86 UI checks also passed. The handoff browser checks copied the packet to the clipboard, reviewed a literal script-like reply as text, and separately accepted it; they made no sign-in or native calls. For the parent/child update, 11 QA checks covered persistence including SQLite across restart, and 10 regression checks covered descendant counting. A final synthetic browser fixture showed one completed parent with one unresolved child; Recovery opened without changing the parent's status and preserved keyboard focus through polling. It made no sign-in or native calls. The independent source review found and fixed a child-count issue. After local application, a metadata-only check of a live task returned `activity_unverified` and `metadata_unavailable`; diagnosis is ongoing and live coverage remains unverified. No live task was resumed, and there is no evidence here of native continuation, inference, or external-chat provenance. For exact routes, limits and stale-packet behavior, see [recovery and assessment API](dashboard-api.md#recovery-and-assessment-api).

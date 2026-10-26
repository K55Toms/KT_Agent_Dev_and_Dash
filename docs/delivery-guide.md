# Check delivery readiness

Use **Delivery readiness** on an eligible task to record current checks, an independent review, and your decision. This is separate from the task's execution status: a completed task remains completed while you assess its delivery evidence.

The guide describes the implemented workflow; it is not release sign-off. A disposable project completed the real Codex workflow through the browser: approved unittest execution, a separate model-backed review, and explicit fixture acceptance reached Ready for delivery. This verifies that integration on synthetic source files, not the acceptance or release of any existing project. See the [task board](task-board.md) for final regression and review status.

## Which tasks can use this

The gate applies to newly started, policy-bound Backend or Frontend work, and to an eligible coordinating task with an observed direct implementation child. A legacy task without the policy record shows **Not enforced for this run**; it is not retroactively verified by this feature.

For new managed work, the dashboard loads its approved Ponytail Full policy from the installed, pinned version and adds it to the Backend or Frontend role instructions before native dispatch. A missing, changed, or unverified policy or role profile blocks dispatch. Repair or update the approved installation/profile through the reviewed project process, wait until the dashboard is idle, and reload it before retrying. The injected policy guides the agent; it cannot prove that a model followed the instructions.

An agent may still create child work that the dashboard cannot attribute or verify. Unknown or active child work, a recovery hold, an unavailable policy, or an incomplete project snapshot keeps readiness unverified. Do not treat a clean parent task as proof that all child activity is complete.

## Save the project's approved checks

1. Open the completed task and expand **Delivery readiness**. Read the current status and any reason shown. Opening this panel starts no work.
2. Enter one exact command per line in **Approved project checks**. You can save 1–8 distinct commands, each up to 2,000 characters, with at most 8,000 characters across the plan. The dashboard scans and stores the commands exactly as entered.
3. Select **I approve these exact checks for this project**, then choose **Save approved checks**. Saving approves the project's plan; it does not run the commands. You cannot change the plan while work in that project is active.

Choose commands that test the project's required behavior. Check each command carefully before saving: the later run executes these exact approved commands from the registered project root.

## Run checks through Codex

1. Review the current project state and saved check plan. Select **I understand that starting checks or review can consume workspace usage and request native approvals**.
2. Choose **Run approved checks**. This starts a separate dashboard-managed `qa_engineer` task through Codex, using the existing sandbox and native approval controls. It does not use a host-side command runner and does not bypass native approval requests. Review and handle any native request through the usual approval flow.
3. Follow the checks task in its conversation and refresh **Delivery readiness** to see recorded progress. A check passes only when the current, owned check task reports the exact approved command in the registered project working directory and a completed result with exit code `0`. The command may be direct or carried by a supported `/bin/zsh`, `/bin/bash`, or `/bin/sh` `-lc` wrapper. Every approved command must pass. A matching command text alone or a success message without the matching completion evidence does not count.

If a command fails or the task asks for changes, fix the project and then refresh the evidence. Any changed code, file set, file mode, Git `HEAD`, task state, approved plan, policy/profile, or App Server connection can make prior evidence stale. Rerun checks and obtain a new review against the current state.

## Read and decide on the independent review

After every approved check passes, choose **Start independent review**. The dashboard starts a separate `code_quality_reviewer` task to inspect the current project changes and agreed task outcome. It is instructed not to edit the implementation or delegate work. You can open its conversation to follow the review.

When the review is complete, choose **Read independent review** and read the full checked report. Then choose:

- **Accept review and mark delivery ready** only if you accept the report for the current code and check results.
- **Request changes** to send the work back for correction. After changes, refresh and repeat checks and review.

The preview and decision are tied to the current project snapshot and review. The preview expires after 60 seconds and its decision receipt can be used once. If it becomes stale, refresh delivery status and read the current review again before deciding. Acceptance records readiness only; it does not commit, publish, deploy, approve a native permission request, or grant release approval.

## If an action has an uncertain result

The dashboard does not retry delivery actions automatically. If the request may have been accepted but the response was lost, refresh the status and reconcile the existing operation. If the UI offers **Retry original request**, it resends only the same frozen request; it does not create a second check or review task. Do not start a different action while the previous request is unresolved. A stale retry can be rejected; refresh and review the current state before making a fresh decision.

If the dashboard confirms that an action **did not start**, fix the reported setup issue and make a new explicit attempt. If saving a review decision fails after its receipt was consumed, read the current report again to obtain a fresh receipt, then make a new decision. Never reuse a consumed receipt.

## What the evidence covers

The current snapshot fingerprints the registered project directory identity, Git `HEAD`, and Git-visible tracked and non-ignored untracked files, including file modes. Tracked files remain included even when Git ignores them. The reviewed scanner checks the collected file bytes, but the fingerprint does not interpret opaque assets for visual correctness or prove that a file has no sensitive meaning. Ignored untracked files, runtime/environment state outside the collected project files, and unsupported paths are not covered. Unsupported links or file types, scanner failures, or exceeded coverage limits make the snapshot unavailable rather than ready.

Readiness means that the current approved checks were observed passing, a separate review was recorded, and you explicitly accepted that current review. It is evidence for the reviewed project snapshot, not proof that external effects stopped, that every child was observed, or that the change is safe to release in every environment.

For API fields, current limits, and detailed recovery behavior, see [delivery readiness in the API reference](dashboard-api.md#ponytail-policy-and-delivery-readiness) and [delivery checks and readiness operations](dashboard-operations.md#delivery-checks-and-readiness).

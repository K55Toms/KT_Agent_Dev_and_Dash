# Review a Codex request in the dashboard

Open **Approvals** or choose **Review request** beside a pending item. Read the project, task, requester, reason, full request context, and decision scope before responding. Supported requests are reviewed against the live native request. If it is missing, stale, disconnected, unsafe, or has changed, the dashboard disables approval; refresh and review the current request. Nothing is replayed automatically.

For command and file-change requests, inspect the checked command or proposed changes and any displayed working directory or permission details. **Approve once** answers that exact request. Choose **Decline request** or **Cancel** only when that choice is offered. A command's effects may extend beyond the displayed project, and content checks do not prove an action is safe.

For a permission request, inspect every requested filesystem and network permission. **Approve for this turn** grants the displayed subset for the remainder of that native turn. It is broader than approving one command. Rejecting grants none. The dashboard does not offer a session-wide grant through this flow, and project automatic approval settings do not apply to it.

Some connected tools ask you to choose or provide an answer. Read the request and select the exact answer that matches your intent; sending an answer can authorize that tool action. For supported structured forms, complete only fields you understand and are permitted to share. Never enter passwords, tokens, API keys, or other secrets in an agent or tool form. Forms the dashboard cannot safely represent require a human step in Codex.

An external sign-in or device-verification request requires a separate human step in Codex. Read the named server and instructions, complete the step there, and return to the dashboard when the request is ready for review. The dashboard does not open the external page or manufacture verification proof. URL and device-verification requests, and forms the dashboard cannot safely represent, must be completed in Codex. Use **Reject request**, **Cancel**, or **Stop run** when offered or when you do not want the request to continue.

After you respond, check the task or conversation for observed progress. A response acknowledgement alone does not prove the agent resumed or completed the work. If the dashboard disconnects or the request becomes unavailable, inspect the task state before taking another action; approvals from an earlier run are not restored after restart.

The delivered approval flows passed a synthetic Safari check. A live Codex request continuation has not been verified, so check the task or conversation for observed progress after responding. An acknowledgement alone does not prove that work resumed or completed.

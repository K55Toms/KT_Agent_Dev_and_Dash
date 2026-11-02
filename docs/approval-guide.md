# Review a Codex request in the dashboard

Open **Approvals** or choose **Review request** beside a pending item. Read the project, task, requester, reason, full request context, and decision scope before responding. Supported requests are reviewed against the live native request. If it is missing, stale, disconnected, unsafe, or has changed, the dashboard disables approval; refresh and review the current request. Nothing is replayed automatically.

For command and file-change requests, inspect the checked command or proposed changes and any displayed working directory or permission details. **Approve once** answers that exact request. Choose **Decline request** or **Cancel** only when that choice is offered. A command's effects may extend beyond the displayed project, and content checks do not prove an action is safe.

For a permission request, inspect every requested filesystem and network permission. **Approve for this turn** grants the displayed subset for the remainder of that native turn. It is broader than approving one command. Rejecting grants none. The dashboard does not offer a session-wide grant through this flow, and project automatic approval settings do not apply to it.

Some connected tools ask you to choose or provide an answer. Read the request and select the exact answer that matches your intent; sending an answer can authorize that tool action. For supported structured forms, complete only fields you understand and are permitted to share. Never enter passwords, tokens, API keys, or other secrets in an agent or tool form. Forms the dashboard cannot safely represent require a human step in Codex.

An external sign-in or device-verification request requires a separate human step in Codex. Read the named server and instructions, complete the step there, and return to the dashboard when the request is ready for review. The dashboard does not open the external page or manufacture verification proof. URL and device-verification requests, and forms the dashboard cannot safely represent, must be completed in Codex. Use **Reject request**, **Cancel**, or **Stop run** when offered or when you do not want the request to continue.

After you respond, check the task or conversation for observed progress. A response acknowledgement alone does not prove the agent resumed or completed the work. If the dashboard disconnects or the request becomes unavailable, inspect the task state before taking another action; approvals from an earlier run are not restored after restart.

The delivered approval flows passed a synthetic Safari check. A live Codex request continuation has not been verified, so check the task or conversation for observed progress after responding. An acknowledgement alone does not prove that work resumed or completed.

# Review a Claude request in the dashboard

This applies when the dashboard was started with `claude`. A run you start asks for permission when Claude
Code wants to use a tool that is not already allowed. Open **Approvals**; the card says "A tool call
requires approval", names the task and the requester ("<role> via Claude Code"), says "This one call only"
and shows the longest time the run will wait for you.

1. Choose **Review request**. The dialog shows the tool name (for example `Bash`, `Write` or `Edit`) and the
   complete input the tool would receive: the whole command, or the file path and content. For a subagent
   it also shows the agent type, marked "not verified" because Claude Code supplies it. Read all of it; long
   values scroll.
2. Unusual characters are not hidden. A control character or a character that changes text direction (for
   example U+202E) appears as a visible `\uXXXX` code, so the text cannot look different from what it
   does. Newlines and tabs are shown as they are. This applies to Claude requests; the Codex review above is not changed.
3. Choose **Accept** to allow this one call, or **Decline** to refuse it. You can also choose **Decline**
   straight from the list. Accepting never allows a later call: if Claude asks for a second command, even
   a similar one, it is a new request you review again.
4. If the input contains text that looks like a secret, the normal review is blocked. Only if you have
   turned on sensitive review in Settings can you reveal the request on this computer, read it, and then
   accept once. Never copy revealed text into chat, screenshots or Git.

If you do nothing, the call is denied when the wait ends (15 minutes unless you changed "Claude approval
wait" in Settings; the range is 60 to 3600 seconds). A card then shows "Expired" or "Unavailable" and has no
buttons. The same happens if you stop the run, close the dashboard or the dashboard restarts: the call is
denied, never allowed, and a request from an earlier run is not restored. Waits longer than about 5 minutes are
unverified: if Claude Code gives up earlier, the card shows Unavailable and the call is denied.

You cannot answer these requests inside Claude Code: a run started from the dashboard has no terminal prompt.
To skip the review for routine work, you can switch one Claude project to Automatic in Settings (it needs
the confirmation box). The dashboard then accepts `Bash`, `Write`, `Edit` and `NotebookEdit` requests one call
at a time, shows them as "Accepted automatically by project policy (one call)", and still asks you for
anything else, including web, MCP and agent tools and any input that looks like a secret. File changes are accepted
only inside the project folder (never under `.git`, `.claude` or `.local`); other paths wait for you. `Bash` cannot be
limited to the project, so Automatic `Bash` is unrestricted code execution as your user. Switch back to
Manual to stop it. Content checks do not prove a command is safe, and a command's effects can reach beyond
the project.

After you answer, check the task for observed progress; an acknowledgement alone does not prove the run
went on. This flow is tested with a fake `claude` and has not been run with the real one through the
dashboard or checked in a browser.

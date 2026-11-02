"""Fixed, bounded diagnostic labels; upstream text is never retained or returned."""

DETAILS = {
    "approved_policy_unavailable": ("The approved Ponytail policy or registered profiles are unavailable or changed.", "Repair the approved plugin or profile files, reload the dashboard when idle, and retry explicitly. Policy updates require review."),
    "thread_history_unavailable": ("Codex could not find the saved history for this thread.", "Delegation or thread continuation could not load its source history. Verify persistent parent sessions and the current runtime before starting a fresh run; this task will not be replayed automatically."),
    "config_invalid": ("Codex could not load a valid configuration.", "Review the project's .codex/config.toml for this installed CLI version, then start a new run."),
    "model_unavailable": ("The selected model is unavailable for this Codex installation or account.", "Verify current Codex model availability and update the CLI before changing models; older catalogs can include retired models. No replacement is selected automatically."),
    "authentication_required": ("Codex authentication or account access was rejected.", "Check sign-in through the Codex CLI; never paste credentials into the dashboard."),
    "usage_limit": ("Codex reported an account usage limit.", "Check workspace usage and retry explicitly after allowance is available."),
    "invalid_params": ("Codex rejected the request parameters.", "Check dashboard compatibility with the installed Codex App Server."),
    "safety_mismatch": ("Codex did not retain the required sandbox, working directory or approval settings.", "Review the configured permission profile; the dashboard blocked inference rather than weakening its boundary."),
    "sandbox_initialization": ("Codex could not initialize its local sandbox helper.", "Check the installed CLI and operating-system sandbox permissions before starting another run. The dashboard has not weakened its required boundary."),
    "request_rejected": ("Codex explicitly rejected this request.", "Check the installed CLI configuration and account access. Raw server details are withheld."),
    "transport_lost": ("The Codex response was lost; execution state is unknown.", "Inspect the project before starting new work. This run will not be replayed automatically."),
    "protocol_invalid": ("Codex returned an unexpected response shape.", "Check compatibility with the installed App Server before starting another run."),
    "execution_failed": ("Codex reported a failed execution.", "Review these diagnostics and the project state before starting another run."),
    "service_unavailable": ("Codex reported a connection or service failure.", "Check service availability and account access before explicitly retrying."),
    "context_limit": ("The run exceeded the model context limit.", "Start a narrower task with the relevant context."),
    "legacy_failure": ("This earlier failure predates detailed diagnostic recording.", "Its original generic error remains available; no detailed cause was recorded."),
    "claude_api_error": ("Claude Code reported an API error.", "Check service availability and your Claude Code sign-in, then start a new run. Raw error details are withheld."),
    "claude_not_logged_in": ("Claude Code was not signed in or its account access was rejected.", "Sign in through the Claude Code CLI outside the dashboard; never paste credentials into the dashboard."),
    "claude_model_unavailable": ("The role's Claude model is unavailable for this Claude Code installation or account.", "Check the role's model alias and your plan's model access. No replacement model is selected automatically."),
    "claude_aborted": ("Claude Code aborted the run.", "Inspect the project before starting new work. This run will not be replayed automatically."),
    "claude_exit_nonzero": ("Claude Code exited with an error before reporting a result.", "Check the installed Claude Code CLI and start a new run. Its output is withheld."),
    "claude_no_result": ("Claude Code ended without reporting a result; execution state is unknown.", "Inspect the project before starting new work. This run will not be replayed automatically."),
    "claude_permission_mode": ("Claude Code was not in the default permission mode, so the dashboard stopped the run and denied the requests it made.", "Check the user-level Claude Code settings for a default permission mode, then start a new run."),
    "claude_output_too_large": ("Claude Code sent an output line over the size limit, so the dashboard stopped reading it; execution state is unknown.", "Inspect the project before starting new work. This run will not be replayed automatically."),
    "claude_launch_invalid": ("The Claude Code run could not be prepared safely, so nothing was started.", "Check the role file, the project's CLAUDE.md imports and the Claude Code installation, then start a new run."),
    "claude_session_rejected": ("The Claude session could not be registered, so the run was stopped.", "The resumed session did not match; check the run before sending a follow-up. If the runtime tracking limit was reached, restart the dashboard after checking project state."),
    "claude_calls_denied": ("Some tool calls were denied because they were not approved: by you, by the approval wait running out, or because the run was stopped.", "Review the denied tool names on this run; the run continued without them. The Approvals page shows any request that is still waiting for you."),
    "claude_hook_session_unknown": ("A tool call was asked for before the dashboard knew this run's session, so it was denied.", "The run went on without that call. If it keeps happening, check the Claude Code installation before starting another run."),
    "claude_hook_turn_inactive": ("A tool call was asked for after this run's turn had ended, so it was denied.", "The run went on without that call. Inspect the project before sending a follow-up."),
    "claude_hook_limit": ("A tool call was denied because too many approvals were already waiting in the dashboard.", "Answer or stop the waiting approvals, then send a follow-up if the call is still needed."),
    "claude_hook_subagent_session": ("A tool call from a subagent was denied because it named a different session than this run.", "The run went on without that call. If subagents need tools, report it; the subagent session id is not yet verified against live Claude Code."),
    "claude_restart_unknown": ("The dashboard restarted while this run was active; its result is unknown.", "Inspect the project, then send a follow-up to continue the session if the work should go on."),
    "claude_possibly_running": ("A Claude Code process from before the restart may still be running.", "Check for a leftover Claude Code process for this project before starting new work."),
}


def classify_error(error):
    """Classify ephemeral upstream data into local constants, never echo it."""
    if not isinstance(error, dict):
        return "execution_failed"
    info = error.get("codexErrorInfo")
    enums = {"unauthorized": "authentication_required", "usageLimitExceeded": "usage_limit",
             "contextWindowExceeded": "context_limit", "sandboxError": "safety_mismatch",
             "serverOverloaded": "service_unavailable", "internalServerError": "service_unavailable"}
    if isinstance(info, str) and info in enums:
        return enums[info]
    if isinstance(info, dict) and any(k in info for k in ("httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "responseTooManyFailedAttempts")):
        return "service_unavailable"
    message = error.get("message")
    text = message[:16000].lower() if isinstance(message, str) else ""
    if "no rollout found for thread id" in text or "invalid thread-store request" in text:
        return "thread_history_unavailable"
    if any(x in text for x in ("failed to load config", "error loading config", "invalid config", "config.toml", "toml parse")):
        return "config_invalid"
    if "sandbox-exec" in text or ("sandbox" in text and "helper" in text):
        return "sandbox_initialization"
    if "model" in text and any(x in text for x in ("not supported", "unsupported", "not found", "does not exist", "not available", "unavailable", "unknown model")):
        return "model_unavailable"
    if any(x in text for x in ("unauthorized", "authentication", "not logged in", "sign in", "401")):
        return "authentication_required"
    if any(x in text for x in ("usage limit", "rate limit", "quota exceeded")):
        return "usage_limit"
    if error.get("code") == -32602:
        return "invalid_params"
    return "request_rejected"



def classify_claude(error, exit_code):
    """Classify a Claude Code result error (allow-listed fields only) or exit code into a claude_* code."""
    error = error if isinstance(error, dict) else {}
    status = error.get("api_error_status")
    status = status if type(status) is int else None
    reason = error.get("terminal_reason")
    reason = reason if isinstance(reason, str) else ""
    if status in (401, 403) or reason in {"authentication_failed", "not_logged_in", "unauthorized"}:
        return "claude_not_logged_in"
    if status == 404:
        return "claude_model_unavailable"
    if status is not None:
        return "claude_api_error"
    if reason.startswith("aborted"):
        return "claude_aborted"
    if type(exit_code) is int and exit_code != 0:
        return "claude_exit_nonzero"
    return "claude_api_error"

def diagnostic(stage, code, timestamp):
    code = code if code in DETAILS else "execution_failed"
    message, action = DETAILS[code]
    return {"at": timestamp, "stage": stage, "code": code, "message": message, "action": action}

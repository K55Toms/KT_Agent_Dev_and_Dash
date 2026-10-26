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


def diagnostic(stage, code, timestamp):
    code = code if code in DETAILS else "execution_failed"
    message, action = DETAILS[code]
    return {"at": timestamp, "stage": stage, "code": code, "message": message, "action": action}

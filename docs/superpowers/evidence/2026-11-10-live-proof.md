# Live proof evidence (Claude deployment)

Plan: `docs/superpowers/plans/2026-11-10-live-proof.md`. Owner go in chat: Parts 1 and 2 on 2026-11-10 (alias `haiku`,
5 runs, about 0.06 USD); raised to 7 launches on 2026-11-11 after the sign-in blocker ("Signed in, retry").

Status: **Parts 1 and 2 run. "Ready for delivery" was not reached** (the review report was not a review; see finding 2).
Parts 3 and 4 not started.

Every live result below is one run, alias `haiku`, effort `low`, Claude Code 2.1.322 (2.1.312 on 10 November), subscription
login. The controller drove the dashboard in the built-in browser; nothing was owner-clicked. Recorded by the controller
session; no `qa_engineer`, `security_reviewer`, writer or agent-evaluation dispatch has been made yet (open).

## Setup (no model use)

- Scratch clone of `main` at `1c1860f`; every Claude role set to `haiku` / `low` in the clone's `team_source/models.toml`
  and regenerated with `scripts/sync_roles.py`. The real tree and its roles were not changed.
- Fresh state folder (the clone's own `.local`), port 8766, a scratch git project (`notes-seed.txt`, `check.sh`) outside the
  repository.
- Side effect outside the scratch folders: starting the `claude` deployment created the per-install token folder and file for
  Terminal sessions in the owner's user configuration folder (folder mode 0700; contents not read). None existed before.
- After the runs: dashboard stopped, ports 8766 and 47615 closed, no `claude -p` process, run-settings folder empty.

## Launches

| # | Kind | What | Result | Estimate (USD, list price) |
| --- | --- | --- | --- | --- |
| 1 | live + browser | M1 development run (10 Nov) | Failed in about 5 s, `claude_api_error`, 0 tokens (expired login) | 0 |
| 2 | live, direct CLI | Diagnostic one-word prompt (10 Nov), not in the plan | Exit 1; authentication failed, OAuth session expired | 0 |
| 3 | live + browser | M1 rerun, role `chief_of_staff` | Completed | 0.0099 |
| 4 | live + browser | M2 follow-up on the same task (turn 2) | Completed | 0.0139 |
| 5 | live + browser | M3 delivery checks, role `qa_engineer` | Completed, 1 of 1 checks passing | 0.0037 |
| 6 | live + browser | M4 independent review, role `code_quality_reviewer` | Completed; report was not a review | 0.0018 |
| 7 | live, direct CLI | S12 `--disallowedTools` | Completed | 0.0082 |

Total about 0.038 USD (dashboard and CLI estimates; the owner was told about 0.06).

## What the runs showed

| Journey | Observed | Kind |
| --- | --- | --- |
| Start a run, approve once | `Write` request held; review dialog showed tool, complete input and agent type `chief_of_staff`; Accept; file created with `alpha` | live + browser |
| `Edit` through the hook | Request held; input field names `file_path`, `old_string`, `new_string`, `replace_all`; Accept; file became `beta` | live + browser |
| Reply in the conversation | Two replies shown for turn 1 ("finished", then a summary after the helper ended) | live + browser |
| Subagent as delegate | "Unattributed delegated task", Completed, "Role not recorded", under the Chief of Staff on the task and the Team page | live + browser |
| Follow-up turn | Turn 2 ran on the same task; `Edit` to `beta2` held and accepted | live + browser |
| Subagent approval (carry item e) | The helper's `Write` request reached the dashboard, labelled "a subagent via Claude Code", agent type `general-purpose`; Accept; `sub.txt` created with `gamma`. It was not refused as `claude_hook_subagent_session`, so the request carried the run's session id (inferred from the dashboard's rule, not read from the payload) | live + browser |
| Subagent stop (carry item d) | Both helpers ended as Completed, and neither blocked delivery | live + browser |
| Owner-attached output | `notes.md` associated (server recorded it, source `human`, turn 2); after reopening, the dialog listed it and **Open report** showed a one-line checked preview | browser |
| Delivery checks | Plan `sh check.sh` saved; separate QA Engineer run; `Bash` request for exactly `sh check.sh` held and accepted; panel: "1 of 1 approved checks observed passing", "Awaiting independent review"; Ponytail row "Not applicable for Claude" | live + browser |
| Independent review | Separate Code Quality Reviewer run completed with no approval request; **Read independent review** showed the report; **Request changes** recorded; panel "Changes requested" | live + browser |
| Delete | The failed run from 10 November deleted through the confirmation dialog; it left the task list | browser |
| S12 `--disallowedTools Write,Edit,NotebookEdit` | The session's tool list had none of `Write`, `Edit`, `NotebookEdit` (`Bash` and `Read` present); the model replied "blocked"; no file written; no permission denial recorded | live, direct CLI |

## Findings (all open, none fixed here)

1. **Expired login reads as a generic API error.** Shown as `claude_api_error`, not `claude_not_logged_in`: the result line
   had no `api_error_status` and `terminal_reason` `api_error`; the cause was only in the withheld text. Owner:
   backend_developer.
2. **The independent review did not review (fixed in code afterwards, not re-run live).** The review prompt ends with "Task objective:" followed by the task's
   instruction text (`dashboard/delivery.py`, about line 527). The reviewer read the pasted follow-up steps as steps for
   itself, declined them (it edited nothing and delegated nothing) and reported that, instead of reviewing the changes.
   The dashboard still offered **Accept review and mark delivery ready**. One run on `haiku` / `low`; the configured
   reviewer model (`opus` / `high`) was not tried. Owner: technical_architect and backend_developer; security_reviewer to
   look, because task text reaches a reviewer as apparent instructions.
3. **Outputs dialog does not update after attaching.** It kept "No output recorded" until closed and reopened, although
   the request succeeded. Owner: frontend_developer.
4. **Delivery panel redraws about once a second.** The check commands field is replaced each time; typed text is kept but
   keyboard focus was lost within 3 seconds (one observation, through browser automation). Owner: frontend_developer.
5. **Not every Bash call asks.** The helper's `echo ok` raised no approval request; the model reported that it ran
   (model-reported, not verified). Claude Code allows some commands itself, so the dashboard's list is not a complete
   record of Bash calls in a managed run. Owner: technical_writer to check the wording in the operations guide.
6. **Task-list delivery line lagged.** After the checks run finished, the task's summary still read `checks_running`,
   `stale`, `context_changed` until the panel was opened. Owner: frontend_developer or backend_developer.
7. **CLI changed under the proof.** 2.1.312 on 10 November, 2.1.322 on 11 November. In 2.1.322 the helper ran in the
   background: the main reply came before the helper ended and a second reply followed.
8. Known leftover confirmed in the browser: the Team page subtitle still says "celebrate contributions" on Claude.

## Not verified

- "Ready for delivery" through **Accept review**; a failing check ("not ready"); deleting a finished development task that
  has outputs and delegates.
- Any model other than `haiku`, any effort other than `low`, the roles' real model settings.
- What the `Edit` and subagent payloads contain beyond the fields the dialog showed; `NotebookEdit`.
- Whether `--disallowedTools` behaves the same inside a dashboard-managed run (S12 was a direct CLI run without `--agents`
  or a hook).
- Part 3 (terminal sessions with the owner at the keyboard, S11) and Part 4 (Codex).

## Follow-up: review prompt fix (2026-11-11)

Finding 2 was fixed in `dashboard/delivery.py` (Claude deployments only): the task text is passed between the markers
`<<<TASK STATEMENT` and `TASK STATEMENT>>>` and introduced as a statement given to a different agent that the reviewer
must judge, not carry out; task text containing a marker is refused (409). Tests (fake-binary): three new tests in
`tests/test_claude_delivery.py` (framing, marker refusal, checks prompt unchanged); the first two failed before the change.
Full Python suite on 3.12 at this change: 1555 tests OK, 36 skipped (clean HOME); Node 215 of 215. Not run live: whether
`haiku` now reviews. Open: the dashboard still offers **Accept review** after a report that is not a review.

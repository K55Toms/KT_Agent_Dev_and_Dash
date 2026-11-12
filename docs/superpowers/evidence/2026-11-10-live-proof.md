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
Full Python suite on 3.12 at this change: 1555 tests OK, 36 skipped (clean HOME); Node 215 of 215. Live check afterwards: see the next section (one direct run). Open: the dashboard still offers **Accept review** after a report that is not a review.

## Follow-up: one live review run with the new prompt (2026-11-11)

Owner go in chat: "Yes, one review run" (about 0.002 USD). Kind: **live, direct CLI, not through the dashboard.** The scratch
folders from the first session were gone (the session scratchpad had been emptied), so the dashboard journey could not be
repeated without about 0.016 USD of extra launches (a development run, a checks run and a review); that was not asked for and
was not done.

What was run: a fresh scratch clone of `live-proof` at `c480a8e` (roles set to `haiku` / `low`), a scratch git project with
`notes.md` (`beta2`) and `sub.txt` (`gamma`) left untracked, and a script that took the role `code_quality_reviewer` from the
clone (tools `Read`, `Grep`, `Glob`), built the prompt with the real `Dashboard._claude_review_instruction` from the exact
follow-up text that confused the reviewer on 2026-11-11, and the real `build_argv` (no approval hook, `--max-budget-usd 0.05`
added). `claude` 2.1.322, alias `haiku`.

| Result | Observed |
| --- | --- |
| Behaviour | The reviewer read the project (`Read`, `Glob` x3, `Read`), did not try any write or delegate call, and did not treat the pasted steps as its own. It reported a verdict that the file artifacts matched the task (`notes.md` is `beta2`, `sub.txt` is `gamma`) and listed what it could not verify (the Agent call, other changed files, the original content) |
| Scratch project afterwards | Unchanged (same two untracked files) |
| Run | Exit 0, `success`, 6 turns, about 0.0028 USD at list price (launch 8) |

Total live spend for the whole proof: about 0.041 USD.

Limits: one run, `haiku` / `low`, one task text; the configured reviewer model (`opus` / `high`) was not tried; the prompt
came from the real function but the run did not go through the dashboard (no approval hook, no snapshot, no review report
reading or acceptance). It shows the wording fixes this failure on this input; it does not show every task text is safe.
The dashboard still offers **Accept review** after any report; whether the report accepts the work is the owner's reading.

## Part 3: terminal sessions with the owner at the keyboard (2026-11-11)

Kind: **live, interactive**: the owner typed the prompts and answered permission dialogs in their own terminal (`claude`
2.1.322, `--model haiku --permission-mode manual`, scratch project outside the repository). The controller ran the stub
or the dashboard and read logs; on the dashboard page the controller pressed Allow and Deny in the built-in browser
(browser evidence, controller-driven). Owner-reported items are marked. One run per case. Owner-pasted terminal text is
the source for what the terminal showed. Estimate of spend: not read (about 15 short `haiku` prompts).

**Stub cases** (details and per-case results: `docs/superpowers/spikes/S11-observed-replies.md`):

| Case | Result |
| --- | --- |
| A1 `{}` reply | Passed: prompt stayed 18 s, nothing ran before the owner's Yes |
| B2 terminal No (second try; the first was a Yes) | Passed: "Interrupted"; no `PostToolUse`, no `Stop` followed |
| B3 Allow from the hook while the prompt is open | Passed: prompt closed at 5 s, call ran once |
| C3 and B4 Deny from the hook while the prompt is open | Passed: prompt closed at 5 s, "Not run", nothing written, no retry |
| D4 stub down | Passed, owner-reported: prompt stayed until answered; `Stop hook error: connect ECONNREFUSED` shown after the turn |
| D5 `settings.local.json` | Passed: hooks fired, and a session already running picked them up |

**Dashboard page (the real Terminal sessions page, snippet written into `.claude/settings.local.json` without printing the token):**

| Case | Observed |
| --- | --- |
| Page | "Observed sessions on", port 47615; sessions listed active and ended |
| T1 Allow on the page | Card showed tool, project, exact command, expiry and "may already be answered in the terminal"; after Allow the card read "Allowed here: ran"; the file has one `T1` line |
| T2 Deny on the page | Prompt closed by itself; terminal showed "Not run · permission denied", reason "Declined in the dashboard."; card "Denied here: no run seen"; nothing written |
| T3 Yes in the terminal | Card "Answered in the terminal (inferred): ran", "Inferred from later events, not a receipt"; one `T3` line |
| T4 No in the terminal | Card "closed: answered elsewhere or timed out"; nothing written |
| T6 `/exit` | Session shows ended; the T4 card changed to "Answered in the terminal (inferred): no run seen" |
| T5 dashboard stopped | Command ran (one `T5` line, 16:31:22); the terminal showed "PostToolUse:Bash hook error: connect ECONNREFUSED 127.0.0.1:47615" and a Stop hook error. **Not confirmed:** whether the permission prompt appeared and waited; the owner did not answer that question. D4 above covers it with the stub |

**Findings:**
1. `{}` as the no-decision reply is safe on this version; the `NO_DECISION_MODE` default stays `empty_object`.
2. Real payloads (field names only): `PostToolUse` has `tool_input` and `tool_use_id`; `PermissionRequest` has `prompt_id` and no `tool_use_id`; `PostToolUse` and `Stop` carry `prompt_id` too. The design notes and docs say no `prompt_id` exists. The matching rule was not changed.
3. A terminal No leaves no later event, so a card stays "closed: answered elsewhere or timed out" until `SessionEnd` settles it as "no run seen".
4. With the dashboard down every hook event shows a visible but non-blocking error line (`PostToolUse:Bash hook error`, `Stop hook error`).
5. Hooks added to `settings.local.json` while a session was running fired without a restart.
6. Git ignored `settings.local.json` only through the owner's global ignore file.
7. **Unexplained:** the page showed "subagent activity seen" for the T3 session although no subagent was asked for.
8. The reason text sent with a dashboard Deny reaches the terminal verbatim.

**Not run:** A2, A3, A4, C1, C2, C4, D1, D2 (the stub has no 413/415 mode), D3 (two hooks), the page on a second session, the Auto permission mode, a second CLI version, any model other than `haiku`.

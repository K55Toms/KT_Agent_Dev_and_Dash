# Plan 5 leftovers: evidence (2026-11-11)

Plan: `docs/superpowers/plans/2026-11-09-plan5-leftovers.md` (Task 0 security review and rulings at its end). Branch
`plan5-leftovers`. Each kind of evidence is labelled; nothing here is a live run of the new code through the dashboard.

## What was built

1. Deleting a possibly-running task: decision closed as warning only; no code change.
2. Output suggestions from main-session `Write` and `Edit` calls (stream state, string-only path conversion, descriptor and Git checks,
   path-only batch scan outside the dashboard lock, snapshot field `output_suggestions`, Outputs dialog section).
3. The delivery checks runner starts with `--disallowedTools Write,Edit,NotebookEdit` (last in argv).
4. Team page subtitle without "celebrate contributions" where rewards are off.
5. Added during the browser check (not in the plan): the Outputs dialog is drawn again from the refreshed task after an attach. In the live
   proof (finding 3) and again here the dialog kept saying "No output recorded" after a successful attach when a poll had replaced the page's
   state while the request ran. This also keeps an attached path from staying in the suggestions list.

## Task 0: design review (read-only Opus subagent, 2026-11-11)

Verdict: nothing Critical. Important findings accepted and built: string-only path conversion (no `resolve`, `realpath` or `stat` on a raw
path); path-only scan with the content scanned at attach time; no path or error text in any log, diagnostic or snapshot; scans outside the
lock, batched, with a time budget and a stop at 8, then re-validation under the lock; a Git-visible filter; Unicode format characters
rejected. Minor findings accepted: store under `task['claude']`, subagent lines (`parent_tool_use_id` of `""` or `0` included) ignored,
unified labels. Full list: the plan's rulings section.

## Tests (labelled)

- **Unit and fake-binary (Python 3.12, clean HOME):** `tests/test_claude_launch.py` (the flag: exact value, last in argv, refusals);
  `tests/test_claude_delivery.py` (only the checks run carries the flag; a `Write` line still fails a checks run that has it);
  `tests/test_claude_stream.py` (`WrittenPathsTests`: state only, subagent lines ignored, dedupe and cap, replay); `tests/test_task_outputs.py`
  (`SuggestionPathTests`: sibling directory, `..`, FIFO, hard link, symlink, credential path, ignored file, oversize, bidi and zero-width
  characters, changed project identity, finding on one path, unavailable scanner, an `OSError` naming the path, the cap of 8 and the time
  budget; `SuggestionIntegrationTests`: a fake-binary run replaying `tests/fixtures/claude/write_edit.jsonl` offers only project files from
  the main session, attach removes a suggestion, other turns and non-completed tasks show none, the scan never runs under the lock);
  `tests/test_claude_docs.py`. One mutation check: scanning under the lock makes the lock test fail.
- **Node (DOM double):** suggestions section, `Use this path` fills the field only, markup renders as text, no section without
  `can_attach_output`, the Team subtitle for Claude and Codex, the redraw after an attach (fails without the fix, passes with it).

## Browser check (built-in browser, scratch clone of the branch, fake `claude` replaying `write_edit.jsonl`; controller-driven)

- The task snapshot over the API listed `docs/report.md` (Write) and `src/app.py` (Edit); the stored raw list was not in `task.claude`.
- The Outputs dialog showed "Files this run wrote or edited" with the model-chosen note, two rows and `Use this path` buttons; the
  outside-the-project, `..`, missing, `.env` and subagent paths from the fixture were not listed.
- `Use this path` filled the field and focused it, left the confirmation unticked and sent nothing.
- After ticking the confirmation and associating, the output was recorded (server state) and the suggestion left the list. Before the
  redraw fix the dialog kept "No output recorded"; after it the dialog listed both attached files and no suggestions.
- Team page on a Claude deployment: subtitle "Meet the agents and review their latest recorded work."; no reward area.

## Not verified

- A real `claude` run through the dashboard with the new code (suggestions from a real `Write` and `Edit` stream; the flag inside a
  dashboard-managed checks run). The `Write` and `Edit` input field names (hook requests, 2.1.322) and the flag's effect (one direct CLI run) were seen live earlier (`docs/superpowers/evidence/2026-11-10-live-proof.md` on branch `live-proof`, pull request 12); the stream line was captured live for `Write` only (2.1.312), not for `Edit`.
- Codex deployments (nothing changed there except the Team subtitle logic, covered by a node test only).
- A project registered under a path that Claude reports differently (for example `/tmp` against `/private/tmp`): suggestions are dropped,
  by design.
- The remaining live-proof findings (generic expired-login error, delivery panel redraw and focus, stale delivery line) are untouched.

## Final counts and reviews

- Python 3.12, full suite, clean HOME, at the final code commit: **1577 tests OK, 36 skipped**. Node: **220 of 220**. Docs test OK.
- The first full run (before the review fixes) failed 15 characterization tests: the new `output_suggestions` field had been added to
  every task in the snapshot, Codex tasks included. It is now added for Claude tasks only. This is the kind of Codex regression the
  characterization goldens exist to catch; the focused modules had not covered it.
- Whole-branch code review (read-only Opus): no Critical finding. Fixed: missing tests for path-spelling variants, for the absence of a
  leak through the real exit path and for the re-check after the scan; the dialog redraw could wipe typed input and focus; a
  docstring; one odd path cost all suggestions; the scan ran during shutdown; one test could pass without proving anything; two
  help sentences duplicated.
- Documentation review (read-only Sonnet acting as technical_writer and user_documentation_writer): fixed an overclaim about which
  `Write` and `Edit` shapes were seen live (field names in hook requests; stream line for `Write` only), the wrong button name
  ("Outputs", not "Attach output"), a stale task board line, a stale browser statement, a link to a file that is only on another branch,
  and dates. Sign-offs: technical_writer and user_documentation_writer reviewed the operations guide, API, setup, decisions, task board and
  evidence. The agent_evaluation_engineer checkpoint for this branch is not yet recorded in docs/model-evaluation.md.

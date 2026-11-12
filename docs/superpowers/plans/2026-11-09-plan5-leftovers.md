# Plan 5 Leftovers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four items left open after Plan 5 (slice 2b): record the deletion decision, suggest output files from a Claude run's `Write` and `Edit` calls, start the delivery checks runner without its write tools, and fix the Team page subtitle when rewards are off.

**Architecture:** Three small changes to existing flows plus records. The stream parser starts remembering one thing it did not before (file paths of main-session `Write`/`Edit` calls, in state only, never in an event); the dashboard turns them into bounded, scanned, project-relative suggestions that the owner still confirms one by one. The checks runner gets one extra CLI flag. No new module, listener, route or setting.

**Tech Stack:** Python 3.12+ standard library, SQLite store, plain browser JS (`dashboard/static/app.js`), `unittest`, node UI tests.

**Spec:** No separate spec file. The design was approved in chat by the owner on 2026-11-09 (bounded change). The owner's answers, which bind this plan:

1. Deleting a `claude_possibly_running` task: **warning only, as now**. No code change.
2. Output suggestions: **Write and Edit**. `Edit` was documentation-only when this was agreed; its input field names were seen in a live hook request on 2026-11-11 (one run, CLI 2.1.322: `file_path`, `old_string`, `new_string`, `replace_all`); the stream line itself was not captured for `Edit`, so it is labelled "field names seen live (hook request)" and not "untested".
3. Checks runner: **add** the switched-off tools. Existing guards stay.
4. Team subtitle: **drop the celebrate part when rewards are off**; Codex deployments keep today's text.

## Global Constraints

- One provider per deployment. Nothing here changes a Codex deployment's behaviour or wire output, except nothing: the Team subtitle changes only when `rewards === false`.
- Applies to Claude runs only. `build_argv` output for a run that is not a delivery checks run must stay byte-identical to today (pinned by existing tests in `tests/test_claude_launch.py`).
- Suggestions are never attached automatically. Attaching still goes through `attach_task_output` with `confirmed: true` and the existing checked-file preview.
- No file contents, tool input other than the one path, or command text is kept, logged or put into an event.
- Every displayed or stored path passes `checked_path` and `scan_preview` first; a refused path is dropped silently (no error text carries it).
- Caps: 32 raw paths remembered per run (`MAX_WRITTEN_PATHS`), 4096 characters per path, 8 suggestions shown per task turn (`MAX_OUTPUTS`).
- Evidence labels in docs and UI: `Write` path shape "seen live (CLI 2.1.312 and 2.1.322)"; `Edit` path shape "seen live (one run, CLI 2.1.322)"; `--disallowedTools` "removed `Write`, `Edit` and `NotebookEdit` from the tool list in one direct CLI run (2.1.322, 2026-11-11); not tested inside a dashboard-managed run".
- Run `python3 scripts/security_check.py staged` before each commit. No push, PR or live `claude` run without the owner's go in chat.
- Run full suites with a clean HOME (`HOME=$(mktemp -d)`); do not edit files while a full run is in progress.
- Roles are generated from `team_source/`; this plan edits no role file.

## Review Focus

1. A `Write`/`Edit` path outside the project, through a symlink, or with `..`: expected to be dropped, never shown. Test in Task 3.
2. A path that looks like a credential (secret scan refuses it): dropped, and no error or log line carries it. Test in Task 3.
3. A subagent's `Write`/`Edit` line (has `parent_tool_use_id`): not remembered; only main-session calls count. Test in Task 2.
4. More than 32 calls, or a replayed line after `--resume`: bounded, deduplicated, no growth. Test in Task 2.
5. A delivery checks or review run, or a task that cannot accept outputs: no suggestions exposed. Test in Task 3.

---

### Task 0: Security review of the output-suggestion design (before any build)

**Files:** none changed. Reviewer reads this plan (Tasks 2 to 4), `dashboard/backends/claude_stream.py`, `dashboard/task_outputs.py`, `SECURITY.md`.

- [ ] **Step 1:** Dispatch `security_reviewer` (read tools only) with the question: does keeping main-session `Write`/`Edit` file paths in `StreamState`, and showing scanned, project-relative ones as suggestions, open any route to disclose a secret, a path outside the project, or content; and are the caps and drop rules in Global Constraints enough.
- [ ] **Step 2:** Record findings in the ledger. Rule on each before Task 2 starts; fold accepted changes into the task dispatches. A Critical finding stops Tasks 2 to 4 and goes to the owner.

### Task 1: Checks runner starts without Write, Edit and NotebookEdit

**Files:**
- Modify: `dashboard/backends/claude_launch.py` (`build_argv`)
- Modify: `dashboard/server.py` (the one `build_argv(` call, near line 1389)
- Test: `tests/test_claude_launch.py`, `tests/test_claude_delivery.py`

**Interfaces:**
- Produces: `CHECKS_DISALLOWED_TOOLS = ("Write", "Edit", "NotebookEdit")` in `claude_launch.py`; `build_argv(..., disallowed_tools: Optional[Sequence[str]] = None)`.

- [ ] **Step 1: Failing tests** in `tests/test_claude_launch.py`:

```python
def test_disallowed_tools_adds_one_joined_flag(self):
    argv = build_argv(**self.base, disallowed_tools=CHECKS_DISALLOWED_TOOLS)
    i = argv.index("--disallowedTools")
    self.assertEqual(argv[i + 1], "Write,Edit,NotebookEdit")
    self.assertEqual(argv.count("--disallowedTools"), 1)

def test_no_disallowed_tools_leaves_argv_unchanged(self):
    self.assertEqual(build_argv(**self.base), build_argv(**self.base, disallowed_tools=None))
    self.assertNotIn("--disallowedTools", build_argv(**self.base))

def test_disallowed_tools_refuses_anything_else(self):
    for bad in (["Bash"], ["Write", "-x"], "Write", [], ["Write", "Write"], [1]):
        with self.assertRaises(ValueError):
            build_argv(**self.base, disallowed_tools=bad)
```

(`self.base` = the keyword set the file's existing tests already use for a valid call.)

- [ ] **Step 2:** Run `python3 -m unittest tests.test_claude_launch -v`; expect the three to fail.
- [ ] **Step 3: Implement.** Accept only a list or tuple whose items are distinct members of `CHECKS_DISALLOWED_TOOLS`, non-empty; else `ValueError("Invalid launch arguments")`. Append `["--disallowedTools", ",".join(items)]` after `--effort`/`--resume`, before the size check. One comma-joined value, because the CLI option is variadic.
- [ ] **Step 4: Failing test** in `tests/test_claude_delivery.py`: a delivery checks run's recorded argv (the file's fake-binary harness) contains `--disallowedTools Write,Edit,NotebookEdit`; a development run's and a review run's argv do not.
- [ ] **Step 5: Implement** in `server.py`: pass `disallowed_tools=CHECKS_DISALLOWED_TOOLS if isinstance(check_commands, Mapping) else None`. Leave `_check_calls` and the after-exit project-change check untouched.
- [ ] **Step 6:** Run `python3 -m unittest tests.test_claude_launch tests.test_claude_delivery tests.test_claude_stream`; expect OK.
- [ ] **Step 7:** Commit: `Start the delivery checks runner without Write, Edit and NotebookEdit`.

### Task 2: Stream parser remembers main-session Write and Edit paths

**Files:**
- Modify: `dashboard/backends/claude_stream.py` (`StreamState`, `_assistant`, module docstring lines 6 to 12)
- Test: `tests/test_claude_stream.py`

**Interfaces:**
- Produces: `MAX_WRITTEN_PATHS = 32`, `MAX_PATH_CHARS = 4096`, `WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path"}`; `StreamState.written_paths: list` of `(tool_name, raw_path)` tuples in first-seen order; `StreamState.written_overflow: bool`.

- [ ] **Step 1: Failing tests** (build lines with the file's existing assistant-line helper):

```python
def test_write_and_edit_paths_are_remembered_in_state_only(self):
    events = feed(state, assistant(tool_use("Write", {"file_path": "/p/a.md", "content": "SECRET"})))
    feed(state, assistant(tool_use("Edit", {"file_path": "/p/b.py", "old_string": "x", "new_string": "y"})))
    self.assertEqual(state.written_paths, [("Write", "/p/a.md"), ("Edit", "/p/b.py")])
    self.assertNotIn("/p/a.md", repr(events)); self.assertNotIn("SECRET", repr(state))

def test_subagent_lines_other_tools_and_bad_shapes_are_ignored(self):
    # parent_tool_use_id set; NotebookEdit; Bash; file_path not a str, empty, with NUL, or over 4096 chars
    self.assertEqual(state.written_paths, [])

def test_paths_are_deduplicated_and_capped(self):
    # same (tool, path) twice -> once; 40 distinct -> 32 kept and written_overflow True

def test_checks_run_still_reports_a_write_as_unmatched(self):
    # state.check_commands = {} ; a Write tool_use still yields check_command with check_id None
```

- [ ] **Step 2:** Run `python3 -m unittest tests.test_claude_stream -v`; expect the new ones to fail.
- [ ] **Step 3: Implement** in `_assistant`, after `content` is known and only when the line is a main-session line (the same test the function already uses for main-session text; a line whose `parent_tool_use_id` is a non-empty value is not). Inspect only `content[:MAX_MESSAGE_BLOCKS]`. Keep nothing but the tool name and the path string. Update the module docstring: tool_use input is still never copied into an event; the one exception kept in state is this path.
- [ ] **Step 4:** Run `python3 -m unittest tests.test_claude_stream`; expect OK.
- [ ] **Step 5:** Commit: `Remember main-session Write and Edit paths in the Claude stream state`.

### Task 3: Dashboard turns remembered paths into suggestions

**Files:**
- Modify: `dashboard/task_outputs.py` (`TaskOutputsMixin`)
- Modify: `dashboard/server.py` (where a Claude run's `StreamState` is finished and the task saved; the task snapshot near line 645)
- Test: `tests/test_task_outputs.py`, `tests/test_claude_delivery.py` or the Claude run test file that already drives a fake-binary development run

**Interfaces:**
- Consumes: `StreamState.written_paths` (Task 2).
- Produces: `TaskOutputsMixin.output_suggestions_from(project, turn_id, written_paths) -> list` of `{"path": <project-relative posix>, "tool": "Write"|"Edit", "turn_id": turn_id}`, at most `MAX_OUTPUTS`; stored on the task as `output_suggestions`; `TaskOutputsMixin.suggestion_metadata(task) -> list` of `{"path", "tool"}`; task snapshot key `output_suggestions` (always a list).

- [ ] **Step 1: Failing unit tests** in `tests/test_task_outputs.py` (real temp project directory):

```python
def test_suggestions_are_project_relative_and_bounded(self):
    # /proj/docs/a.md -> "docs/a.md"; 12 valid paths -> 8 kept, first-seen order
def test_outside_symlinked_dotdot_and_missing_paths_are_dropped(self):
    # /etc/passwd, proj/../x, a symlink inside proj pointing outside, a path that no longer exists, a directory
def test_secret_shaped_path_is_dropped_without_a_trace(self):
    # a path scan_preview refuses: result is [], and assertNoLogs / no exception text carries it
def test_suggestion_metadata_hides_wrong_turn_unattachable_and_already_attached(self):
    # turn_id mismatch -> []; can_attach_output False -> []; path already in outputs for the turn -> omitted
```

- [ ] **Step 2:** Run `python3 -m unittest tests.test_task_outputs -v`; expect failures.
- [ ] **Step 3: Implement.** Resolve each raw path against the project's real path the same way `preview_file`/`checked_path` already confine paths (reuse, do not reimplement; no follow of a symlink that leaves the project). Require an existing regular file. Run `scan_preview(path.encode("utf-8"))`. Any refusal or `OSError`/`FileAccessError`/`ValueError`: skip that path. Never read file contents here.
- [ ] **Step 4: Failing integration test:** a fake-binary development run whose stream holds one `Write` and one `Edit` inside the project and one `Write` outside it ends `completed` with `task["output_suggestions"]` naming the two inside paths; `GET /api/state` (or the route the file already uses) shows `output_suggestions` with `tool` set; a delivery checks run and a review run show `[]`; a follow-up turn replaces the previous turn's suggestions.
- [ ] **Step 5: Implement** in `server.py`: when a Claude development run (not a delivery context, `check_commands` not a Mapping) finishes as `completed`, compute and store the list under the dashboard lock with the task's current `turn_id`; otherwise store `[]`. A failure computing suggestions stores `[]` and never fails the run. Add `task['output_suggestions'] = self.suggestion_metadata(...)` beside the existing `outputs` line.
- [ ] **Step 6:** Run `python3 -m unittest tests.test_task_outputs tests.test_claude_delivery tests.test_claude_stream tests.test_delivery_backend`; expect OK.
- [ ] **Step 7:** Commit: `Offer Write and Edit paths of a Claude run as output suggestions`.

### Task 4: Outputs dialog shows suggestions; Team subtitle without rewards

**Files:**
- Modify: `dashboard/static/app.js` (`openOutputs`, `updateView`, the Team render)
- Test: the node UI test that covers the Outputs dialog and the one that covers the Team page (find with `grep -l "outputs-dialog\|team-grid" tests/*.js`); add `tests/test_output_suggestions_ui.js` if neither fits.

**Interfaces:**
- Consumes: task snapshot `output_suggestions` (Task 3); `/api/team` `rewards` flag (existing).

- [ ] **Step 1: Failing UI tests:**
  - With `can_attach_output: true` and two suggestions, the dialog shows a section headed `Files this run wrote or edited`, one row per suggestion with the path, the label `Write` or `Edit (path shape not verified live)`, and a button `Use this path`.
  - Pressing `Use this path` sets `#output-report-path` to that path, moves focus to it, does not tick the confirmation box and sends no request.
  - With `can_attach_output` not true, or an empty list, the section is absent.
  - The help text reads: `Suggested paths come from this run's Write and Edit tool calls, not from conversation. Only an explicitly selected, checked text file within this project can be associated.`
  - Paths render as text (`textContent`), never as HTML.
  - Team: with `rewards: false` the page subtitle is `Meet the agents and review their latest recorded work.`; with rewards on it is unchanged (`Meet the agents, review their latest recorded work and celebrate contributions.`). The subtitle is correct both when the Team view opens before `/api/team` answers and after.
- [ ] **Step 2:** Run the node tests (`node --test tests/*.js` or the project's existing command); expect the new ones to fail.
- [ ] **Step 3: Implement.** Suggestions section goes inside the existing `task.can_attach_output===true` block, above the form. Subtitle: choose the team text from `teamSnapshot?.rewards===false`, and refresh `#page-subtitle` after the team snapshot loads while the Team view is open.
- [ ] **Step 4:** Run all node tests; expect all pass.
- [ ] **Step 5:** Commit: `Show output suggestions in the Outputs dialog; fix the Team subtitle without rewards`.

### Task 5: Records, documentation, verification

**Files:**
- Modify: `docs/decisions.md` (new 2026-11-09 entry; mark the "OPEN owner decision: deleting a `claude_possibly_running` task" as decided: warning only, cost accepted), `docs/task-board.md` (carry items a, b, g and the subtitle), `docs/dashboard-operations.md`, `docs/dashboard-api.md` (`output_suggestions`), `docs/claude-code-setup.md` (evidence table rows with the labels from Global Constraints)
- Create: `docs/superpowers/evidence/2026-11-09-plan5-leftovers.md`
- Test: `tests/test_claude_docs.py` if it pins any changed sentence

- [ ] **Step 1:** `technical_writer` updates the operator and API docs and the records; `user_documentation_writer` reviews the dialog wording and the operations text. Each returns an explicit sign-off line naming what it reviewed.
- [ ] **Step 2:** Full Python suite on 3.12 and the default Python with a clean HOME, and all node tests, at the final head. Record counts and the head commit in the evidence file.
- [ ] **Step 3:** One browser check on a scratch copy by `qa_engineer`: Outputs dialog with suggestions (use, confirm, attach succeeds; an attached path disappears from suggestions), Team subtitle on a Claude deployment. Label it browser evidence; state what was not checked.
- [ ] **Step 4:** Whole-branch code review, then `agent_evaluation_engineer` completion checkpoint recorded in `docs/model-evaluation.md`.
- [ ] **Step 5:** Commit docs and evidence. Stop: pushing and the PR are the owner's decision. A live run to confirm `--disallowedTools` and the `Edit` shape needs the owner's go, with alias, count and cost estimate stated first.

---

## Task 0 result and rulings (binding on Tasks 2 to 4; they replace any conflicting text above)

Task 0 was run on 2026-11-11 by a read-only Opus reviewer (verdict: nothing Critical; three changes needed in Task 3). Its claims about
`project_files.py`, the stream dispatcher and `_claude_exit_locked` were checked against the code before ruling. Rulings:

1. **Path to project-relative: string logic only (Important, accepted).** Never `resolve`, `realpath` or `stat` a raw path. Use
   `PurePosixPath(raw).relative_to(PurePosixPath(project['path']))` (a prefix test without the separator is wrong: `/proj2` is not inside
   `/proj`). A path that does not match the registered project path as written (for example `/tmp/x` against `/private/tmp/x`) is dropped; that
   loses a suggestion and is the safe side. Order: string stage, then `checked_path`, then descriptor open (`root_descriptor`,
   `directory_identity` check as `_output_context` does, `source_descriptor`, which gives O_NOFOLLOW, regular file only and `st_nlink == 1`).
   Also drop files over the 256 KiB preview limit and paths whose characters include Unicode category Cf (bidi and zero-width characters).
2. **Scan the path only, never read content (Important, accepted).** The brief said content; Task 3 says path. Ruled: path only, as attach does
   first (`scan_preview(path.encode())`); the content is scanned at attach time by `preview_file`. Catch `Exception` around everything and never
   pass `str(error)` to a log, a diagnostic, a notice or a snapshot. No dropped count and no overflow flag is stored or exposed;
   `StreamState.written_overflow` is not built.
3. **Cost and locks (Important, accepted).** `scan_preview` starts two gitleaks processes (up to 12 s). Compute outside `self.lock`, after
   `_claude_exit_locked` has returned (in `_claude_exit`, after the hook cleanup), never inside it. Scan all candidate paths in one batch call
   (newline-joined); only if that is refused scan them one by one; stop at 8 accepted; total budget 15 s, then keep what is accepted. Also
   require "Git-visible and not ignored" (new small helper `git_visible_paths(root, paths)` in `project_files.py`, one `git ls-files` call for
   all candidates), otherwise attach would always refuse. Re-validate under the lock before storing exactly as `_register_output` does
   (`_output_context` stamp before and after: `turn_id`, `status`, `revision`, holds). The stream state reaches the exit handler as an
   optional fourth argument: `_claude_exit(task_id, run, run_exit, state=None)`, set from the launch code's closure.
4. **Storage (Minor, accepted).** Store the raw list as `task['claude']['output_suggestions']` (the snapshot already replaces `task['claude']`
   with an allow-listed summary). The snapshot adds `task['output_suggestions'] = suggestion_metadata(task)`, which is string-only, touches no
   file system, returns `[]` unless the provider is Claude and `can_attach_output(task)`, keeps only entries of the task's current `turn_id`,
   omits paths already attached for that turn, and returns `{"path", "tool"}` at most 8.
5. **Main-session rule (Minor, accepted).** Capture only in the stream parser's main-agent path (the dispatcher already drops any line whose
   `parent_tool_use_id` is not None or that has `agent_id`). Add test cases with `parent_tool_use_id` set to `""` and `0`. No second test.
6. **UI labels (Minor, accepted).** `Write` and `Edit` are both seen live, so rows read `Write` and `Edit` with no "not verified" text. Heading:
   `Files this run wrote or edited`. Help text adds that the paths were chosen by the model: `Suggested paths come from this run's Write and Edit
   tool calls and were chosen by the model, not by you. Only an explicitly selected, checked text file within this project can be associated.`
   Paths render as text in full (wrap, never cut off at the end).
7. **`--disallowedTools` (Task 1) strengthens only (accepted).** Keep `--disallowedTools` last in argv (after `--resume`). Add a test that a
   checks run started with the flag still fails when a `Write` line arrives (the existing guard stays).
8. **Extra tests Task 3 must have:** a FIFO, a hard link and a symlinked parent directory inside the project; a sibling directory whose name
   extends the project's (`/proj2`); case and Unicode-normalization variants of the project path; a stub that raises `OSError` naming the path
   (assert no log, diagnostic, notice or snapshot text carries it); a slow-scanner stub showing the exit handler never holds `self.lock` while
   scanning; Cf characters dropped; a non-Git-visible (ignored) file dropped.

# Claude Dashboard Plan 3: Managed Run Loop (no approvals yet)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a `claude` deployment the dashboard starts a managed `claude -p` run for a task, shows its status, usage and estimated cost, lets the owner stop it and send a follow-up through `--resume`, and keeps working on a machine that has no Codex. Calls that need permission are denied by Claude Code itself (no hook is installed until Plan 4) and the dashboard says so.

**Architecture:** A real `ClaudeBackend` (replacing the Plan 2 stub) in `dashboard/backends/` made of four small modules: a pure stream parser, a pure launch builder (argv, environment, roles, project instructions), a process runner, and the backend that joins them. The dashboard feeds the parser's `NeutralEvent`s into the same lifecycle handler Codex uses, extracted from `Dashboard.on_message` into `_apply_neutral_event`. A Claude `session_id` is the run's `thread_id`; a per-invocation counter is its `turn_id`. Everything is tested against a fake `claude` executable that replays sanitized stream-json.

**Tech Stack:** Python 3.15 standard library, the existing `unittest` and `node --test` suites, the `claude` CLI (Task 1 only, live).

**Spec:** `docs/superpowers/specs/2026-10-27-claude-dashboard-phase-2-3-design.md` (sections 4.1, 4.2, 4.4, 5, 8). Evidence this plan relies on: `docs/superpowers/spikes/` (S3, S6, S7, S8), `docs/superpowers/evidence/2026-10-28-provider-seam.md`. Code map (git-ignored scratch, implementers re-read the code): `.superpowers/sdd/plan3-map.md`.

**Plans after this one (not written):** Plan 4 = managed-run hook receiver and approvals (the "approve once and work resumes" journey, live acceptance). Plan 5 = slice 2b (conversations, team view, outputs, deletion, delivery readiness without the Ponytail gate). Plan 6 = Phase 3 (observed sessions).

## Decisions made for this plan (proposed defaults; the owner confirms or changes them at plan review)

1. **Role becomes the main session through the mechanism Task 1 proves.** Order tried: `--agent <role>` with `--agents` carrying the definitions; fallback `--model <alias>` plus the role body in `--append-system-prompt` (proven for text by S8). Task 1 decides; Task 5 builds only the winner.
2. **Child environment is an allow-list** (`PATH`, `HOME`, `USER`, `LANG`, `LC_*`, `TMPDIR`, `SHELL`, `TERM`) and always drops `ANTHROPIC_*`, `CLAUDE_CODE_*`, `AWS_*`, `GOOGLE_*`, `VERTEX*`, `BEDROCK*` so runs use the subscription login. Task 1 checks that a scrubbed environment still logs in; if it does not, the allow-list is widened by the smallest set that works and the note says which.
3. **Token mapping:** `input_tokens = inputTokens + cacheReadInputTokens + cacheCreationInputTokens`, `cached_input_tokens = cacheReadInputTokens`, `output_tokens = outputTokens`, `reasoning_output_tokens = thinkingTokens`, `total_tokens = input + output`, summed over every model in `modelUsage`. Cost is `total_cost_usd` shown as "Estimated USD (list price)", never a billed amount.
4. **Denied calls are surfaced** as a bounded list of tool names and a count on the task (no `tool_input`, no message text), with a notice "N tool calls were denied; approvals arrive in a later release".
5. **A run that ends without a `result` is `unknown`, not `recovery_hold`,** and can be continued with `--resume` because its session id is known.
6. **The dashboard passes the generic security baseline plus the expanded project instructions** through `--append-system-prompt` (S8). The project's `CLAUDE.md` gets its `@AGENTS.md` import expanded by the dashboard (one level, inside the project, regular files only, size capped).
7. **Stop ladder:** SIGINT, wait 10 s, SIGTERM to the process group, wait 5 s, SIGKILL; the child starts in its own session. Interrupt status is recorded from the dashboard's own signal, not from the exit code. On restart a possibly-still-running child is only warned about (pid and start time are recorded at spawn).
8. **A run whose `init.permissionMode` is not `default` is stopped immediately** and marked `failed` with a diagnostic; nothing it asks for is ever answered.
9. **The `claude` binary is looked up on `PATH`** (like Codex); `scripts/run_dashboard.sh claude` checks that it exists, as the `codex` argument checks for `codex`.
10. **Readiness is `claude --version` only.** The UI says "login not verified"; no account data is read.

## Global Constraints

- Codex behaviour must not change: `git diff --stat b547e0b..HEAD -- tests/fixtures/characterization/` stays empty; Plan 2's lifecycle parity tests keep passing. Existing tests are edited only in Task 7, and only the ones that pin the Plan 2 stub's "Claude backend is not implemented yet" behaviour (expected in `tests/test_provider_setting.py`, `tests/test_provider_routes.py`, `tests/test_provider_ui.js`; the implementer lists every edited test and why, and the reviewer checks each edit changes only the stub expectation).
- After every task, in a clean environment: `HOME=$(mktemp -d) XDG_CONFIG_HOME=$(mktemp -d) python3 -m unittest discover -s tests` (baseline at the start of this plan: 924 OK, skipped=36) and `node --test tests/*.js` (133 pass). No test removed or skipped to get green.
- Fail closed everywhere (spec section 7): an unknown state stays unknown; nothing is auto-allowed; there is no hook in this plan, so every call that needs permission is denied by Claude Code.
- Secrets: none in tracked files, fixtures, logs or commit messages. The fixtures are synthetic; every fixture passes the repository secret scan. The parser keeps only allow-listed fields: it never stores prompt text, assistant text, `tool_input`, `permission_denials[].tool_input`, hook output, `message` or `needs_action` text, plugin or MCP inventories, or absolute paths.
- `ProviderUnavailable` and `ProviderRefusal` are `ValueError`s: they are raised before any state change or caught before the generic launch and send error handlers, which would otherwise record `unknown` with `recovery_hold`.
- Live Claude runs only in Task 1 and the optional smoke in Task 11, each within the owner's approval recorded in the ledger (alias, count, estimated list price); `claude --version` recorded with each.
- Nothing is pushed, merged or published without the owner. Commit identity `K55Toms <K55Toms@users.noreply.github.com>`, every message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; run `python3 scripts/security_check.py staged` before each commit.
- Evidence kinds stay labelled: fake-binary tests, live runs and browser checks are separate kinds; a fake never establishes live behaviour.

## Review Focus

Each line is pinned by a test in the task named in brackets.

1. A `claude` deployment starts runs on a machine with no Codex plugin cache and no GPT-only role validation; the Codex deployment is unchanged. [Task 7]
2. `ANTHROPIC_API_KEY`, cloud-provider switches and `CLAUDE_CODE_*` variables never reach the child; the child gets exactly the allow-list. [Task 5, Task 6]
3. A run whose first `init` reports `permissionMode` other than `default` is stopped and marked failed; later events from it change nothing. [Task 8]
4. After `--resume` the usage and cost totals add the previous invocations' totals; a smaller number from a new process never lowers them; an empty `modelUsage` keeps the previous totals. [Task 3, Task 9]
5. A process that exits without `result` is `unknown` and resumable; a second or late `result` never flips a terminal state; an exit after our SIGINT is `interrupted` whatever the exit code. [Task 8, Task 9]
6. A fake that ignores SIGINT is escalated and reaped; closing the dashboard with a live run leaves no process. [Task 6, Task 9]
7. Sensitive stream content (hook output, tool input, message and summary text, absolute paths) never appears in the task record, the store, the snapshot or any log line. [Task 3, Task 8]
8. Instruction edge cases: a prompt starting with `-`, containing newlines, empty after trimming, over the length cap; a project `CLAUDE.md` importing a file outside the project, through a symlink, or a missing file: each is refused or handled safely, never passed unchecked. [Task 5]
9. The three-run cap, the 256-session cap (`runtime_tracking_lost`) and run deletion keep working with Claude sessions; sessions are not leaked after completion beyond what Codex threads do. [Task 8, Task 9]

---

### Task 1: Spike S9, role as main session, scrubbed environment, effort (live)

**Files:**
- Create: `docs/superpowers/spikes/S9-role-and-environment.md`
- Scratch (outside the repository, reuse the S6 and S8 harness folders next to each other: copy to `<scratchpad>/s9`)

**Interfaces:**
- Produces: the verdict Task 5 builds on: how the main session becomes a role, whether a scrubbed environment still logs in, and whether a main-session effort setting exists.

- [ ] **Step 1: Check the documented switches before spending a run.** `claude --help`: `--agent`, `--agents`, `--append-system-prompt`, any `--effort` or effort environment variable, and the `--bare` text. Record what is documented and what is not.
- [ ] **Step 2: Build a scratch project** with a role file in the generated format (`name`, `description`, `model: haiku`, `effort`, body containing the codeword `slate-orchard-3333`) and a prompt "State the codeword in your role instructions; answer NONE if you have none. No tools."
- [ ] **Step 3: Run, at most 4 live runs, alias `haiku`, one per condition, stdin `/dev/null`, `--setting-sources user`, cwd an empty directory:** R9a `--agents '<json with the role>' --agent <role>`; R9b `--model haiku --append-system-prompt "<role body>"` (control, only if R9a fails); R9c the winner again with `env -i` and exactly the allow-list from decision 2 (does it log in and answer?); R9d only if Step 1 found an effort switch: the winner with that switch. Record `claude --version`, `init.model`, `init.permissionMode`, the answers, `result` fields.
- [ ] **Step 4: Write the note** in the format of `docs/superpowers/spikes/S8-project-instructions.md`: header, documented switches, verdict table, commands, what each run does not prove, and a one-line recommendation for Task 5 (the mechanism, the environment allow-list actually needed).
- [ ] **Step 5: Commit** `docs: S9 role and environment spike` after `python3 scripts/security_check.py staged`.

### Task 2: Fake `claude` executable and sanitized fixtures

**Files:**
- Create: `tests/fixtures/claude/` (sanitized `.jsonl` fixtures: `success.jsonl`, `denied.jsonl`, `resumed.jsonl`, `interrupted.jsonl`, `bad_model.jsonl`, `no_result.jsonl`, `multi_result.jsonl`, `malformed.jsonl`, `permission_mode_auto.jsonl`, `huge_line.jsonl`), `tests/fake_claude.py`, `tests/test_claude_fixtures.py`
- Source material: `<scratchpad>/s6/out`, `<scratchpad>/s8/out`, `<scratchpad>/s3` stream files; `.superpowers/sdd/plan3-map.md` section 5 for shapes

**Interfaces:**
- Produces: `tests/fake_claude.py`, an executable script (`#!` with `sys.executable`) that replays `FAKE_CLAUDE_FIXTURE` (a fixture name) to stdout, optionally slowly (`FAKE_CLAUDE_DELAY_MS`), honours SIGINT by printing the `interrupted` tail and exiting 0 unless `FAKE_CLAUDE_IGNORE_SIGINT=1`, and appends its argv, working directory and the names (not values) of its environment variables to the file named by `FAKE_CLAUDE_RECORD`. `tests/fake_claude.py` is also importable: `fixture_path(name) -> Path`, `recorded(path) -> dict`.

- [ ] **Step 1: Write failing tests** in `tests/test_claude_fixtures.py`: `test_every_fixture_is_valid_jsonl_except_malformed`, `test_fixtures_pass_the_repository_secret_scan` (use `project_files.scan_preview` or the characterization `normalize` scanner path, skipping like the others when the scanner is missing and failing in CI via `require_scanner`), `test_fixtures_contain_no_absolute_paths_or_real_ids`, `test_fake_replays_success_and_exits_0`, `test_fake_sigint_prints_tail_and_exits_0`, `test_fake_ignoring_sigint_keeps_running_until_killed`, `test_fake_records_argv_cwd_and_env_names_only`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Build the fixtures from the real streams** by replacing ids, paths and text with fixed placeholders (`<SID>` becomes a synthetic UUID, texts become short synthetic strings); keep every key the parser needs (map section 5); `huge_line.jsonl` has one line just over 16 MiB generated at test time, not stored (the test builds it; the fixture file holds a marker).
- [ ] **Step 4: Run the tests; expected pass; run both full suites.**
- [ ] **Step 5: Commit** `test: fake claude executable and sanitized stream fixtures`.

### Task 3: Stream parser, usage and cost mapping

**Files:**
- Create: `dashboard/backends/claude_stream.py`, `tests/test_claude_stream.py`

**Interfaces:**
- Consumes: `NeutralEvent` from `dashboard/backends/base.py`; fixtures from Task 2.
- Produces, in `claude_stream.py`:
  - `@dataclass class StreamState`: `session_id: Optional[str]`, `turn_id: str`, `baseline: Mapping` (previous invocations' usage totals and cost, defaults zero), `seen_result: bool`, `denied_tools: list` (names only, at most 20, duplicates kept as counts in `denied_count`), `permission_mode: Optional[str]`, `model_id: Optional[str]`, `version: Optional[str]`.
  - `translate_stream_line(line: str, state: StreamState) -> list[NeutralEvent]`: total, never raises, bounded; parses one JSON line (non-JSON or non-dict gives `[]`); mutates only `state`. `system/init` gives `turn_started(thread_id=session_id, turn_id=state.turn_id)` and fills `state`; `result` gives `usage_updated` (running totals = baseline + this process's `modelUsage` sums, never lower than the previous event's totals; empty `modelUsage` keeps the previous totals) then, only if `not state.seen_result`, `turn_completed` with `status` `completed` (`is_error` false), `failed` (`is_error` true and not an abort), or `unknown` (`terminal_reason` starting `aborted`; the dashboard overrides to `interrupted` when it sent SIGINT), with `data["error"]` a small dict `{"terminal_reason", "api_error_status", "subtype"}` (no text); a later `result` returns `[]`. `system/permission_denied` and `result.permission_denials[]` update `denied_tools`/`denied_count` from tool names only. Every other event, including `assistant`, `user`, `stream_event`, hook events and `task_*`, returns `[]`. Events carrying `parent_tool_use_id` or `agent_id` are ignored.
  - `usage_from_model_usage(model_usage: Mapping) -> dict` with exactly the five keys of `USAGE_KEYS`, using decision 3; `cost_usd(result: Mapping) -> float` (`total_cost_usd`, bounded `0 <= x <= 1e6`, else 0).
  - `NeutralEvent.data` for `usage_updated` adds `{"cost_usd": <running total>}`.
  - `ClaudeCapabilities`: `Capabilities(provider="claude", guidance_while_running=NO, subagent_questions=NO, plan=UNCONFIRMED, recovery=NO, assessment=NO, approval_alternative=NO)`.

- [ ] **Step 1: Write failing tests**, one per behaviour above using the Task 2 fixtures: `test_init_gives_turn_started_and_fills_state`, `test_result_success_gives_usage_then_completed`, `test_result_error_is_failed`, `test_aborted_terminal_reason_is_unknown`, `test_second_result_is_ignored`, `test_denials_keep_tool_names_and_counts_only`, `test_subagent_events_are_ignored`, `test_junk_lines_never_raise` (`""`, `"x"`, `"[]"`, `"{"`, nested wrong types, a 1 MB line), `test_usage_mapping_sums_models_and_counts_cache_as_input`, `test_baseline_adds_and_totals_never_decrease` (Review Focus 4), `test_empty_model_usage_keeps_previous_totals`, `test_no_sensitive_text_in_any_event` (feed `success.jsonl`/`denied.jsonl`; assert the repr of all events contains none of the fixture's synthetic text, path or `tool_input` markers; Review Focus 7), `test_every_emitted_kind_is_in_event_kinds`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** to the signatures above; allow-list readers only.
- [ ] **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude stream parser`.

### Task 4: Extract the neutral lifecycle handler (Codex unchanged)

**Files:**
- Modify: `dashboard/server.py` (`on_message` body after `self.backend.translate`), `dashboard/conversation.py` (`_conversation_metadata` turn bookkeeping around :258-275)
- Create: `tests/test_neutral_apply.py`

**Interfaces:**
- Produces: `Dashboard._apply_neutral_event(self, task: dict, event: NeutralEvent) -> None` (caller holds `self.lock`; contains today's branches and the shared tail `updated_at` + `store.put("task", task)`); `Dashboard._note_turn(self, thread_id: str, turn_id: str, phase: str, status: Optional[str] = None) -> None` where `phase` is `"started"` or `"completed"`, doing exactly the `owned_threads[...]["turns"/"current_turn"/"active"/"last_status"]` updates `_conversation_metadata` does. `on_message` and `_conversation_metadata` call them; behaviour is identical for Codex.

- [ ] **Step 1: Write tests that pass before the change** (`test_apply_neutral_event_matches_on_message_for_each_kind`: for each lifecycle kind, build the same task state twice, once through `on_message`, once through `_apply_neutral_event(task, translate(msg))`, and compare tasks and stores; `test_note_turn_started_and_completed_update_owned_thread`). Capture the passing baseline.
- [ ] **Step 2: Refactor** the two extractions; no logic change.
- [ ] **Step 3: Run the lifecycle parity tests, the characterization modules and both full suites; expected: unchanged results plus the new tests, goldens identical.** **Step 4: Commit** `refactor: extract neutral lifecycle application`.

### Task 5: Claude launch builder (argv, environment, roles, instructions)

**Files:**
- Create: `dashboard/backends/claude_launch.py`, `tests/test_claude_launch.py`
- Read: `.claude/agents/*.md`, `team_source/policy.py`, `team_source/models.toml`, `dashboard/server.py` (`SAFETY_INSTRUCTIONS`), `docs/superpowers/spikes/S8-project-instructions.md`, `docs/superpowers/spikes/S9-role-and-environment.md`

**Interfaces:**
- Produces, in `claude_launch.py`:
  - `load_claude_roles(root: Path) -> dict`: reads `.claude/agents/*.md` (tiny front-matter reader for `name`, `description` (bare or JSON string), `model`, `effort`, `tools` (comma list), `disallowedTools`; body = instructions); returns the same shape `Dashboard.roles` uses (`id, label, model, profile_model, reasoning, instructions, description`); validates model and effort against `team_source.policy` sets and rejects anything else with `ValueError`.
  - `agents_json(role: Mapping) -> str`: the `--agents` JSON for one role in the shape proven live (`description`, `prompt`, `tools` array when present, `model`).
  - `expand_project_instructions(project: Path, max_bytes: int = 65536) -> str`: reads `<project>/CLAUDE.md`; replaces each line that is exactly `@<relative path>` with that file's contents (one level only; the target must resolve inside the project, be a regular file and not a symlink, be at most `max_bytes`, UTF-8, free of control characters other than newline and tab); anything else raises `ValueError` with a fixed message; a missing `CLAUDE.md` gives `""`.
  - `child_environment(parent: Mapping) -> dict`: the allow-list of decision 2 (adjusted by Task 1), dropping the listed prefixes.
  - `build_argv(claude_path: str, *, prompt: str, alias: str, role_mechanism: <as proven by Task 1>, instructions: str, resume: Optional[str]) -> list[str]`: exactly `[claude_path, "-p", prompt, "--output-format", "stream-json", "--verbose", "--setting-sources", "user", "--model", alias, ...]` plus the Task 1 role flags, `--append-system-prompt <safety baseline + instructions>` and `--resume <sid>`; rejects a prompt that is empty after trimming, longer than 16000 characters, contains NUL, or starts with `-` by raising `ValueError("Invalid instruction")` (the prompt is not passed as a flag value).

- [ ] **Step 1: Write failing tests**, including Review Focus 2 and 8: `test_roles_load_from_generated_files_and_validate`, `test_role_with_unknown_model_or_effort_is_rejected`, `test_agents_json_matches_the_live_shape`, `test_expand_inlines_agents_md_one_level`, `test_expand_refuses_outside_project_symlink_missing_oversize_and_nested_import`, `test_environment_is_exactly_the_allow_list` (parent has `ANTHROPIC_API_KEY`, `AWS_PROFILE`, `CLAUDE_CODE_USE_BEDROCK`, `PATH`, `HOME`; assert only allowed names remain), `test_argv_is_exact_and_fixed_flags_come_first`, `test_prompt_edge_cases_are_refused`, `test_resume_is_appended_only_with_a_session_id`.
- [ ] **Step 2: Run them to see them fail.** **Step 3: Implement.** **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude launch builder`.

### Task 6: Process runner

**Files:**
- Create: `dashboard/backends/claude_runner.py`, `tests/test_claude_runner.py`

**Interfaces:**
- Consumes: Task 2's fake, Task 3's `translate_stream_line`/`StreamState`, Task 5's `build_argv`/`child_environment`.
- Produces: `class ClaudeRun` with `__init__(self, argv, *, cwd, env, state: StreamState, on_event, on_exit, process_factory=subprocess.Popen, clock=time.monotonic)`; `start() -> None` (spawns with `stdin=DEVNULL`, `stdout=PIPE`, `stderr=PIPE` drained by a bounded thread (last 8 KiB kept, never logged), `start_new_session=True`, `close_fds=True`); a reader thread that reads lines with a 16 MiB cap (a longer line ends the run as `unknown` with a fixed diagnostic and stops the child), calls `translate_stream_line`, and passes each event to `on_event`; `stop(reason: str) -> None` implementing decision 7 and setting `stopped_by_us=True` before the first signal; `pid`, `started_at`, `exit_code`, `cleanup_complete` (an Event); `on_exit(RunExit)` is called exactly once with `RunExit(code, stopped_by_us, reason, saw_result, overflow)`. The runner never decides statuses; the dashboard does.

- [ ] **Step 1: Write failing tests** using the fake: `test_spawn_uses_devnull_stdin_new_session_and_exact_env` (Review Focus 2: the fake records env names), `test_events_flow_in_order_and_exit_is_reported_once`, `test_line_over_the_cap_ends_the_run_unknown_and_stops_the_child`, `test_malformed_line_is_skipped`, `test_stop_sends_sigint_and_reports_stopped_by_us`, `test_child_ignoring_sigint_is_terminated_then_killed_and_reaped` (Review Focus 6; shorten the waits through constructor arguments), `test_stop_after_exit_is_a_noop`, `test_stderr_is_bounded_and_not_in_events`, `test_close_reaps_and_leaves_no_zombie`.
- [ ] **Step 2: Run them to see them fail.** **Step 3: Implement.** **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude process runner`.

### Task 7: Claude backend, readiness and a provider-aware start gate

**Files:**
- Modify: `dashboard/backends/claude.py` (replace the stub), `dashboard/backends/__init__.py` (resolver unchanged in signature), `dashboard/server.py` (`start()`, `_provider_refusal`, `DISABLED_DETAIL`, `_start_task` policy and connection gates, `_verify_task_policy`), `scripts/run_dashboard.sh`, `dashboard/static/app.js` (labels only), `README.md`, `docs/dashboard-operations.md`
- Create: `tests/test_claude_readiness.py`

**Interfaces:**
- Produces: `ClaudeBackend` with `capabilities = ClaudeCapabilities`, `probe() -> dict` (runs `[claude_path, "--version"]` through an injectable runner with a 5 s timeout; returns `{"ok": bool, "version": str|None, "detail": str}`; the output is validated against `^[0-9][0-9A-Za-z.\- ]{0,40}( \(Claude Code\))?$` and nothing else is kept), `start_run(spec, on_event, on_exit) -> ClaudeRun` (built in Task 8), and the Codex-shaped protocol methods still raising `ProviderUnavailable("This operation is not available for the Claude backend")`. `Dashboard.start()` for `claude` runs the probe once in a thread; success sets `connection = {"status": "connected", "detail": "Claude Code <version> (login not verified)", "server_version": <version>, ...}`, failure sets `disabled` with "Claude Code was not found on PATH." (a fixed text). `_provider_refusal` no longer refuses `claude`. For a `claude` Dashboard `_start_task` skips `policy_provider.load()` and the Codex-only `native_roles.config` verification and sets `compliance_policy=None`, `compliance_role_digest=None`; delivery stays off because `compliance_policy` is None (verify the snapshot and delivery summary tolerate it). `scripts/run_dashboard.sh claude` requires `claude` on `PATH` (usage text unchanged otherwise).

- [ ] **Step 1: Write failing tests**: `test_probe_accepts_a_version_line_only` (fake prints a good line, a long line, a line with control characters, a multi-line output), `test_claude_dashboard_connects_after_probe_and_enables_start`, `test_missing_claude_disables_with_fixed_text`, `test_claude_start_works_without_codex_plugin_cache_or_gpt_roles` (Review Focus 1: construct with `policy_provider` that raises and assert the Claude path never calls it), `test_codex_deployment_gates_are_unchanged`, `test_protocol_methods_still_raise_provider_unavailable`, `test_script_requires_claude_on_path_for_claude_only` (scratch PATH without `claude`: exit 1 with the fixed message; with `codex` argument no `claude` check), and a Node test that the connection label for `claude`/`connected` reads "Claude connected" and Start run is enabled, while `disabled` keeps the Task 10 behaviour.
- [ ] **Step 2: Run them to see them fail.** **Step 3: Implement.** **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude readiness and provider-aware start gate` (the commit message notes the CODEOWNERS-reviewed script change).

### Task 8: Claude start path and lifecycle

**Files:**
- Modify: `dashboard/server.py` (`_start_task` Claude branch, new `_launch_claude_task`, `_claude_event`, `_claude_exit`, the 3-run cap check, `launching_tasks`), `dashboard/diagnostics.py` (Claude codes and wording), `dashboard/backends/claude.py` (`start_run`)
- Create: `tests/test_claude_runs.py`

**Interfaces:**
- Produces: for a `claude` Dashboard, `start_task` creates the same task record as Codex (`provider: "claude"`, `model` and `reasoning` from the Claude role, `thread_id: None`, `turn_id: None`, `claude: {"invocations": 1, "session_id": None, "version": None, "model_id": None, "pid": None, "started_at": None, "denied_count": 0, "denied_tools": [], "usage_baseline": {...}, "cost_baseline": 0.0}`), then a worker calls `_launch_claude_task(task_id)`, which builds the argv (Task 5), registers the run in `self.runs[task_id]` and starts it (Task 6). `_claude_event(task_id, run, event)` (stale runs ignored: `self.runs.get(task_id) is run`) registers the thread on the first event carrying the session id (`_register_thread`), records `session_id`, version and `model_id`, applies `_apply_neutral_event` (Task 4) under `self.lock`, calls `_note_turn`, updates `task["usage"]` and `task["cost"] = {"basis": "estimated", "unit": "usd-estimate", "usd": <total>, "credits": None, "source": "Claude Code result.total_cost_usd (list price)", "pricing_date": None}`, and sets `denied_count`/`denied_tools`; a `turn_started` whose state reports `permission_mode != "default"` stops the run (decision 8) and marks it `failed` with diagnostic `claude_permission_mode`. `_claude_exit(task_id, run, exit)` finishes: no `result` seen gives `unknown` without `recovery_hold` and the diagnostic `claude_no_result`; `stopped_by_us` gives `interrupted`; a `result` already applied is kept; the run is removed from `self.runs`. Diagnostics: `classify_claude(error: Mapping|None, exit_code) -> str` returning codes `claude_api_error`, `claude_not_logged_in`, `claude_model_unavailable`, `claude_aborted`, `claude_exit_nonzero`, `claude_no_result`, `claude_permission_mode`, `claude_output_too_large` with Claude-worded fixed messages added to `DETAILS`; unknown codes still coerce to `execution_failed`. The instruction is appended to the message log as `_append_message(task_id, "user", instruction, turn_id, "You", status="sent")` exactly as Codex does. The task's `denied_count` > 0 adds the notice of decision 4 to `task["blocker"]`-style display data (use the existing diagnostic list with code `claude_calls_denied`).

- [ ] **Step 1: Write failing tests** driving the fake through `Dashboard.start_task` with `client_factory` untouched and a `ClaudeBackend` using the fake binary: `test_run_goes_queued_running_completed_with_usage_and_cost`, `test_failed_result_is_failed_with_claude_diagnostic`, `test_exit_without_result_is_unknown_not_recovery_hold`, `test_late_second_result_changes_nothing`, `test_permission_mode_not_default_stops_and_fails` (Review Focus 3, with `permission_mode_auto.jsonl`; assert later events change nothing), `test_denied_calls_are_counted_by_name_only_and_noticed`, `test_no_sensitive_text_reaches_task_store_or_snapshot` (Review Focus 7: grep the store rows and snapshot JSON for fixture markers), `test_three_run_cap_applies_to_claude_runs`, `test_session_registration_uses_owned_threads_and_respects_the_cap` (Review Focus 9), `test_provider_unavailable_before_state_change_does_not_record_unknown` (R3 ordering), `test_stale_run_events_are_ignored`.
- [ ] **Step 2: Run them to see them fail.** **Step 3: Implement.** **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude managed run lifecycle`.

### Task 9: Stop, shutdown, restart and follow-up

**Files:**
- Modify: `dashboard/server.py` (`interrupt`, `close()`, the `main()` shutdown handler, the restart sweep), `dashboard/conversation.py` (`send_message`, `_send_state`)
- Create: `tests/test_claude_stop_resume.py`

**Interfaces:**
- Produces: `Dashboard.interrupt(task_id)` for a Claude task calls `self.runs[task_id].stop("owner")` with no connection check and returns once the signal is sent; `Dashboard.stop_all_runs(timeout: float = 20.0) -> None` stops every live run and reaps; `close()` and the shutdown handler call it. The restart sweep still marks active tasks `unknown`, now also keeping `claude.session_id` and recording a diagnostic `claude_possibly_running` with the stored pid and start time when that pid still exists with the same start time (compare via `ps -o lstart= -p <pid>` through an injectable runner; warn only). `send_message` for a Claude task: mode `followup` only (`steer` answers "Guidance cannot be sent into a running Claude turn; send a follow-up after it finishes"), allowed when the task is `completed`, `failed`, `interrupted` or `unknown` and `claude.session_id` is set, increments `claude.invocations`, uses turn id `turn-<n>`, passes `--resume <session_id>`, sets baselines from the current totals, keeps the 200-turn cap, and refuses while a run is active.

- [ ] **Step 1: Write failing tests**: `test_stop_during_streaming_records_interrupted_whatever_the_exit_code` (Review Focus 5), `test_stop_escalates_when_the_child_ignores_sigint` (Review Focus 6), `test_close_with_a_live_run_leaves_no_process`, `test_restart_marks_unknown_keeps_session_and_warns_about_a_live_pid`, `test_followup_resumes_the_same_session_and_adds_usage_and_cost` (Review Focus 4: `resumed.jsonl`; the fake asserts `--resume <sid>` in argv), `test_followup_refused_while_running_and_for_steer`, `test_unknown_run_without_session_id_cannot_resume`, `test_followup_after_unknown_with_session_id_works`, `test_instruction_edge_cases_are_refused_before_state_change` (Review Focus 8 through the HTTP layer).
- [ ] **Step 2: Run them to see them fail.** **Step 3: Implement.** **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude stop, shutdown, restart and follow-up`.

### Task 10: Cost, usage and UI adaptation

**Files:**
- Modify: `dashboard/server.py` (`snapshot()["pricing"]` per provider), `dashboard/static/app.js`, `dashboard/static/index.html`
- Create: `tests/test_claude_ui.js`, `tests/test_claude_snapshot.py`

**Interfaces:**
- Produces: for `claude`, `snapshot()["pricing"] = {"unit": "usd-estimate", "source": "Claude Code client-side list-price estimate", "speed_basis": "Not a billed amount; the subscription login is not billed per call"}` (Codex snapshot unchanged, goldens identical). The UI sums `cost.usd` when `cost.unit == "usd-estimate"` and labels "Estimated USD (list price)"; mixed units show "Mixed basis"; the pricing note drops the credits-only links for `claude`; the plan empty text and the usage empty text name the provider ("No plan steps have been reported by <provider>."); `renderDetail` shows the denied-call notice from the diagnostics list; the Stop button is enabled for an active Claude task when `connection.status === "connected"`.

- [ ] **Step 1: Write failing tests**: Python `test_claude_snapshot_has_usd_pricing_and_codex_snapshot_is_unchanged`; Node `test_usd_estimate_is_summed_and_labelled`, `test_mixed_units_show_mixed_basis`, `test_plan_and_usage_text_name_the_provider`, `test_denied_notice_renders_as_text` (no HTML injection), `test_stop_enabled_for_active_claude_task`, `test_codex_wording_unchanged_without_provider_endpoint`.
- [ ] **Step 2: Run them to see them fail.** **Step 3: Implement** (add nodes and functions; keep ids used by the existing JS tests). **Step 4: Run the full suites.** **Step 5: Commit** `feat: Claude cost, usage and UI wording`.

### Task 11: Journey tests, documentation closeout and evidence

**Files:**
- Create: `tests/test_claude_journey.py`, `docs/superpowers/evidence/2026-10-28-managed-run-loop.md`
- Modify: `docs/dashboard-operations.md`, `docs/dashboard-api.md`, `docs/product-brief.md`, `docs/claude-code-setup.md`, `docs/decisions.md`, `docs/task-board.md`, this plan's Interfaces text if the build refined it

- [ ] **Step 1: Write the fake-binary journey test** over HTTP: start a Claude deployment, start a run, stream, a denied call, completion, usage and cost visible in `/api/state`, follow-up with `--resume`, stop of a second run, restart sweep; label it fake-binary evidence.
- [ ] **Step 2: Assign `technical_writer` and `user_documentation_writer`** (`AGENTS.md`); update the docs listed (what a `claude` deployment can do now, what it cannot: no approvals, no conversation view, no plan, no delivery; the denied-call notice; the environment allow-list; the new `diagnostic` codes; the cost unit); record each decision of this plan in `docs/decisions.md`.
- [ ] **Step 3: Optional live smoke, only with the owner's recorded approval** (alias `haiku`, one run through the dashboard on a scratch project: start, completion, follow-up; `claude --version` recorded; list-price estimate stated before the run): the note `docs/superpowers/spikes/S10-dashboard-live-smoke.md` labels it live evidence. Without approval, record the gap.
- [ ] **Step 4: Write the evidence file:** commits per task, suite counts before and after, `git diff --stat b547e0b..HEAD -- tests/fixtures/characterization/` (expected empty), the kinds of evidence, what remains untested (approvals, a long real run, Windows or Linux, other aliases, user-level allow rules), review history.
- [ ] **Step 5: Run both suites in the clean environment, `python3 scripts/sync_roles.py --check`, `python3 scripts/security_check.py staged` and `history`;** commit `docs: managed run loop closeout`; ask the owner for review; do not start Plan 4 without their go.

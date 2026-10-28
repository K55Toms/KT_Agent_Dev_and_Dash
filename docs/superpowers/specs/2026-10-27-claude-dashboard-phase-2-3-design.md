# Claude dashboard (Phases 2 and 3): design

Project: [K55Toms/KT_Agent_Dev_and_Dash](https://github.com/K55Toms/KT_Agent_Dev_and_Dash)
Date: 2026-10-27
Status: approved by the owner on 2026-10-27, including the assumptions in section 1 and the open items in
section 8 as written. Nothing in this document is implemented. Plan 1 (baseline and spikes) has been
run: spikes S6 and S7 are written up in `docs/superpowers/spikes/2026-10-27-phase-2-spikes-findings.md`
(owner go for Plan 2 given 2026-10-28; sections 4.2, 4.3 and 8 updated from the findings). Plan 1 is in
`docs/superpowers/plans/2026-10-27-claude-dashboard-baseline-and-spikes.md`. Builds on the
approved [Claude Code adaptation design](2026-10-26-claude-code-adaptation-design.md), whose Phase 0
and Phase 1 are merged. Amends that design as listed in section 2.

## 1. Intent

### Stated by the owner

- The dashboard is deployed on ChatGPT (Codex) or on Claude, never both at the same time. One
  build holds both providers; a deployment setting selects exactly one and the other stays disabled
  (decision recorded 2026-10-27 in `docs/decisions.md` by pull request 3, open and not yet merged).
- In a Claude deployment, every dashboard feature works except the Codex-only ones (unknown-task
  recovery and assessment, which need Codex or ChatGPT-plan sign-in).
- Phase 2 (dashboard starts and owns Claude runs) and Phase 3 (observing the owner's own Claude
  sessions, including approvals) are both part of this release, in one design.
- Build Phase 2 in two slices inside one release: slice 2a (provider setting, Claude backend,
  core run loop, approvals) and slice 2b (the carried-over features).
- Architecture: a provider-neutral backend interface, with `server.py` and its collaborators
  refactored onto it (approach B). The owner chose this over a Claude client behind the existing
  `client_factory` seam (approach A, which was the recommendation) and over a parallel module.
- Managed approvals use `claude -p` with a hook, not the Agent SDK. This is untested in the
  dashboard's launch mode, so a feasibility spike (S6) comes first.
- Sign-in stays the Claude subscription login (recorded 2026-10-26). The Anthropic terms question
  is the owner's own judgement and is not resolved by this design.
- Ponytail is off in the Claude deployment now. The policy source is chosen per provider so a later
  switch-on needs no redesign.
- Done when: a run starts, requests permission, the owner approves once, work resumes and
  completes, and decline, stop and stale-request outcomes are distinct (Phase 2); and the owner can
  see and answer permission requests from their own Claude session (Phase 3).

### Assumed, not yet confirmed

- Codex behaviour must not change. The full Python and Node suites run before the refactor and
  after every step.
- The per-project Automatic approval mode does not extend to Claude runs; they are manual-only.
- `AGENTS.md`, `SECURITY.md`, gitleaks and the git hooks apply unchanged.
- Delivery readiness for Claude runs keeps every gate except Ponytail compliance, which reads
  "not applicable for Claude" and never counts as passed.
- Cost is shown as a list-price estimate with its source, never as a billed amount.

## 2. Amendments to the 2026-10-26 design

| # | Earlier text | Now |
| --- | --- | --- |
| P1 | Recovery, task deletion and delivery readiness are Codex-only in the first version. | Task deletion and delivery readiness work for Claude runs (slice 2b). Recovery and assessment stay Codex-only. |
| P2 | Observing own sessions is a later phase, not part of the first version. | Phase 3 is part of this release. |
| P3 | Non-goal: recovery, deletion and delivery-readiness support for Claude runs. | Narrowed to recovery only. |
| P4 | Backend adapter, interface undefined. | A neutral interface with a Codex translator and a Claude backend (section 4). |
| P5 | Spike S2/S3 decide Agent SDK versus `claude -p`. | `claude -p` with a hook, pending spike S6. If S6 fails the owner decides again. |
| P6 | Ponytail not used on the Claude side. | Unchanged for now, with the gate's policy source made per provider. |

## 3. Findings that shaped the design

- Codex coupling is concentrated in a few modules. Counts of Codex-shaped references (thread and
  turn ids, `item/` and `turn/` methods, `codex`): `server.py` 105, `conversation.py` 123,
  `recovery.py` 72, `approval_review.py` 27, `delivery.py` 16, `diagnostics.py` 14,
  `task_outputs.py` 17. `native_roles.py` has none.
- `Dashboard.__init__` already takes `client_factory=CodexClient`, and `server.py` uses about a
  dozen request methods (`thread/start`, `turn/start`, `turn/steer`, `turn/interrupt`,
  `model/list` and recovery reads). This is the seam approach A would have used; approach B goes
  further.
- Phase 0 evidence (see `docs/superpowers/spikes/2026-10-26-phase-0-findings.md`): a headless run
  prints stream-json; there was no plan event; running is inferred from the absence of a final
  `result`; subagent lineage is `parent_tool_use_id`, `task_id` and `agent_id`; a project-level
  hook is skipped under `--setting-sources user`; a hook answered permissions in `-p` mode;
  permission hooks reach only requests that get to a prompt, so Auto mode approvals are not seen.
- Ponytail 5.3.2 is the latest release of the MIT repository DietrichGebert/ponytail (checked
  2026-10-27 with the GitHub API). The release ships both Claude and Codex plugin manifests.
  The dashboard's gate reads `skills/ponytail/SKILL.md` from the Codex plugin cache and checks
  version 5.3.2 and a SHA-256 digest (`dashboard/ponytail_policy.py`). The benefit claims found by a
  web search (about 15% less code in a JetBrains test) could not be verified: the post returned
  HTTP 403.

## 4. Architecture

### 4.1 Provider-neutral backends

New package `dashboard/backends/`:

- `base.py`: the interface, capability flags and neutral event types.
- `codex.py`: wraps today's `CodexClient` and translates native messages into neutral events.
- `claude.py`: the Claude backend (section 4.2).

The interface covers readiness; starting a run for a project and role; sending guidance;
interrupting; an event stream (status, plan, messages, usage, delegation lineage); approval
requests and a way to answer each. Each backend declares capability flags and the UI shows what a
run supports. Known differences: Claude subagents cannot ask the owner questions; Claude plan
support is unconfirmed rather than absent.

Provider selection: a start-up setting names `codex` or `claude`. A missing or unrecognised value
starts no backend (fail closed). Projects and runs record their provider (SQLite migration) and the
UI labels it. Codex-only routes (recovery, assessment) answer "not available for this provider" in
a Claude deployment. The setting's exact home (settings file, environment variable or flag) is
decided in the plan.

### 4.2 Claude managed runs

- Fixed argv: `claude -p --output-format stream-json --verbose --setting-sources user --model
  <alias>`, input from `/dev/null`. Roles are passed per run with `--agents`, so no registered
  project is modified. The subscription login is used; no API key is read or stored.
- Stream events become neutral events: session start, messages, tool use, subagent lineage, usage
  and a final result. Plan is "unconfirmed". Cost is a list-price estimate.
- Approvals: the dashboard writes a per-run settings file in its private state folder (not in the
  project) and passes it with `--settings`. The file adds one `PermissionRequest` hook, a small
  fixed command that posts the request to the loopback receiver (4.3) and waits. The request goes
  through the existing approval pipeline: complete checked context, secret scan, exact-request
  scope, memory only. Allow means one call; there are no session grants. No answer within the wait,
  a crash, or an unreachable dashboard means deny.
- Managed runs use the default permission mode, not Auto, so every call that needs permission
  reaches the hook (S6: `permissionMode` was `default` with no flag). A hook that is silent, unreachable or
  timed out is denied by Claude Code itself (S6 R3, R4), so the hook timeout is set far above the 20 s used in S6.
- Project instructions (owner decision 2026-10-28, after S6 R5b): `--setting-sources user` does not load the
  project `CLAUDE.md`. Managed runs keep `user` and the dashboard passes the project's instructions itself,
  with `--append-system-prompt` (or its `-file` form) first and `--add-dir` as the alternative; the first task of
  Plan 2 tests which works (codeword visible, `@AGENTS.md` import expanded by the dashboard). `user,project` is
  the fallback only if the project's own settings are reviewed. The CLI records the system prompt once per
  conversation (`--system-prompt-snapshot`, default on), so a resumed run keeps the original text.
- User-level configuration (owner decision 2026-10-28): managed runs inherit the owner's user-level settings,
  hooks, plugins and MCP servers as they are at each launch, including ones added later. Accepted. Runs already
  started keep what they loaded. Not tested: a user-level allow rule that would skip the hook.
- Stop interrupts the process and records "interrupted". Guidance sent during a run is queued and
  delivered as a follow-up turn with `--resume <session id>`. Injecting guidance into a running turn
  is not promised.

### 4.3 Hook receiver and observed sessions (Phase 3)

- One receiver on 127.0.0.1 accepts session start and end, subagent start and stop, and permission
  requests. Managed runs use a per-run token. The owner's terminal sessions use a per-install token
  stored outside the repository. The two kinds are accepted on separate paths, so a managed token
  cannot answer an observed approval. The receiver enforces body-size limits, a Host and Origin
  guard and constant-time token checks.
- The dashboard never edits the owner's Claude settings. It shows the exact hook configuration for
  the owner to add.
- Observed sessions are read-only apart from approvals: no ownership, guidance, replay or recovery.
  Request payloads are held in memory, secret-scanned before display, and only ids and status are
  stored.
- Limits shown in the UI: only calls that reach a permission prompt are sent, so in Auto mode the
  dashboard's list is not a complete record. Requests are matched on `session_id`, `prompt_id` and
  tool input because the hook payload has no tool call id.
- If the dashboard is down, Claude Code's own prompt appears and nothing is auto-allowed (confirmed
  once, in manual mode). S7 results: a reachable but silent dashboard leaves the terminal prompt open and the hook
  connection closes at its configured timeout (60 s tested); a stub allow while the prompt is open resolves the
  prompt; a terminal Yes followed by a late allow ran the command once. The request stays open after the owner
  answers in the terminal, so pending approvals carry a "may already be answered elsewhere" state and an expiry.
  Untested and to be tested before Phase 3 ships: terminal No then a late allow, terminal Yes then a late deny, a
  deny while the prompt is open, and a simultaneous answer.
- `SessionStart` over `http` was not delivered in two sessions; do not rely on it. `SessionEnd`,
  `SubagentStart` and `SubagentStop` arrived; `SubagentStop` fires more often than subagents start, so stops are
  never counted. A subagent's permission request carries `agent_id` and `agent_type`. Launching a subagent raised
  no permission request. There is no tool call id. Details: `docs/superpowers/spikes/S7-observed-hooks.md`.

### 4.4 Features by slice

- Slice 2a: the neutral interface, the Codex translator, the provider setting and migration, the
  Claude backend, approvals, provider labelling.
- Slice 2b (through the neutral events): conversations, the team view, completed-task outputs, task
  deletion, and delivery readiness without the Ponytail gate. Git and file review need no change.
- Phase 3: the receiver and observed sessions.
- Codex-only and unchanged: recovery, assessment and ChatGPT sign-in.

### 4.5 Ponytail

Off in the Claude deployment. The delivery gate's policy source (plugin cache path, version and
digest) becomes a per-provider value. For Claude the gate reads "not applicable" and never counts as
passed. Turning Ponytail on later means installing the Claude plugin at a reviewed, pinned version
(owner action), adding its path and digest, and loading it into Backend and Frontend runs.

## 5. Order of work

1. Baseline: the full suites, plus characterization tests that pin current Codex behaviour in the
   modules to be moved.
2. Spike S6 (managed hook under `--setting-sources user`; `--agents` and `CLAUDE.md` still load;
   `--resume` and interrupt) and spike S7 (interactive hooks). Live Claude runs need the owner's
   approval beforehand and S7 needs the owner at the keyboard.
3. Slice 2a. 4. Slice 2b. 5. Phase 3.

Each slice has its own plan, task reviews and a final review. A security review covers the receiver,
the hook and the approval path before merging. If S6 fails, work stops and the owner decides.

## 6. Evidence and testing

- The full Python and Node suites run after every refactor step. CI takes about 17 minutes on a
  macOS runner (pull request 2).
- The Claude backend is tested against a fake `claude` executable replaying sanitized stream-json
  from the spikes. Fake-binary tests, live Claude runs and browser checks are labelled as separate
  kinds of evidence; mocks alone never establish that the live integration works.
- Journey checks follow `AGENTS.md`: a run starts, asks for permission, the owner approves once,
  work resumes and finishes; decline, stop and stale-request outcomes are distinct; authorized
  actions succeed as well as unsafe ones being blocked.
- `claude --version` is recorded with every live run.

## 7. Security and failure behaviour

- Fail closed everywhere: missing provider setting, missing or wrong token, oversized body, no
  answer to a request, unreachable dashboard. Unknown state stays unknown.
- Tokens, any API-key fallback and the per-install token live outside the repository.
- Claude Code keeps session transcripts locally outside the dashboard's scanning; this is documented,
  as it is for Codex.
- Hook payloads are untrusted input: size-bounded, validated and secret-scanned before display or
  storage. The receiver binds to loopback only.
- Work happens on branches. Nothing is pushed or published without the owner's authorization.

## 8. Open risks and items

1. The refactor of `server.py`, `conversation.py` and `recovery.py` could change Codex behaviour.
   Small steps and characterization tests reduce this and cannot prove its absence.
2. The managed hook (S6) and interactive hooks (S7) are unproven.
3. Subscription use through the dashboard is the owner's judgement on the Anthropic terms and is not
   resolved here.
4. Plan support for Claude runs is unconfirmed.
5. The delivery gate's treatment of Ponytail ("not applicable") is an assumption for the owner to
   confirm (section 1).
6. Automatic approval mode for Claude runs is out of scope; confirm.
7. The location of the provider setting is a plan decision.
8. Phase 3 depends on the owner adding hooks to their own Claude settings.
9. The existing unresolved items from the 2026-10-26 design (section 8) still apply, including the
   evidence listed in the Phase 0 findings under "Not tested".
10. Managed runs inherit later additions to the owner's user-level configuration (accepted 2026-10-28). A
    user-level allow rule or hook could change which calls reach the dashboard; untested.
11. The Claude Code CLI updated between the S7 sessions (2.1.310 to 2.1.312). Every live run records
    `claude --version`; behaviour may differ across versions.
12. The late or conflicting answer cases in section 4.3 are untested.

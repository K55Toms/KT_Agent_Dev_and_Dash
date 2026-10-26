# Claude Code adaptation: design

Project: [K55Toms/KT_Agent_Dev_and_Dash](https://github.com/K55Toms/KT_Agent_Dev_and_Dash)
Date: 2026-10-26
Status: draft for owner review. Not committed anywhere. No implementation has started.

## 1. Intent

The owner built this project on Codex: an agent team (Chief of Staff plus 13 specialist roles
and an on-demand escalation profile) and a local dashboard that starts, observes and
approves Codex runs. The owner wants the same project to also work on Claude Code, keeping
Codex fully working.

### Stated by the owner

- Support both harnesses; Codex is not being replaced.
- Both layers move: the agent team, and the dashboard.
- One repository, built on a branch. The owner will first sync their local uncommitted work
  to GitHub; the work starts from that state, not from the stale GitHub copy this analysis read.
- The 14 roles stay. Superpowers skills add process discipline on the Claude side; they
  replace nothing.
- Role models come from one shared policy file with a column per harness. The owner assigns
  the Claude models, role by role.
- The dashboard starts and owns Claude runs, and also observes the owner's own Claude Code
  sessions, including approving their permission requests.
- Sign-in is the owner's Claude subscription. No keys in the project.
- The first version is done when: the team runs in Claude Code; the dashboard starts a Claude
  run; approvals work.
- Ponytail is not used on the Claude side.
- Dashboard approach: backend adapter (section 4).

### Assumed, confirmed by the owner

- Observing own sessions and approving them are a later phase, not part of the first version.
- Codex must not regress: the existing suite (584 Python tests, 126 Node tests at the last
  recorded count) keeps passing.
- `AGENTS.md`, `SECURITY.md`, gitleaks and the git hooks are unchanged and apply to both harnesses.
- Recovery assessment and handoff, task deletion rules and delivery readiness are Codex-only
  in the first version. Claude runs show a safe read-only "unknown" state for those.
- The per-project Automatic approval mode does not extend to Claude runs yet; they are manual-only.

## 2. Non-goals

- Replacing or retiring Codex.
- Replacing the 14 roles with superpowers skills.
- A Claude equivalent of Ponytail.
- Recovery, deletion and delivery-readiness support for Claude runs (a later effort).
- Automatic approval mode for Claude runs.
- Silently editing the owner's Claude settings, or any project's `.claude/` directory.

## 3. Findings that shaped the design

Sources checked 2026-10-26: Claude Code docs for
[sub-agents](https://code.claude.com/docs/en/sub-agents),
[hooks](https://code.claude.com/docs/en/hooks),
[headless / CLI](https://code.claude.com/docs/en/headless),
[Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) and
[SDK approvals](https://code.claude.com/docs/en/agent-sdk/user-input).

| Topic | Finding |
| --- | --- |
| Role files | Markdown with YAML frontmatter in `.claude/agents/`. Fields include `name`, `description`, `tools`, `disallowedTools`, `model`, `effort`, `permissionMode`, `maxTurns`, `skills`, `hooks`. |
| Models | `model` accepts `sonnet`, `opus`, `haiku`, `fable`, a full model ID, or `inherit`. An environment variable can force one model on every subagent, overriding frontmatter. |
| Read-only roles | A `tools` allowlist can restrict a role. Allowing `Bash` does not make it read-only; that needs a `PreToolUse` hook or deny rules. |
| Delegation | Subagents can nest up to three layers by default; 20 run concurrently by default. `AskUserQuestion` is unavailable inside subagents. |
| Managed runs | The Agent SDK or `claude -p --output-format stream-json` give events, session IDs, resume and usage. Subagent messages carry `parent_tool_use_id`. |
| Managed approvals | The SDK `canUseTool` callback receives tool name and input, may wait indefinitely, and returns allow or deny. Allow applies to that call unless a permission update is returned. |
| Session approvals | A `PermissionRequest` hook fires in interactive sessions, including ones the owner starts. A command or HTTP hook can return allow or deny. A silent hook leaves the normal prompt in place. |
| Cost | `total_cost_usd` is a client-side estimate and can differ from the real bill. |
| Auth | The SDK docs say Anthropic does not allow third-party developers to offer claude.ai login or its rate limits in their products, and point to API-key auth. `--bare` mode ignores subscription login. |
| Project hooks | A non-interactive run executes a project's own hooks and MCP servers without a trust dialog unless `--bare` is used. |
| Branding | Products built on the SDK must not be labelled "Claude Code". |

Not verified: whether `CLAUDE.md` can import `AGENTS.md`; the exact `PermissionRequest`
timeout; whether hook-driven approval behaves the same in every permission mode.

### Current Codex coupling (from the repository)

Codex-specific code is concentrated in `dashboard/codex_client.py` (spawns `codex app-server`,
JSONL JSON-RPC), `native_roles.py` (role snapshots, hard-coded GPT-6 model IDs),
`approval_review.py`, `recovery_capabilities.py`, `diagnostics.py` and `server.py`. The Git
and file review, secret scanning, SQLite store, UI and `.githooks` are harness-independent.

## 4. Architecture

Approach chosen: a backend adapter. The Codex-specific parts of `dashboard/` move behind a
backend interface, and a Claude backend is added beside them.

### 4.1 Shared team layer

- One role source holds each role's id, description, instructions, ownership and tool
  profile (read-only reviewer or editor).
- A shared policy file holds model and effort with one column per harness. The owner
  assigns the Claude values role by role. This is a decision owed during Phase 1 planning,
  not an unfilled field in this design.
- A generator writes `.codex/agents/*.toml` and `.claude/agents/*.md` from the source. The
  generated files are committed, and a test fails if they drift from the source.
- `AGENTS.md` stays the canonical rules file. `CLAUDE.md` is thin: it imports `AGENTS.md`
  (if Spike S4 confirms that works; otherwise it references it) and adds Claude-specific
  notes, including how the Chief of Staff uses superpowers.
- Security and code-quality reviewers get an enforced read-only tool profile on the Claude side.
- For managed runs, roles are passed per run through the `--agents` flag, so registered
  projects are not modified.

### 4.2 Dashboard backend interface

The interface covers: readiness; starting a run for a project and role; sending guidance and
interrupting; an event stream (status, plan, messages, usage, delegation lineage); approval
requests and a way to answer them.

- Each backend declares capability flags. The UI shows per run what is supported. Known
  difference: Claude subagents cannot ask the owner questions.
- The Codex backend is the existing code moved behind the interface with no behaviour change.
  The full suite runs before the refactor as a baseline and again after.
- Projects, runs and tasks record their harness (SQLite migration). The UI shows it, labelling
  the Claude backend "Claude".
- Claude managed runs use the Agent SDK or `claude -p` stream-json; Spike S2/S3 decide which.
  Either adds a dependency to a project that currently has almost none.
- Claude permission requests (tool name plus input) go through the existing approval pipeline:
  complete checked context, secret scan, exact-request scope, held in memory only. Allow means
  one call. No session grants.
- Cost is shown as an estimate with its source, never as a billed amount, consistent with the
  brief's observed / estimated / unknown distinction.

### 4.3 Observed sessions (Phase 3)

A local-only receiver on 127.0.0.1 with a per-install token accepts Claude Code hook events
(session lifecycle, subagent events, permission requests). The dashboard never edits Claude
settings itself: it shows the exact hook configuration for the owner to add. Observed sessions
are read-only apart from approvals, with no ownership, replay or recovery.

## 5. Phases

One spec, then a separate implementation plan per phase, each reviewed by the owner.

### Phase 0: spikes (throwaway; output is findings)

- S1 Auth: does a headless run work on the owner's subscription login, and is the owner
  comfortable with the terms? Fallback: an API key supplied outside the project (environment
  variable name only). Also find a launch mode that keeps the login without running a project's
  untrusted hooks.
- S2 Approvals: a managed run using `canUseTool`; an interactive session using an HTTP
  `PermissionRequest` hook waiting on a stub dashboard. Check allow-once scope, timeout and the
  dashboard-down fallback.
- S3 Events: map stream-json events to dashboard projections (status, usage, lineage).
- S4 Team loading: `CLAUDE.md` import of `AGENTS.md`; subagent definitions load; a read-only
  role cannot edit; each role resolves to the intended model.

### Phase 1: the team

Role source, generator, `CLAUDE.md`, `.claude/agents/`, drift test.
Done when a specialist run shows the intended instructions, tools and model, shown by evidence
and not by the agent's own claim.

### Phase 2: the dashboard

Baseline, refactor behind the interface, Claude managed backend, approvals, harness labelling.
Done when a run starts, requests permission, the owner approves once, work resumes and
completes, and decline, stop and stale-request outcomes are distinct.

### Phase 3: observed sessions

Hook receiver, owner-applied configuration, approvals for the owner's own sessions.

## 6. Evidence and testing

Evidence stays labelled as the project already does: fake-process protocol tests (a fake
`claude` emitting stream-json), real native checks, and browser checks are reported
separately. Real Claude checks consume the owner's subscription usage, so each needs the
owner's explicit approval first. Each phase ends with verification-before-completion: a
claim of "done" requires command output, not assertion.

## 7. Security and failure behaviour

- Fail closed: if the dashboard is down or an approval is unanswered, a managed run denies and
  an observed session falls back to Claude Code's own prompt. Nothing is auto-allowed.
  Unknown state stays unknown.
- The hook receiver token and any API-key fallback live outside the repository.
- Claude Code retains session transcripts locally outside the dashboard's scanning; this is
  documented, as it is for Codex.
- All work happens on a branch, with the Codex baseline taken before the refactor.

## 8. Open risks and items

1. Managed runs may execute a project's own hooks and MCP servers, and `--bare` (which avoids
   that) does not use subscription login. If Spike S1 finds no mode that does both, the
   choice is an API key, or accepting the risk for projects the owner trusts.
2. Whether a subscription-login dashboard is permitted is the owner's call; the SDK docs
   point to API-key auth for third-party products. The owner's tool is personal and local, but
   the docs do not say which side of the line that falls on.
3. The owner's local uncommitted work (for example approval-parity changes) is unseen. This
   design was prepared from the GitHub state and must be re-checked after the owner syncs.
4. The Claude model per role is the owner's decision.
5. Items marked "not verified" in section 3.

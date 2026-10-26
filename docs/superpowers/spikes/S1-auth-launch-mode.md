# S1: Authentication and launch mode (spike findings)

Date: 2026-10-26. Claude Code version: `2.1.296 (Claude Code)` (`claude --version`).
Scratch project (outside the repo): `<scratchpad>/s1`, initially empty. Later it held only
`.claude/settings.json` (one `SessionStart` command hook running `touch <scratchpad>/s1/hook-ran`).
Every `claude` command was run from inside that directory with `--model haiku`, the prompt
`Reply with OK`, `--output-format json`, and stdin redirected from `/dev/null`. The owner approved
these real runs on the subscription login. No credential, token, environment variable or keychain
content was read, printed or recorded; only the credential category is noted below.

## Summary

| # | Question | Result |
|---|----------|--------|
| 1 | Does a headless `claude -p` run work on the owner's login? | PASS |
| 2 | Does a project `SessionStart` hook run in that headless run? | YES (hook ran) |
| 3 | Is there a launch mode that keeps the login but skips the project hook? | YES, with caveats (`--setting-sources user`, `--safe-mode`, `--restricted`); `--bare` loses the login |
| 4 | Owner decision: subscription or API key | Subscription login (owner, 2026-10-26; see "Owner decision") |
| 5 | Recommended Phase 2 launch mode | `--setting-sources user`, provisional and conditional on agents/CLAUDE.md still loading (see Recommendation) |

## Step 1: Login check: PASS

Command (no `--bare`, empty scratch dir, no project settings):

```
claude -p "Reply with OK" --model haiku --output-format json
```

Observed: exit 0, `is_error: false`, `subtype: success`, `result: "OK"`, `num_turns: 1`,
`modelUsage` listing only `claude-haiku-5-5`, `permission_denials: []`.

Credential source: the run's JSON output has no field that names the credential source. To get the
category only, `claude auth status` was run and just the non-identifying fields were read
(`loggedIn: true`, `authMethod: claude.ai`, `apiProvider: firstParty`, `subscriptionType: pro`). So the
category is a claude.ai subscription OAuth login, not an API key. (That command's output also contains
account identifiers; they were deliberately discarded and are not recorded here.) This is an inference
that the `-p` run used that login, since `--bare` (below) fails with "Not logged in" while the plain run
succeeds, and no API key variable was set for the runs by me; I did not inspect the environment.

`total_cost_usd` for this run: about 0.0039 USD. This is a computed estimate reported by the tool, not
a charge; on a subscription no per-token bill is expected.

Side note: the first run printed `Warning: no stdin data received in 3s, proceeding without it` on
stderr. A dashboard launching `claude -p` should redirect stdin explicitly (`< /dev/null` or a pipe it
closes); later runs used `< /dev/null` and printed nothing on stderr.

## Step 2: Hook-execution check: the project hook RAN

`<scratchpad>/s1/.claude/settings.json` contains a `SessionStart` command hook whose only action is
`touch <scratchpad>/s1/hook-ran`. Same command as Step 1 (no `--bare`), run in that directory:
exit 0, result `OK`, and `hook-ran` existed afterwards (it did not exist before; it was deleted
before each following run). This matches the docs: in `-p` mode a project's own settings hooks are
executed, and the `--help` text for `-p` says the workspace trust dialog is skipped in non-interactive
mode. So a dashboard that starts headless runs inside an untrusted project would execute that
project's hooks by default.

## Step 3: Candidate mitigations

Flags found with `claude --help` that control what loads (exact help text, wrapped lines joined):

- `--setting-sources <sources>`: "Comma-separated list of setting sources to load (user, project, local)."
- `--safe-mode`: "Start with all customizations (CLAUDE.md, skills, installed plugins, hooks, MCP servers,
  custom commands and agents, output styles, workflows, custom themes, keybindings, and more) disabled
  ... Admin-managed (policy) settings still apply. Auth, model selection, built-in tools and plugins,
  and permissions work normally. Sets CLAUDE_CODE_SAFE_MODE=1."
- `--restricted`: "Restricted mode: removes the built-in tools that run commands or code (Bash,
  PowerShell, REPL and the other code-running tools) and WebFetch unless --tools names them, and ignores
  user, project and local settings files (managed settings and --settings still apply; add
  --strict-mcp-config to skip MCP servers too). Also confines the file tools to the working directories
  (--add-dir included), refuses bypassPermissions, and lets only a person or the configured permission
  handler approve writes to settings, git and tool-configuration files."
- `--bare`: "Minimal mode: skip hooks (those defined in settings and by installed plugins ...), LSP, plugin
  sync, attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery.
  Sets CLAUDE_CODE_SIMPLE=1. Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings
  (OAuth and keychain are never read) ..."
- `--settings <file-or-json>`: "Path to a settings JSON file or a JSON string to load additional
  settings from". This only adds settings; it is not a way to remove the project's, so it was not tested
  as a mitigation.

Method for each test: delete `hook-ran`, run the Step 1 command plus the flag in the scratch dir (which
still contains the hook), record exit code, result and whether `hook-ran` exists. One run per condition.

| Flag | Command (after `claude -p "Reply with OK" --model haiku --output-format json`) | Exit | Login works | Project hook ran (`hook-ran`) | Est. cost (USD) |
|------|------|------|------|------|------|
| none (Step 2 baseline) | (no flag) | 0 | yes | YES | 0.0032 |
| `--setting-sources user` | `--setting-sources user` | 0 | yes | no | 0.0032 |
| `--setting-sources project` (positive control) | `--setting-sources project` | 0 | yes | YES | 0.0017 |
| `--safe-mode` | `--safe-mode` | 0 | yes | no | 0.0015 |
| `--restricted` | `--restricted` | 0 | yes | no | 0.0054 |
| `--bare` | `--bare` | 1 | NO | no | 0 |

`--bare` result, recorded exactly: `is_error: true`, `result: "Not logged in · Please run /login"`,
exit 1, empty stderr. The hook did not run because the session never started a model call. This
confirms `--bare` does not use the subscription login (consistent with its help text: only
`ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings`).

The positive control matters: it shows the marker mechanism does detect a project hook when project
settings load (`--setting-sources project` created `hook-ran`), so the absence in the other three rows
is meaningful and not a broken marker.

Differences between the three working candidates (from the help text; behaviour beyond the hook marker
was not tested):

- `--setting-sources user` drops project and local settings (hooks, permission rules, env, and so on)
  but keeps the user's own settings, so the owner's own user-level hooks still run (not tested; I did
  not read the user settings). Whether project `CLAUDE.md`, `.claude/agents`, skills and `.mcp.json`
  still load under it was NOT tested.
- `--safe-mode` disables project customizations, including `CLAUDE.md`, agents and skills, which would
  also disable the team roles Phase 2 needs.
- `--restricted` removes Bash and the other code-running tools and WebFetch, which a development agent
  needs.

## Docs statement on third-party claude.ai login

Page: https://code.claude.com/docs/en/agent-sdk/overview (fetched 2026-10-26). In a note, it says that,
unless Anthropic has previously approved it, third-party developers may not offer claude.ai login or
the subscription's rate limits in their own products, including agents built on the Claude Agent SDK,
and it points those developers to API key authentication instead. This note is about products offered
by third parties; whether the owner's own local dashboard falls under it is a policy question I cannot
settle, and I make no claim either way. The same page also describes running the CLI as a subprocess
with `-p` and `--output-format json` as a supported way to drive the agent from another language.

## Owner decision

Decision (recorded 2026-10-26, from the owner in chat): "Subscription login" for dashboard-run Claude
sessions, for the owner's personal, local use. The terms question raised by the SDK overview page's
note above remains the owner's own judgement; this spike did not and cannot resolve it.

Fallback if the owner later reverses this: authenticate with an API key supplied outside the project
through an environment variable (name only recorded here; never a value in the repository, prompts or
logs). Under an API key, `--bare` becomes a candidate launch mode (see the Recommendation section).

## Recommendation for Phase 2 (Step 5)

Recommended managed-run launch mode (PROVISIONAL): `claude -p ... --setting-sources user`.
It is the only candidate observed to keep the subscription login and skip the untrusted project's own
hook. Basis: one run per condition showed login works and `hook-ran` was absent, with the `project`
control showing the marker can appear.

The recommendation is conditional on one unverified point: project agents (`.claude/agents/*.md`, or
roles passed per run with `--agents`) and `CLAUDE.md` with its `@AGENTS.md` import must still load
under `--setting-sources user`; S4 depended on both. If they do not load, there is no usable launch
mode on the subscription login and the answer becomes "none found: API key or trusted projects only".
The other open points are listed in the next section.

If the owner chooses an API key, `--bare` becomes viable for untrusted projects (it skips hooks and
CLAUDE.md auto-discovery, and context is passed explicitly), but then needs `ANTHROPIC_API_KEY` or
`apiKeyHelper`; none of that was exercised.

## Not yet tested (Phase 2 must check)

1. Under `--setting-sources user`: do project agents (`.claude/agents`), `CLAUDE.md` with its
   `@AGENTS.md` import, skills, `.mcp.json` servers and project plugins still load, or start? (MCP
   servers and plugins can launch commands, so they must not start for an untrusted project;
   `--strict-mcp-config` is a listed flag that may help, also untested.)
2. Do roles passed per run with the `--agents` flag still load under `--setting-sources user`? This is
   the Phase 2 plan for managed runs.
3. `--setting-sources user` drops the project's permission deny rules, so the dashboard must supply its
   own permission rules and mode for managed runs.
4. The owner's own user-level hooks, if any, still run under it. They were not examined.
5. Only a `SessionStart` hook was tested, one run per condition; other hook events and repeat runs
   were not.
6. Absence of an API key was inferred (from the `--bare` failure), not checked; the environment was
   not inspected.
7. Redirect stdin explicitly when launching `claude -p` (the first run printed a no-stdin warning
   after 3 seconds).

## Limits of this spike

- One run per condition; model and CLI behaviour could vary.
- Only the hook marker was used to judge "project settings skipped". Project agents, skills,
  `CLAUDE.md`, MCP servers and permission rules under each flag were not checked.
- Only a `SessionStart` hook was tested, not other hook events.
- The credential category came from `claude auth status`, not from the run output; the run output
  does not expose it. Only one login (claude.ai, `pro`) was involved, and the environment was not
  inspected, so a set `ANTHROPIC_API_KEY` is not strictly ruled out by observation (the `--bare`
  failure is consistent with none being set).
- `total_cost_usd` values are estimates.
- Subscription terms: the docs note above was read, not interpreted legally.

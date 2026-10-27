Tracked copy of the independent security review of the Claude Code adaptation (branch
`closeout-fixes`), run by security_reviewer on 2026-10-26 after completion, read-only. The report
below is verbatim except that the absolute repository path is replaced with `<repo>` and one
synthetic home-directory path quoted from a test file is replaced with `<synthetic home path>`.
The controller's addendum, with the disposition of each finding, follows the report.

# Security review: Claude Code adaptation (branch `closeout-fixes`), read-only

This was a read-only review with Read, Grep and Glob only. I changed no files and found no credential values.

I found no Critical or High issues. There are 4 Medium and 6 Low findings, plus 3 informational notes. Most Medium findings are gaps in defence-in-depth that an untrusted pull request (PR) or a prompt-injected editor agent could exploit.

## What I could not check (no shell)

- I did not run `python3 scripts/sync_roles.py --check`, the unit tests, `node --test`, gitleaks or `scripts/security_check.py staged|history`. Every "this check catches X" statement below comes from reading the code, not from running it.
- I could not confirm which files are tracked by git. The Glob and Grep tools may skip gitignored files, so I cannot rule out local untracked files such as `.claude/settings.local.json` or `CLAUDE.local.md`. I also could not see whether any committed entry is a symlink.
- I could not inspect the superpowers plugin or the user-level Claude settings and hooks. Both are outside the repository.
- Claude Code behaviour claims marked HYPOTHESIS come from my reading of its documentation, not from live runs.

---

## Findings

### F1. Medium: `sync_roles.py` writes through symlinks at the expected output paths

- **Location:** `<repo>/scripts/sync_roles.py:41-49`
- **Evidence:** `current = path.read_bytes() if path.is_file() else None` and `path.parent.mkdir(parents=True, exist_ok=True)` / `path.write_bytes(data)`.
  - `is_file()`, `read_bytes()` and `write_bytes()` all follow symlinks.
  - The script never calls `lstat`, never checks that the resolved path stays inside `.claude/agents` or `.codex/agents`, and never checks whether `.claude`, `.claude/agents` or `.codex/agents` are themselves symlinks.
- **How it is exploited (HYPOTHESIS, not executed):**
  1. A PR replaces `.claude/agents/<id>.md` (or the `.claude/agents` directory) with a symlink, for example to `../../scripts/run_dashboard.sh`, `.githooks/pre-push`, or a relative path to a file outside the repository.
  2. The same PR changes the role body in `team_source/roles/<id>.md`.
  3. The documented routine step `python3 scripts/sync_roles.py` then writes the rendered text, which the attacker controls, into the symlink's target.
  - Shell targets would still run the payload lines, because a leading `---` or `# Generated…` line is only a failed command or a comment.
- **What does not stop it:**
  - `security_check.py staged` rejects symlinks only for the local committer (`security_check.py:181-182`), and `history` only at push time.
  - A PR checked out from GitHub creates the symlink on disk before either check runs, and `sync_roles.py` runs no check of its own.
- **Role ids are not a traversal route:** the id must equal the file stem and is concatenated with the suffix. I traced `...md`, which gives stem `..` and output `...toml`, and it stays inside the folder. The only route out of the agent folders is through symlinks.
- **Impact:** an arbitrary file write with attacker-chosen content, as the user running the sync. This can turn into code execution.
- **Remediation:**
  - Before reading or writing, check with `os.lstat` / `Path.is_symlink()` and refuse any symlink or non-regular file at an output path.
  - Refuse any symlinked parent directory (`.claude`, `.claude/agents`, `.codex`, `.codex/agents`), and require `path.resolve().parent == (root/dir).resolve()`.
  - Write each file to a temporary file in the same directory, then `os.replace` it. Open with `O_NOFOLLOW` where possible.
  - Treat a failed check as an error that writes nothing.
- **Retest:** new tests in a temporary skeleton where:
  - (a) `.claude/agents/qa_engineer.md` is a symlink to a file outside the root;
  - (b) `.claude/agents` is a symlink to an outside directory;
  - (c) a directory sits at an expected file name.
  - Each case must make both `sync` and `--check` fail, and the outside target's bytes and mtime must be unchanged.

### F2. Medium: nothing runs the drift check or the tests automatically, so hand-edited role front matter and instruction files are caught only by human review

- **Locations:**
  - `<repo>/.githooks/pre-commit:4` (`exec python3 scripts/security_check.py staged`)
  - `<repo>/.githooks/pre-push:4-5`
  - `<repo>/SECURITY.md:31` ("Branch protection and required CI checks remain unconfigured")
  - No `.github/` directory was found.
- **What a PR could do unnoticed:**
  - Hand-edit a generated `.claude/agents/*.md` file to add `permissionMode: bypassPermissions`, `hooks:`, `mcpServers:` or `skills:`. These are front matter fields listed in design spec §3, `docs/superpowers/specs/2026-10-26-claude-code-adaptation-design.md:63`.
  - Delete `tools: Read, Grep, Glob` from `security_reviewer.md`, or delete `disallowedTools: Agent`.
  - `sync_roles.py --check` and `tests/test_sync_roles.py::test_repository_roles_are_in_sync` would catch all of these, but only if someone runs them.
- **Consistent edits that `--check` cannot catch:**
  - A PR can change `profile: "reviewer"` to `"editor"` in the role source, or edit `render_claude` in `team_source/roles.py`, and regenerate. The result passes `--check`.
  - `tests/test_team_source_migration.py:158` pins the reviewer profiles, but it is not enforced either, and the same PR can edit it.
- **Edits to `CLAUDE.md` / `AGENTS.md`:**
  - `tests/test_claude_docs.py` checks only that certain strings are present. It does not check that unwanted text is absent.
  - Appended prompt-injection text, such as an instruction to ignore SECURITY.md or to push, passes every automated check.
  - Subagents receive this text as injected context (`CLAUDE.md:30-31`).
- **Impact:** a role could gain privileges, or the agents' governing instructions could be subverted, with no automated signal. SECURITY.md:32 correctly asks for human review of agent-instruction changes, but no automation backs that up.
- **Remediation (owner/platform decisions, not made by this reviewer):**
  - Add a required CI job, or a pre-commit step, that runs `python3 scripts/sync_roles.py --check` and the unit tests.
  - Enable branch protection with required review and checks.
  - Add a CODEOWNERS-style required review for `CLAUDE.md`, `AGENTS.md`, `SECURITY.md`, `team_source/**`, `.claude/**`, `.codex/**`, `.githooks/**` and `scripts/**`.
  - Add a test that pins the exact front matter key set of every committed `.claude/agents/*.md`. It should allow only `name, description, model, effort, tools, disallowedTools`, and require `tools` exactly for the two reviewers.
- **Retest:**
  - Commit a test branch that adds `permissionMode: bypassPermissions` to one generated file. The pre-commit hook or required CI must block it.
  - On a second branch, change `security_reviewer`'s profile to `editor` and regenerate. The pinned front matter test must fail.

### F3. Medium: `security_check.py` has a path allowlist for `.codex` but none for `.claude`, and other Claude Code configuration paths are not covered at all

- **Locations:**
  - `<repo>/scripts/security_check.py:124-128`: `if '.codex' in p.parts: return not (path == '.codex/config.toml' or ...)`. There is no `.claude` branch.
  - `<repo>/.gitignore:52-55`: `.claude/*`, `!.claude/agents/`, `.claude/agents/*`, `!.claude/agents/*.md`.
- **What `.gitignore` does and does not cover:**
  - It stops an ordinary `git add` of `.claude/settings.json`, `.claude/settings.local.json` and other `.claude/` state.
  - It does not stop `git add -f`. A local user could force-add a file even though AGENTS.md forbids it, and a prompt-injected agent could too.
  - It does not stop a file that arrives already tracked in a PR or merge. `.gitignore` has no effect on tracked files.
  - In both cases, `staged` and `history` would pass any `.claude/**` path, because only gitleaks scans the content.
- **What happens to a future `.claude/settings.json`:**
  - Its hooks would run. Spike S1 shows a project `SessionStart` hook runs in headless `-p` mode with no trust dialog (`docs/superpowers/spikes/S1-auth-launch-mode.md:47-55`).
  - Its permission allow rules would also apply.
  - No path policy would flag it.
- **Paths outside `.claude/` that no control covers:**
  - Root `.mcp.json` (project MCP servers that can launch commands).
  - `CLAUDE.local.md` (personal memory, likely to be committed by accident).
  - Nested `**/CLAUDE.md` files. HYPOTHESIS from the Claude Code docs: these load when Claude works in that subtree.
  - None of these is gitignored, denied by `security_check.py`, or included in the drift check.
- **Claude credential file names (HYPOTHESIS):** `.credentials.json` and `.claude.json` are not in `DENIED_FILES`. The pattern `credentials.json` does not match `.credentials.json`. Whether gitleaks 8.30.1's built-in rules match Claude OAuth token formats was not verified.
- **Impact:** hooks, MCP servers, local permission state, or instruction files can enter the repository without a path-level block. Executable project configuration then runs when someone uses Claude Code on a checkout.
- **Remediation:**
  - Mirror the `.codex` rule: `if '.claude' in p.parts: allow only .claude/agents/<name>.md with len(parts)==3`.
  - Add `.mcp.json`, `CLAUDE.local.md`, `.claude.json` and `.credentials.json` to the deny lists, unless the owner explicitly decides otherwise.
  - Decide whether nested `CLAUDE.md` files are allowed, and enforce that decision.
  - Add `CLAUDE.local.md` to `.gitignore`.
  - This changes security automation, so it needs the reviewed policy change that SECURITY.md requires.
- **Retest:**
  - Synthetic index tests: entries `.claude/settings.json`, `.claude/settings.local.json`, `.claude/agents/sub/x.md`, `.mcp.json` and `CLAUDE.local.md` must each make `staged` fail with "Forbidden tracked path".
  - `.claude/agents/qa_engineer.md` must still pass.
  - Run the same cases through `history`.

### F4. Medium (HYPOTHESIS, not executed): Python module shadowing can subvert the security check and the sync

- **Locations:**
  - `<repo>/.githooks/pre-commit:4` and `pre-push:4-5`: `python3 scripts/security_check.py …`, with no `-I` or `-P`.
  - `<repo>/scripts/sync_roles.py:12`: `sys.path.insert(0, str(ROOT))`.
- **How it works:**
  - Python puts the script's directory (`scripts/`) at the front of `sys.path`.
  - `security_check.py` imports pure-Python standard library modules that are not frozen and not preloaded: `subprocess`, `shutil`, `tempfile`, `hashlib`, `fnmatch` and `selectors`.
  - A file such as `scripts/subprocess.py` or `scripts/shutil.py` would therefore be imported instead of the real module. It could make the pre-commit and pre-push gate report "Security check passed" without scanning anything.
  - `sync_roles.py` puts the repository root first. A root-level `json.py`, `re.py`, `tomllib.py` or `dataclasses.py` would shadow those modules when `team_source.roles` imports them.
- **Who could do this:**
  - An editor role (with Write and Bash inherited) acting on injected instructions.
  - A malicious PR, where a new oddly named file is easier to miss in review than an edit to `security_check.py`.
- **Context:** SECURITY.md:33-34 already says local hooks are not an enforcement boundary against someone who can change the repository. This finding is about how subtle and reviewable the route is.
- **Remediation:**
  - Run the hooks as `python3 -I scripts/security_check.py …`, or use `-P` (Python 3.11+), and use the same flags in the documented commands.
  - In `sync_roles.py`, avoid putting `ROOT` at position 0; append it, or load `team_source` by explicit path.
  - Add a path rule that rejects tracked `*.py` files in `scripts/` or the repository root whose stem matches a standard library module (`sys.stdlib_module_names`).
- **Retest:** in a temporary clone, add `scripts/shutil.py` with a module that sets a marker file. Running the pre-commit hook must not create the marker, and the new path rule must block the commit.

### F5. Low: role ids are not validated, so a newline in an id can inject front matter keys; the Claude renderer has no parse-back self-check

- **Locations:**
  - `<repo>/team_source/roles.py:116-117`: only `if not values["id"]`.
  - `roles.py:205`: `f"name: {role.id}",`, which is not escaped. Compare `description` at `roles.py:206`, which is JSON-escaped.
- **How the injection works:**
  - The id is decoded with `json.loads`, so `"x\npermissionMode: bypassPermissions"` is accepted.
  - The checks that remain are both satisfiable:
    - stem equality (`roles.py:153`): POSIX and APFS file names may contain a newline and `:`, and git can track them;
    - matching `models.toml` keys (`policy.py:72`): TOML quoted keys allow `\n` escapes.
  - The rendered Claude file would then contain an extra `permissionMode:` line.
- **Which outputs the self-check covers:**
  - The Codex output is safe: `render_codex` JSON-encodes `name`, then parses the TOML back and compares it (`roles.py:187-192`).
  - `render_claude` has no equivalent check, so the self-check closes injection only for TOML.
- **Other source content cannot inject keys:**
  - Source front matter keys are restricted to `id, description, profile` (`roles.py:96`).
  - `model` and `effort` pass both an allowlist (`policy.py:86-95`) and `BARE_VALUE` (`roles.py:198-202`).
  - The body is appended after the closing `---`.
  - HYPOTHESIS, low impact: `json.dumps(..., ensure_ascii=False)` leaves U+0085/U+2028 unescaped. A YAML 1.1 parser may fold them inside the quoted description, which changes the value but cannot add a key.
- **Impact:** a crafted PR could escalate a role's permissions by adding keys. The odd file name would show in a diff, which limits this.
- **Remediation:**
  - In `parse_role`, require ids to match `^[a-z][a-z0-9_]*$`.
  - In `render_claude`, parse the produced front matter back and assert that the key list exactly equals the expected list.
- **Retest:** unit tests where an id containing `\n`, `:`, `#` or a leading space raises `RoleSourceError`, and the parse-back assertion fails on a crafted `Role` object.

### F6. Low: the Ponytail exclusion in `CLAUDE.md` also switches off a sentence that says security is mandatory, and it ends with an open-ended override clause

- **Locations:**
  - `<repo>/CLAUDE.md:11-15`.
  - `<repo>/AGENTS.md:45-46`.
- **Evidence:**
  - The excluded span runs from "Backend and Frontend default to Ponytail Full" to "no savings are assumed" (AGENTS.md:37-47).
  - That span contains AGENTS.md:45-46: "Security, accessibility, required checks, documentation, independent reviews and human approval boundaries remain mandatory; fewer lines alone never establish success."
  - CLAUDE.md:15 then adds "still applies, except where this file says otherwise."
- **Assessment:**
  - Nothing is lost in practice. CLAUDE.md:5 ("The rules above are the same on both harnesses") and AGENTS.md's "Security applies to every role" section (lines 16-33, before the Ponytail heading) keep the security rules in force.
  - None of the generated Claude role bodies drops a security sentence. I compared the `codex-only` and `claude-only` blocks in `chief_of_staff`, `frontend_developer` and `ui_designer`.
  - The risks are a literal reading that a gate stated only in that paragraph is off on Claude, and that the "except where this file says otherwise" clause gives any future CLAUDE.md edit an override over AGENTS.md (see F2).
- **Remediation (needs owner approval; AGENTS.md is security-sensitive):**
  - Carve that sentence out of the exclusion in CLAUDE.md, or move it outside the Ponytail paragraph in AGENTS.md.
  - Make the override clause explicit: "CLAUDE.md never relaxes AGENTS.md security rules or SECURITY.md."
- **Retest:** a docs test that asserts CLAUDE.md contains the non-relaxation sentence, and that the AGENTS.md security-mandatory sentence falls outside the excluded span or is explicitly kept.

### F7. Low: `docs/claude-code-setup.md` does not explain what an untrusted checkout runs or loads (S1)

- **Location:** `<repo>/docs/claude-code-setup.md:23-24, 26-34, 262`.
- **Evidence:**
  - Quick start says "Launch Claude Code from the repository root".
  - S1 appears only as a link labelled "(sign-in and launch mode)" at line 262.
  - The S1 finding itself is in `docs/superpowers/spikes/S1-auth-launch-mode.md:47-55`: "a dashboard that starts headless runs inside an untrusted project would execute that project's hooks by default".
- **Assessment:**
  - The S2 Auto-mode statement at lines 199-201 is accurate and fairly presented.
  - Nothing on the page tells someone checking out a public-repo PR that `CLAUDE.md`, `AGENTS.md` and `.claude/agents/*.md` load as instructions. It also does not say that any project `.claude/settings.json` hooks or `.mcp.json` servers would run, headless with no trust dialog per S1, or that `--setting-sources user` / `--safe-mode` were the observed mitigations.
  - "A clone does not install anything on your machine" (line 23) is true but could be read as "a clone is inert".
  - The repository ships no `.claude/settings.json` today, as far as Glob shows (see the limits above).
  - Design spec line 72 states that MCP servers run headless without a trust dialog. That part is docs-sourced; S1 tested only a `SessionStart` hook, and the line is not labelled as docs-only.
- **Remediation:** add a short "Untrusted checkouts" note:
  - review `CLAUDE.md`, `AGENTS.md`, `team_source/`, `.claude/` and `.mcp.json` diffs before launching;
  - headless runs execute project hooks (S1, one run);
  - the observed mitigations, with their limits;
  - label the MCP claim in design spec line 72 as docs-sourced.
- **Retest:** a docs test that asserts the note exists and links S1.

### F8. Low (HYPOTHESIS): the superpowers plugin is a required but unpinned third-party dependency, and its precedence below AGENTS.md is not stated

- **Locations:**
  - `<repo>/CLAUDE.md:47-50`.
  - `docs/claude-code-setup.md:54-60` ("does not install or pin it"; version 6.4.2 recorded).
- **Assessment:**
  - The plugin is installed per machine from an external homepage.
  - Plugins can ship skills, hooks and commands. I did not inspect this plugin. Some skills may suggest merging, pushing or opening PRs.
  - CLAUDE.md says the AGENTS.md rules "stay as they are", but it does not say that skill guidance cannot authorize actions or override AGENTS.md or SECURITY.md.
  - The Codex `ui_designer` block has "skill guidance does not expand assigned implementation ownership" (`team_source/roles/ui_designer.md:26`); the Claude block has no equivalent.
- **Remediation:**
  - State in CLAUDE.md that skill instructions never override AGENTS.md or SECURITY.md, or authorize push, publish or merge.
  - Record a reviewed plugin version and digest, and require security review of plugin updates, including any plugin hooks.
- **Retest:** a docs test for the precedence sentence, and an entry in the setup doc recording the reviewed plugin version and hooks.

### F9. Low: editor roles inherit every session tool, and `disallowedTools: Agent` is a narrow control

- **Location:** `<repo>/team_source/roles.py:210-213`. Only `reviewer` gets `tools:`.
- **Generated files verified by Grep of front matter:**
  - Only `security_reviewer.md:6` and `code_quality_reviewer.md:6` have `tools: Read, Grep, Glob`.
  - All 13 non-coordinator roles have `disallowedTools: Agent`.
  - `chief_of_staff.md:1-6` has neither, as intended.
- **What editor roles inherit:**
  - Twelve editor roles inherit the full tool set, including non-implementer roles: `product_manager`, `technical_writer`, `user_documentation_writer`, `agent_evaluation_engineer`, `technical_architect` and `expert_escalation`.
  - R8 observed `Bash`, `Edit`, `Write`, `Skill`, `Artifact`, `ListAgents` and `SendMessage`, plus any MCP tools (`docs/superpowers/evidence/2026-10-26-phase-1-live.md:149-151`).
- **What `disallowedTools: Agent` does not do:**
  - It does not stop Bash running `claude` once approved, `SendMessage`, or MCP tools. CLAUDE.md:26-29 and setup doc lines 237-243 document this honestly.
  - The nested `general-purpose` agent was itself offered `Agent` (evidence:203), so the coordinator can nest further.
  - Reviewers are also offered `advisor`, which is outside their allowlist (evidence:118-120, 257-263). Its capabilities and whether it can be removed are unknown and labelled docs-sourced. This is accurate.
- **Impact:** a larger blast radius if a non-implementer role is prompt-injected.
- **Remediation (owner decision):**
  - Give the non-implementer roles explicit allowlists, for example writers `Read, Grep, Glob, Edit, Write`, with no Bash.
  - Consider adding `disallowedTools` for `SendMessage` on workers.
  - Track the open `advisor` question (CC-EVAL-02, `docs/model-evaluation.md:1574`).
- **Retest:** render tests that pin each role's tool profile, plus one live run per changed profile showing the offered tools.

### F10. Low: drift-check coverage gaps, partial writes, and a slight overstatement in the docs

- **Location:** `<repo>/scripts/sync_roles.py:42-58`.
- **Suffix matching is case-sensitive:**
  - `entry.name.endswith(suffix)` ignores `Evil.MD`, `x.markdown` and similar names.
  - HYPOTHESIS: on macOS with `core.ignorecase=true`, `!.claude/agents/*.md` may match `.MD`, so such a file could be committed. Whether Claude Code loads it is UNTESTED.
- **A directory at an expected file name:**
  - With `check=True`, it is reported as "missing" (acceptable).
  - In write mode, `write_bytes` raises `IsADirectoryError` after earlier files have already been written.
- **Write errors and atomicity:**
  - Any `OSError` part-way through leaves a partial set of files, and each write truncates the file before writing.
  - Render-before-write atomicity holds: `render_all` runs first, and `tests/test_sync_roles.py:172-181` covers it.
  - `docs/claude-code-setup.md:163-164` ("the sync writes nothing, because every file is rendered before any is written") is accurate for the listed error classes, but should say that write-time errors are not transactional.
- **`--root`:** it is unguarded (`sync_roles.py:65`) but needs CLI control to use, so it is informational. Code is always imported from the real `ROOT`, while data is read and written under `--root`.
- **Remediation:**
  - Flag any entry whose lower-cased suffix is `.md`, `.toml` or `.markdown`, or simply any non-allowlisted name other than `.DS_Store`.
  - Make the writes transactional, as in F1.
  - Correct the docs sentence.
- **Retest:**
  - `.claude/agents/Extra.MD` is reported as unexpected.
  - A directory at `qa_engineer.md` aborts before any write, with a snapshot unchanged.

### Informational

- **I1:** The live evidence records a broader search for environment variable names (`*EFFORT*`, names only; `docs/superpowers/evidence/2026-10-26-phase-1-live.md:69-74`). S1 ran `claude auth status`, and the account identifiers it returned were discarded (`S1-auth-launch-mode.md:33-36`). No values were recorded. AGENTS.md says "Do not … print environment variables", so future runs should get explicit approval before listing environment variable names.
- **I2:** CLAUDE.md:23-35 and setup doc lines 212-260 describe the reviewer allowlist, the `advisor` offer, the limits of `disallowedTools`, and the fact that the Ponytail text is visible to subagents. They label these accurately as observed, one run per condition, or docs-sourced. I found no overclaim.
- **I3:** S2 Auto mode: setup doc lines 199-201 and design spec lines 69 and 141-143 honestly say that a `PermissionRequest` hook is not reached for calls that Auto mode approves itself, and that the dashboard must not treat its list as complete.

---

## Secrets and identifiers scan (Grep)

These scans are pattern-based and limited. They do not decode encoded content, may skip gitignored files, and do not prove that no secrets exist. Gitleaks was not run.

**Scope:** `docs/**`, `.claude/**`, `.codex/**`, `tests/**`, `team_source/**`, `scripts/**`, `CLAUDE.md`, `AGENTS.md`, `SECURITY.md`, `README.md`.

- **Provider key and token shapes** (AWS `AKIA…`, `sk-…`, `sk-ant-`, GitHub `gh?_` and `github_pat_`, Slack `xox?-`, `BEGIN … PRIVATE KEY`, Google `AIza…`, `glpat-`, JWT-like strings): 0 matches.
- **`password|secret|api_key|access_token|auth_token|client_secret` followed by a value:** 0 matches.
- **`Bearer <12+ chars>`:** 0 matches. The S2 doc contains only `Bearer $S2_TOKEN`, a variable reference.
- **Emails:** only synthetic ones (`test@example.invalid` in `tests/test_git_service.py:67,351,352` and `tests/test_security.py:23,206,207`) and SSH remote forms (`tests/test_git_service.py:181,187`). There are no emails in `docs/superpowers/`, the generated role files, CLAUDE.md or the setup doc. The local username and the user's relay email do not appear anywhere.
- **Absolute paths:**
  - Only the synthetic `<synthetic home path>` in `tests/test_recovery_handoff.py:329`.
  - Generic `/private/tmp/...` paths in tests and scripts, plus `docs/recovery-architecture.md:102` and `docs/model-evaluation.md:1194`.
  - None in `docs/superpowers/`, `.claude/agents`, `.codex/agents`, `CLAUDE.md` or `docs/claude-code-setup.md`. The last two are also guarded by `tests/test_claude_docs.py:198-202`.
- **Long hex strings:** only git commit SHAs in `docs/superpowers/plans/phase-1-baseline.md:7,12`. They are not secrets.
- No credential was detected, so incident handling was not triggered.

---

## Summary by question

1. **sync_roles write paths:** the script writes only to `root/.codex/agents/<id>.toml` and `root/.claude/agents/<id>.md`, plus `mkdir` of their parents. It renders everything before writing anything. It has no symlink or containment checks (F1), and writes are not transactional (F10). Role ids and file names cannot leave the folders by themselves; only symlinks can.
2. **Front matter and TOML injection:** source keys are allowlisted, model and effort are allowlisted, and the body comes after the closing `---`. The TOML parse-back closes injection for Codex. The Claude `name:` line has no escaping and no parse-back (F5).
3. **Generated tool allowlists:** verified as intended. The limits of `disallowedTools: Agent` and the `advisor` offer are documented accurately (F9, I2).
4. **Untrusted PRs:** no automated control catches front matter, CLAUDE.md, AGENTS.md or role-source tampering. The security check and gitleaks cover only credentials, symlinks and path denylists, and the drift check and tests are not enforced (F2, F4).
5. **`.claude` path policy:** there is no `.claude` allowlist in `security_check.py`. A force-added or PR-delivered `.claude/settings.json` (with hooks), `.mcp.json`, `CLAUDE.local.md` or nested `CLAUDE.md` would not be blocked by path (F3).
6. **CLAUDE.md and setup-doc statements:** mostly accurate. The Ponytail exclusion technically swallows one security-mandatory sentence, and the override clause is open-ended (F6). The superpowers precedence is unstated (F8).
7. **Secrets and identifiers:** no credential-like matches; only synthetic emails and paths.
8. **S1 and S2:** S2's Auto-mode limit is described honestly. S1's headless project-hook risk is not explained in the setup doc (F7).

security review: pass with findings

---

## Addendum (controller, dated 2026-10-27)

Written by the Chief of Staff (controller) after a hardening wave on branch `closeout-fixes`. It
records what was reproduced, what changed and what stays open. It is not a security re-review: the
fixes have not been re-reviewed by security_reviewer, and nothing here says the branch is safe or
the work complete.

**The review.** security_reviewer ran on 2026-10-26 after completion, read-only (Read, Grep, Glob;
no shell). Verdict "pass with findings": 0 Critical, 0 High, 4 Medium, 6 Low, plus 3
informational notes. The run's estimated cost was 1.79 USD on a list-price basis; that is the
tool's computed estimate, not a charge.

**The reviewer's limits, as it stated them.** It ran no command: no sync check, tests, gitleaks or
`security_check.py`. It could not see which files are tracked, whether any entry is a symlink, the
superpowers plugin or the user-level Claude settings. F4 and F8 were marked HYPOTHESIS, and so were
the exploit paths in F1 and parts of F3, F5 and F10.

**How the findings were checked.** Before any fix, each code finding was reproduced in a scratch
`git archive HEAD` extraction (at HEAD 56bae37) and in disposable git repositories built from it.
The scratch scripts and their output stay in the local session scratchpad and are not tracked.
Documentation findings were checked by reading the cited text.

| Finding | Reproduced? | Disposition |
| --- | --- | --- |
| F1 (Medium) sync writes through symlinks | Yes. With `.claude/agents/qa_engineer.md` a symlink to an outside file, `--check` said only "stale" and a plain sync overwrote the outside file with the rendered role. With `.claude/agents` a symlink to an outside folder, the sync wrote 14 files there. | FIXED (commit "fix: harden sync against symlinks, unsafe paths and partial writes"). Before reading or writing a generated file, `scripts/sync_roles.py` checks that `.codex`, `.codex/agents`, `.claude` and `.claude/agents` are real folders when present, and that each of the 28 output paths is a regular file, not a symlink, whose resolved parent is its agents folder. Any violation is reported as `<path>: unsafe, ...` in both modes, the command exits 1 and nothing is written. Files are written to a hidden `.tmp` file in the same folder and renamed into place with `os.replace`. Pinned by `UnsafeOutputPathTests` in `tests/test_sync_roles.py` (symlinked file, symlinked agents and top-level folders, a folder at an output name, an interrupted write, file permissions, the CLI). |
| F2 (Medium) no automation runs the drift check or tests | Yes, by inspection: the hooks run only `security_check.py`, and there is no `.github/`. In disposable repositories a `.claude/agents/*.md` file with arbitrary content passed `security_check.py staged`. | PARTLY FIXED (commit "docs: pin generated file keys, ..."). `CommittedRoleFileKeysTests` in `tests/test_sync_roles.py` pins the real committed files. Claude front matter keys must be a subset of name, description, model, effort, tools and disallowedTools, with the name equal to the file stem. `tools: Read, Grep, Glob` is required exactly for the two reviewers, and `disallowedTools: Agent` on every role except chief_of_staff. Codex top-level keys must be exactly the five expected ones. Both of the reviewer's retest scenarios fail this test in a scratch copy: a hand-added `permissionMode`, and `security_reviewer` switched to `editor` and regenerated (which passes `--check`). OPEN, for the owner and platform to decide: CI, branch protection, CODEOWNERS-style review, and any rule that stops a PR from changing a profile and the renderer consistently. Nothing runs the new test automatically, and a PR could edit it too. |
| F3 (Medium) no `.claude` path policy | Yes. `.claude/settings.json`, `.claude/settings.local.json`, `.claude/agents/sub/x.md`, `.claude/commands/a.md`, `.mcp.json`, `CLAUDE.local.md`, `.claude.json` and `.credentials.json` each passed `security_check.py staged` when force-added. | FIXED (commit "fix: block unreviewed .claude paths and Claude local/credential files in security_check"); the owner reviews this diff. The new `forbidden()` rule mirrors the `.codex` rule: a path with a `.claude` part is allowed only as `.claude/agents/<name>.md`. `DENIED_FILES` gains `.mcp.json`, `claude.local.md`, `.claude.json` and `.credentials.json`. Names are matched lower-cased, so `claude.local.md` covers `CLAUDE.local.md`. `.gitignore` ignores `CLAUDE.local.md`. The change only adds rules; no existing rule changed. Pinned in `tests/test_security.py`: each path fails `staged` ("Forbidden tracked path") and `history` ("Forbidden historical path"), the role file still passes, a truth table covers case variants, and the `.codex` behaviour is unchanged. A future `.claude/settings.json` or `.mcp.json` needs a reviewed policy change first. Side effect, OWNER DECISION PENDING: the dashboard uses `forbidden()`, so it also (a) refuses (403) a registered project root whose path contains a `.claude` folder, such as a Claude Code worktree under `.claude/worktrees/`, as it already does for `.codex`; (b) hides `.claude/settings.json`, `.claude/commands/*`, `.mcp.json` and `CLAUDE.local.md` from the file and change listings of any registered project, counted as hidden changes; and (c) refuses dashboard Git publish (403) for any registered project whose history contains `.claude/**` other than `agents/*.md`, `.mcp.json`, `CLAUDE.local.md`, `.claude.json` or `.credentials.json`. This fails closed and matches `.codex`, but it can block publishing for other Claude Code projects that legitimately commit `.claude/settings.json` or `.mcp.json`. No dashboard file was changed; the behaviour changes through the shared import. |
| F4 (Medium, hypothesis) module shadowing | Yes, and worse than a crash. A `scripts/shutil.py` stand-in was imported by the pre-commit hook. One that prints the pass line made the hook exit 0 with a forbidden `.env` staged, and `python3 -I` blocked it. A root-level `json.py` was imported by `sync_roles.py`. | PARTLY FIXED: the hooks and the sync's repo-root path are fixed; `scripts/`-folder shadowing remains for the sync and the manual commands (commit "fix: run security hooks in isolated mode; ..."). Both hooks run `python3 -I scripts/security_check.py`, which imports only standard-library modules. `sync_roles.py` appends the repository root to `sys.path` instead of inserting it first. Pinned in `tests/test_security.py`: stdlib-named stand-ins in `scripts/` are not imported, the check still passes or blocks as the content dictates, and `PYTHONPATH` is ignored. Also in `tests/test_sync_roles.py`: a root-level `json.py` is not imported. OPEN: an optional path rule against tracked stdlib-named `.py` files. The documented manual commands (`python3 scripts/security_check.py ...` in AGENTS.md, and `python3 scripts/sync_roles.py`) still run without `-I`, so the `scripts/` folder stays first on `sys.path` for them. |
| F5 (Low) newline in a role id injects a front-matter key | Yes, at parse and render level: `parse_role` accepted the id `"x\npermissionMode: bypassPermissions"` and `render_claude` emitted a separate `permissionMode` line. The full route through a file name with a newline and a matching `models.toml` key was not built. | FIXED (commit "fix: validate role ids and parse back Claude front matter"). `parse_role` requires `^[a-z][a-z0-9_]*$` (fullmatch), and all 14 ids pass. `render_claude` parses its front matter back and requires the exact expected key list. Pinned in `tests/test_team_source_roles.py` and `tests/test_team_source_render.py`. All 28 generated files are byte-identical. |
| F6 (Low) Ponytail exclusion swallows the security-mandatory sentence; open-ended override | Yes, by reading: the excluded span contains that sentence, and CLAUDE.md said "except where this file says otherwise". | FIXED (docs commit). `CLAUDE.md` states that it never relaxes the security rules in AGENTS.md or SECURITY.md, and it keeps the "Security, accessibility, required checks, ... remain mandatory" sentence. The open clause now reads "read with the substitutions listed in this section". AGENTS.md is unchanged. Pinned in `tests/test_claude_docs.py`. |
| F7 (Low) no untrusted-checkout guidance | Yes, by reading. | FIXED (docs commit). `docs/claude-code-setup.md` has an "Untrusted checkouts" section. It covers the instruction files, project hooks (S1, one run), MCP servers (docs-sourced, not tested), the S1 mitigations and their limits, and reviewing diffs before launching. The design spec's MCP claim is labelled docs-sourced. Pinned in `tests/test_claude_docs.py`. |
| F8 (Low, hypothesis) superpowers unpinned, precedence unstated | The documentation gap was confirmed by reading. The plugin's contents were not inspected in this wave either. | PARTLY FIXED (docs commit). `CLAUDE.md` says skill instructions never override AGENTS.md or SECURITY.md and never authorize pushing, publishing or merging. The setup doc records the plugin as an unpinned third-party dependency whose hooks and skills this project has not security-reviewed, and asks for each update to be reviewed. Pinned in `tests/test_claude_docs.py`. OPEN: recording a reviewed plugin version and digest, and reviewing the plugin's own hooks and skills. |
| F9 (Low) editor roles inherit every session tool | Not re-tested; the generated files match the reviewer's description (2 `tools` lines, 13 `disallowedTools: Agent`). | OPEN, an owner design decision that needs live checks: tool profiles for the non-implementer roles, `SendMessage` for workers, and the `advisor` question (CC-EVAL-02). |
| F10 (Low) case-sensitive suffix rule, partial writes, docs overstatement | Yes. `.claude/agents/Extra.MD` was ignored by `--check`. A folder at `qa_engineer.md` made a plain sync raise `IsADirectoryError` after 17 files had already been written. | FIXED (sync commit and docs commit). The unexpected-entry rule ignores letter case on the extension; `.DS_Store` and other plain files are still ignored. An unsafe path stops the sync before any write. Each file is replaced atomically. The setup doc says a write error part-way, such as a full disk, can leave a partial set. With F3, `security_check.py` also refuses to track `.claude/agents/Extra.MD`. The macOS `core.ignorecase` hypothesis was not tested. `--root` is unchanged (informational). |
| I1 environment variable names | Not applicable. | Process note: future live runs must not list environment variable names without the owner's explicit approval. |
| I2, I3 | Not applicable. | No action: the reviewer found these statements accurate. |
| Nested `CLAUDE.md` files (from F3) | Not tested. | OPEN: an owner policy decision. Nothing blocks a nested `CLAUDE.md`. |

**Checks run by the controller after the wave.** These are synthetic and automated, not independent
QA. `python3 scripts/sync_roles.py --check` reported "role files are in sync". `git diff --stat
main..HEAD -- .codex .claude` shows only `.claude/agents/chief_of_staff.md`, which was already
different before this wave. Python ran 723 tests (690 before the wave plus 33 new). In the normal
environment there were the same 2 pre-existing failures in `tests/test_git_service.py` and 36
skipped; with an empty `XDG_CONFIG_HOME`, 0 failed and 36 skipped. Node passed 126/126.
`security_check.py staged` and `history` passed, run both directly and as `python3 -I`, and the
pre-commit hook passed on every commit.

**Still open, beyond the table.** No security_reviewer re-review of these fixes, and no qa_engineer
retest. Nothing has been pushed; CC-EVAL-08 (git identity and commit trailer) is still open before
any push.

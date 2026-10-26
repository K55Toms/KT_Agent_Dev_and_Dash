# S5: Model alias pre-check for `opus` and `fable` (spike findings)

Date: 2026-10-26. Claude Code version: `2.1.310 (Claude Code)` (`claude --version`). Note: S1 and S4 were
run on `2.1.296`; the CLI was updated in between, so this spike ran on a newer build than those.
Scratch project (outside the repo): `<scratchpad>/s5`, containing only `.claude/agents/opus_probe.md`
(`model: opus`, `effort: high`, `disallowedTools: Agent`) and `.claude/agents/fable_probe.md`
(`model: fable`, `effort: low`, `disallowedTools: Agent`). Each body is one sentence telling the agent to
reply with the single word OK and use no tools. All `claude` commands were run from inside that
directory, with `--model haiku` for the main session, `--output-format json`, and stdin redirected from
`/dev/null` (S1 note). No extra flags were used. The owner approved one real run per alias on the
subscription login. No credential, token, environment variable or account identifier was read or
recorded. Costs below are the tool's computed estimates, not charges.

Method follows S4: the model that ran the subagent is read from `result.modelUsage` and from the
persisted subagent transcript at `~/.claude/projects/<project-slug>/<session-id>/subagents/agent-<id>.jsonl`
(`message.model`, plus the recorded effort fields). The haiku main session is a different model from both
probes, so its usage is distinguishable.

## Summary

| # | Question | `opus` (effort `high`) | `fable` (effort `low`) |
|---|----------|------------------------|------------------------|
| 1 | Alias resolves to a model ID | PASS: `claude-opus-5-5` | PASS (from the outgoing request only): `claude-fable-5-1` |
| 2 | Pairing accepted without error | PASS: run completed, subagent replied OK | FAIL: run ended with an API 429 (usage credits required); not an alias or effort error |
| 3 | Effort value proven accepted | Applied by Claude Code and API accepted the request; see below | INCONCLUSIVE: applied by Claude Code, request rejected before any response |
| 4 | Planned role usable on this account today | YES | NO, until usage credits are enabled for Fable |

## Runs (2 total, no reruns)

### Run 1: `opus_probe`

Command:

```
cd <scratchpad>/s5
claude -p "Use the opus_probe agent to reply OK, then report its reply." --model haiku --output-format json < /dev/null
```

- Exit code 0; `is_error: false`, `subtype: success`; stderr empty; `permission_denials: []`.
- No error about the alias or the effort value.
- `modelUsage`: `claude-haiku-5-5` (main session) and `claude-opus-5-5` (subagent).
- Subagent transcript: one assistant message with `message.model` = `claude-opus-5-5`, text `OK`.
- `subagent_stats.by_type`: `opus_probe` 1 spawned, 1 completed, 0 failed.
- Estimated cost: about 0.146 USD total, of which about 0.141 USD attributed to `claude-opus-5-5`
  (`modelUsage` for Opus shows 2 input, 4 output and about 28,000 cache-creation tokens, which is where
  the cost comes from). Computed estimate, not a charge.

### Run 2: `fable_probe`

Command:

```
cd <scratchpad>/s5
claude -p "Use the fable_probe agent to reply OK, then report its reply." --model haiku --output-format json < /dev/null
```

- Exit code 0 (the CLI exit code does not signal the failure); `is_error: false`, `subtype: success`,
  `permission_denials: []`, stderr empty. The main session reported that the subagent failed.
- Exact error, as recorded in the subagent transcript's synthetic assistant message:
  `Fable 5.1 requires usage credits. Switch to another model, or manage usage credits at <settings-url>,
  to continue.` The underlying API response was HTTP 429, error type `rate_limit_error`, message
  "Usage credits are required for this model.", `error_code: credits_required`,
  `disabled_reason: org_level_disabled`. (The transcript marks it with `apiErrorStatus: 429`,
  `apiErrorCode: credits_required`.)
- This is an entitlement/billing refusal, not an error about the alias or the effort value. Nothing in
  the response complains about `fable` or `low`.
- `modelUsage`: only `claude-haiku-5-5`. There is no Fable entry because no Fable tokens were served.
- Subagent transcript: `message.model` is `<synthetic>` (Claude Code's placeholder for the error
  message), so the transcript does not show a served model here. There is no `OK` reply.
- The alias resolution is visible only in the request the subagent attempted: the transcript's recorded
  request parameters contain `"model":"claude-fable-5-1"` and `"output_config":{"effort":"low"}`, the
  error details name `claude-fable-5-1` / display name "Fable", and the subagent's injected
  system reminder states "Fable 5.1" with model ID `claude-fable-5-1`. So `fable` resolved to
  `claude-fable-5-1`, but no response from that model was observed.
- Estimated cost: about 0.0048 USD, all haiku main session. Computed estimate, not a charge.
- The run was not repeated. The failure is a deterministic account/organization setting, not a transient
  error, so a rerun would not have added information. Total `claude` runs: 2.

## Effort: what is and is not proven

Per S4, a bogus `effort` value is silently ignored and falls back to the session default, so the absence
of an error cannot prove a value was accepted. This spike checked whether the transcript itself records
the effort. It does:

- The subagent transcript carries `effort` and `perTurnEffort` fields on its records.
- `opus_probe`: the transcript recorded `"effort":"high"` and `"perTurnEffort":"high"`, and the outgoing
  request carried `"output_config":{"effort":"high"}` to `claude-opus-5-5`. The request succeeded (the
  model replied). So for `opus` + `high`: Claude Code parsed and applied the value (it did not fall
  back to the `medium` default, as seen in S4), sent it to the API, and the API did not reject it.
  This is stronger than absence of an error, but it does not show that `high` changes the model's
  behaviour (see "Not tested").
- `fable_probe`: the transcript recorded `"effort":"low"` and `"perTurnEffort":"low"`, and the outgoing
  request carried `"output_config":{"effort":"low"}` to `claude-fable-5-1`. Claude Code applied the
  value, but the API returned the credits error before any Fable response. Whether the Fable API
  accepts `low` for that model is therefore INCONCLUSIVE; the 429 is a rejection at an earlier gate
  (entitlement), so it says nothing for or against the effort value.
- The method still cannot prove acceptance for a model that is never reached, and it cannot validate
  value spelling by itself in general: the recorded `effort` shows what Claude Code applied, so a typo
  would show up as the default (as in S4) only if someone looks at the transcript.

## Open items for the owner

- `fable` (planned for `expert_escalation`) cannot be used on this account today: the organization has
  Fable usage credits disabled (`org_level_disabled`). The planned role needs either credits enabled or a
  different model. This needs an owner decision; this spike did not change any account setting.
- Once credits are enabled, one more `fable_probe` run (same command) would settle questions 1 (served
  model ID in `modelUsage`/transcript) and 3 (effort `low` accepted). That run needs fresh approval.

## Not tested

- Any other effort value per model: `opus` at `medium` (planned for some roles), `xhigh`, `max`, `low`;
  `fable` at anything other than `low`; and which levels each model supports ("available levels depend on
  the model" per the sub-agents docs, as quoted in S4).
- Whether effort changes reasoning depth or output quality (only the applied value was observed).
- A Fable response of any kind, including its served model ID and cost.
- The same aliases as a main-session `--model` (here they were used only as subagent models under a
  haiku main session), and in interactive mode.
- Alias behaviour across Claude Code versions or on an API-key login (the account is a subscription
  login, per S1); the `opus` alias pointing to `claude-opus-5-5` is true for this build and account on
  2026-10-26 and may change as aliases are updated.
- The `CLAUDE_CODE_EFFORT_LEVEL` override (unset here, not inspected beyond S4's note).
- Roles with tool use, longer prompts, or the real team definitions; only one-word replies were used.

## Limits of this spike

- One run per alias, as approved. Model behaviour (for example the main session's wording) may vary.
- Costs are tool-computed estimates from one run each; a cold start pays cache-creation tokens, so a repeat run could cost less.
- The transcript effort fields and request parameters are Claude Code internals read from persisted
  files; their layout is not a documented contract and may change between versions.

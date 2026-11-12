# Live proof plan (Claude deployment)

Date: 2026-11-10. Branch: `live-proof` (from `main` at `1c1860f`, CI green on that commit).
Status: draft for the owner. **No run in this plan starts without the owner's go in chat.**

## Goal

Show, against the real `claude` CLI, the journeys that today rest on fake-binary tests or on documentation only.
This plan builds nothing. Its output is one evidence file and updated records.

## What is unproven today (sources)

| Area | Unproven | Source |
| --- | --- | --- |
| Terminal sessions (Phase 3) | Everything against a real interactive session: the `{}` reply, dashboard down, `settings.local.json`, real `PostToolUse`/`Stop` payloads, deny, late and simultaneous answers, two hooks | `docs/superpowers/spikes/S11-observed-replies.md`, `docs/claude-code-setup.md` evidence table |
| Delivery for Claude | A real checks run and a real independent review, to "Ready for delivery" | `docs/superpowers/evidence/2026-11-05-slice-2b.md` ("Not verified") |
| Managed run details | `Edit` call shape; follow-up turn through the dashboard; subagent approval (`session_id`, carry item e); subagent stop line (carry item d) | `docs/task-board.md` Plan 5 carry items |
| Browser | Attaching an output, a held approval card, subagent rows, a follow-up | slice-2b evidence, "NOT exercised in the browser" |
| Plan 5 leftovers input | Effect of `--disallowedTools` on a real run | `docs/superpowers/plans/2026-11-09-plan5-leftovers.md` |
| Codex after the refactor | No live Codex run is recorded since the provider seam landed | not found in the evidence files |

## Rules for every run

- Model alias `haiku`. Scratch copy of the repository at `main`, a scratch `haiku` role, a fresh state folder, port 8766, a
  scratch git project outside the repository (the 2 November setup). The real tree, its roles and the owner's Claude settings
  are not touched.
- Harmless prompts only (`echo`, a small text file). No real credentials anywhere.
- Record `claude --version` first (installed now: 2.1.312). Evidence holds event names and **field names**, never values,
  paths, tokens or prompt text.
- Each result row is labelled live, browser or owner-reported. One run per condition is stated as one run.
- No code change during the proof. A failure is recorded and becomes a fix task afterwards.
- Stop at once and tell the owner if: a call runs that nobody allowed; a card shows "ran although denied"; a secret-shaped
  value appears; a run passes 3 minutes or 15 turns (Stop is pressed).
- Cost figures are list-price estimates from the CLI, approximate, on the subscription login. Basis: 0.0105 USD for the
  six-turn run on 5 November, 0.0157 USD for the four runs on 2 November. Dashboard-managed runs have no budget cap flag
  today; the direct CLI run in Part 2 uses `--max-budget-usd`.

## Part 0: preparation (no model use)

1. Build the scratch copy, role, state folder and project. The project holds `notes-seed.txt` and `check.sh` (prints `ok`,
   exits 0).
2. Run `python3 -m unittest tests.test_spike_s11_stub` and start the dashboard (`claude` provider, port 8766). Confirm the
   Terminal sessions page reports enabled on port 47615.
3. Find where the per-install token file is written before using it. If the owner already has one, leave it as it is.

## Part 1: managed runs through the dashboard (4 runs, owner not needed at the keyboard)

The controller drives the built-in browser; every approval is pressed in the dashboard.

| Run | Action | Proves |
| --- | --- | --- |
| M1 | Development run: `Write` a file, `Edit` one line, one `Agent` subagent that runs `echo ok`, reply "finished" | `Edit` shape; held approval cards in the browser; a subagent's approval (does it carry the parent `session_id`); subagent stop line; reply in the conversation; delegate row on the Team page |
| M2 | Follow-up on the same task: append one line | A resumed turn through the dashboard |
| (browser) | Attach the written file as an output and open its preview | The owner-attached output journey |
| M3 | Save `sh check.sh` as the approved check; **Run approved checks** | A real checks run: check events, pass, no project change |
| M4 | **Start independent review**, read the report, accept | A real review; "Ready for delivery" with the Ponytail row "Not applicable for Claude" |
| (browser) | Delete the task | Deletion of a finished Claude task |

Optional fifth run: a checks run with a failing `check.sh`, expecting "not ready".

Estimate: 4 runs, about 0.05 USD in total (approximate).

## Part 2: one direct CLI run (no dashboard)

S12: `claude -p` with `--disallowedTools Write,Edit,NotebookEdit --max-budget-usd 0.10`, prompt asks to write a file.
Expected: no file is written; record whether the tools are absent from the session's tool list or refused when called.
This decides the wording of Task 1 in the Plan 5 leftovers plan. Estimate: 1 run, about 0.01 USD.

## Part 3: terminal sessions, owner at the keyboard (about 45 to 60 minutes)

The owner types short prompts in an interactive `claude --model haiku` session in the scratch project and answers Yes or No
when asked. The controller runs the stub or the dashboard and reads the logs.

**3a. Stub kit (S11), core cases first:**

| Case | Question it answers |
| --- | --- |
| A1 | Does `{}` leave the terminal prompt open and allow nothing? (decides `NO_DECISION_MODE`) |
| D4 | Dashboard down: does Claude Code's own prompt appear, nothing allowed? |
| D5 | Do hooks in `.claude/settings.local.json` fire? |
| B1, B2 | What do real `PostToolUse` and `Stop` carry after a terminal Yes and a terminal No? |
| B4, C3 | Is a dashboard deny honoured, and does the prompt close? |

If time allows: A4, C1, C2, C4, D1, D2, D3, then A2 and A3. Cases not run stay "pending" in S11.

**3b. The real Terminal sessions page** (snippet pasted into the scratch project's `.claude/settings.local.json`):

| Step | Owner does | Expected in the dashboard |
| --- | --- | --- |
| T1 | Trigger a prompt, do not answer | Card appears; controller presses Allow; call runs once; "ran after your Allow" |
| T2 | Trigger a prompt, do not answer | Controller presses Deny; call refused; no "ran although denied" |
| T3 | Answer Yes in the terminal | Card closes as `terminal (inferred)`, outcome ran |
| T4 | Answer No in the terminal | Card closes, "no run seen" |
| T5 | Controller stops the dashboard; owner triggers a prompt | Own prompt appears; nothing allowed automatically |
| T6 | End the session | Session shows ended |

Estimate: about 20 short prompts in the owner's session, under 0.15 USD (approximate; no interactive run has been costed
before).

Pre-agreed rule (owner, 2026-11-09): if A1 shows `{}` disturbs the prompt, switch `NO_DECISION_MODE` to `hold` afterwards.

## Part 4 (optional, owner decision): Codex regression

One live Codex run in a `codex` deployment: start, approve once, complete. Needs the owner's Codex sign-in. Cost not
estimated here.

## Records and roles

- `qa_engineer` records the results in `docs/superpowers/evidence/2026-11-10-live-proof.md` and fills the S11 tables.
- `security_reviewer` (read tools only) reads the deny, down and two-hook results before any statement in the docs changes
  from "not verified".
- `technical_writer` updates the evidence table in `docs/claude-code-setup.md`, the task board carry items and
  `docs/decisions.md`; `user_documentation_writer` checks any changed operator wording.
- `agent_evaluation_engineer` records a checkpoint in `docs/model-evaluation.md`.
- Each dispatch is recorded with role, model and effort.

## Not covered

`fable` and other models, Auto mode, other CLI versions, waits beyond 5 minutes, loaded timing runs. These stay "not
verified".

## Owner approvals needed

1. Parts 1 and 2: alias `haiku`, 5 runs (6 with the optional one), about 0.06 USD.
2. Part 3: a time when the owner is at the terminal; alias `haiku`, about 20 prompts, under 0.15 USD.
3. Part 4: yes or no.

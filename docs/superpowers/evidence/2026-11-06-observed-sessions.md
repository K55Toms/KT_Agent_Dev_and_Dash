# Observed sessions (Claude Phase 3, Plan 6) evidence

Date: 2026-11-09 to 2026-11-10. Branch `observed-sessions` (local, unpushed), code at `819e8f9`+ docs commits, HEAD at the time of writing `6f21006`. Plan: `docs/superpowers/plans/2026-11-06-claude-observed-sessions.md`. Spec: `docs/superpowers/specs/2026-11-06-claude-observed-sessions-design.md` (where it differs from the built behaviour, `docs/decisions.md` 2026-11-06 and the code win). Agent-evaluation record: see `docs/model-evaluation.md` (entry for this checkpoint). Each statement below is labelled by evidence kind. No secrets, tokens, session ids or keys appear here.

## Evidence kinds

### Unit and fake-binary

No real `claude` is involved: raw-socket HTTP to the observed listener, the dashboard API through the key harness, journeys through real HTTP, a DOM double for the UI.

| Check | Result |
| --- | --- |
| Full Python suite, Python 3.15, clean HOME, HEAD `8524ba2` | 1552 tests OK, 36 skipped |
| Full Python suite, Python 3.12, clean HOME, HEAD `6f21006` | 1552 tests OK, 36 skipped (536 s) |
| Focused observed set (docs, observed api/journey/receiver/sessions/hook/token, hook_http, hook_receiver, approval lifecycle) | 210 OK on Python 3.15 and 3.12 at `8524ba2`; 64 (docs + api) OK on both at `6f21006` |
| Node (`node --test tests/*.js`) | 215/215 at `8524ba2` |
| Journey and receiver modules repeated | 6/6 and 3/3 repeated runs green (flake check) |
| Managed path unchanged | managed receiver tests unedited; one added test pins the single changed label (`request_ended`) |

Defects the tests found during the build (all fixed with a regression test): a credential-shaped session id was shown and stored unscanned (journey, H2); a NodeList misuse hidden by a test double that returned arrays (re-review, fixed and the double made stricter); a transient failure of `test_provider_routes` in one full run (`inspect.getsource` while agents edited `server.py` mid-run; passes alone and in the final full runs).

### Browser (the AI controller, not the owner)

One real-browser check on a scratch copy at `1e9ac7b` (isolated HOME, fake `claude` 2.1.312, fake hook events over HTTP). Seen: the nav entry and page; status line, port and the Auto-mode sentence; sessions active/ended with "subagent activity seen" and no count; two pending cards with Allow/Deny; focus on an Allow button surviving a changed snapshot with no error banner; Enter on a focused Allow answering the held hook with the allow reply and the card reading "Allowed here: outcome not known", then "Allowed here: ran" after a matching `PostToolUse`; the hook snippet showing a 43-character token and all 7 events only after opening, absent elsewhere on the page and from browser storage, cleared after leaving the page and returning.
Not seen (changed after that check, covered by unit and journey tests only): the final snippet note wording, "no run seen", opaque ids, managed-session ignoring and its fail-closed check, `pagehide`, load-on-view-change. Not checked at all: the deny path and the quiet state in a browser, other browsers, screen readers, a true page reload (bfcache).

### Live

None for this feature. No real interactive terminal session has been used with it. Earlier live evidence (spike S7 in Phase 2, the Plan 5 headless `haiku` run) is not this feature. Spike kit S11 (`scripts/spike_s11_stub.py`, `docs/superpowers/spikes/S11-observed-replies.md`) is built and its owner-attended run is PENDING: the `{}` no-decision reply, the connection-drop and 413/415 endings, the two-hook merge, dashboard-down, `settings.local.json` loading, the terminal-first/dashboard-first cases and the real `PostToolUse`/`Stop` payloads.

### Owner-reported

None.

## Independent reviews

Per task: a fresh reviewer (spec and quality) and scoped re-reviews of every fix round; a read-only whole-feature security review (no Critical; 3 Important, all handled: managed runs ignored, fixed-port exposure warned and recorded as an owner decision, the `{}` reply labelled docs-sourced); a whole-branch review (ready after two doc fixes, done); a writers' documentation review (6 Important, done); a final scoped re-review (all addressed). Rulings R1 to R24 are in `docs/decisions.md` and the ledger summary there.

## Routing record (role / agent type / model / effort / usage)

Every dispatch was a general-purpose worker (not a loaded project role); "Work" is the job given. Effort was passed explicitly on every dispatch. Controller: session model. Usage figures are the subagent totals reported in the completion notices; fix rounds resumed an earlier agent and show that agent's running total.

| Dispatch | Work | Agent type | Model | Effort | Tokens | Tool uses | Minutes |
|---|---|---|---|---|---|---|---|
| Task 1 implementer | S11 spike kit | general-purpose | sonnet | medium | 74177 | 12 | 3.7 |
| Task 1 reviewer | review | general-purpose | sonnet | medium | 68504 | 3 | 0.6 |
| Task 1 fix round 1 (resumed implementer) | fix | general-purpose | sonnet | medium | 79735 total incl. earlier | 5 | 0.7 |
| Task 1 re-reviewer | scoped re-review | general-purpose | sonnet | low | 60651 | 4 | 0.3 |
| Task 2 implementer | hook_http split | general-purpose | sonnet | high | 83475 | 20 | 7.2 |
| Task 2 reviewer | review | general-purpose | sonnet | high | 73107 | 5 | 0.5 |
| Task 3 implementer | token file + setting | general-purpose | sonnet | high | 99868 | 28 | 8.1 |
| Task 3 reviewer | review (security) | general-purpose | opus | medium | 77956 | 5 | 0.9 |
| Task 3 fix round 1 (resumed implementer) | fix | general-purpose | sonnet | high | 108888 total | 5 | 1.0 |
| Task 3 re-reviewer | scoped re-review | general-purpose | sonnet | medium | 69458 | 3 | 0.5 |
| Task 4 implementer (incl. pre-review fix round) | parse + sessions model | general-purpose | opus | high | 140377 + fix | 38+ | 7.4+ |
| Task 4 reviewer | review (security/concurrency) | general-purpose | opus | medium | 81856 | 7 | 1.6 |
| Task 5 implementer | observed listener | general-purpose | opus | high | 157648 | 47 | 24.1 |
| Task 5 reviewer | review (security) | general-purpose | opus | high | 100193 | 10 | 2.3 |
| Task 6 implementer | server wiring + routes | general-purpose | opus | high | 175791 | 51 | 18.9 |
| Task 6 reviewer | review (security) | general-purpose | opus | high | 92795 | 16 | 1.6 |
| Task 6 fix round 1 (resumed implementer) | fix | general-purpose | opus | high | 183884 total | 12 | 2.1 |
| Task 6 re-reviewer | scoped re-review | general-purpose | sonnet | low | 58437 | 2 | 0.3 |
| Task 7 implementer | sessions page UI | general-purpose | sonnet | high | 127519 | 22 | 4.6 |
| Task 7 reviewer | review (security UI) | general-purpose | sonnet | high | 103185 | 11 | 2.0 |
| Task 7 fix round 1 (resumed implementer) | fix | general-purpose | sonnet | high | 146988 total | 8 | 2.3 |
| Task 7 re-reviewer | scoped re-review | general-purpose | sonnet | medium | 69289 | 4 | 0.8 |
| Task 7 fix round 2 (resumed implementer) | fix | general-purpose | sonnet | high | 153709 total | 6 | 1.1 |
| Task 7 re-reviewer 2 | scoped re-review | general-purpose | sonnet | medium | 71019 | 5 | 0.6 |
| Task 8 implementer | journeys + hardening H1-H6 | general-purpose | opus | high | 181466 | 52 | 20.2 |
| Task 8 reviewer | review | general-purpose | opus | medium | 105960 | 8 | 1.7 |
| Whole-feature security review | security (read-only) | general-purpose | opus | high | 165851 | 28 | 5.7 |
| Task 8 hardening + final fix wave (resumed implementer) | fix | general-purpose | opus | high | 256418 total | 48 | 18.4 |
| Task 8 fix-wave re-reviewer | scoped re-review (security) | general-purpose | opus | high | 118286 | 14 | 2.1 |
| Task 9 docs (technical/user doc writer role) | docs + doc tests | general-purpose | sonnet | high | 137712 | 33 | 4.0 |
| Task 8 R23 fix (resumed implementer) | fix | general-purpose | opus | high | 269498 total | 9 | 4.2 |
| Final whole-branch review | review | general-purpose | opus | high | 214885 | 43 | 7.4 |
| Writers' documentation review | docs review (technical/user doc writer role) | general-purpose | sonnet | high | 164111 | 29 | 4.3 |
| Task 9 final fix wave (resumed docs writer) | docs + small code | general-purpose | sonnet | high | 209006 total | 39 | 9.5 |
| Final fix-wave re-reviewer | scoped re-review | general-purpose | sonnet | high | 134318 | 24 | 2.0 |

## Not verified

- Everything in the Live section above (the S11 owner run).
- How Claude Code merges two PermissionRequest hook decisions; the behaviour with the dashboard down or the port taken (docs-sourced); the real PostToolUse and Stop payloads the inference depends on.
- Linux; Codex deployment in a browser (a journey test covers it); screen readers; other browsers.

## Open owner decisions

- Fixed-port exposure while the dashboard is down (accepted with warnings; alternative: a `command`-hook wrapper that checks the listener's uid).
- Keep the empty `{}` no-decision default until S11 is run (one-line switch to `hold`).
- Whether the managed check should become a precomputed set to avoid dropping events under a busy dashboard (deferred).
- Merging: PR pending the owner's authorisation; older code refuses a `config.toml` containing `observed_port`.

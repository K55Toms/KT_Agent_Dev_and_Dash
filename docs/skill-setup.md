# Agent skill setup

This repository stores role prompts and project instructions; a Git clone does not install
user-level skills or plugins. The role names in `.codex/agents/` are roles, not skill packages.
Install dependencies separately on each Codex environment. Before starting an agent whose prompt
requires a skill, confirm that skill is installed and loadable. Start a fresh role invocation after
changing its profile.

| Roles | Dependency | Source / local requirement |
| --- | --- | --- |
| `backend_developer`, `frontend_developer` | Ponytail Full 5.3.2 | External Codex plugin; dashboard verifies the approved version and digest |
| `ui_designer`, `frontend_developer` | `ui-skills-root` 1.0.0 | Installed Codex skill; Node.js/npm/npx for the unpinned UI Skills CLI |

## Ponytail Full: backend and frontend

`backend_developer` and `frontend_developer` use Ponytail Full. The dashboard enforces the
approved source in `dashboard/ponytail_policy.py`: version `5.3.2`, SHA-256
`9badd22a32e19cb884e46dfa8d3aae82bb81dfa5484105b8b4f0262df823a509`, under the home-relative
Codex plugin cache `~/.codex/plugins/cache/ponytail/ponytail/5.3.2/skills/ponytail/SKILL.md`.
The version and digest are strict pins. Review a proposed upstream update and change the policy
pin through the normal code review; do not replace the installed source or pin blindly.

The [Ponytail repository's `INSTALL.md`](https://github.com/DietrichGebert/ponytail/blob/main/INSTALL.md)
documents these Codex plugin commands:

```sh
codex plugin marketplace add DietrichGebert/ponytail
codex plugin add ponytail@ponytail
```

The install guide says to review and trust its two lifecycle hooks in Codex `/hooks`, then start a
new thread; for Codex desktop, restart the app after installing. These commands install from the
marketplace and do not select the dashboard's pinned version. If the resulting installed source
does not match the approved version and digest, stop and ask the project maintainer to review the
update before relying on it. Check the upstream install guide for current instructions.

From the repository root, verify that the dashboard can load and validate the installed policy:

```sh
python3 -c 'from dashboard.ponytail_policy import PonytailPolicy; print(PonytailPolicy().load().metadata)'
```

This check requires the repository's configured Gitleaks scanner because policy content is scanned
before use. A successful result reports the approved name, mode, version and digest. Keep plugin
files in the external Codex plugin cache, not in the Git repository.

## UI Skills root: designer and frontend

`ui_designer` and `frontend_developer` use the `ui-skills-root` router. It is one skill that tells
the role how to select focused UI guidance; it is not a separate `ui-designer` skill and does not
expand either role's ownership. The current upstream skill metadata reports version `1.0.0`.
That metadata version is separate from the `ui-skills` CLI package version. This project does not
pin the CLI package version, so the commands below are current smoke checks, not a reproducible
version lock.

Install the reviewed [`ui-skills-root`](https://github.com/ibelick/ui-skills/blob/main/skills/ui-skills-root/SKILL.md)
from the [upstream UI Skills repository](https://github.com/ibelick/ui-skills) into the Codex skill
catalogue with Codex's `$skill-installer` workflow. The
[official Codex skills guide](https://learn.chatgpt.com/docs/build-skills) describes local skill
locations and installation from other repositories. Confirm the installed `SKILL.md` is the
reviewed upstream root before use; do not copy a plugin cache or workstation-specific path into
this repository.

The UI Skills README documents browsing and fetching through `npx ui-skills`. Node.js with npm/npx
must be available on `PATH`. `npx` may fetch the CLI package, so an uncached first run needs network
access. From a project directory where you have permission to run commands, the root skill's
selection workflow uses:

```sh
npx ui-skills categories
npx ui-skills list --category <category>
npx ui-skills get <slug>
```

Choose the smallest useful skill set: usually one, never more than three. Route by topic, stack and
specificity. If the goal is unclear, ask one short question; if the skill or CLI cannot be loaded,
report that before dependent work. The UI designer includes the root source and selected skills in
the design handoff to frontend.

## Verification status

On the maintainer workstation, the pinned Ponytail policy load and digest check passed, Node/npm/npx
were available, and the native role suite passed (coordinator evidence). The installation commands
and UI Skills CLI smoke commands were not run here. A clean-machine install, marketplace version
match, and CLI version reproducibility remain unverified. Review the linked upstream instructions
before setup, since external install flows and latest versions can change.

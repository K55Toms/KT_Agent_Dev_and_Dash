#!/bin/sh
# Fixed local launch: no installation, authentication, or model turn is performed here.
set -eu
umask 077

if [ "$#" -ne 1 ] || { [ "$1" != codex ] && [ "$1" != claude ]; }; then
    printf '%s\n' 'Usage: sh scripts/run_dashboard.sh codex|claude' >&2
    exit 2
fi

script_dir=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
cd "$script_dir/.."

if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.11 or newer is required on PATH.' >&2
    exit 1
fi
dashboard_python=python3
if [ -x .venv/bin/python ]; then
    dashboard_python=.venv/bin/python
fi
if ! "$dashboard_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    printf '%s\n' 'Python 3.11 or newer is required on PATH.' >&2
    exit 1
fi
if [ "$1" = codex ] && ! command -v codex >/dev/null 2>&1; then
    printf '%s\n' 'Codex CLI is required on PATH. See docs/dashboard-operations.md.' >&2
    exit 1
fi
if [ "$1" = claude ] && ! command -v claude >/dev/null 2>&1; then
    printf '%s\n' 'Claude Code CLI is required on PATH.' >&2
    exit 1
fi

printf '%s\n' 'Starting the local dashboard on http://127.0.0.1:8765/'
printf '%s\n' 'Open the dashboard with the URL printed below (it ends in #key=...). Each start prints a new URL;'
printf '%s\n' 'older links and bookmarks stop working. Anyone with that URL can act as you. Ctrl-C shuts down the dashboard.'
exec "$dashboard_python" -m dashboard.server --port 8765 --provider "$1"

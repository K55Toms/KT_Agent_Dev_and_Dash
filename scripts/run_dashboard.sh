#!/bin/sh
# Fixed local launch: no installation, authentication, or model turn is performed here.
set -eu
umask 077

if [ "$#" -ne 0 ]; then
    printf '%s\n' 'Usage: sh scripts/run_dashboard.sh' >&2
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
if ! command -v codex >/dev/null 2>&1; then
    printf '%s\n' 'Codex CLI is required on PATH. See docs/dashboard-operations.md.' >&2
    exit 1
fi

printf '%s\n' 'Starting local dashboard at http://127.0.0.1:8765/'
printf '%s\n' 'Wait for server readiness. Ctrl-C shuts down the dashboard.'
exec "$dashboard_python" -m dashboard.server --port 8765

#!/bin/sh
set -eu
cd "$(git rev-parse --show-toplevel)"
command -v python3 >/dev/null || { echo 'Python 3.11+ is required.' >&2; exit 1; }
command -v gitleaks >/dev/null || { echo 'Install Gitleaks 8.30.1 before continuing.' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
test "$(gitleaks version)" = '8.30.1' || { echo 'Gitleaks 8.30.1 is required; review version upgrades explicitly.' >&2; exit 1; }
chmod +x .githooks/pre-commit .githooks/pre-push
git config --local core.hooksPath .githooks
git config --local push.default simple
git config --local fetch.fsckObjects true
git config --local transfer.fsckObjects true
echo 'Repository hooks installed. Run python3 scripts/security_check.py staged before committing.'

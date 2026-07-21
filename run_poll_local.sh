#!/bin/bash
# Real-time poll: check for NEW Trump posts and email an alert the moment one
# mentions a company. Runs every ~2 min via launchd. Wrapped in `caffeinate -i`
# so a plugged-in Mac won't idle-sleep between polls (keep the lid open).
# Path-agnostic; safe to run by hand too.
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PY="$PROJECT_DIR/venv/bin/python"
[ -x "$PY" ] || { echo "venv missing — run setup_mac.sh first"; exit 1; }

# -i: prevent idle sleep for the duration of the poll.
exec caffeinate -i "$PY" src/poll.py --lookback-min 30

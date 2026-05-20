#!/usr/bin/env bash
# curate.sh — hourly auto-lessons curator wrapper (host cron entry point).
#
# Add to crontab for hourly runs:
#   0 * * * * cd /path/to/repo && .specship/lessons/curate.sh >> .specship/lessons/curate.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/curate.py" "$@"

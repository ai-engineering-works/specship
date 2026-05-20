#!/usr/bin/env bash
# common.sh — shared env, paths, and helpers for the e2e harness.
# Source this from every harness script: . "$(dirname "$0")/../lib/common.sh"
set -euo pipefail

# Repo root = three levels up from lib/ (tests/e2e/lib -> repo root).
E2E_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$E2E_LIB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../.." && pwd)"

# Tunables (env-overridable).
SPECSHIP_E2E_MODEL="${SPECSHIP_E2E_MODEL:-sonnet}"
SPECSHIP_E2E_TIMEOUT="${SPECSHIP_E2E_TIMEOUT:-600}"
SPECSHIP_E2E_DRYRUN="${SPECSHIP_E2E_DRYRUN:-0}"

# Per-run bundle for transcripts/artifacts. Set by run.sh; default to a temp dir.
RUN_BUNDLE="${RUN_BUNDLE:-$(mktemp -d)}"

log()  { printf '  %s\n' "$*" >&2; }
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*" >&2; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*" >&2; }
hdr()  { printf '\n=== %s ===\n' "$*" >&2; }

# Path to the installed ledger CLI inside a target repo.
ledger_cli() { echo "$1/.specship/ledger/specship_ledger.py"; }

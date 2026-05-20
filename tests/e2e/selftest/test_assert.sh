#!/usr/bin/env bash
. "$(dirname "$0")/../lib/common.sh"
fails=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.specship/ledger"
cp "$REPO_ROOT/dist/ledger/specship_ledger.py" "$T/.specship/ledger/"
cp "$E2E_DIR/fixtures/selftest-events.jsonl" "$T/.specship/ledger/events.jsonl"

run() { python3 "$E2E_DIR/lib/assert.py" "$@"; }
check() { if eval "$1"; then ok "$2"; else fail "$2"; fails=$((fails+1)); fi; }
check "run event '$T' session_start --op eq --n 1"   "session_start counted"
check "run event '$T' gate_passed --op eq --n 1"     "gate_passed counted"
check "run count '$T' sessions --op ge --n 1"        "sessions projected"
check "! run event '$T' gate_passed --op eq --n 5"   "wrong count fails (negative)"
[[ $fails -eq 0 ]]

#!/usr/bin/env bash
. "$(dirname "$0")/../lib/approve.sh"
fails=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.specship/ledger"
cli="$T/.specship/ledger/specship_ledger.py"
cp "$REPO_ROOT/dist/ledger/specship_ledger.py" "$cli"
# Seed a drafted (un-reviewed) plan, run from $T so the ledger resolves to it.
( cd "$T" && python3 "$cli" log plan_drafted plan_id='"pln-123"' \
  drafted_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" scope='"backend"' --quiet )

PID="$(approve_latest_plan "$T")"
( cd "$T" && python3 "$cli" rebuild-index ) >/dev/null
got_verdict="$( ( cd "$T" && python3 "$cli" query "SELECT verdict FROM plans WHERE plan_id='pln-123'" ) | tail -1 | tr -d ' ')"
approved_events="$(python3 "$E2E_DIR/lib/assert.py" event "$T" plan_approved --op eq --n 1 >/dev/null && echo y)"

[[ "$PID" == "pln-123" ]] && ok "returned plan id" || { fail "plan id"; fails=$((fails+1)); }
[[ "$got_verdict" == "approved" ]] && ok "verdict projected approved" || { fail "verdict=$got_verdict"; fails=$((fails+1)); }
[[ "$approved_events" == "y" ]] && ok "plan_approved event present" || { fail "no plan_approved"; fails=$((fails+1)); }
[[ $fails -eq 0 ]]

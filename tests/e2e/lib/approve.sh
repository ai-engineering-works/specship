#!/usr/bin/env bash
# approve.sh — act as the human reviewer by logging the real approval events.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Approve the most recent un-reviewed plan in TARGET's ledger.
# Satisfies the `/work --from-plan` safety check, which refuses to execute a
# plan lacking a matching plan_approved event.
approve_latest_plan() {
  local target="$1" cli; cli="$(ledger_cli "$target")"
  ( cd "$target" && python3 "$cli" rebuild-index ) >/dev/null 2>&1 || true
  local plan_id
  plan_id="$(python3 - "$target" <<'PY'
import sqlite3, sys
from pathlib import Path
db = Path(sys.argv[1]) / ".specship" / "ledger" / "index.db"
con = sqlite3.connect(db)
row = con.execute(
    "SELECT plan_id FROM plans WHERE verdict IS NULL ORDER BY drafted_at DESC LIMIT 1"
).fetchone()
print(row[0] if row else "")
PY
)"
  if [[ -z "$plan_id" ]]; then
    log "approve_latest_plan: no un-reviewed plan found in $target"
    return 1
  fi
  ( cd "$target" && python3 "$cli" log plan_approved \
    plan_id="\"$plan_id\"" \
    verdict='"approved"' \
    reviewer_note='"approved by e2e harness"' \
    reviewed_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    --quiet ) >/dev/null
  log "approved plan $plan_id"
  echo "$plan_id"
}

# Generic verdict logger for /review-decisions style flows.
review_decision() {
  local target="$1" artifact="$2" verdict="$3" cli; cli="$(ledger_cli "$target")"
  ( cd "$target" && python3 "$cli" log decision_reviewed \
    artifact="\"$artifact\"" review_verdict="\"$verdict\"" \
    reviewed_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" --quiet )
}

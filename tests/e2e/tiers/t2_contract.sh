#!/usr/bin/env bash
# T2 — full-stack: /spec -> /contract -> /work backend + frontend -> /check -> commit
. "$(dirname "$0")/../lib/provision.sh"
. "$(dirname "$0")/../lib/claude_cmd.sh"
. "$(dirname "$0")/../lib/approve.sh"
A="$E2E_DIR/lib/assert.py"

# NOTE: claude_run calls below are intentionally unguarded. These scripts inherit
# `set -e` (from common.sh), so a nonzero exit from a Claude step (timeout/CLI
# error) aborts the tier before the assertions run. That is deliberate fail-fast
# on infrastructure failure — `claude -p` normally exits 0 even on semantic issues,
# so the structural assertions still execute in the common case.

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"

TICKET="$(cat "$E2E_DIR/fixtures/t2_ticket.md")"
claude_run "$T" 01-spec "/spec DEMO-2 full-stack. $TICKET"
SPEC="$(ls "$T"/specs/*.md 2>/dev/null | head -1)"; [[ -n "$SPEC" ]] || { fail "no spec"; exit 1; }
REL="${SPEC#"$T"/}"

claude_run "$T" 02-contract "/contract $REL"

for scope in backend frontend; do
  claude_run "$T" "03-work-plan-$scope" "/work $REL --plan-only --scope $scope"
  approve_latest_plan "$T" >/dev/null
  claude_run "$T" "04-work-exec-$scope" "/work $REL --from-plan"
done

claude_run "$T" 05-check "/check $REL"
( cd "$T" && git add -A && git commit -qm "feat: DEMO-2 subscribe

§ref:$REL" )

fails=0
# Contract artifacts generated and hash-stamped.
[[ -d "$T/_generated" ]] && ls "$T"/_generated/* >/dev/null 2>&1 && ok "generated artifacts exist" || { fail "_generated empty"; fails=$((fails+1)); }
python3 "$A" count "$T" sessions --op ge --n 3 || fails=$((fails+1))
python3 "$A" count "$T" coverage --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" plans "--where" "verdict='approved'" --op ge --n 2 || fails=$((fails+1))
python3 "$A" event "$T" gate_passed --op ge --n 1 || fails=$((fails+1))

cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]

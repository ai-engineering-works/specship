#!/usr/bin/env bash
# T1 — single-scope happy path: /spec -> /work (plan-gated) -> /review-decisions -> commit
. "$(dirname "$0")/../lib/provision.sh"
. "$(dirname "$0")/../lib/claude_cmd.sh"
. "$(dirname "$0")/../lib/approve.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"

TICKET="$(cat "$E2E_DIR/fixtures/t1_ticket.md")"
claude_run "$T" 01-spec "/spec DEMO-1 backend-only. $TICKET"
SPEC="$(ls "$T"/specs/*.md 2>/dev/null | head -1)"; [[ -n "$SPEC" ]] || { fail "no spec drafted"; exit 1; }
REL="${SPEC#"$T"/}"

claude_run "$T" 02-work-plan "/work $REL --plan-only --scope backend"
approve_latest_plan "$T" >/dev/null
claude_run "$T" 03-work-exec "/work $REL --from-plan"
claude_run "$T" 04-review "/review-decisions"

# Commit production code with spec linkage (Wall must pass).
( cd "$T" && git add -A && git commit -qm "feat: DEMO-1 version endpoint

§ref:$REL" )

fails=0
python3 "$A" count "$T" sessions --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" decisions --op ge --n 1 || fails=$((fails+1))
python3 "$A" event "$T" gate_passed --op ge --n 1 || fails=$((fails+1))
python3 "$A" event "$T" plan_approved --op eq --n 1 || fails=$((fails+1))

if [[ "${NO_DASH:-0}" -eq 0 ]]; then
  node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "h1=specship dashboard" || fails=$((fails+1))
fi
cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]

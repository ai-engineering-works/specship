#!/usr/bin/env bash
# T3 — the full pipeline: /ship -> /qa -> bug -> /investigate -> /fix -> /encode-lesson
#      -> /capture-lessons -> curator -> /review-lessons
. "$(dirname "$0")/../lib/provision.sh"
. "$(dirname "$0")/../lib/claude_cmd.sh"
. "$(dirname "$0")/../lib/approve.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"

TICKET="$(cat "$E2E_DIR/fixtures/t3_ticket.md")"
claude_run "$T" 01-spec "/spec DEMO-3 full-stack. $TICKET"
SPEC="$(ls "$T"/specs/*.md 2>/dev/null | head -1)"; [[ -n "$SPEC" ]] || { fail "no spec"; exit 1; }
REL="${SPEC#"$T"/}"

# /ship runs --plan-only inside its subagents; approve the drafted plans, then
# let /ship continue. We approve every un-reviewed plan after the planning phase.
claude_run "$T" 02-ship-plan "/ship $REL --plan-only"
while approve_latest_plan "$T" >/dev/null 2>&1; do :; done
claude_run "$T" 03-ship-exec "/ship $REL --from-plan"

# QA artifacts for the spec (supply interview answers up front).
claude_run "$T" 04-qa "/qa $REL
Author one scenario and one property artifact. For the scenario, action is HTTP POST /export; expectations: http_status 200 for a valid range, http_status 400 when from > to. Language python, generator pytest. No ui_action. Approve and generate tests."

# Seed the known bug, then investigate -> fix.
claude_run "$T" 05-investigate "/investigate DEMO-3-BUG the /export endpoint returns 200 when 'from' is after 'to'; it must return 400. Find the root cause in src/app.py."
INV="$(ls "$T"/investigations/*.md 2>/dev/null | head -1)"; INVREL="${INV#"$T"/}"
claude_run "$T" 06-fix "/fix DEMO-3-BUG --against $REL --from-investigation $INVREL"
FIX="$(ls "$T"/fixes/*.md 2>/dev/null | head -1)"; FIXREL="${FIX#"$T"/}"
claude_run "$T" 07-work-fix "/work $FIXREL --plan-only --scope backend"
approve_latest_plan "$T" >/dev/null
claude_run "$T" 08-work-fix-exec "/work $FIXREL --from-plan"

# Close the loop and exercise the lessons pipeline.
claude_run "$T" 09-encode "/encode-lesson $INVREL --fix $FIXREL"
claude_run "$T" 10-capture "/capture-lessons"
( cd "$T" && bash .specship/lessons/curate.sh >/dev/null 2>&1 || true )
claude_run "$T" 11-review-lessons "/review-lessons"

fails=0
python3 "$A" count "$T" plans "--where" "verdict='approved'" --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" qa_artifacts --op ge --n 1 || fails=$((fails+1))
python3 "$A" event "$T" qa_tests_generated --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" lessons --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" lesson_candidates --op ge --n 1 || fails=$((fails+1))
ls "$T"/tests/scenario/*.py >/dev/null 2>&1 && ok "generated scenario test exists" || { fail "no generated test"; fails=$((fails+1)); }

if [[ "${NO_DASH:-0}" -eq 0 ]]; then
  node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "h1=specship dashboard" || fails=$((fails+1))
fi
cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]

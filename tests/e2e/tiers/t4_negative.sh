#!/usr/bin/env bash
# T4 — negative/gate cases. Deterministic (no tokens): exercises the Wall, the
# coverage gate, the un-approved-plan state behind --from-plan refusal, and the
# advisory qa-check warning.
. "$(dirname "$0")/../lib/provision.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"
cli="$(ledger_cli "$T")"
fails=0

# --- Case 1: Wall blocks a src/ commit with no linkage ---
( cd "$T" && printf '\ndef feature():\n    return 1\n' >> src/app.py && git add src/app.py )
if ( cd "$T" && git commit -qm "feat: no linkage" ) >/dev/null 2>&1; then
  fail "Wall did not block no-linkage commit"; fails=$((fails+1))
else
  ok "Wall blocked no-linkage commit"
fi
( cd "$T" && git reset -q HEAD src/app.py >/dev/null 2>&1 || true; git checkout -q -- src/app.py )

# --- Case 2: un-approved plan present (the state --from-plan refusal needs) ---
( cd "$T" && python3 "$cli" log plan_drafted plan_id='"pln-x"' \
  drafted_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" --quiet ) >/dev/null
if python3 "$A" count "$T" plans "--where" "verdict IS NULL" --op ge --n 1; then
  ok "un-approved plan present (from-plan would refuse)"
else
  fail "expected an un-approved plan row"; fails=$((fails+1))
fi

# --- Case 3: coverage gate blocks a commit when the latest measurement failed ---
( cd "$T" && python3 "$cli" log coverage_measured tool='"pytest"' metric='"line"' \
  delta_pct='12.0' threshold_delta='80.0' passed='false' \
  artifact="\"specs/demo.md\"" --quiet ) >/dev/null
( cd "$T" && printf '\ndef covered():\n    return 2\n' >> src/app.py \
  && mkdir -p specs && echo "# demo" > specs/demo.md && git add src/app.py specs/demo.md )
if ( cd "$T" && git commit -qm "feat: with spec but failing coverage" ) >/dev/null 2>&1; then
  fail "coverage gate did not block commit"; fails=$((fails+1))
else
  ok "coverage gate blocked commit"
fi
python3 "$A" event "$T" gate_blocked --op ge --n 1 || fails=$((fails+1))
( cd "$T" && git reset -q HEAD . >/dev/null 2>&1 || true; git checkout -q -- src/app.py 2>/dev/null || true; rm -f specs/demo.md )

# --- Case 4: qa-check warns on edit to an approved regression (advisory) ---
mkdir -p "$T/regressions"
cat > "$T/regressions/r1.md" <<'EOF'
---
regression_id: rr01
parent_fix: fixes/f.md
status: approved
language: python
generator: pytest
---
# Regression: demo
## Input
```json
{"x": 1}
```
## Expected output
```json
{"ok": true}
```
EOF
( cd "$T" && git add regressions/r1.md && git commit -qm "seed regression

§ref:fixes/f.md" --no-verify )
( cd "$T" && perl -pi -e 's/"x": 1/"x": 2/' regressions/r1.md && git add regressions/r1.md )
WARN="$( cd "$T" && python3 .specship/hooks/qa-check.py 2>&1 || true )"
if echo "$WARN" | grep -q "approved"; then
  ok "qa-check warned on approved-regression edit"
else
  fail "no qa-check warning (got: $WARN)"; fails=$((fails+1))
fi

cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]

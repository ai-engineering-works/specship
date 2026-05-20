#!/usr/bin/env bash
. "$(dirname "$0")/../lib/common.sh"
if ! (cd "$E2E_DIR" && npx --no-install playwright --version) >/dev/null 2>&1; then
  log "Playwright not installed — skipping dashboard self-test"; exit 0
fi
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.specship/ledger" "$T/.specship/dashboard"
cp "$REPO_ROOT/dist/dashboard/dashboard.html" "$T/.specship/dashboard/"
cp "$E2E_DIR/fixtures/selftest-events.jsonl" "$T/.specship/ledger/events.jsonl"
node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "h1=specship dashboard"

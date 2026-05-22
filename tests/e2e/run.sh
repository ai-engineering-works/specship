#!/usr/bin/env bash
# run.sh — specship live e2e harness entry point.
#   ./run.sh [--tier t1,t3] [--model opus] [--keep]
. "$(dirname "$0")/lib/common.sh"

TIERS="t1,t2,t3,t4"; KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) TIERS="$2"; shift 2;;
    --model) export SPECSHIP_E2E_MODEL="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
export KEEP

hdr "Prerequisites"
command -v claude  >/dev/null 2>&1 || { fail "claude CLI not on PATH (required)"; exit 1; }
command -v python3 >/dev/null 2>&1 || { fail "python3 not on PATH (required)"; exit 1; }
ok "prerequisites satisfied"

declare -i passed=0 failed=0
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
for t in ${TIERS//,/ }; do
  script="$E2E_DIR/tiers/${t}_"*.sh
  # shellcheck disable=SC2086
  script=$(ls $script 2>/dev/null | head -1 || true)
  [[ -z "$script" || ! -f "$script" ]] && { fail "no tier script for $t"; failed+=1; continue; }
  export RUN_BUNDLE="$E2E_DIR/runs/$RUN_TS/$t"; mkdir -p "$RUN_BUNDLE"
  hdr "Tier $t"
  if bash "$script"; then ok "tier $t"; passed+=1; else fail "tier $t"; failed+=1; fi
done

hdr "Summary"
log "passed=$passed failed=$failed   bundles: $E2E_DIR/runs/$RUN_TS"
[[ $failed -eq 0 ]]

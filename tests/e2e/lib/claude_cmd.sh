#!/usr/bin/env bash
# claude_cmd.sh — single choke point for invoking specship commands via Claude.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# claude_run <target_repo> <slug> <prompt>
# Runs `claude -p` from inside the target repo. Captures stdout+stderr+exit code
# into the run bundle. Honors SPECSHIP_E2E_DRYRUN=1 (print the command, do not
# run). Returns Claude's exit code (or the timeout's).
claude_run() {
  local target="$1" slug="$2" prompt="$3"
  local logf="$RUN_BUNDLE/${slug}.log"
  if [[ "$SPECSHIP_E2E_DRYRUN" == "1" ]]; then
    printf 'DRYRUN [%s] model=%s\n%s\n' "$slug" "$SPECSHIP_E2E_MODEL" "$prompt" | tee "$logf" >&2
    return 0
  fi
  log "claude: $slug (model=$SPECSHIP_E2E_MODEL)"
  set +e
  ( cd "$target" && timeout "$SPECSHIP_E2E_TIMEOUT" \
      claude -p "$prompt" \
        --permission-mode bypassPermissions \
        --model "$SPECSHIP_E2E_MODEL" ) >"$logf" 2>&1
  local rc=$?
  set -e
  [[ $rc -ne 0 ]] && log "claude '$slug' exited $rc (see $logf)"
  return $rc
}

#!/usr/bin/env bash
#
# ledger.sh — bash helpers for the specship observability ledger
#
# Source this in any script:
#     source .specship/ledger/ledger.sh
#
# Then use:
#     specship_log session_start command=spec artifact_path=specs/foo.md
#     specship_log session_end session_id="$SID" outcome=completed
#     specship_session_id  # generates a UUID
#
# All helpers call specship_ledger.py under the hood. They never fail in a way
# that would break the calling command — ledger writes are best-effort. If
# the ledger is broken, specship commands still work; you just lose the trace.

# Resolve the path to specship_ledger.py
_specship_ledger_py() {
    # 1. Look in the calling repo's .specship/ledger/
    local repo
    repo="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    if [[ -f "$repo/.specship/ledger/specship_ledger.py" ]]; then
        echo "$repo/.specship/ledger/specship_ledger.py"
        return 0
    fi
    # 2. Look next to this script (the installed location)
    local self_dir
    self_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "$self_dir/specship_ledger.py" ]]; then
        echo "$self_dir/specship_ledger.py"
        return 0
    fi
    return 1
}

specship_log() {
    # specship_log <event_type> [key=value ...]
    # Best-effort. Stderr captured; never propagates failure.
    local event_type="$1"; shift
    local script
    if ! script=$(_specship_ledger_py); then
        return 0  # ledger not installed, silently skip
    fi
    python3 "$script" log "$event_type" "$@" --quiet 2>/dev/null || true
}

specship_session_id() {
    # Print a fresh UUID for use as session_id
    python3 -c "import uuid; print(uuid.uuid4())"
}

specship_summary() {
    local script
    script=$(_specship_ledger_py) || { echo "ledger not installed" >&2; return 1; }
    python3 "$script" summary "$@"
}

specship_rebuild_index() {
    local script
    script=$(_specship_ledger_py) || { echo "ledger not installed" >&2; return 1; }
    python3 "$script" rebuild-index "$@"
}

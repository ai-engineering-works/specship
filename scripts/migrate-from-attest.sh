#!/bin/bash
# migrate-from-attest.sh — one-time migration for repos previously using `attest`
#
# Renames .attest/ → .specship/, updates pre-commit hook references, and adds the
# new gitignore entries. After this script runs, the new `install.sh` can be re-run
# to drop in the renamed binaries.
#
# The on-disk ledger (events.jsonl) is byte-for-byte preserved. Event types,
# session IDs, and audit history all stay intact. The audit trail of work done
# under the old name is preserved exactly.
#
# Usage:
#     ./migrate-from-attest.sh <target-repo-path>
#     ./migrate-from-attest.sh <target-repo-path> --dry-run
#
# After this completes:
#     ./scripts/install.sh <target-repo-path>

set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "Usage: $0 <target-repo-path> [--dry-run]"
    exit 1
fi

DRY_RUN=0
for arg in "$@"; do
    [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

if [[ ! -d "$TARGET" ]]; then
    echo "Error: $TARGET is not a directory"
    exit 1
fi

cd "$TARGET"

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] $*"
    else
        eval "$@"
    fi
}

echo "Migrating $TARGET from attest → specship"
echo ""

# --- Sanity checks ------------------------------------------------------------

if [[ ! -d .attest ]]; then
    echo "  No .attest/ directory found. Either this repo never used attest, or"
    echo "  the migration has already been run."
    exit 0
fi

if [[ -d .specship ]]; then
    echo "  Error: both .attest/ and .specship/ exist. This shouldn't happen."
    echo "  Decide which one is authoritative, remove the other manually, then"
    echo "  re-run this script if needed."
    exit 1
fi

# --- Step 1: rename .attest/ → .specship/ ------------------------------------

echo "1/4  Renaming .attest/ → .specship/"
run "mv .attest .specship"

# --- Step 2: rename the ledger binary if present ------------------------------

if [[ -f .specship/ledger/attest_ledger.py ]]; then
    echo "2/4  Renaming ledger binary"
    run "mv .specship/ledger/attest_ledger.py .specship/ledger/specship_ledger.py"
else
    echo "2/4  Ledger binary already renamed or absent (skipped)"
fi

# --- Step 3: update pre-commit hook references --------------------------------

HOOK=".git/hooks/pre-commit"
if [[ -f "$HOOK" ]] && grep -q "attest" "$HOOK"; then
    echo "3/4  Updating pre-commit hook"
    if [[ $DRY_RUN -eq 0 ]]; then
        cp "$HOOK" "$HOOK.pre-specship.bak"
        sed -i.tmp 's|\.attest/ledger/attest_ledger\.py|.specship/ledger/specship_ledger.py|g; s|\.attest/|.specship/|g' "$HOOK"
        rm -f "$HOOK.tmp"
    else
        echo "  [dry-run] would sed .attest/ → .specship/ in $HOOK"
    fi
else
    echo "3/4  Pre-commit hook unchanged (no attest references or no hook)"
fi

# --- Step 4: update .gitignore -----------------------------------------------

if [[ -f .gitignore ]] && grep -q '^\.attest/' .gitignore; then
    echo "4/4  Updating .gitignore"
    if [[ $DRY_RUN -eq 0 ]]; then
        cp .gitignore .gitignore.pre-specship.bak
        sed -i.tmp 's|^\.attest/|.specship/|g' .gitignore
        rm -f .gitignore.tmp
    else
        echo "  [dry-run] would rewrite .attest/ entries in .gitignore"
    fi
else
    echo "4/4  .gitignore unchanged (no attest entries)"
fi

echo ""
echo "Migration complete."
echo ""
if [[ $DRY_RUN -eq 0 ]]; then
    echo "Backups left at:"
    [[ -f "$HOOK.pre-specship.bak" ]] && echo "  $HOOK.pre-specship.bak"
    [[ -f .gitignore.pre-specship.bak ]] && echo "  .gitignore.pre-specship.bak"
    echo ""
    echo "Next step:"
    echo "  cd /path/to/specship && ./scripts/install.sh \"$TARGET\""
    echo ""
    echo "Then commit:"
    echo "  cd \"$TARGET\""
    echo "  git add .specship/ledger/events.jsonl .gitignore"
    echo "  git rm --cached -r .attest 2>/dev/null || true"
    echo "  git commit -m 'migrate from attest to specship'"
fi

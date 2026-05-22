#!/usr/bin/env bash
#
# install.sh — install the specship workflow into a target repo
#
# Usage:
#   ./scripts/install.sh <path-to-target-repo>
#   ./scripts/install.sh <path-to-target-repo> --skip-skill   # don't install user-scoped skill
#   ./scripts/install.sh <path-to-target-repo> --user-commands # install commands to ~/.claude instead of project
#   ./scripts/install.sh <path-to-target-repo> --with-cron    # install hourly curator cron for auto-lessons
#
# What this script does:
#   1. Drops CLAUDE.md template at the target repo root (only if no CLAUDE.md exists)
#   2. Creates specs/, fixes/, _generated/ directories
#   3. Installs slash commands under <target>/.claude/commands/
#   4. Installs the pre-commit hook into <target>/.git/hooks/pre-commit
#   5. Installs the claude-md-architect skill under ~/.claude/skills/ (user-scoped)
#
# This script is idempotent — re-running it is safe; existing files are
# preserved (with .bak backup) rather than overwritten.

set -euo pipefail

# ---- Argument parsing ----

if [[ $# -lt 1 ]]; then
    cat >&2 <<EOF
Usage: $0 <path-to-target-repo> [options]

Options:
  --skip-skill        Skip installing the claude-md-architect skill
  --user-commands     Install slash commands to ~/.claude (user-scoped)
                      instead of <target>/.claude (project-scoped)
  --skip-hook         Skip installing the pre-commit hook
  --with-cron         Install hourly cron job for the auto-lessons curator
  --dry-run           Print what would be done; make no changes
EOF
    exit 2
fi

TARGET="$1"; shift
SKIP_SKILL=0
USER_COMMANDS=0
SKIP_HOOK=0
DRY_RUN=0
WITH_CRON=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-skill) SKIP_SKILL=1 ;;
        --user-commands) USER_COMMANDS=1 ;;
        --skip-hook) SKIP_HOOK=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --with-cron) WITH_CRON=1 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# ---- Validate target ----

if [[ ! -d "$TARGET" ]]; then
    echo "Target directory does not exist: $TARGET" >&2
    exit 1
fi

if [[ ! -d "$TARGET/.git" ]]; then
    echo "Target is not a git repository: $TARGET" >&2
    echo "Run 'git init' there first, or point install.sh at a real repo." >&2
    exit 1
fi

# Resolve absolute paths
TARGET=$(cd "$TARGET" && pwd)
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$REPO_ROOT/dist"

if [[ ! -d "$DIST" ]]; then
    echo "Cannot find dist/ at $DIST" >&2
    echo "Are you running install.sh from a clone of specship?" >&2
    exit 1
fi

# ---- Helpers ----

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "DRY: $*"
    else
        eval "$@"
    fi
}

# Copy a file, backing up the destination if it already exists with different content
safe_copy() {
    local src="$1" dest="$2"
    if [[ -f "$dest" ]]; then
        if cmp -s "$src" "$dest"; then
            echo "  unchanged: $dest"
            return
        fi
        local backup="${dest}.bak.$(date +%Y%m%d-%H%M%S)"
        echo "  backing up existing → $backup"
        run "cp '$dest' '$backup'"
    fi
    run "cp '$src' '$dest'"
    echo "  installed: $dest"
}

# ---- Install steps ----

echo "Installing specship workflow into: $TARGET"
[[ $DRY_RUN -eq 1 ]] && echo "(dry run — no files will be changed)"
echo ""

# Step 0: refuse to install if the target has a legacy `attest` install
# (the old name for specship — see CHANGELOG v0.12.0). Running install.sh on
# top of a .attest/ install would create a confusing parallel state with two
# ledgers, two helper trees, and a hook that still points to the old binary.
if [[ -d "$TARGET/.attest" ]]; then
    echo "Found a legacy .attest/ directory in $TARGET — this repo was previously"
    echo "set up with the old name (attest). specship cannot install on top of an"
    echo "attest install."
    echo ""
    echo "Run the one-time migration first:"
    echo "    $REPO_ROOT/scripts/migrate-from-attest.sh \"$TARGET\""
    echo ""
    echo "After migration completes, re-run this script."
    exit 1
fi

# 1. CLAUDE.md template (only if no CLAUDE.md exists)
echo "1/9  CLAUDE.md template"
if [[ -f "$TARGET/CLAUDE.md" ]]; then
    echo "  CLAUDE.md already exists — leaving untouched."
    echo "  To convert it to the specship template, run the claude-md-architect skill in Claude Code."
else
    run "cp '$DIST/templates/CLAUDE.md.template' '$TARGET/CLAUDE.md'"
    echo "  installed: $TARGET/CLAUDE.md (fill in the placeholders)"
fi
echo ""

# 2. Directories
echo "2/9  Directories"
for dir in specs fixes investigations _generated .specship .specship/ledger .specship/contract .specship/coverage .specship/plans .specship/lessons .specship/hooks; do
    if [[ -d "$TARGET/$dir" ]]; then
        echo "  exists: $TARGET/$dir/"
    else
        run "mkdir -p '$TARGET/$dir'"
        echo "  created: $TARGET/$dir/"
    fi
done
# .gitattributes for _generated
if [[ ! -f "$TARGET/_generated/.gitattributes" ]]; then
    run "echo '* linguist-generated=true' > '$TARGET/_generated/.gitattributes'"
    echo "  installed: $TARGET/_generated/.gitattributes"
fi
echo ""

# 3. Slash commands
if [[ $USER_COMMANDS -eq 1 ]]; then
    CMD_DEST="$HOME/.claude/commands"
    echo "3/9  Slash commands (user-scoped → $CMD_DEST)"
else
    CMD_DEST="$TARGET/.claude/commands"
    echo "3/9  Slash commands (project-scoped → $CMD_DEST)"
fi
run "mkdir -p '$CMD_DEST'"
for cmd_file in "$DIST/commands/"*.md; do
    cmd_base=$(basename "$cmd_file")
    [[ "$cmd_base" == "README.md" ]] && continue
    safe_copy "$cmd_file" "$CMD_DEST/$cmd_base"
done
echo ""

# 4. Pre-commit hook
if [[ $SKIP_HOOK -eq 1 ]]; then
    echo "4/9  Pre-commit hook (skipped via --skip-hook)"
else
    echo "4/9  Pre-commit hook"
    safe_copy "$DIST/hooks/pre-commit" "$TARGET/.git/hooks/pre-commit"
    run "chmod +x '$TARGET/.git/hooks/pre-commit'"
    # Advisory QA helper invoked best-effort by the hook (never blocks).
    safe_copy "$DIST/hooks/qa-check.py" "$TARGET/.specship/hooks/qa-check.py"
    run "chmod +x '$TARGET/.specship/hooks/qa-check.py'"
fi
echo ""

# 5. Observability ledger
echo "5/9  Observability ledger"
LEDGER_DEST="$TARGET/.specship/ledger"
run "mkdir -p '$LEDGER_DEST'"
safe_copy "$DIST/ledger/specship_ledger.py" "$LEDGER_DEST/specship_ledger.py"
safe_copy "$DIST/ledger/ledger.sh" "$LEDGER_DEST/ledger.sh"
safe_copy "$DIST/ledger/HOW-TO-LOG.md" "$LEDGER_DEST/HOW-TO-LOG.md"
run "chmod +x '$LEDGER_DEST/specship_ledger.py' '$LEDGER_DEST/ledger.sh'"
# Stamp the installed specship version (read by specship-dashboard and by the
# ledger to tag session_start events).
if [[ -f "$REPO_ROOT/VERSION" ]]; then
    safe_copy "$REPO_ROOT/VERSION" "$TARGET/.specship/VERSION"
fi
# Add SQLite index AND plans directory to gitignore. The JSONL log IS committed;
# the SQLite index is rebuildable. Plans (.specship/plans/*.md) are transient
# artifacts of /work --plan-only — regenerated on each /ship invocation, and
# the audit-relevant facts (plan_drafted, plan_approved) live in the ledger.
if [[ -f "$TARGET/.gitignore" ]] && ! grep -qE '^\.specship/ledger/index\.db$' "$TARGET/.gitignore"; then
    echo "  appending .specship entries to .gitignore"
    run "printf '\n# specship: rebuildable SQLite index (JSONL log is committed)\n.specship/ledger/index.db\n.specship/ledger/index.db-journal\n.specship/ledger/index.db-wal\n.specship/ledger/index.db-shm\n# specship: transient plan files (audit trail lives in the ledger)\n.specship/plans/*.md\n' >> '$TARGET/.gitignore'"
elif [[ ! -f "$TARGET/.gitignore" ]]; then
    echo "  creating .gitignore with specship entries"
    run "printf '# specship: rebuildable SQLite index (JSONL log is committed)\n.specship/ledger/index.db\n.specship/ledger/index.db-journal\n.specship/ledger/index.db-wal\n.specship/ledger/index.db-shm\n# specship: transient plan files (audit trail lives in the ledger)\n.specship/plans/*.md\n' > '$TARGET/.gitignore'"
fi
echo ""

# 6. Auto-lessons helpers
echo "6/9  Auto-lessons helpers"
LESSONS_DEST="$TARGET/.specship/lessons"
run "mkdir -p '$LESSONS_DEST'"
for f in lessons_query.py curate.py curate.sh selftest.py HOW-IT-WORKS.md; do
    run "cp '$DIST/lessons/$f' '$LESSONS_DEST/$f'"
done
run "chmod +x '$LESSONS_DEST/curate.sh'"

# Auto-lessons: SessionEnd capture hook + optional hourly curator cron.
HOOK_SNIPPET="$DIST/hooks/session-end-capture.json"
SETTINGS_FILE="$TARGET/.claude/settings.json"
echo ""
echo "Auto-lessons setup:"
echo "  To capture lessons automatically at session end, merge this into $SETTINGS_FILE:"
echo "    $(cat "$HOOK_SNIPPET")"
CRON_LINE="0 * * * * cd '$TARGET' && .specship/lessons/curate.sh >> .specship/lessons/curate.log 2>&1"
if [[ "${WITH_CRON:-0}" == "1" ]]; then
    if crontab -l 2>/dev/null | grep -qF ".specship/lessons/curate.sh"; then
        echo "  cron: hourly curator already installed"
    else
        ( crontab -l 2>/dev/null; echo "$CRON_LINE" ) | crontab -
        echo "  cron: installed hourly curator"
    fi
else
    echo "  To run the curator hourly, add this crontab line (or re-run install with --with-cron):"
    echo "    $CRON_LINE"
fi
echo ""

# 7. Contract helpers (breaking-change detection)
echo "7/9  Contract helpers"
CONTRACT_DEST="$TARGET/.specship/contract"
run "mkdir -p '$CONTRACT_DEST'"
safe_copy "$DIST/contract/breaking-change-check.sh" "$CONTRACT_DEST/breaking-change-check.sh"
safe_copy "$DIST/contract/breaking-change-fallback.py" "$CONTRACT_DEST/breaking-change-fallback.py"
run "chmod +x '$CONTRACT_DEST/breaking-change-check.sh' '$CONTRACT_DEST/breaking-change-fallback.py'"
# Detect whether oasdiff is on PATH and surface the recommendation
if command -v oasdiff >/dev/null 2>&1; then
    echo "  ✓ oasdiff found on PATH — /contract will use it for breaking-change detection"
else
    echo "  ℹ oasdiff NOT found on PATH. /contract will use the built-in fallback detector."
    echo "    For full OpenAPI 3.x breaking-change coverage, install oasdiff:"
    echo "      go install github.com/oasdiff/oasdiff@latest"
fi
echo ""

# 8. Coverage helper
echo "8/9  Coverage helper"
COVERAGE_DEST="$TARGET/.specship/coverage"
run "mkdir -p '$COVERAGE_DEST'"
safe_copy "$DIST/coverage/coverage-check.py" "$COVERAGE_DEST/coverage-check.py"
run "chmod +x '$COVERAGE_DEST/coverage-check.py'"
# Detect whether CLAUDE.md declares a Coverage policy and surface guidance
if [[ -f "$TARGET/CLAUDE.md" ]] && grep -q "^##[[:space:]]\+Coverage policy" "$TARGET/CLAUDE.md" 2>/dev/null; then
    echo "  ✓ CLAUDE.md declares a Coverage policy. /work post-flight will measure."
else
    echo "  ℹ No Coverage policy in CLAUDE.md. Coverage gating is disabled."
    echo "    Add a '## Coverage policy' section to enable. See CLAUDE.md.template"
    echo "    for the expected format."
fi
echo ""

# 9. Skills (user-scoped)
if [[ $SKIP_SKILL -eq 1 ]]; then
    echo "9/9  Skills (skipped via --skip-skill)"
else
    echo "9/9  Skills (user-scoped)"

    # claude-md-architect
    SKILL_DEST="$HOME/.claude/skills/claude-md-architect"
    echo "  claude-md-architect → $SKILL_DEST"
    run "mkdir -p '$SKILL_DEST/references'"
    safe_copy "$DIST/skill/claude-md-architect/SKILL.md" "$SKILL_DEST/SKILL.md"
    for ref in template nested-template conversion-rules examples hierarchy-examples; do
        safe_copy "$DIST/skill/claude-md-architect/references/${ref}.md" "$SKILL_DEST/references/${ref}.md"
    done

    # spec-reverse-engineer
    RE_SKILL_DEST="$HOME/.claude/skills/spec-reverse-engineer"
    echo "  spec-reverse-engineer → $RE_SKILL_DEST"
    run "mkdir -p '$RE_SKILL_DEST/references'"
    safe_copy "$DIST/skill/spec-reverse-engineer/SKILL.md" "$RE_SKILL_DEST/SKILL.md"
    for ref in from-code from-docs examples; do
        safe_copy "$DIST/skill/spec-reverse-engineer/references/${ref}.md" "$RE_SKILL_DEST/references/${ref}.md"
    done
fi
echo ""

# ---- Done ----

cat <<EOF
Done.

Next steps:
  1. Open $TARGET/CLAUDE.md and fill in the placeholders (Project type,
     Backend language, Frontend language, Contract pair name, invariants).
  2. In Claude Code, run /spec on your next ticket to start the workflow.
  3. Read $REPO_ROOT/README.md for the full daily loop.

If anything looks wrong, re-run with --dry-run to see what would happen
without making changes.
EOF

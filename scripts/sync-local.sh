#!/usr/bin/env bash
#
# sync-local.sh — sync dist/ → .claude/ for self-hosting development
#
# This repo eats its own dog food: the commands and skill defined in
# dist/ are also used to develop this repo itself. .claude/ is the
# generated local copy that Claude Code picks up when you open this repo.
#
# Workflow:
#   1. Edit files under dist/ (the source of truth)
#   2. Run ./scripts/sync-local.sh
#   3. .claude/ is regenerated to match dist/
#   4. Commit dist/ AND .claude/ together
#
# CI checks that the two are in sync via scripts/verify-sync.sh.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$REPO_ROOT/dist"
LOCAL="$REPO_ROOT/.claude"

if [[ ! -d "$DIST" ]]; then
    echo "Missing dist/ — run from a clone of specship" >&2
    exit 1
fi

echo "Syncing $DIST → $LOCAL"

# Wipe and regenerate .claude/commands and .claude/skills
rm -rf "$LOCAL/commands" "$LOCAL/skills" "$LOCAL/ledger" "$LOCAL/contract" \
       "$LOCAL/coverage" "$LOCAL/transcripts" "$LOCAL/hooks" "$LOCAL/retrospective"
mkdir -p "$LOCAL/commands"
mkdir -p "$LOCAL/skills/claude-md-architect/references"
mkdir -p "$LOCAL/skills/spec-reverse-engineer/references"

# Commands (excluding the auxiliary README and test-fixtures — those
# are bundle documentation, not slash commands)
for cmd in spec contract work check fix investigate ship encode-lesson review-decisions capture-lessons review-lessons; do
    cp "$DIST/commands/${cmd}.md" "$LOCAL/commands/${cmd}.md"
done

# Ledger files — synced for repo-internal use; the target-repo install path
# puts them under .specship/ledger/ instead
mkdir -p "$LOCAL/ledger"
cp "$DIST/ledger/specship_ledger.py" "$LOCAL/ledger/specship_ledger.py"
cp "$DIST/ledger/ledger.sh" "$LOCAL/ledger/ledger.sh"
cp "$DIST/ledger/HOW-TO-LOG.md" "$LOCAL/ledger/HOW-TO-LOG.md"
chmod +x "$LOCAL/ledger/specship_ledger.py" "$LOCAL/ledger/ledger.sh"

# Contract helpers
mkdir -p "$LOCAL/contract"
cp "$DIST/contract/breaking-change-check.sh" "$LOCAL/contract/breaking-change-check.sh"
cp "$DIST/contract/breaking-change-fallback.py" "$LOCAL/contract/breaking-change-fallback.py"
chmod +x "$LOCAL/contract/breaking-change-check.sh" "$LOCAL/contract/breaking-change-fallback.py"

# Coverage helper
mkdir -p "$LOCAL/coverage"
cp "$DIST/coverage/coverage-check.py" "$LOCAL/coverage/coverage-check.py"
chmod +x "$LOCAL/coverage/coverage-check.py"

# Transcripts reader (shared by SessionEnd token hook + future retrospective)
mkdir -p "$LOCAL/transcripts"
cp "$DIST/transcripts/reader.py" "$LOCAL/transcripts/reader.py"

# SessionEnd token hook script
mkdir -p "$LOCAL/hooks"
cp "$DIST/hooks/session-end-tokens.py" "$LOCAL/hooks/session-end-tokens.py"
chmod +x "$LOCAL/hooks/session-end-tokens.py"

# Retrospective generator (CLI + prompt + selftest + docs)
mkdir -p "$LOCAL/retrospective"
for f in generate.py prompt.md HOW-IT-WORKS.md selftest.py; do
    cp "$DIST/retrospective/$f" "$LOCAL/retrospective/$f"
done
chmod +x "$LOCAL/retrospective/generate.py"

# Lessons helpers — curate pipeline and query library
mkdir -p "$LOCAL/lessons"
cp "$DIST/lessons/lessons_query.py"   "$LOCAL/lessons/lessons_query.py"
cp "$DIST/lessons/curate.py"          "$LOCAL/lessons/curate.py"
cp "$DIST/lessons/curate.sh"          "$LOCAL/lessons/curate.sh"
cp "$DIST/lessons/selftest.py"        "$LOCAL/lessons/selftest.py"
cp "$DIST/lessons/HOW-IT-WORKS.md"   "$LOCAL/lessons/HOW-IT-WORKS.md"
chmod +x "$LOCAL/lessons/curate.sh" "$LOCAL/lessons/curate.py"

# Skill: claude-md-architect
cp "$DIST/skill/claude-md-architect/SKILL.md" "$LOCAL/skills/claude-md-architect/SKILL.md"
for ref in template nested-template conversion-rules examples hierarchy-examples; do
    cp "$DIST/skill/claude-md-architect/references/${ref}.md" \
       "$LOCAL/skills/claude-md-architect/references/${ref}.md"
done

# Skill: spec-reverse-engineer
cp "$DIST/skill/spec-reverse-engineer/SKILL.md" "$LOCAL/skills/spec-reverse-engineer/SKILL.md"
for ref in from-code from-docs examples; do
    cp "$DIST/skill/spec-reverse-engineer/references/${ref}.md" \
       "$LOCAL/skills/spec-reverse-engineer/references/${ref}.md"
done

echo "Done. .claude/ is now in sync with dist/."
echo "Remember to commit both."

#!/usr/bin/env bash
#
# verify-sync.sh — verify that .claude/ is in sync with dist/
#
# Used in CI to prevent the local .claude/ copy from drifting out of
# sync with dist/ (the source of truth). Exits non-zero if they differ.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIST="$REPO_ROOT/dist"
LOCAL="$REPO_ROOT/.claude"

drift=0

check() {
    local source="$1" dest="$2" label="$3"
    if [[ ! -f "$source" ]]; then
        echo "MISSING in dist: $source" >&2
        drift=1
        return
    fi
    if [[ ! -f "$dest" ]]; then
        echo "MISSING in .claude: $dest (expected to match $source)" >&2
        drift=1
        return
    fi
    if ! cmp -s "$source" "$dest"; then
        echo "DRIFT: $label" >&2
        echo "  dist:   $source" >&2
        echo "  .claude: $dest" >&2
        drift=1
    fi
}

for cmd in spec contract work check fix investigate ship encode-lesson review-decisions capture-lessons review-lessons; do
    check "$DIST/commands/${cmd}.md" "$LOCAL/commands/${cmd}.md" "command: ${cmd}"
done

# Ledger
check "$DIST/ledger/specship_ledger.py" "$LOCAL/ledger/specship_ledger.py" \
      "ledger: specship_ledger.py"
check "$DIST/ledger/ledger.sh" "$LOCAL/ledger/ledger.sh" \
      "ledger: ledger.sh"
check "$DIST/ledger/HOW-TO-LOG.md" "$LOCAL/ledger/HOW-TO-LOG.md" \
      "ledger: HOW-TO-LOG.md"

# Contract helpers
check "$DIST/contract/breaking-change-check.sh" "$LOCAL/contract/breaking-change-check.sh" \
      "contract: breaking-change-check.sh"
check "$DIST/contract/breaking-change-fallback.py" "$LOCAL/contract/breaking-change-fallback.py" \
      "contract: breaking-change-fallback.py"

# Coverage helper
check "$DIST/coverage/coverage-check.py" "$LOCAL/coverage/coverage-check.py" \
      "coverage: coverage-check.py"

# Transcripts reader
check "$DIST/transcripts/reader.py" "$LOCAL/transcripts/reader.py" \
      "transcripts: reader.py"

# SessionEnd token hook
check "$DIST/hooks/session-end-tokens.py" "$LOCAL/hooks/session-end-tokens.py" \
      "hooks: session-end-tokens.py"

# Retrospective generator
for f in generate.py prompt.md HOW-IT-WORKS.md selftest.py; do
    check "$DIST/retrospective/$f" "$LOCAL/retrospective/$f" \
          "retrospective: $f"
done

# Lessons helpers
check "$DIST/lessons/lessons_query.py" "$LOCAL/lessons/lessons_query.py" \
      "lessons: lessons_query.py"
check "$DIST/lessons/curate.py"        "$LOCAL/lessons/curate.py" \
      "lessons: curate.py"
check "$DIST/lessons/curate.sh"        "$LOCAL/lessons/curate.sh" \
      "lessons: curate.sh"
check "$DIST/lessons/selftest.py"      "$LOCAL/lessons/selftest.py" \
      "lessons: selftest.py"
check "$DIST/lessons/HOW-IT-WORKS.md" "$LOCAL/lessons/HOW-IT-WORKS.md" \
      "lessons: HOW-IT-WORKS.md"

check "$DIST/skill/claude-md-architect/SKILL.md" \
      "$LOCAL/skills/claude-md-architect/SKILL.md" \
      "skill: claude-md-architect SKILL.md"

for ref in template nested-template conversion-rules examples hierarchy-examples; do
    check "$DIST/skill/claude-md-architect/references/${ref}.md" \
          "$LOCAL/skills/claude-md-architect/references/${ref}.md" \
          "skill reference: claude-md-architect/${ref}"
done

check "$DIST/skill/spec-reverse-engineer/SKILL.md" \
      "$LOCAL/skills/spec-reverse-engineer/SKILL.md" \
      "skill: spec-reverse-engineer SKILL.md"

for ref in from-code from-docs examples; do
    check "$DIST/skill/spec-reverse-engineer/references/${ref}.md" \
          "$LOCAL/skills/spec-reverse-engineer/references/${ref}.md" \
          "skill reference: spec-reverse-engineer/${ref}"
done

if [[ $drift -ne 0 ]]; then
    cat >&2 <<EOF

.claude/ has drifted from dist/. To fix:
  ./scripts/sync-local.sh
  git add .claude
  git commit -m "sync .claude with dist"

EOF
    exit 1
fi

echo ".claude/ is in sync with dist/."

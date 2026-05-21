#!/usr/bin/env bash
# provision.sh — create an isolated target repo with specship installed.
# Usage: TARGET=$(provision_repo); echo "$TARGET"
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

provision_repo() {
  local target; target="$(mktemp -d)"
  cp -R "$E2E_DIR/fixtures/app-skeleton/." "$target/"
  ( cd "$target"
    git init -q
    git config user.email harness@specship.test
    git config user.name "specship harness"
  )
  # Full-stack CLAUDE.md with an active Coverage policy so the gate is live.
  cat > "$target/CLAUDE.md" <<'EOF'
# Project Constitution

## What this codebase is
A demo full-stack service used by the specship e2e harness.

**Project type:** full-stack
**Backend language:** python
**Frontend language:** javascript
**Contract pair name:** web-client / demo-service

## Non-negotiable invariants
- All API responses are JSON objects.

## Conventions worth following
- Keep handlers small.

## How to verify work is done
- `python3 -m pytest tests/ -q` passes

## Coverage policy
- Metric: line
- Threshold: 0
- Project floor: 0
- Tool: pytest
- Report path: coverage.json
- Excluded paths: _generated/**, tests/**
- Bypass policy: --no-verify logged

## Where things live
- `src/` — backend
- `web/` — frontend

## Domain glossary
- demo-service — the backend in this repo
EOF
  ( cd "$target" && git add -A && git commit -qm "seed: app skeleton + constitution" )
  # Install specship from this repo (project-scoped commands, with hook).
  # --skip-skill: avoid writing user-scoped ~/.claude/skills/ from the harness.
  "$REPO_ROOT/scripts/install.sh" "$target" --skip-skill >/dev/null
  echo "$target"
}

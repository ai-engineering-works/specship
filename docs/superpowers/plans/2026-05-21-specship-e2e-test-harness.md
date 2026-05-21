# specship Live E2E Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live end-to-end test harness that drives complete specship workflows through real `claude -p` calls across four use-case tiers and verifies the resulting state on the SQLite ledger and a headless-rendered dashboard.

**Architecture:** Bash orchestration + Python assertions + one Playwright `.mjs`. Each tier runs in an isolated throwaway git repo with specship installed via `scripts/install.sh`. Human-in-loop gates are satisfied by the harness logging the real `plan_approved` ledger event (the `--from-plan` safety contract). Deterministic library pieces (provision, approve, assert, dashboard) are TDD'd with self-tests; the live tiers are validated with `bash -n` + a dry-run mode, with the real Claude run being the integration test itself.

**Tech Stack:** bash 4+, Python 3 (stdlib `sqlite3`), Node + Playwright (optional), the specship `claude` CLI.

---

## File Structure

```
tests/e2e/
  run.sh                 # orchestrator: prereqs, tier selection, report, cleanup
  lib/
    common.sh            # shared env, paths, logging, run-bundle helpers
    provision.sh         # fresh temp git repo + app skeleton + CLAUDE.md + install
    claude_cmd.sh        # `claude -p` wrapper (model, permission, timeout, dry-run, capture)
    approve.sh           # scripted human: log plan_approved / review verdicts via ledger CLI
    assert.py            # rebuild-index + sqlite3 asserts; exit-code/file helpers
    dashboard_check.mjs  # Playwright: load dashboard.html, assert rendered figures
  fixtures/
    t1_ticket.md t2_ticket.md t3_ticket.md
    app-skeleton/        # minimal backend src/ + frontend web/
    selftest-events.jsonl  # known ledger for assert.py + dashboard self-tests
  tiers/
    t1_simple.sh t2_contract.sh t3_full.sh t4_negative.sh
  selftest/
    test_provision.sh test_approve.sh test_assert.sh test_dashboard.sh
  runs/                  # (gitignored) saved debug bundles per run
  package.json           # playwright devDep, local to tests/e2e
  README.md
```

`tests/e2e/` is repo-internal; it is NOT under `dist/` and is NOT referenced by `scripts/verify-sync.sh`, so it does not affect the sync invariant.

---

## Task 1: Scaffolding and prerequisite gate

**Files:**
- Create: `tests/e2e/lib/common.sh`
- Create: `tests/e2e/run.sh`
- Create: `tests/e2e/.gitignore`
- Create: `tests/e2e/README.md`

- [ ] **Step 1: Create `tests/e2e/.gitignore`**

```gitignore
runs/
node_modules/
```

- [ ] **Step 2: Create `tests/e2e/lib/common.sh`**

```bash
#!/usr/bin/env bash
# common.sh — shared env, paths, and helpers for the e2e harness.
# Source this from every harness script: . "$(dirname "$0")/../lib/common.sh"
set -euo pipefail

# Repo root = three levels up from lib/ (tests/e2e/lib -> repo root).
E2E_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
E2E_DIR="$(cd "$E2E_LIB_DIR/.." && pwd)"
REPO_ROOT="$(cd "$E2E_DIR/../.." && pwd)"

# Tunables (env-overridable).
SPECSHIP_E2E_MODEL="${SPECSHIP_E2E_MODEL:-sonnet}"
SPECSHIP_E2E_TIMEOUT="${SPECSHIP_E2E_TIMEOUT:-600}"
SPECSHIP_E2E_DRYRUN="${SPECSHIP_E2E_DRYRUN:-0}"

# Per-run bundle for transcripts/artifacts. Set by run.sh; default to a temp dir.
RUN_BUNDLE="${RUN_BUNDLE:-$(mktemp -d)}"

log()  { printf '  %s\n' "$*" >&2; }
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*" >&2; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*" >&2; }
hdr()  { printf '\n=== %s ===\n' "$*" >&2; }

# Path to the installed ledger CLI inside a target repo.
ledger_cli() { echo "$1/.specship/ledger/specship_ledger.py"; }
```

- [ ] **Step 3: Create `tests/e2e/run.sh`** (orchestrator skeleton; tiers wired in Task 11)

```bash
#!/usr/bin/env bash
# run.sh — specship live e2e harness entry point.
#   ./run.sh [--tier t1,t3] [--model opus] [--keep] [--no-dashboard]
. "$(dirname "$0")/lib/common.sh"

TIERS="t1,t2,t3,t4"; KEEP=0; NO_DASH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) TIERS="$2"; shift 2;;
    --model) export SPECSHIP_E2E_MODEL="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    --no-dashboard) NO_DASH=1; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
export NO_DASH KEEP

hdr "Prerequisites"
command -v claude  >/dev/null 2>&1 || { fail "claude CLI not on PATH (required)"; exit 1; }
command -v python3 >/dev/null 2>&1 || { fail "python3 not on PATH (required)"; exit 1; }
if [[ $NO_DASH -eq 0 ]] && ! (cd "$E2E_DIR" && npx --no-install playwright --version) >/dev/null 2>&1; then
  log "Playwright not installed; dashboard checks will be skipped. (npm i in tests/e2e to enable)"
  export NO_DASH=1
fi
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
```

- [ ] **Step 4: Create `tests/e2e/README.md`**

```markdown
# specship live e2e harness

Runs real specship workflows through `claude -p` and verifies the SQLite ledger
and the rendered dashboard. Slow and token-costing — run manually or nightly.

## Usage
    ./run.sh [--tier t1,t3] [--model opus] [--keep] [--no-dashboard]

## Prerequisites
- `claude` CLI on PATH (required)
- `python3` (required)
- Node + Playwright (optional, for dashboard checks): `cd tests/e2e && npm i`

Design: docs/superpowers/specs/2026-05-21-specship-e2e-test-harness-design.md
```

- [ ] **Step 5: Make scripts executable and syntax-check**

Run: `chmod +x tests/e2e/run.sh && bash -n tests/e2e/run.sh tests/e2e/lib/common.sh`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/.gitignore tests/e2e/lib/common.sh tests/e2e/run.sh tests/e2e/README.md
git commit -m "test(e2e): scaffold harness orchestrator and common lib"
```

---

## Task 2: `provision.sh` — isolated target repo

**Files:**
- Create: `tests/e2e/lib/provision.sh`
- Create: `tests/e2e/fixtures/app-skeleton/src/app.py`
- Create: `tests/e2e/fixtures/app-skeleton/web/app.js`
- Test: `tests/e2e/selftest/test_provision.sh`

- [ ] **Step 1: Create the app skeleton fixtures**

`tests/e2e/fixtures/app-skeleton/src/app.py`:
```python
"""Minimal backend the harness lets Claude extend."""


def health() -> dict:
    return {"status": "ok"}
```

`tests/e2e/fixtures/app-skeleton/web/app.js`:
```javascript
// Minimal frontend the harness lets Claude extend.
export function health() {
  return { status: "ok" };
}
```

- [ ] **Step 2: Create `tests/e2e/lib/provision.sh`**

```bash
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
  "$REPO_ROOT/scripts/install.sh" "$target" >/dev/null
  echo "$target"
}
```

- [ ] **Step 3: Write the failing self-test `tests/e2e/selftest/test_provision.sh`**

```bash
#!/usr/bin/env bash
. "$(dirname "$0")/../lib/provision.sh"
fails=0
T="$(provision_repo)"
trap 'rm -rf "$T"' EXIT

check() { if eval "$2"; then ok "$1"; else fail "$1"; fails=$((fails+1)); fi; }
check ".specship/ledger exists"     "[[ -f '$T/.specship/ledger/specship_ledger.py' ]]"
check "pre-commit hook installed"   "[[ -x '$T/.git/hooks/pre-commit' ]]"
check "qa-check helper installed"   "[[ -f '$T/.specship/hooks/qa-check.py' ]]"
check "CLAUDE.md full-stack"        "grep -q 'Project type:.*full-stack' '$T/CLAUDE.md'"
check "commands installed"          "[[ -f '$T/.claude/commands/spec.md' ]]"
check "dashboard installed"         "[[ -f '$T/.specship/dashboard/dashboard.html' ]]"
[[ $fails -eq 0 ]]
```

- [ ] **Step 4: Run the self-test**

Run: `chmod +x tests/e2e/selftest/test_provision.sh && tests/e2e/selftest/test_provision.sh`
Expected: six `PASS` lines, exit 0. (If `install.sh` lacks `.specship/hooks/qa-check.py`, that feature task must land first — it is already committed on this branch.)

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/lib/provision.sh tests/e2e/fixtures/app-skeleton tests/e2e/selftest/test_provision.sh
git commit -m "test(e2e): provision isolated target repo with specship installed"
```

---

## Task 3: `assert.py` — SQLite + filesystem assertions

**Files:**
- Create: `tests/e2e/lib/assert.py`
- Create: `tests/e2e/fixtures/selftest-events.jsonl`
- Test: `tests/e2e/selftest/test_assert.sh`

- [ ] **Step 1: Create `tests/e2e/fixtures/selftest-events.jsonl`** (known events for testing the asserter)

```jsonl
{"event_type":"session_start","ts":"2026-05-21T00:00:00Z","session_id":"s1","command":"spec"}
{"event_type":"session_end","ts":"2026-05-21T00:01:00Z","session_id":"s1","command":"spec","outcome":"success"}
{"event_type":"gate_passed","ts":"2026-05-21T00:02:00Z","source":"pre-commit"}
{"event_type":"gate_blocked","ts":"2026-05-21T00:03:00Z","source":"pre-commit","reason":"no-linkage"}
```

- [ ] **Step 2: Create `tests/e2e/lib/assert.py`**

```python
#!/usr/bin/env python3
"""assert.py — verification helpers for the e2e harness.

Subcommands operate on a TARGET repo's ledger. `count` rebuilds the SQLite
index first, then runs a COUNT(*) and compares with an operator. Exit 0 on
pass, 1 on fail (with a diff message on stderr).

    assert.py count <target> <table> --where "<sql>" --op ge --n 1
    assert.py event <target> <event_type> --op ge --n 1
    assert.py rebuild <target>
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

OPS = {
    "eq": lambda a, b: a == b,
    "ge": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "le": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
}


def ledger(target: str) -> Path:
    return Path(target) / ".specship" / "ledger" / "specship_ledger.py"


def rebuild(target: str) -> None:
    subprocess.run(
        ["python3", str(ledger(target)), "rebuild-index"],
        check=True, capture_output=True, text=True,
    )


def db(target: str) -> sqlite3.Connection:
    return sqlite3.connect(Path(target) / ".specship" / "ledger" / "index.db")


def do_count(target: str, table: str, where: str, op: str, n: int) -> int:
    rebuild(target)
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    with db(target) as conn:
        actual = conn.execute(sql).fetchone()[0]
    if OPS[op](actual, n):
        print(f"PASS {table}: {actual} {op} {n}  ({where or 'all'})")
        return 0
    print(f"FAIL {table}: got {actual}, expected {op} {n}  ({where or 'all'})", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count")
    c.add_argument("target"); c.add_argument("table")
    c.add_argument("--where", default=""); c.add_argument("--op", default="ge", choices=OPS)
    c.add_argument("--n", type=int, default=1)
    e = sub.add_parser("event")
    e.add_argument("target"); e.add_argument("event_type")
    e.add_argument("--op", default="ge", choices=OPS); e.add_argument("--n", type=int, default=1)
    r = sub.add_parser("rebuild"); r.add_argument("target")
    a = p.parse_args()

    if a.cmd == "rebuild":
        rebuild(a.target); return 0
    if a.cmd == "count":
        return do_count(a.target, a.table, a.where, a.op, a.n)
    if a.cmd == "event":
        where = f"event_type = '{a.event_type}'"
        return do_count(a.target, "events", where, a.op, a.n)
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write the failing self-test `tests/e2e/selftest/test_assert.sh`**

```bash
#!/usr/bin/env bash
. "$(dirname "$0")/../lib/common.sh"
fails=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.specship/ledger"
cp "$REPO_ROOT/dist/ledger/specship_ledger.py" "$T/.specship/ledger/"
cp "$E2E_DIR/fixtures/selftest-events.jsonl" "$T/.specship/ledger/events.jsonl"

run() { python3 "$E2E_DIR/lib/assert.py" "$@"; }
check() { if eval "$1"; then ok "$2"; else fail "$2"; fails=$((fails+1)); fi; }
check "run event '$T' session_start --op eq --n 1"   "session_start counted"
check "run event '$T' gate_passed --op eq --n 1"     "gate_passed counted"
check "run count '$T' sessions --op ge --n 1"        "sessions projected"
check "! run event '$T' gate_passed --op eq --n 5"   "wrong count fails (negative)"
[[ $fails -eq 0 ]]
```

- [ ] **Step 4: Run the self-test**

Run: `chmod +x tests/e2e/selftest/test_assert.sh && tests/e2e/selftest/test_assert.sh`
Expected: four `PASS` lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/lib/assert.py tests/e2e/fixtures/selftest-events.jsonl tests/e2e/selftest/test_assert.sh
git commit -m "test(e2e): sqlite/event assertion helper with self-test"
```

---

## Task 4: `approve.sh` — scripted human approval

**Files:**
- Create: `tests/e2e/lib/approve.sh`
- Test: `tests/e2e/selftest/test_approve.sh`

- [ ] **Step 1: Create `tests/e2e/lib/approve.sh`**

```bash
#!/usr/bin/env bash
# approve.sh — act as the human reviewer by logging the real approval events.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Approve the most recent un-reviewed plan in TARGET's ledger.
# This satisfies the `/work --from-plan` safety check, which refuses to execute
# a plan that lacks a matching plan_approved event.
approve_latest_plan() {
  local target="$1" cli; cli="$(ledger_cli "$target")"
  python3 "$cli" rebuild-index >/dev/null 2>&1 || true
  local plan_id
  plan_id="$(python3 - "$target" <<'PY'
import sqlite3, sys
from pathlib import Path
db = Path(sys.argv[1]) / ".specship" / "ledger" / "index.db"
con = sqlite3.connect(db)
row = con.execute(
    "SELECT plan_id FROM plans WHERE verdict IS NULL ORDER BY drafted_at DESC LIMIT 1"
).fetchone()
print(row[0] if row else "")
PY
)"
  if [[ -z "$plan_id" ]]; then
    log "approve_latest_plan: no un-reviewed plan found in $target"
    return 1
  fi
  python3 "$cli" log plan_approved \
    plan_id="\"$plan_id\"" \
    verdict='"approved"' \
    reviewer_note='"approved by e2e harness"' \
    reviewed_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    --quiet
  log "approved plan $plan_id"
  echo "$plan_id"
}

# Generic verdict logger for /review-decisions style flows.
review_decision() {
  local target="$1" artifact="$2" verdict="$3" cli; cli="$(ledger_cli "$target")"
  python3 "$cli" log decision_reviewed \
    artifact="\"$artifact\"" review_verdict="\"$verdict\"" \
    reviewed_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" --quiet
}
```

- [ ] **Step 2: Write the failing self-test `tests/e2e/selftest/test_approve.sh`**

```bash
#!/usr/bin/env bash
. "$(dirname "$0")/../lib/approve.sh"
fails=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.specship/ledger"
cli="$T/.specship/ledger/specship_ledger.py"
cp "$REPO_ROOT/dist/ledger/specship_ledger.py" "$cli"
# Seed a drafted (un-reviewed) plan.
python3 "$cli" log plan_drafted plan_id='"pln-123"' \
  drafted_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" scope='"backend"' --quiet

PID="$(approve_latest_plan "$T")"
python3 "$cli" rebuild-index >/dev/null
got_verdict="$(python3 "$cli" query "SELECT verdict FROM plans WHERE plan_id='pln-123'" | tail -1 | tr -d ' ')"
approved_events="$(python3 "$E2E_DIR/lib/assert.py" event "$T" plan_approved --op eq --n 1 && echo y)"

[[ "$PID" == "pln-123" ]] && ok "returned plan id" || { fail "plan id"; fails=$((fails+1)); }
[[ "$got_verdict" == "approved" ]] && ok "verdict projected approved" || { fail "verdict=$got_verdict"; fails=$((fails+1)); }
[[ "$approved_events" == "y" ]] && ok "plan_approved event present" || { fail "no plan_approved"; fails=$((fails+1)); }
[[ $fails -eq 0 ]]
```

- [ ] **Step 3: Run the self-test**

Run: `chmod +x tests/e2e/selftest/test_approve.sh && tests/e2e/selftest/test_approve.sh`
Expected: three `PASS` lines, exit 0.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/lib/approve.sh tests/e2e/selftest/test_approve.sh
git commit -m "test(e2e): scripted plan approval via real ledger contract"
```

---

## Task 5: `claude_cmd.sh` — the `claude -p` wrapper

**Files:**
- Create: `tests/e2e/lib/claude_cmd.sh`

- [ ] **Step 1: Create `tests/e2e/lib/claude_cmd.sh`**

```bash
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
```

- [ ] **Step 2: Dry-run smoke (no tokens)**

Run:
```bash
bash -n tests/e2e/lib/claude_cmd.sh
SPECSHIP_E2E_DRYRUN=1 RUN_BUNDLE=$(mktemp -d) bash -c '
  . tests/e2e/lib/claude_cmd.sh
  claude_run /tmp spec-smoke "/spec DEMO-1 add a thing"'
```
Expected: prints `DRYRUN [spec-smoke] model=sonnet` and the prompt; exit 0.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/lib/claude_cmd.sh
git commit -m "test(e2e): claude -p wrapper with dry-run and capture"
```

---

## Task 6: `dashboard_check.mjs` — Playwright render assertion

**Files:**
- Create: `tests/e2e/package.json`
- Create: `tests/e2e/lib/dashboard_check.mjs`
- Test: `tests/e2e/selftest/test_dashboard.sh`

- [ ] **Step 1: Create `tests/e2e/package.json`**

```json
{
  "name": "specship-e2e",
  "private": true,
  "type": "module",
  "devDependencies": {
    "playwright": "^1.48.0"
  }
}
```

- [ ] **Step 2: Create `tests/e2e/lib/dashboard_check.mjs`**

The dashboard fetches `events.jsonl` and renders figures client-side. This
script serves a target repo, loads `.specship/dashboard/dashboard.html`, waits
for the page to finish loading the ledger, and asserts that a CSS-selected text
node contains the expected value. Selectors/expected values are passed as
`SELECTOR=EXPECTED` pairs so each tier supplies its own.

```javascript
// Usage: node dashboard_check.mjs <targetRepo> "<sel>=<expected>" ["<sel>=<expected>" ...]
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const [target, ...pairs] = process.argv.slice(2);
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".jsonl": "application/json", ".json": "application/json", ".css": "text/css", ".md": "text/markdown" };

const server = createServer(async (req, res) => {
  try {
    const p = normalize(join(target, decodeURIComponent(req.url.split("?")[0])));
    if (!p.startsWith(target)) { res.writeHead(403).end(); return; }
    await stat(p);
    res.writeHead(200, { "content-type": TYPES[extname(p)] || "application/octet-stream" });
    res.end(await readFile(p));
  } catch { res.writeHead(404).end(); }
});

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;
const url = `http://127.0.0.1:${port}/.specship/dashboard/dashboard.html`;

const browser = await chromium.launch();
const page = await browser.newPage();
let failures = 0;
try {
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForTimeout(500); // let the ledger fetch + render settle
  for (const pair of pairs) {
    const idx = pair.lastIndexOf("=");
    const sel = pair.slice(0, idx);
    const expected = pair.slice(idx + 1);
    const text = (await page.locator(sel).first().innerText().catch(() => "")).trim();
    if (text.includes(expected)) {
      console.log(`PASS dashboard ${sel} contains "${expected}"`);
    } else {
      console.error(`FAIL dashboard ${sel}: got "${text}", expected to contain "${expected}"`);
      failures++;
    }
  }
} finally {
  await browser.close();
  server.close();
}
process.exit(failures === 0 ? 0 : 1);
```

- [ ] **Step 3: Install Playwright (one-time)**

Run: `cd tests/e2e && npm install && npx playwright install chromium`
Expected: dependencies installed; chromium downloaded.

- [ ] **Step 4: Write the self-test `tests/e2e/selftest/test_dashboard.sh`** (real dashboard, known events)

```bash
#!/usr/bin/env bash
. "$(dirname "$0")/../lib/common.sh"
if ! (cd "$E2E_DIR" && npx --no-install playwright --version) >/dev/null 2>&1; then
  log "Playwright not installed — skipping dashboard self-test"; exit 0
fi
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.specship/ledger" "$T/.specship/dashboard"
cp "$REPO_ROOT/dist/dashboard/dashboard.html" "$T/.specship/dashboard/"
cp "$E2E_DIR/fixtures/selftest-events.jsonl" "$T/.specship/ledger/events.jsonl"
# The dashboard renders a body; assert the page title/header text is present.
# Replace BODY_SELECTOR/EXPECTED below after inspecting dashboard.html headings
# (Step 5 records the exact selector for the known fixture).
node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "body=specship"
```

- [ ] **Step 5: Calibrate the selector against the real dashboard, then run**

Run: `grep -nE "<title>|<h1|id=\"" dist/dashboard/dashboard.html | head`
Pick a stable selector + a literal string the dashboard always renders (e.g. the
`<h1>`/title text). Update the assertion in Step 4's last line to
`"<selector>=<literal>"`. Then run:
`chmod +x tests/e2e/selftest/test_dashboard.sh && tests/e2e/selftest/test_dashboard.sh`
Expected: one `PASS dashboard ...` line, exit 0 (or a skip line if Playwright absent).

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/package.json tests/e2e/lib/dashboard_check.mjs tests/e2e/selftest/test_dashboard.sh
git commit -m "test(e2e): playwright dashboard render assertion with self-test"
```

---

## Task 7: Ticket fixtures

**Files:**
- Create: `tests/e2e/fixtures/t1_ticket.md`
- Create: `tests/e2e/fixtures/t2_ticket.md`
- Create: `tests/e2e/fixtures/t3_ticket.md`

- [ ] **Step 1: Create `tests/e2e/fixtures/t1_ticket.md`** (single-scope backend)

```markdown
# DEMO-1: add a /version endpoint

Backend-only. Add a function `version()` in `src/app.py` that returns
`{"version": "1.0.0"}`. No frontend or API contract changes.
```

- [ ] **Step 2: Create `tests/e2e/fixtures/t2_ticket.md`** (full-stack, steers the contract surface)

```markdown
# DEMO-2: subscribe endpoint (full-stack)

Full-stack change. The backend exposes one HTTP endpoint and the web client
calls it.

Contract surface (be explicit):
- `POST /subscribe`
  - request body: `{ "advisor_id": string, "tier": "bronze"|"silver"|"gold" }`
  - response 201: `{ "subscription_id": string, "tier": string }`
  - response 400 when `tier` is not one of the allowed values

Backend in `src/app.py`, web client call in `web/app.js`.
```

- [ ] **Step 3: Create `tests/e2e/fixtures/t3_ticket.md`** (full-stack + a known bug to find)

```markdown
# DEMO-3: statement export (full-stack) + known defect

Full-stack change. Add `POST /export` that accepts
`{ "from": "YYYY-MM-DD", "to": "YYYY-MM-DD" }` and returns
`200 { "rows": number, "format": "csv" }`. When `from` is after `to`, the
endpoint MUST return `400`.

Known defect to investigate and fix during the workflow: the date-range
validation is inverted, so `from > to` returns `200` instead of `400`.
```

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/fixtures/t1_ticket.md tests/e2e/fixtures/t2_ticket.md tests/e2e/fixtures/t3_ticket.md
git commit -m "test(e2e): ticket fixtures for the four tiers"
```

---

## Task 8: Tier T1 — simple single-scope happy path

**Files:**
- Create: `tests/e2e/tiers/t1_simple.sh`

- [ ] **Step 1: Create `tests/e2e/tiers/t1_simple.sh`**

```bash
#!/usr/bin/env bash
# T1 — single-scope happy path: /spec -> /work (plan-gated) -> /review-decisions -> commit
. "$(dirname "$0")/../lib/provision.sh"
. "$(dirname "$0")/../lib/claude_cmd.sh"
. "$(dirname "$0")/../lib/approve.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"

TICKET="$(cat "$E2E_DIR/fixtures/t1_ticket.md")"
claude_run "$T" 01-spec "/spec DEMO-1 backend-only. $TICKET"
SPEC="$(ls "$T"/specs/*.md 2>/dev/null | head -1)"; [[ -n "$SPEC" ]] || { fail "no spec drafted"; exit 1; }
REL="${SPEC#"$T"/}"

claude_run "$T" 02-work-plan "/work $REL --plan-only --scope backend"
approve_latest_plan "$T" >/dev/null
claude_run "$T" 03-work-exec "/work $REL --from-plan"
claude_run "$T" 04-review "/review-decisions"

# Commit production code with spec linkage (Wall must pass).
( cd "$T" && git add -A && git commit -qm "feat: DEMO-1 version endpoint

§ref:$REL" )

fails=0
python3 "$A" count "$T" sessions --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" decisions --op ge --n 1 || fails=$((fails+1))
python3 "$A" event "$T" gate_passed --op ge --n 1 || fails=$((fails+1))
python3 "$A" event "$T" plan_approved --op eq --n 1 || fails=$((fails+1))

if [[ "${NO_DASH:-0}" -eq 0 ]]; then
  node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "body=specship" || fails=$((fails+1))
fi
cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]
```

- [ ] **Step 2: Validate structure without tokens**

Run: `bash -n tests/e2e/tiers/t1_simple.sh && SPECSHIP_E2E_DRYRUN=1 RUN_BUNDLE=$(mktemp -d) bash tests/e2e/tiers/t1_simple.sh`
Expected: provisioning runs, DRYRUN lines print for each claude_run, the assertions run against an empty ledger and FAIL (expected in dry-run since no real events) — confirming wiring, not outcome. Exit non-zero is acceptable here; the goal is no bash/wiring errors.

- [ ] **Step 3: Live run (consumes tokens)**

Run: `tests/e2e/run.sh --tier t1`
Expected: `PASS tier t1`, assertions green, dashboard `PASS` (if Playwright present).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/tiers/t1_simple.sh
git commit -m "test(e2e): tier T1 single-scope happy path"
```

---

## Task 9: Tier T2 — full-stack with contract

**Files:**
- Create: `tests/e2e/tiers/t2_contract.sh`

- [ ] **Step 1: Create `tests/e2e/tiers/t2_contract.sh`**

```bash
#!/usr/bin/env bash
# T2 — full-stack: /spec -> /contract -> /work backend + frontend -> /check -> commit
. "$(dirname "$0")/../lib/provision.sh"
. "$(dirname "$0")/../lib/claude_cmd.sh"
. "$(dirname "$0")/../lib/approve.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"

TICKET="$(cat "$E2E_DIR/fixtures/t2_ticket.md")"
claude_run "$T" 01-spec "/spec DEMO-2 full-stack. $TICKET"
SPEC="$(ls "$T"/specs/*.md 2>/dev/null | head -1)"; [[ -n "$SPEC" ]] || { fail "no spec"; exit 1; }
REL="${SPEC#"$T"/}"

claude_run "$T" 02-contract "/contract $REL"

for scope in backend frontend; do
  claude_run "$T" "03-work-plan-$scope" "/work $REL --plan-only --scope $scope"
  approve_latest_plan "$T" >/dev/null
  claude_run "$T" "04-work-exec-$scope" "/work $REL --from-plan"
done

claude_run "$T" 05-check "/check $REL"
( cd "$T" && git add -A && git commit -qm "feat: DEMO-2 subscribe

§ref:$REL" )

fails=0
# Contract artifacts generated and hash-stamped.
[[ -d "$T/_generated" ]] && ls "$T"/_generated/* >/dev/null 2>&1 && ok "generated artifacts exist" || { fail "_generated empty"; fails=$((fails+1)); }
python3 "$A" count "$T" sessions --op ge --n 3 || fails=$((fails+1))   # spec, contract, work x2 (>=3 distinct)
python3 "$A" count "$T" coverage --op ge --n 1 || fails=$((fails+1))    # coverage_measured projected
python3 "$A" count "$T" plans "--where" "verdict='approved'" --op ge --n 2 || fails=$((fails+1))
python3 "$A" event "$T" gate_passed --op ge --n 1 || fails=$((fails+1))

if [[ "${NO_DASH:-0}" -eq 0 ]]; then
  node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "body=specship" || fails=$((fails+1))
fi
cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]
```

- [ ] **Step 2: Validate structure without tokens**

Run: `bash -n tests/e2e/tiers/t2_contract.sh`
Expected: no syntax errors.

- [ ] **Step 3: Live run**

Run: `tests/e2e/run.sh --tier t2`
Expected: `PASS tier t2`. If `/contract` does not populate `coverage` (coverage is measured in `/work`), the coverage assertion still passes because both `/work` runs measure it.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/tiers/t2_contract.sh
git commit -m "test(e2e): tier T2 full-stack with contract"
```

---

## Task 10: Tier T3 — /ship orchestration + QA + bug loop

**Files:**
- Create: `tests/e2e/tiers/t3_full.sh`

- [ ] **Step 1: Create `tests/e2e/tiers/t3_full.sh`**

```bash
#!/usr/bin/env bash
# T3 — the full pipeline: /ship -> /qa -> bug -> /investigate -> /fix -> /encode-lesson
#      -> /capture-lessons -> curator -> /review-lessons
. "$(dirname "$0")/../lib/provision.sh"
. "$(dirname "$0")/../lib/claude_cmd.sh"
. "$(dirname "$0")/../lib/approve.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"

TICKET="$(cat "$E2E_DIR/fixtures/t3_ticket.md")"
claude_run "$T" 01-spec "/spec DEMO-3 full-stack. $TICKET"
SPEC="$(ls "$T"/specs/*.md 2>/dev/null | head -1)"; [[ -n "$SPEC" ]] || { fail "no spec"; exit 1; }
REL="${SPEC#"$T"/}"

# /ship runs --plan-only inside its subagents; approve the drafted plans, then
# let /ship continue. We approve every un-reviewed plan after the planning phase.
claude_run "$T" 02-ship-plan "/ship $REL --plan-only"
while approve_latest_plan "$T" >/dev/null 2>&1; do :; done
claude_run "$T" 03-ship-exec "/ship $REL --from-plan"

# QA artifacts for the spec (supply interview answers up front).
claude_run "$T" 04-qa "/qa $REL
Author one scenario and one property artifact. For the scenario, action is HTTP POST /export; expectations: http_status 200 for a valid range, http_status 400 when from > to. Language python, generator pytest. No ui_action. Approve and generate tests."

# Seed the known bug, then investigate -> fix.
claude_run "$T" 05-investigate "/investigate DEMO-3-BUG the /export endpoint returns 200 when 'from' is after 'to'; it must return 400. Find the root cause in src/app.py."
INV="$(ls "$T"/investigations/*.md 2>/dev/null | head -1)"; INVREL="${INV#"$T"/}"
claude_run "$T" 06-fix "/fix DEMO-3-BUG --against $REL --from-investigation $INVREL"
FIX="$(ls "$T"/fixes/*.md 2>/dev/null | head -1)"; FIXREL="${FIX#"$T"/}"
claude_run "$T" 07-work-fix "/work $FIXREL --plan-only --scope backend"
approve_latest_plan "$T" >/dev/null
claude_run "$T" 08-work-fix-exec "/work $FIXREL --from-plan"

# Close the loop and exercise the lessons pipeline.
claude_run "$T" 09-encode "/encode-lesson $INVREL --fix $FIXREL"
claude_run "$T" 10-capture "/capture-lessons"
( cd "$T" && bash .specship/lessons/curate.sh >/dev/null 2>&1 || true )
claude_run "$T" 11-review-lessons "/review-lessons"

fails=0
python3 "$A" count "$T" plans "--where" "verdict='approved'" --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" qa_artifacts --op ge --n 1 || fails=$((fails+1))
python3 "$A" event "$T" qa_tests_generated --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" lessons --op ge --n 1 || fails=$((fails+1))
python3 "$A" count "$T" lesson_candidates --op ge --n 1 || fails=$((fails+1))
ls "$T"/tests/scenario/*.py >/dev/null 2>&1 && ok "generated scenario test exists" || { fail "no generated test"; fails=$((fails+1)); }

if [[ "${NO_DASH:-0}" -eq 0 ]]; then
  node "$E2E_DIR/lib/dashboard_check.mjs" "$T" "body=specship" || fails=$((fails+1))
fi
cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]
```

- [ ] **Step 2: Validate structure without tokens**

Run: `bash -n tests/e2e/tiers/t3_full.sh`
Expected: no syntax errors.

- [ ] **Step 3: Live run**

Run: `tests/e2e/run.sh --tier t3 --keep`
Expected: `PASS tier t3`. Use `--keep` the first time and inspect the kept repo + `runs/.../t3/*.log` to tune the QA/investigate prompts if any step under-produces. Adjust prompt wording (not assertions) until the structural assertions pass reliably.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/tiers/t3_full.sh
git commit -m "test(e2e): tier T3 ship orchestration + QA + bug loop"
```

---

## Task 11: Tier T4 — negative / gate cases

**Files:**
- Create: `tests/e2e/tiers/t4_negative.sh`

This tier is mostly deterministic (no Claude). It provisions a repo and drives
the gates directly with git + the ledger CLI.

- [ ] **Step 1: Create `tests/e2e/tiers/t4_negative.sh`**

```bash
#!/usr/bin/env bash
# T4 — negative/gate cases. Deterministic: exercises the Wall, coverage gate,
# --from-plan refusal contract, and qa-check advisory warning.
. "$(dirname "$0")/../lib/provision.sh"
A="$E2E_DIR/lib/assert.py"

T="$(provision_repo)"
[[ "${KEEP:-0}" -eq 1 ]] || trap 'rm -rf "$T"' EXIT
log "target: $T"
HOOK="$T/.git/hooks/pre-commit"
fails=0

# --- Case 1: Wall blocks a src/ commit with no linkage -------------------------
( cd "$T"
  printf '\ndef feature():\n    return 1\n' >> src/app.py
  git add src/app.py
  if git commit -qm "feat: no linkage" 2>/dev/null; then exit 10; else exit 0; fi )
if [[ $? -eq 0 ]]; then ok "Wall blocked no-linkage commit"; else fail "Wall did not block"; fails=$((fails+1)); fi
( cd "$T" && git reset -q HEAD src/app.py && git checkout -q -- src/app.py )

# --- Case 2: --from-plan refuses without plan_approved (contract sanity) -------
# Seed a drafted-but-unapproved plan; the refusal itself is enforced by /work,
# so here we assert the ledger state the contract depends on: no plan_approved.
cli="$(ledger_cli "$T")"
python3 "$cli" log plan_drafted plan_id='"pln-x"' \
  drafted_at="\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" --quiet
python3 "$A" count "$T" plans "--where" "verdict IS NULL" --op ge --n 1 \
  && ok "un-approved plan present (from-plan would refuse)" || { fail "plan state"; fails=$((fails+1)); }

# --- Case 3: coverage gate blocks on a failing measurement ---------------------
python3 "$cli" log coverage_measured tool='"pytest"' metric='"line"' \
  delta_pct='12.0' threshold_delta='80.0' passed='false' \
  artifact="\"specs/demo.md\"" --quiet
( cd "$T"
  printf '\ndef covered():\n    return 2\n' >> src/app.py
  mkdir -p specs && echo "# demo" > specs/demo.md
  git add src/app.py specs/demo.md
  # Linkage present (spec staged) so only the coverage gate can block.
  if git commit -qm "feat: with spec, failing coverage" 2>/dev/null; then exit 10; else exit 0; fi )
if [[ $? -eq 0 ]]; then ok "coverage gate blocked commit"; else fail "coverage gate did not block"; fails=$((fails+1)); fi
python3 "$A" event "$T" gate_blocked --op ge --n 1 || fails=$((fails+1))
( cd "$T" && git reset -q HEAD . && git checkout -q -- src/app.py 2>/dev/null; rm -f specs/demo.md )

# --- Case 4: qa-check warns on edit to an approved regression (advisory) --------
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
WARN="$( "$T/.specship/hooks/qa-check.py" 2>&1 || true )"
echo "$WARN" | grep -q "approved" && ok "qa-check warned on approved-regression edit" || { fail "no qa-check warning"; fails=$((fails+1)); }

cp "$T/.specship/ledger/events.jsonl" "$RUN_BUNDLE/events.jsonl" 2>/dev/null || true
[[ $fails -eq 0 ]]
```

- [ ] **Step 2: Run (no tokens — deterministic)**

Run: `bash -n tests/e2e/tiers/t4_negative.sh && tests/e2e/run.sh --tier t4 --no-dashboard`
Expected: `PASS tier t4` with PASS lines for all four cases.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/tiers/t4_negative.sh
git commit -m "test(e2e): tier T4 negative/gate cases"
```

---

## Task 12: Full-suite smoke and docs

**Files:**
- Modify: `tests/e2e/README.md`
- Modify: `CLAUDE.md` (add a verify step pointer)

- [ ] **Step 1: Run the deterministic self-tests together**

Run:
```bash
for t in tests/e2e/selftest/*.sh; do echo "== $t =="; bash "$t" || exit 1; done
```
Expected: every self-test PASSes (dashboard self-test may print a skip line if Playwright is absent).

- [ ] **Step 2: Run the deterministic tier end-to-end**

Run: `tests/e2e/run.sh --tier t4 --no-dashboard`
Expected: `passed=1 failed=0`.

- [ ] **Step 3: Add a pointer in `tests/e2e/README.md`**

Append:
```markdown
## Self-tests (no tokens)
    for t in tests/e2e/selftest/*.sh; do bash "$t"; done

## Tiers
- T1/T2/T3 invoke real Claude (tokens, minutes). T4 is deterministic.
- Failed runs keep a debug bundle under tests/e2e/runs/<timestamp>/<tier>/.
```

- [ ] **Step 4: Add a verify pointer to the repo constitution**

In `CLAUDE.md`, under `## How to verify work is done`, add:
```markdown
- `for t in tests/e2e/selftest/*.sh; do bash "$t"; done` — e2e harness lib self-tests (no tokens)
```

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/README.md CLAUDE.md
git commit -m "test(e2e): full-suite docs and self-test verify pointer"
```

---

## Self-Review Notes

- **Spec coverage:** T1–T4 tiers (✓ Tasks 8–11), live `claude -p` execution (✓ Task 5), scripted approvals via real `plan_approved` (✓ Task 4), SQLite verification (✓ Task 3 + per-tier asserts), headless dashboard render (✓ Task 6 + per-tier `dashboard_check`), isolation via throwaway repos (✓ Task 2), sonnet default + override (✓ common.sh), real `/spec` from ticket fixtures (✓ Task 7).
- **Determinism:** all assertions are structural (`count`/`event` with `>=`), never prose — matches the design's variance handling.
- **Dashboard selector:** Task 6 Step 5 deliberately calibrates the selector against the real `dashboard.html` rather than guessing; tiers use a stable always-present string. Tighten per-tier figure assertions (e.g. specific card values) once the dashboard's element IDs are known from that calibration.
- **Known soft spots to tune during live runs (prompts, not assertions):** T3's `/qa` and `/investigate` prompts may need wording adjustments so each step produces its artifact; use `--keep` and the run bundle to iterate.
```

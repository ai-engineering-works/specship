# specship live end-to-end test harness — design

**Date:** 2026-05-21
**Status:** approved (design); pending implementation plan
**Author:** drafted with Claude (brainstorming session)

## Problem

specship's value is the *workflow* — `/spec → /contract → /work → /ship → /qa →
/check → /fix → /encode-lesson` — and the audit trail it produces (the ledger
SQLite tables, `events.jsonl`, the dashboard). Today there is no test that
exercises a complete workflow against a real repository and verifies that the
audit trail and dashboard reflect what happened. The deterministic helpers
(ledger, hook, generators, coverage) can be unit-tested in isolation, but
nothing proves the *commands* — which are LLM-driven prompts — drive those
helpers correctly end to end.

This harness fills that gap: it runs real specship commands through Claude
against throwaway repositories and verifies the resulting state on the SQLite
ledger and the rendered dashboard.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Execution model | **Live Claude** — real `claude -p` headless calls run each slash command |
| Human-in-loop gates | **Scripted approvals via the real mechanism** — `--plan-only` → log `plan_approved` via the ledger CLI → `--from-plan`; `/qa` answers supplied up front |
| Dashboard verification | **Headless browser render** (Playwright) loads the real `dashboard.html` and asserts rendered figures |
| Use-case tiers | **All four** — T1 simple, T2 full-stack+contract, T3 /ship+QA+bug loop, T4 negative/gate |
| Model default | **sonnet** (overridable via `SPECSHIP_E2E_MODEL`) |
| Spec authoring | **Real `/spec` from ticket fixtures** for every tier (more realistic; ticket fixtures steer the contract surface to bound variance) |

## Non-goals

- A fast, deterministic unit gate. This suite is slow and token-costing; it
  runs manually or nightly, not on every commit.
- Asserting on Claude's prose or exact wording. Assertions check **structural
  facts** only (events, table rows, statuses, file existence, exit codes).
- Installing anything into consumer repos. The harness is repo-internal test
  infrastructure; it lives outside `dist/` and does not affect
  `verify-sync.sh`.
- Testing the `/spec` Invariants section or `/ship` Stage 0 QA gate — those are
  not yet wired into the command files (see CHANGELOG "partially landed").

## Architecture

Repo-internal suite under `tests/e2e/`:

```
tests/e2e/
  run.sh                 # orchestrator: prereqs, tier selection, report, cleanup
  lib/
    provision.sh         # fresh temp git repo + app skeleton + CLAUDE.md + scripts/install.sh
    claude_cmd.sh        # wrapper around `claude -p` (flags, model, cwd, timeout, capture)
    approve.sh           # scripted "human": logs plan_approved / review verdicts via ledger CLI
    assert.py            # rebuild-index + SQL asserts; file/exit-code/hook asserts
    dashboard_check.mjs  # Playwright: load real dashboard.html, assert rendered figures
  fixtures/
    t1_ticket.md         # ticket text fed to /spec (single-scope backend)
    t2_ticket.md         # full-stack ticket steering explicit endpoints/fields
    t3_ticket.md         # full-stack ticket + seeded bug for the investigate/fix loop
    app-skeleton/        # minimal backend (src/) + frontend (web/) Claude works against
  tiers/
    t1_simple.sh
    t2_contract.sh
    t3_full.sh
    t4_negative.sh
  runs/<timestamp>/<tier>/   # saved events.jsonl, index.db, claude transcripts (debug bundle)
  package.json           # playwright devDep, local to tests/e2e
```

Language: bash orchestration + Python assertions + one Playwright `.mjs`,
matching the repo's existing bash+python idiom.

### Unit responsibilities

- **`run.sh`** — entry point. Parses `--tier`, `--model`, `--keep`,
  `--no-dashboard`. Checks prerequisites (`claude`, `python3` hard; Playwright
  optional). Runs selected tiers, collects PASS/FAIL, prints a summary, and
  preserves debug bundles for failures.
- **`provision.sh`** — creates a temp git repo, lays down `app-skeleton/`, writes
  a full-stack `CLAUDE.md` from `dist/templates/CLAUDE.md.template` (Project
  type: full-stack, languages set, a Coverage policy section so the coverage
  gate is active), runs `scripts/install.sh <target>`, and confirms the
  pre-commit hook + `.specship/` tree exist. Returns the repo path.
- **`claude_cmd.sh`** — single choke point for invoking Claude:
  `claude -p "<prompt>"` with `--permission-mode bypassPermissions` **(throwaway
  repo only)**, `--model "${SPECSHIP_E2E_MODEL:-sonnet}"`, cwd = target repo, a
  timeout, and stdout/stderr/exit-code capture into the run bundle.
- **`approve.sh`** — the scripted human. Reads the latest `plan_drafted` (or
  relevant) event from the target ledger and logs the corresponding
  `plan_approved` (and `/review-*` verdicts) via the target's
  `.specship/ledger/specship_ledger.py`, exactly as a human reviewer would.
- **`assert.py`** — verification library. Runs `rebuild-index`, executes SQL
  against the projected tables, and exposes assert helpers
  (`assert_count(table, where, op, n)`, `assert_status(...)`, `assert_file(...)`,
  `assert_exit(...)`). Emits a clear diff on failure.
- **`dashboard_check.mjs`** — starts a static server rooted at the target repo
  (mirroring `open-dashboard.sh`), loads `.specship/dashboard/dashboard.html`,
  waits for the `events.jsonl` fetch + render, and asserts rendered figures
  equal the SQLite-derived expectations passed in by the tier.

## Workflow per tier (control flow)

**T1 — simple, single-scope happy path**
`/spec t1_ticket` → `/work --plan-only` → `approve.sh` logs `plan_approved` →
`/work --from-plan` → `/review-decisions` → `git commit` (Wall passes).
*Assert:* `sessions ≥ 1`, `decisions ≥ 1`, a `gate_passed` event, spec file
exists, commit succeeded.

**T2 — full-stack with contract**
`/spec t2_ticket` (full-stack) → `/contract` (hash-lock + `_generated/`
artifacts, breaking-change check) → `/work` backend + `/work` frontend (each
plan-gated and approved) → `/check` → `git commit`.
*Assert:* contract hash stamped into generated artifacts, `coverage` rows
present, `breaking_changes` table populated/empty as expected, `/check` reports
no drift, generated artifacts exist under `_generated/`.

**T3 — hard: /ship orchestration + QA + bug loop**
`/spec t3_ticket` → `/ship` (planning phase → `approve.sh` → execution phase →
`/check`) → `/qa` (author regression + scenario + property, generate tests) →
seed the bug from the fixture → `/investigate` → `/fix --from-investigation` →
`/work` → `/encode-lesson` → `/capture-lessons` → run the curator
(`.specship/lessons/curate.sh`) → `/review-lessons`.
*Assert:* `plans` rows with `verdict=approved`, `qa_artifacts` rows for all
three kinds, `qa_tests_generated` events + generated test files exist,
`lessons` row written, `lesson_candidates` rows present and the curator ran.

**T4 — negative / gate cases** (no LLM where avoidable; mostly deterministic)
- Commit touching `src/` with no spec/fix/investigation linkage → Wall blocks
  (exit 1), `gate_blocked` event with reason `no-linkage`.
- CLAUDE.md Coverage policy active + a failing `coverage_measured` event →
  commit blocked, `gate_blocked` reason `coverage-below-threshold`.
- `/work --from-plan` with no `plan_approved` event → command refuses.
- Breaking change introduced into a spec's Contract surface → `/contract`
  flags it, `breaking_changes` row recorded.
- Edit the `Input` of an approved regression artifact → `qa-check.py` warns
  (stderr), commit still succeeds (advisory).
*Assert:* expected non-zero exits, expected `gate_blocked` rows, expected
warning text on stderr.

## Verification strategy

**SQLite.** After each workflow, `specship_ledger.py rebuild-index`, then SELECT
against the projected tables. Assertions use `>=` thresholds and presence/status
checks, never exact prose or LLM-chosen IDs, so they tolerate model variance.

**Dashboard.** Playwright loads the real `dashboard.html` against the target's
`events.jsonl` and asserts the rendered figures **equal the SQLite-derived
expectations** for that tier — a cross-check that the displayed dashboard agrees
with the database. Runs for every tier unless `--no-dashboard`/Playwright
missing; T3 (the richest state) is the must-pass dashboard case.

## Determinism & variance handling

- Ticket fixtures are written to strongly steer the contract surface (explicit
  endpoint paths, methods, field names) so `/spec`/`/contract` output is
  predictable enough to assert on structurally.
- Assertions never depend on exact wording, counts that the LLM controls
  freely, or generated IDs.
- Each tier runs in a fresh isolated repo; no shared state between tiers.
- Failures preserve a debug bundle (`events.jsonl`, `index.db`, transcripts).

## Operational

- `./run.sh [--tier t1,t3] [--model opus] [--keep] [--no-dashboard]`.
- Prereqs: `claude` + `python3` required; `node` + Playwright optional (dashboard
  layer skips with a clear message if absent).
- Slow, token-costing integration suite — manual/nightly, not a fast gate.
- Default cleanup of temp repos; `--keep` retains them.

## Risks

- **Token cost / runtime.** Mitigated by sonnet default, `--tier` subsetting, and
  positioning as a nightly/manual suite.
- **Flakiness from LLM variance.** Mitigated by structural-only assertions and
  steering ticket fixtures; accept occasional reruns rather than over-fitting.
- **`claude -p` gate behavior.** If a command stalls waiting for input despite
  the scripted-approval flags, the timeout in `claude_cmd.sh` fails the step
  with a captured transcript rather than hanging the suite.
- **Playwright dependency weight.** Kept local to `tests/e2e/package.json` and
  optional; the SQLite layer is the primary gate.

## Out of scope / future

- A fast deterministic lane that exercises only the helper scripts (no Claude).
- CI wiring (the repo currently has no `.github/workflows/`).
- A second-Claude reviewer for gates (we chose scripted approvals instead).

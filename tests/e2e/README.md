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

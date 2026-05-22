# specship live e2e harness

Runs real specship workflows through `claude -p` and verifies the SQLite ledger.
Slow and token-costing — run manually or nightly.

## Usage
    ./run.sh [--tier t1,t3] [--model opus] [--keep]

## Prerequisites
- `claude` CLI on PATH (required)
- `python3` (required)

Design: docs/superpowers/specs/2026-05-21-specship-e2e-test-harness-design.md

## Self-tests (no tokens)
    for t in tests/e2e/selftest/*.sh; do bash "$t"; done

## Tiers
- T1/T2/T3 invoke real Claude (tokens, minutes). T4 is deterministic.
- Failed runs keep a debug bundle under tests/e2e/runs/<timestamp>/<tier>/.

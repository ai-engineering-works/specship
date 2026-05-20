# Example Conversions

Concrete before/after examples showing how to apply the conversion rules.

## Example 1: A typical bloated CLAUDE.md

### Before (167 lines, paraphrased composite of real ones)

```markdown
# Claude Instructions for SGEN Project

## Overview
This is the SGEN batch processing pipeline. It processes events from
NCBS and writes to OFPC. Please be careful when making changes as this
is a critical financial system. Always think before you act.

## Important Rules
- Always run tests before committing
- Never push to main directly
- Be careful with deletions
- Make sure code is high quality
- Follow PEP 8
- Use type hints
- Write good tests
- Don't make up function names — check that they exist first
- VERY IMPORTANT: never modify the audit tables
- Use ~|~ as the delimiter for multi-character delimiters
- All Kafka consumers must distinguish recoverable from unrecoverable errors
- Comply with MAS AIRG regulations at all times
- Be helpful and concise in your responses
- Don't apologize unnecessarily

## How to test
Run the tests to make sure everything works. You should also check
that linting passes. We use pytest and mypy.

## Project structure
The src/ directory has all the production code. It's organized by
module. The tests/ directory has tests. They mirror the src/ structure
mostly. There's also a runbooks/ directory with operational procedures
and a docs/ directory with documentation including the architecture
overview which explains how the 5 main services interact through the
event bus and how the GL posting rules engine works with the rules
DSL we built last year...

[long architecture prose continues for 40 more lines]

## Glossary
- NCBS: New Core Banking System
- OFPC: Output Financial Posting Cache
- GL: General Ledger
- AIRG: AI Risk Governance (MAS publication)
```

### After (the converted version)

```markdown
# Project Constitution

## What this codebase is

SGEN batch pipeline that consumes NCBS Kafka events, applies GL
posting rules under MAS AIRG controls, and writes posted journals
to OFPC tables. Runs nightly. Critical financial path.

## Non-negotiable invariants

- Never modify or delete from audit tables (`audit_*`). Soft-delete only.
- Multi-character delimiters use `~|~`. Never single `|`. §ref:DELIM-001
- All Kafka consumers explicitly handle recoverable vs unrecoverable error tiers. §ref:KAFKA-ERR-001
- All changes touching GL posting logic must satisfy MAS AIRG traceability — every code path links to a spec via §ref. §ref:AIRG-TRACE-001

## Conventions worth following

- Type hints required on public functions
- Tests colocated under `tests/` mirroring `src/`
- Prefer composition over inheritance
- Verify function existence before referencing — no invented APIs

## How to verify work is done

- `pytest tests/` exits 0
- `mypy src/` clean
- `ruff check src/` clean
- New code in `src/` has §ref:specs/ comments

## Where things live

- `src/` — production code, organised by module
- `tests/` — mirrors `src/`
- `specs/` — spec files (see `/spec` command)
- `runbooks/` — operational procedures
- `docs/architecture.md` — full module and event-bus breakdown

## Domain glossary

- NCBS — New Core Banking System (upstream)
- OFPC — Output Financial Posting Cache (downstream)
- GL — General Ledger
- AIRG — AI Risk Governance, MAS publication
- §ref — traceability comment linking code to spec
```

### What changed and why

- "Overview" prose with "be careful" / "think before you act" → tightened to 3 sentences in "What this codebase is". Generic caution dropped.
- "Always run tests before committing" → moved to "How to verify work is done" as a concrete command.
- "Never push to main directly" → DROPPED (this is a git server policy, not a CLAUDE.md concern).
- "Be careful with deletions", "make sure code is high quality" → DROPPED (not mechanical).
- "PEP 8", "type hints", "good tests" → moved to "Conventions worth following" as concrete items.
- "Don't make up function names" → kept as a convention (it's a real, concrete behavioural rule).
- "VERY IMPORTANT: never modify audit tables" → promoted to invariant, stripped of all-caps emphasis.
- `~|~` delimiter, Kafka error tiers, MAS AIRG → promoted to invariants with §ref tags (asked user to confirm/supply real codes).
- "Be helpful and concise" / "don't apologize" → DROPPED (assistant tone, not project rule).
- Long architecture prose → EXTRACTED to `docs/architecture.md` (which likely already exists), linked from "Where things live".
- Glossary terms → kept verbatim, formatted consistently.

Result: 167 lines → 38 lines. Every line earns its place.

## Example 2: A skeletal CLAUDE.md

### Before (12 lines)

```markdown
# CLAUDE.md

This is our trading agent project.

Use Python 3.11. Use pytest for tests. We use Hermes for the agent framework.

The main entry point is `main.py`. Watchlist is hardcoded for now.

Don't make changes without testing.
```

### After (greenfield-ish — needs interview to complete)

```markdown
# Project Constitution

## What this codebase is

[fill in — confirm: a trading agent built on the Hermes framework,
Python 3.11, single entry point at `main.py`, hardcoded watchlist]

## Non-negotiable invariants

[fill in — ask user: are there hard rules around order placement,
risk limits, broker API safety, paper-vs-live trading modes? These
are likely candidates for invariants in a trading system.]

## Conventions worth following

- Python 3.11 baseline
- pytest for tests
- Hermes for agent framework

## How to verify work is done

- `pytest` exits 0
- [fill in — ask user: linter? type checker? any backtest gate?]

## Where things live

- `main.py` — entry point
- [fill in — ask user for the rest of the layout]

## Domain glossary

- [fill in — ask user: any acronyms or strategy-specific terms?]
```

### What happened

The source was thin. Most of the structured file is `[fill in]` placeholders with hints. The skill should now interview the user to fill these, especially the invariants (which are critical in trading systems — risk limits, mode safety, order idempotency are classic ones).

This is correct behaviour. **Do not invent trading invariants.** Ask.

## Example 3: An AGENTS.md being migrated

### Before (excerpt)

```markdown
# Agent Instructions

You are an expert Python developer working on the data-pipeline repo.
You should write clean, idiomatic Python code.

When writing code:
- Always use type hints
- Always write tests
- Prefer pandas over numpy when working with tabular data
- Use Dask for datasets over 1GB

When responding:
- Be concise
- Don't add unnecessary explanations
- Don't apologize

The architecture: we have an ingestion layer that reads from S3...
[continues for many lines]
```

### After

```markdown
# Project Constitution

## What this codebase is

Data pipeline that ingests files from S3, transforms via pandas/Dask,
writes to the warehouse. Python-only.

## Non-negotiable invariants

[fill in — ask user: any data integrity rules, idempotency
requirements, ordering guarantees? The source file didn't list any.]

## Conventions worth following

- Type hints on all functions
- Tests written alongside new code
- pandas for tabular work; Dask for datasets > 1GB

## How to verify work is done

- [fill in — ask user for the actual test/lint commands]

## Where things live

- See `docs/architecture.md` for the ingestion → transform → warehouse layout

## Domain glossary

- [fill in if there are domain terms]
```

### What changed

- "You are an expert Python developer..." → DROPPED (role-priming, not project rules).
- "Be concise / don't apologize" → DROPPED (assistant tone).
- "Always use type hints" etc → moved to Conventions.
- Architecture prose → EXTRACTED to a referenced file.
- No invariants in source → left as `[fill in]` placeholder with prompt to ask user. **Critical:** do not invent invariants just because the section feels empty.

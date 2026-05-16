---
name: spec-reverse-engineer
description: Reverse-engineer specship spec files from existing code, existing documentation, OpenAPI/AsyncAPI definitions, BDD .feature files, or JIRA exports. Use when adopting specship on a codebase that already exists, migrating from another spec-driven framework (SpecKit, BMAD, Kiro, Tessl), or backfilling specs for code that was written before specship was introduced. Trigger phrases include "reverse engineer", "migrate", "backfill specs", "import from", "adopt specship on existing code", "convert docs to specship specs", "we have code but no specs". Do NOT trigger for fresh greenfield specs — use the /spec command for those.
---

# spec-reverse-engineer

A skill for producing specship spec files from material that already exists: source code, documentation, OpenAPI definitions, BDD feature files, or other spec frameworks' artifacts.

The output is always a draft spec under `specs/` with status `draft-reverse-engineered`. The user reviews, refines, and promotes to `draft` (or `contract-locked` if `/contract` runs against it).

## Honest framing

Reverse-engineering specs from code is **lossy**. The skill produces what's *observable* from the source: type signatures, route shapes, validation rules, test assertions. It does NOT reconstruct original intent — if the code has evolved over years, the original requirements are lost and no skill can recover them. Specs produced this way are marked clearly as such, and every uncertain section carries a `[needs review]` flag.

Three things this skill will NOT do:

1. **Invent business motivation.** If the code's purpose isn't obvious from names, comments, and tests, the skill says `[purpose unclear]` rather than guessing.
2. **Promise round-trip fidelity.** Code → spec → code doesn't reproduce identical code.
3. **Auto-merge with existing docs without review.** Conflicts between code-derived and doc-derived content are surfaced for the user to adjudicate.

## Three input scenarios

The skill detects which scenario applies and behaves accordingly.

### Scenario A: Code only (no docs)

User has source code and wants specs that retroactively cover it. Read `references/from-code.md` for detailed extraction rules.

### Scenario B: Existing docs/specs in another format

User has Confluence pages, Notion exports, OpenAPI YAML, BDD `.feature` files, JIRA tickets, or specs from another framework. Read `references/from-docs.md` for the source-format mapping.

### Scenario C: Hybrid — code + scattered docs

Both signals are available. Use both, mark conflicts, prioritise the higher-reliability source per field. Read both reference files.

## How to choose a scope

The user usually asks "reverse engineer the whole codebase". That produces unreviewable output. Default to one of these scopes, in order of preference:

1. **One module/package** — e.g. `src/notifications/` produces one spec covering that module's externally-observable surface
2. **One endpoint or one service class** — finest-grained, highest fidelity
3. **One feature area, drawing from multiple modules** — only when there's a clear feature boundary

Ask the user to pick a scope. Never reverse-engineer more than one spec per invocation unless the user explicitly says they want bulk migration (in which case, warn that bulk output needs careful review and produce one spec per module sequentially, not all at once).

## Signal reliability — apply in this order

| Signal | Reliability | What it gives you |
|---|---|---|
| OpenAPI/AsyncAPI in repo | Highest | Direct contract surface — use verbatim |
| Type signatures, schemas (Pydantic, Zod, Java types) | High | Shape of types and validation |
| Test assertions | High | Acceptance criteria (the closest match to specship's checkbox format) |
| Route/handler declarations | High | Endpoint paths and HTTP methods |
| Existing docs (recent, dated within last 6 months) | Medium-High | Intent and rationale |
| DB migrations | Medium | Persisted state shape |
| README, docstrings, code comments | Variable | Hints — verify against code |
| Inferring purpose from code structure alone | Low | Last resort; mark output as `[needs review]` |

Use higher-reliability signals to fill confident sections. Lower-reliability signals fill `[needs review]` sections that the user must confirm.

## The output spec

Use the standard `specship` spec shape, with three modifications:

1. **Status:** `draft-reverse-engineered` (a new status distinct from `draft`)
2. **Metadata field:** `Reverse-engineered from:` listing the source paths the skill consulted (code files, doc paths, OpenAPI files, etc.)
3. **Every uncertain section** is marked `[needs review — <why>]` with an explicit reason

Example metadata block:

```markdown
# Notification preferences (reverse-engineered)

**Ticket:** none
**Status:** draft-reverse-engineered
**Scope:** full-stack
**Created:** 2026-05-12
**Reverse-engineered from:**
  - `src/backend/notifications/NotificationController.java`
  - `src/backend/notifications/NotificationService.java`
  - `src/frontend/pages/preferences.tsx`
  - `tests/backend/test_notifications.py`
  - `docs/notifications-design.md` (last edited 2025-08-12, may be stale)
```

## Workflow

### Step 1: Detect scenario

Sniff the user's input and the repo:

- User points at a `.py`/`.java`/`.ts` file or a `src/` directory → Scenario A
- User points at a `.md`/`.feature`/`.yaml` doc → Scenario B
- User mentions both, or both are present in the area being migrated → Scenario C

If unclear, ask.

### Step 2: Confirm scope

Confirm with the user which one-module-or-endpoint scope they want for this invocation. If they say "all of it", warn about reviewability and suggest starting with one to validate the output shape before doing more.

### Step 3: Read `CLAUDE.md`

The reverse-engineered spec must respect existing invariants. If `CLAUDE.md` doesn't exist, recommend the user run `claude-md-architect` first — without a constitution, the reverse-engineered spec has no invariants to anchor against. Proceed only if the user insists.

### Step 4: Extract

Apply the rules in `references/from-code.md` (Scenario A or C) and/or `references/from-docs.md` (Scenario B or C). Build the spec section by section.

### Step 5: Mark uncertainty honestly

For every section that wasn't derived from a high-reliability signal, append `[needs review — <reason>]` with the actual reason:

- `[needs review — purpose inferred from method name, not documented]`
- `[needs review — type union derived from observed test inputs only; may not cover all cases]`
- `[needs review — doc was last edited 18 months ago; may be stale]`

The user can search for `[needs review]` across the spec to find everything that needs human verification.

### Step 6: Output

Save to `specs/YYYY-MM-DD-<slug>-reverse-engineered.md`. Use today's date. Slug from the module or feature name. Tell the user:

```
Reverse-engineered spec saved to specs/2026-05-12-notif-prefs-reverse-engineered.md

Status: draft-reverse-engineered (NOT yet usable with /work or /contract)

Next steps:
  1. Open the spec and search for "[needs review]" — there are N flags.
  2. Confirm or correct each one.
  3. When confident, change Status to "draft" (or "contract-locked" after running /contract).
  4. Optionally: rename the file to drop the "-reverse-engineered" suffix.

The spec respects invariants from CLAUDE.md, but does not currently link to
any specific code via §ref comments. Adding those comments is the user's
job — typically as a follow-up /fix once code is being modified.
```

## When to recommend NOT reverse-engineering

Sometimes the right answer is to **not produce a spec for existing code**. Specifically:

- **Trivial utility code** — the spec would be longer than the code itself
- **Code about to be deleted** — don't write specs for things on their way out
- **Code generated from another tool** — protobuf-generated, OpenAPI-generated, ORM scaffolding. Reverse-engineering a generated file produces a spec that describes the generator's output, which is not useful.
- **Code with no observable behaviour** — pure refactors of internal helpers. There's nothing external to spec.

When the user asks to reverse-engineer one of these, push back. Tell them the spec would not provide value and the maintenance burden isn't worth it. The user can override; the skill records the override as a Note in the spec for transparency.

## What not to do

- Do not fabricate intent. `[purpose unclear]` is better than a confident-sounding wrong answer.
- Do not invent acceptance criteria. Derive them from tests; if there are no tests, mark as `[needs review — no tests found, please add]`.
- Do not skip the `[needs review]` flags even if you feel confident. Reverse-engineered specs are by definition uncertain.
- Do not promote a `draft-reverse-engineered` spec to `draft` automatically. That's a human decision.
- Do not bulk-process more than one scope per invocation without explicit user opt-in.
- Do not overwrite an existing spec. If `specs/<slug>.md` exists, save with a unique suffix and tell the user.

## Reference files

- `references/from-code.md` — extraction rules for source code (Python, Java, TypeScript)
- `references/from-docs.md` — migration rules for various doc formats (OpenAPI, BDD, Confluence-style markdown, other-framework specs)
- `references/examples.md` — concrete before/after migrations

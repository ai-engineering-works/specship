# Hierarchy Examples

Worked examples for Mode 4 (designing or refactoring nested CLAUDE.md files).

---

## Example 1: Splitting a bloated monorepo root

### Before (one 340-line root CLAUDE.md)

```
my-monorepo/
├── CLAUDE.md     ← 340 lines, covers everything
├── services/
│   ├── api/
│   ├── worker/
│   └── scheduler/
└── apps/
    └── web/
```

The root file has sections like:
- "Invariants" — mixed: some cross-cutting (regulatory), some only apply to `api/`
- "How to verify" — lists `pytest`, `npm test`, `cargo test` interchangeably
- "Domain glossary" — 40 terms, half of them frontend-only

### After (root + 4 nested files, total smaller)

```
my-monorepo/
├── CLAUDE.md                  ← 95 lines, cross-cutting only
├── services/
│   ├── api/
│   │   └── CLAUDE.md          ← 45 lines
│   ├── worker/
│   │   └── CLAUDE.md          ← 30 lines
│   └── scheduler/             ← (no CLAUDE.md — sufficiently covered by root)
└── apps/
    └── web/
        └── CLAUDE.md          ← 70 lines
```

**Root contains:**
- Cross-cutting invariants (regulatory, data integrity, audit)
- Project type, Backend language, Frontend language, Contract pair name fields
- High-level "how to verify": the umbrella command (e.g. `make ci`) that delegates
- Cross-cutting glossary (NCBS, OFPC, etc.)

**`services/api/CLAUDE.md` contains:**
- API-specific invariants ("all endpoints emit audit events", "rate limit enforced at gateway")
- API-specific verification (`pytest services/api/tests/` exits 0)
- API-specific terms (e.g. "tenant context")

**`services/scheduler/CLAUDE.md` doesn't exist** — the user evaluated and found nothing module-specific. Root coverage is enough.

**Total content:** original 340 lines → 240 lines across 4 files. Each file is focused. Each is loaded only when relevant.

### What the skill reports back

```
Hierarchy refactor complete.

Files created:
  services/api/CLAUDE.md           (45 lines)
  services/worker/CLAUDE.md        (30 lines)
  apps/web/CLAUDE.md               (70 lines)

Files modified:
  CLAUDE.md  (was 340 lines, now 95 lines)

Files NOT created:
  services/scheduler/  — sufficiently covered by root. No module-specific
                         invariants or verification commands.

Total CLAUDE.md content:  340 lines → 240 lines.
Token reduction at session start: 340 → 95 lines (root only loads at launch).
Nested files load on demand when Claude reads files in those subtrees.
```

---

## Example 2: When NOT to create nested files

### Setup

User asks: *"I have a Python package with `core/`, `utils/`, and `cli/` subdirectories. Should each have its own CLAUDE.md?"*

### What the skill does

Run through the "When nested CLAUDE.md files earn their place" checklist for each candidate:

| Module | Distinct invariants? | Distinct verification? | Distinct glossary? | Distinct layout? | Different team? | Verdict |
|---|---|---|---|---|---|---|
| `core/` | No (same regulatory rules apply) | No (same `pytest`) | No (same terms) | No | No | **Skip** |
| `utils/` | No | No | No | No | No | **Skip** |
| `cli/` | No | Maybe (`pytest tests/cli/` runs faster than full suite) | No | No | No | **Skip — the speed argument doesn't justify a whole file** |

The skill reports:

```
No nested CLAUDE.md files needed. Reasoning:

- core/, utils/, cli/ all share the same invariants, verification
  command, and domain vocabulary as the root.
- The fact that subdirectories exist is not a reason to create
  per-directory CLAUDE.md files. Nested files have maintenance cost.
- If you later find that cli/ has distinct rules (e.g. "always
  exit 0 on --help, never read stdin"), THAT's the moment to create
  cli/CLAUDE.md.

Recommendation: keep one CLAUDE.md at the root.
```

This is the correct answer 80% of the time. Nested files should be the exception, not the default.

---

## Example 3: Refactoring duplicates and conflicts

### Before

The user has:

```
CLAUDE.md (root):
  ## Non-negotiable invariants
  - Multi-character delimiters use ~|~
  - All tests must pass before merge
  - pytest runs all tests

backend/CLAUDE.md:
  ## Non-negotiable invariants
  - Multi-character delimiters use ~|~        ← DUPLICATE
  - Backend tests use unittest                 ← CONFLICT with root
  - All endpoints must have OpenAPI specs     ← genuinely module-specific
```

### What the skill flags

```
Issues detected:

1. DUPLICATE: "Multi-character delimiters use ~|~" appears in both root
   and backend/CLAUDE.md. Delete from backend/ — it's a cross-cutting rule.

2. CONFLICT: root says "pytest runs all tests"; backend/CLAUDE.md says
   "Backend tests use unittest". These contradict.
   → Ask user which is correct.
   → Either fix the root (if backend really uses unittest) or fix the
     nested file (if pytest is the actual command).

3. KEEP: "All endpoints must have OpenAPI specs" is genuinely backend-
   specific. Keep in backend/CLAUDE.md.
```

After the user clarifies that backend really uses `pytest` and the unittest line was stale:

### After

```
CLAUDE.md (root):
  ## Non-negotiable invariants
  - Multi-character delimiters use ~|~
  - All tests must pass before merge

  ## How to verify work is done
  - pytest runs all tests (root); per-module commands in module CLAUDE.md

backend/CLAUDE.md:
  ## Non-negotiable invariants
  - All endpoints must have OpenAPI specs       ← module-specific only

  ## How to verify work is done
  - pytest backend/tests/ exits 0               ← scoped command
```

The nested file is now half its previous size and contains only what genuinely differs.

---

## Common patterns

### Frontend / backend split

The most common nested-file case. Root has cross-cutting rules; `frontend/CLAUDE.md` has UI-specific invariants (accessibility, browser support, bundle size limits); `backend/CLAUDE.md` has server-specific invariants (rate limits, idempotency, audit emissions).

Each side typically has its own test command, glossary, and `Where things live` map.

### Library packages inside a monorepo

If a monorepo contains internally-published libraries, each library may warrant its own CLAUDE.md if it has distinct stability guarantees (e.g. "this library is published to npm; never break the public API without a major version bump").

### Service-per-team

If different teams own different services in the same repo, each team's service gets a CLAUDE.md reflecting that team's conventions. Root handles cross-team invariants. This pattern is valuable but requires governance — without it, nested files drift in different directions and the repo becomes incoherent.

### Anti-pattern: per-directory CLAUDE.md

If every directory has its own CLAUDE.md, the system has failed. Nested files should mark *meaningful module boundaries*, not arbitrary directory boundaries. Three nested files for a 6-service repo is reasonable; twenty is not.

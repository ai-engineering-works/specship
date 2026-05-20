# specship

> **Renamed from `attest` as of v0.12.0.** Existing installs migrate via `scripts/migrate-from-attest.sh` — see CHANGELOG. The audit trail is preserved exactly; event schema, command names, and workflow are all unchanged.

A standalone workflow for AI-assisted development with [Claude Code](https://docs.claude.com/en/docs/claude-code). Designed for regulated environments (banks, financial services, healthcare) where every code change needs a traceable contract and an auditable trail.

The name reflects what the workflow does: it carries a *spec* all the way to *ship*. Every artifact is a checkpoint along that path. The spec captures intent. The contract locks the API boundary. The fix captures a bug and its resolution. A `§ref` comment traces code back to the spec. The pre-commit hook verifies nothing slips through without that paper trail. The hash mechanism verifies contracts haven't drifted. Spec to ship, end to end.

The whole system: one constitution per repo, nine slash commands, two skills, one pre-commit hook, an observability ledger, and a structural breaking-change detector.

## Quick start

```bash
# Clone this repo
git clone https://github.com/<you>/specship.git
cd specship

# Install into your project
./scripts/install.sh /path/to/your/repo

# Open your repo in Claude Code and start with:
#   /spec <your-ticket-id>
```

The installer is idempotent — re-running it is safe. Use `--dry-run` to preview what it would change.

## Scope — what specship is, and what it isn't

specship is a **spec-driven development workflow** for AI-assisted coding in a single repository with Claude Code as the agent. It is not a platform, not a framework, not an agent fleet manager. To help you decide whether specship fits your need:

| specship IS | specship IS NOT — use this instead |
|---|---|
| A spec/fix/investigation-driven workflow for Claude Code | A general agent framework — use LangGraph, CrewAI, or AutoGen for multi-agent orchestration outside Claude Code |
| A pre-commit "Wall" that requires spec-or-fix linkage on `src/` changes | A code review tool — use GitHub PRs, Gerrit, Crucible |
| A contract-integrity layer (hash + structural breaking-change detection on OpenAPI) | A contract registry / API gateway — use Apigee, Kong, or your in-house registry |
| A local observability ledger (JSONL + SQLite) for command-level events | A full observability platform — use LangSmith, Arize Phoenix, or MLflow for production agent monitoring at scale |
| A learning loop (`/encode-lesson`) that promotes investigation findings into CLAUDE.md invariants | An incident management system — use PagerDuty, Statuspage, your internal IR process |
| Aligned with MAS AIRG / SR 11-7 documentation requirements | A complete AI risk governance program — those programs cover model approval, bias auditing, third-party assessments, customer-facing transparency |
| Friendly to single-repo workflows | A monorepo build system — use Bazel, Pants, Nx, Turborepo |
| Useful at small-to-medium team scale (1-30 engineers per repo) | A multi-tenant agent platform — different problem entirely |
| A `/post-mortem` substrate (via `/investigate` + `/encode-lesson`) | A full post-mortem template — your team's incident review process is the right home for the prose narrative |

If you need specship plus one of the right-column items, run both. specship is deliberately small in surface so it composes rather than competes.

## The workflow at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│  New feature, single scope (backend OR frontend)                 │
├─────────────────────────────────────────────────────────────────┤
│  /spec → /work → /review-decisions → git commit                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  New feature, full-stack (backend AND frontend)                  │
├─────────────────────────────────────────────────────────────────┤
│  /spec → /ship → /review-decisions → review both subagents'     │
│         work → 2× git commit                                     │
│  (/ship runs /contract + parallel /work + /check internally)    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Known bug                                                       │
├─────────────────────────────────────────────────────────────────┤
│  /fix → (optional /contract for spec changes) → /work →         │
│        /review-decisions → commit                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Unknown failure (compile error, runtime error, broken CI)       │
├─────────────────────────────────────────────────────────────────┤
│  /investigate → /fix --from-investigation → /work → commit      │
│  After the fix holds: /encode-lesson to promote invariant       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Drift detection (anytime)        │  Ledger summary (anytime)    │
├───────────────────────────────────┼──────────────────────────────┤
│  /check                           │  specship_ledger.py summary    │
└───────────────────────────────────┴──────────────────────────────┘
```

Each command's full behaviour is documented in its own file under `dist/commands/`.

## What's where in this repo

```
specship/
├── README.md                     ← you are here
├── CLAUDE.md                     ← constitution for THIS repo (self-hosted)
├── LICENSE
├── .gitignore
│
├── dist/                         ← source of truth — install into other repos
│   ├── commands/                 ←   the eight slash commands
│   ├── contract/                 ←   breaking-change detection helpers
│   ├── hooks/                    ←   pre-commit hook
│   ├── ledger/                   ←   observability ledger (Python + SQLite)
│   ├── skill/                    ←   two skills
│   └── templates/                ←   CLAUDE.md template
│
├── .claude/                      ← generated copy for self-hosting (sync'd from dist/)
│   ├── commands/
│   ├── contract/
│   ├── ledger/
│   └── skills/
│
├── docs/
│   └── bug-fix-workflow.md       ← worked examples of the four bug-fix cases
│
├── examples/                     ← example specs and fixes
│
├── scripts/
│   ├── install.sh                ← install into a target repo
│   ├── sync-local.sh             ← regenerate .claude/ from dist/
│   └── verify-sync.sh            ← CI check: .claude/ matches dist/
│
└── .github/
    ├── workflows/                ← CI
    └── CONTRIBUTING.md
```

## Handling failures (compile errors, runtime errors, broken CI)

Failures take several shapes. The workflow handles each differently:

| Situation | Approach |
|---|---|
| Compile error in code Claude wrote during `/work` | `/work` iterates up to ~3 attempts on the same failure, with different hypotheses each time. After that, it stops and asks the user. Don't disable tests or relax invariants to make failures pass. |
| Compile error in code outside `/work`, trivial (typo, missing import) | Just fix it; commit with `--no-verify` if there's no spec to reference. The audit trail captures bypasses in git log. |
| Runtime error you've observed but don't know the cause of | `/investigate` — captures evidence, hypotheses, what you ruled out, and the root cause once found. Then `/fix --from-investigation` pre-populates the fix with what you learned. |
| Production incident | `/investigate --production` — same flow with the audit bar raised. Combine with your normal incident response process. |
| Broken CI you suspect is environmental (not your code) | `/investigate` and conclude with `closed-external` once you've confirmed. No fix needed; the investigation is the audit trail of "we looked and it wasn't us". |
| Bug you know the cause of immediately | Skip `/investigate`, go straight to `/fix`. The investigation is for unknowns. |

### Why `/investigate` is separate from `/fix`

`/fix` requires a known root cause — it refuses to draft a Resolution without one. That's correct discipline for verified bugs but unworkable for "something just broke and I don't know why yet". `/investigate` is the discovery phase; `/fix` is the resolution phase. Keeping them separate means:

- The investigation has its own append-only log (you don't lose what you tried)
- "Closed without fix" is a valid outcome (not reproducible, was environmental, etc.)
- Multiple people can contribute to one investigation over time
- When a similar failure recurs months later, you can search past investigations for the symptom

In a regulated environment, the investigation record is often more important than the fix itself: it shows you investigated rather than guessed.

## The nine commands

| Command | When to use |
|---|---|
| `/spec <ticket>` | New feature, new requirement, or evolution of existing functionality |
| `/contract <spec>` | Compile a spec's Contract surface into `_generated/` artifacts (full-stack only); detects structural breaking changes vs the previous compilation |
| `/work <spec-or-fix> [--scope]` | Execute against a spec or fix file (single scope) |
| `/ship <spec>` | Orchestrate a full-stack spec end-to-end: `/contract` then parallel backend + frontend `/work` via subagents, then `/check`. Saves the user from running four sessions manually. |
| `/check <spec-or-fix> [--deep]` | Detect drift between a spec/fix and the code |
| `/investigate <ticket>` | Investigate a failure (compile error, runtime error, broken CI, production incident) — produces an investigation file with evidence and root cause |
| `/fix <ticket> --against <spec> [--from-investigation <inv>]` | Bug fix against an existing spec — four-case classification, can chain from `/investigate` |
| `/encode-lesson <investigation> [--fix <fix>] [--from-candidate <id>]` | Promote a lesson learned from a resolved investigation (or a reviewed candidate) into a durable invariant in CLAUDE.md (or nested CLAUDE.md, skill gotchas, or command prompt). Closes the learning loop. |
| `/review-decisions [<spec>] [--since DATE]` | Surface decisions Claude logged during `/work` for human review. Mark each as accepted, rejected, or needs-redo. Closes the human-in-loop gap. |
| `/capture-lessons` | Record up to 3 lesson candidates from the current session — corrections, confirmed approaches, preferences, surprising decisions. Runs automatically at session end; also callable manually. |
| `/review-lessons [--since DATE]` | Triage pending lesson candidates: promote to `/encode-lesson`, dismiss, or skip. Surfaces clustered consolidation suggestions from the curator. |

`/work` accepts either spec or fix files. `/check` is invoked automatically by `/work` and can also be run manually. `/investigate` feeds into `/fix` via the `--from-investigation` flag. `/ship` only handles full-stack specs; for single-scope work, run `/work` directly. `/encode-lesson` requires the investigation to have status `closed-resolved`. `/review-decisions` reads from the ledger — it requires `/work` (or another command) to have logged decisions first.

## The observability ledger

Every command logs to a local ledger so you can answer questions like "how many specs did we ship last quarter?", "how often did the pre-commit Wall block us?", "which acceptance criteria triggered the most drift?". Two storage layers:

- **JSONL** at `.specship/ledger/events.jsonl` — source of truth, append-only, committed to git for audit
- **SQLite** at `.specship/ledger/index.db` — derived query index, gitignored, rebuildable from the JSONL

The ledger is queryable from the command line and exportable to CSV for dashboards:

```bash
# Human-readable summary
python3 .specship/ledger/specship_ledger.py summary

# Last 30 days only
python3 .specship/ledger/specship_ledger.py summary --since 2026-04-12

# Sessions by command and outcome
python3 .specship/ledger/specship_ledger.py query "
    SELECT command, outcome, COUNT(*) AS n
    FROM sessions
    GROUP BY command, outcome
    ORDER BY n DESC
"

# Export to CSV for a BI tool
python3 .specship/ledger/specship_ledger.py export-csv sessions.csv --table sessions
```

The full event schema and command-specific logging patterns are documented in `.specship/ledger/HOW-TO-LOG.md`. For the regulated-environment context, the JSONL ledger satisfies the AIRG "AI usage inventory" and "monitoring" requirements; commit it to git and the audit trail is portable across machines.

## The decision log

Every `/work` session may make choices the spec didn't dictate — picking one library over another, handling an edge case the spec was silent on, modifying a verification step. These choices are easy to miss in code review because they live inside diffs, not as explicit artifacts.

specship captures these via `decision_logged` events in the ledger and provides `/review-decisions` as the human review affordance. The flow:

```
/work  →  logs each non-obvious choice as a decision_logged event
        →  surfaces decisions in the post-flight summary

/review-decisions  →  presents unreviewed decisions
                   →  user marks each: accepted | rejected | needs-redo
                   →  records decision_reviewed events back to the ledger
```

Three verdicts, with deliberate distinctions:

- **accepted** — the choice was sound; record agreement and move on
- **rejected** — the choice was wrong but the cost of redoing it exceeds the cost of accepting; the trail records disagreement but the code stands
- **needs-redo** — the choice was wrong and must be fixed before merge; after `/review-decisions`, re-invoke `/work` with the override

The original `decision_logged` events are append-only; verdicts are layered on top as `decision_reviewed` events. This means audits can answer "what did Claude decide?" *and* "what did the human think of it?" as separate questions with separate trails.

```bash
# Show decisions that haven't been reviewed yet
python3 .specship/ledger/specship_ledger.py query "
    SELECT artifact, summary, ts
    FROM decisions WHERE review_verdict IS NULL ORDER BY ts DESC
"

# Show all rejections with the reviewer's reasoning
python3 .specship/ledger/specship_ledger.py query "
    SELECT artifact, summary, reviewer_note, reviewed_at
    FROM decisions WHERE review_verdict = 'rejected'
"
```

## The learning loop

When `/investigate` finds a root cause and `/fix` ships a resolution, that's only half the value. The other half is making sure the same class of bug can't happen the same way again. `/encode-lesson` is the closure step: it promotes a lesson from an investigation into a durable invariant — a line in `CLAUDE.md` (or in a nested `CLAUDE.md`, or in a skill's gotchas, or in a slash command's prompt) that every future Claude session reads automatically.

The flow is intentional:

```
/investigate  →  /fix --from-investigation  →  /work  →  ship  →  observe fix holds  →  /encode-lesson
   ↑                                                                                          │
   │                                                                                          ▼
   └──── future bugs can no longer happen the same way: the invariant is on every read ────────┘
```

The command refuses to encode lessons from unresolved investigations, refuses motherhood statements ("write good tests"), refuses lessons that duplicate existing invariants, and refuses to add more than 3 lessons from one investigation. The discipline is high because invariants are read on every Claude session — bloat them and you slow the agent down.

Each encoded lesson carries a stable ID and a linkback comment that points to the investigation it came from. The ledger logs `lesson_encoded` events into a `lessons` table:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT lesson_id, destination_path, source_investigation
    FROM lessons ORDER BY ts DESC
"
```

This answers the auditor question: "show me every lesson your team has encoded into the system as a result of an investigation."

### Continual learning: auto-lessons

specship captures lessons from finished sessions automatically and feeds them into the
deliberate `/encode-lesson` promotion path:

- **`/capture-lessons`** records up to 3 lesson candidates per session — user corrections,
  confirmed approaches, preferences, surprising decisions. Runs automatically at session end
  (via a `SessionEnd` hook the installer can wire up) and at the end of `/work`, `/ship`,
  `/fix`. Idempotent per session.
- **An hourly curator** (`.specship/lessons/curate.sh`, no LLM) decays stale candidates and
  clusters related ones into consolidation suggestions. Add it to cron, or run
  `./scripts/install.sh --with-cron` to wire it up.
- **`/review-lessons`** surfaces pending candidates so you can promote, dismiss, or skip each.
- **`/encode-lesson --from-candidate <id>`** promotes a reviewed candidate into a durable
  CLAUDE.md invariant — same human-gated guardrails as the investigation path.

Candidates never auto-write to CLAUDE.md; only the human-gated `/encode-lesson` does. The
candidate buffer lives in the observability ledger and self-cleans via decay.

## Contract integrity (hash + structural diff)

Full-stack work hash-locks the API contract via two complementary mechanisms:

**Hash-based drift detection** (the original):
1. `/contract` computes a SHA-256 over the normalised "Contract surface" section of the spec
2. That hash is stamped into every generated artifact's header
3. `/work` recomputes and refuses to proceed if it doesn't match

This catches *that* the contract changed.

**Structural breaking-change detection** (new in v0.8.0):
1. When `/contract` re-runs against a spec it's seen before, it diffs the previous OpenAPI artifact against the new one
2. The diff is classified as additive (safe) or breaking (needs attention)
3. Breaking changes require explicit user confirmation before artifacts are written

This catches *what kind* of change was made.

The structural check uses `oasdiff` if installed (gold-standard OpenAPI breaking-change detection across all OpenAPI 3.x semantics). If `oasdiff` isn't on PATH, a built-in Python fallback detects the most common breaking changes: removed endpoints, removed fields, type changes, new required fields, removed enum values, removed response statuses, required-parameter additions. The fallback is "good enough to refuse a silently breaking change"; the install script tells users how to install `oasdiff` for full coverage:

```bash
go install github.com/oasdiff/oasdiff@latest
```

The ledger records every breaking-change check in a `breaking_changes` table:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT tool, breaking, findings_count, ts
    FROM breaking_changes ORDER BY ts DESC LIMIT 10
"
```

Over time, the ratio of breaking vs clean re-compilations indicates how often the team ships contract-breaking changes — useful signal for API stability retrospectives.

## Adopting specship on an existing codebase

Most adopters have thousands of lines of existing code and no specs. The path:

1. **Install specship** with `./scripts/install.sh /path/to/your/repo`
2. **Write your CLAUDE.md** using the `claude-md-architect` skill (or convert your existing one)
3. **Backfill specs incrementally** using the `spec-reverse-engineer` skill, scoped to one module or endpoint at a time. Bulk reverse-engineering produces unreviewable output.
4. **For new work**, use the standard `/spec → /work` (or `/spec → /contract → /work` for full-stack) loop.
5. **For bugs in already-reverse-engineered code**, use `/fix`. The fix will reference the reverse-engineered spec.

You don't need 100% spec coverage to benefit. The pre-commit hook only enforces spec-linkage on changed `src/` files. If a file hasn't been touched and has no spec, that's fine — it stays as it is. The discipline kicks in when you modify the file.

What does NOT work:

- Bulk auto-generation of specs for the whole codebase in one pass (the output is unreviewable; the skill will warn you)
- Promoting reverse-engineered specs to `draft` without reviewing the `[needs review]` flags (the skill won't do this for you)
- Trying to reverse-engineer pure refactors with no observable behaviour (skip these)

See the `spec-reverse-engineer` skill's reference files for migration rules per source format.

## The skills

Two skills, both user-scoped — installed under `~/.claude/skills/` once, then available in every repo.

### `claude-md-architect`

Writes or converts `CLAUDE.md` files. Four modes:

- **Greenfield** — write a new CLAUDE.md from scratch
- **Conversion** — restructure an existing CLAUDE.md (or AGENTS.md) into the template
- **Audit** — score a CLAUDE.md against the template; surface gaps
- **Hierarchy** — design or refactor nested CLAUDE.md files for monorepos

### `spec-reverse-engineer`

Reverse-engineers specship spec files from material that already exists: source code, existing documentation, OpenAPI definitions, BDD `.feature` files, or specs from other frameworks (Spec Kit, BMAD, Kiro, Tessl). For when you adopt specship on a codebase that already has thousands of files and no specs.

Three scenarios:

- **From code only** — reads source, extracts contract surface from type signatures and routes, extracts acceptance criteria from test assertions
- **From existing docs** — migrates Confluence/Notion/OpenAPI/BDD content into specship's section shape
- **Hybrid** — uses both signals, marks conflicts for human adjudication

Honest about its limits: produces specs with status `draft-reverse-engineered`, marks uncertain sections `[needs review]`, never auto-promotes to `draft`. The user reviews and confirms before the spec is usable with `/work` or `/contract`.

## The Wall (pre-commit hook)

A small bash hook that blocks commits which touch `src/` (or `lib/`, or `app/`) without:

- a `specs/*.md` or `fixes/*.md` file staged in the same commit, OR
- a `§ref:specs/...` or `§ref:fixes/...` reference in the commit message or code

This is the audit gate. Bypassable with `git commit --no-verify` — bypasses are visible in `git log` for after-the-fact review.

Verified against five scenarios in `dist/hooks/`.

## The drift mechanism (key correctness property)

Full-stack work hash-locks the API contract:

1. `/contract` reads a spec's "Contract surface" section, **normalises** it (strips comments, trims whitespace, collapses blank lines), and computes its SHA-256.
2. That hash is stamped into every generated artifact's header (`_generated/openapi/*.yaml`, `_generated/types/*.ts`, etc.).
3. `/work` recomputes the hash and refuses to proceed if it doesn't match the artifacts.

Crucially, the hash is computed over the *Contract surface section only*, not the whole spec file. This means `/contract` can update the spec's metadata (status, contract hash, artifacts list) without breaking the hash equality. The mechanism is verified against three properties:

- Metadata edits don't change the hash ✓
- Real contract edits DO change the hash ✓
- Cosmetic whitespace changes don't change the hash ✓

A reference Python implementation lives at `dist/commands/contract_hash.py`. Test fixtures under `dist/commands/test-fixtures/`.

## Why this design, and what it isn't

The workflow was sparked by the Two-Commander model from a blog post arguing for two human roles managing an agent fleet. The model is rhetorical — what it actually describes is *artifact-centric authority*: the spec carries the contract, the fix carries the bug context, the generated artifacts carry the API boundary, and the commit history carries the audit trail. Tools enforce the boundaries; one human (or several wearing different hats) drives the artifacts through stages.

`specship` is the minimum viable implementation of that idea. It deliberately omits:

- The "two-commander org chart" rhetoric (the human roles aren't the architecture)
- Agent personas (Claude Code's built-in subagents handle that)
- An elaborate framework with 20+ commands

If you need any of those, fork and extend. The README in `dist/commands/` describes when to add each piece and what trigger justifies it.

## Working on this repo itself

This repo eats its own dog food: it uses its own commands and skill to develop itself.

```bash
# After editing files under dist/, sync them into .claude/ for local use
./scripts/sync-local.sh

# Then in Claude Code, you can use /spec, /contract, /work etc. on this repo
```

CI verifies the sync via `./scripts/verify-sync.sh`. PRs that change `dist/` but not `.claude/` will fail.

## Project status

- v6 — current. Full feature set: four work commands, bug-fix workflow, nested CLAUDE.md, hash-locked contracts.
- Active maintenance, but not yet 1.0. Breaking changes possible at the command-prompt level until 1.0.

## Contributing

See `.github/CONTRIBUTING.md`. The short version: edit `dist/`, run `./scripts/sync-local.sh`, commit both, open a PR. CI will reject PRs that break the sync invariant.

## License

MIT. See `LICENSE`.

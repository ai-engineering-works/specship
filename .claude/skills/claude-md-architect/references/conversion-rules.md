# Conversion Rules

Detailed rules for converting existing CLAUDE.md / AGENTS.md / project rules files into the specship template.

## The invariant vs. convention distinction

This is the most important judgement call in any conversion. Get it wrong and the file either has no teeth (everything is "soft guidance") or becomes oppressive (everything is "non-negotiable").

**An item is an invariant if violating it would:**
- Break the audit trail or regulatory posture
- Cause a production incident
- Violate a contractual or legal obligation
- Break a downstream system in a non-recoverable way
- Have caused a real incident before (lesson encoded)

**An item is a convention if violating it would:**
- Make the code less readable
- Diverge from team style
- Cause review friction
- Be "annoying" but not damaging

When in doubt, treat it as a convention. Invariants must earn their place.

## Classification table

| Source content shape | Target section | Notes |
|---|---|---|
| "This system does X for Y" | What this codebase is | Keep to 2–4 sentences |
| "Architecture overview: this system has 5 services..." | EXTRACT to architecture.md | CLAUDE.md links to it |
| "Never delete from audit tables" | Non-negotiable invariants | Hard data integrity rule |
| "All Kafka consumers must handle X" | Non-negotiable invariants | Operational guarantee |
| "Multi-character delimiters use `~|~`" | Non-negotiable invariants | Cross-system contract |
| "Comply with MAS AIRG / SOX / GDPR" | Non-negotiable invariants | Regulatory |
| "Use type hints" | Conventions worth following | Style |
| "Prefer composition over inheritance" | Conventions worth following | Soft guidance |
| "Write tests alongside code" | Conventions worth following | Workflow preference |
| "Run `pytest tests/`" | How to verify work is done | Mechanical |
| "All checks in CI must pass" | How to verify work is done | Reference CI explicitly if it lists commands |
| "Make sure code is well-tested" | DROP or rewrite as command | Not mechanical |
| "src/ contains production code" | Where things live | One-liner |
| "Detailed module-by-module breakdown" | EXTRACT to architecture.md | Too long for CLAUDE.md |
| "NCBS = New Core Banking System" | Domain glossary | One-liner |
| "Be concise in responses" | DROP | Belongs in user preferences |
| "Don't apologise excessively" | DROP | Assistant behaviour, not project |
| "When using bash, prefer rg over grep" | Conventions OR drop | Only if it matters for this project |
| "Always ask before deleting files" | DROP | Generic assistant safety, not project-specific |

## Edge cases

### Aspirational invariants
If the source file has "all code must have 100% test coverage" but the actual repo has 40% coverage, this is aspirational. Demote to convention, or drop, and flag to the user. Invariants that aren't enforced erode the credibility of the whole list.

### Compound rules
"Never deploy on Fridays AND always notify the on-call team" — split into two invariants. One rule per bullet.

### Rules with exceptions
"Never delete audit tables, except during scheduled cleanup runs" — write as: "Never delete from audit tables outside the scheduled cleanup job (`jobs/audit_cleanup.py`)." The exception is part of the rule.

### Rules that are really questions
"Should we use Redis or Kafka here?" — this is an open architectural question, not an invariant. Move to a separate "Open questions" or "Architectural decisions pending" file, or drop entirely. CLAUDE.md is for settled rules.

### Tooling instructions
"Use the script `tools/lint.sh` to lint" — if this is the verification command, put it in "How to verify work is done". If it's a how-to-do-X instruction, it likely belongs in a runbook, not CLAUDE.md.

### Personality and tone
"Be helpful, be concise, don't be apologetic" — drop. These are assistant preferences, not project rules. If the user wants them preserved, suggest moving them to their personal user preferences (a separate mechanism).

## What to drop without ceremony

- "Please remember to..." prefixes
- "It's important that..." prefixes
- Repeated emphasis ("VERY IMPORTANT", "CRITICAL", "MUST")
- Generic safety advice ("be careful with deletions")
- Generic AI behaviour rules ("don't make up information")
- Long explanatory prose justifying rules (the rule itself is the rule; justification can live in commit history or ADRs)

## What to extract to separate files

Move out of CLAUDE.md if:
- A single section exceeds ~30 lines
- The total file is heading past 200 lines
- Content is genuinely reference material (architecture, full runbook, full glossary with 50+ terms)
- Content is procedural (a runbook, a deployment guide)

Link from CLAUDE.md with a short pointer:
```markdown
## Where things live

- `src/` — production code
- See `docs/architecture.md` for the full module breakdown
- See `runbooks/` for operational procedures
```

## Sanity checks before declaring done

After conversion, verify:

1. **Line count ≤ 200.** If over, extract more.
2. **Every invariant is mechanical or referenced.** No "good code", "clean architecture", "high quality".
3. **Every verification step is a command or a precise check.** "Tests pass" → "`pytest tests/` exits 0".
4. **No tone/personality content.** Search for "be ", "don't be", "please", "remember to" — these are red flags.
5. **Section order matches the template.** Tools downstream depend on this.
6. **No invented content.** Every invariant traces to something the user provided or a clear signal from the repo.

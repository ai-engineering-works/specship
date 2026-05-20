# Migrating existing docs and specs into specship format

How to convert documents from other formats into `specship` spec files. Covers OpenAPI/AsyncAPI, BDD `.feature` files, Confluence-style markdown, JIRA exports, and other spec frameworks (GitHub Spec Kit, BMAD, Kiro, Tessl).

## General principles

1. **Preserve the user's terminology.** Project names, domain terms, internal acronyms — keep them verbatim. The skill is restructuring, not editorialising.
2. **Tighten aggressively.** A 6000-word Confluence page becomes a 150-line spec. Most of what was in the doc was rationale, screenshots, or change history — none belong in an `specship` spec.
3. **Drop what doesn't fit.** Architecture diagrams, deployment instructions, runbook content — these don't belong in specs. Extract them to separate files (`docs/architecture.md`, `runbooks/`) and link from the spec's Notes section.
4. **Surface drops explicitly.** When you drop a section, say so in the spec's Notes, with a pointer to where it went (or note that it was deliberately omitted as out-of-scope for specs).

## Source format: OpenAPI / AsyncAPI

This is the **easiest** migration. OpenAPI documents are nearly a Contract surface section already.

### Mapping

| OpenAPI element | specship section |
|---|---|
| `info.title`, `info.description` | Spec title, Intent |
| `paths.<path>.<method>` | Contract surface → HTTP endpoints subsection |
| `components.schemas` | Contract surface → Shared types subsection (translate to TypeScript) |
| `paths.<path>.<method>.responses.<code>` | Response shapes per endpoint |
| `paths.<path>.<method>.security` | Auth field per endpoint |
| `paths.<path>.<method>.parameters` | Request body or path/query parameter declarations |
| `info.version` | Implicit version; `/contract` will manage this going forward |
| `servers`, `externalDocs` | Notes section |
| `tags` descriptions | Notes section |

### Translating schemas to TypeScript (the canonical specship shared-types format)

OpenAPI `type: string, format: date-time` → TS `string` with annotation in description
OpenAPI `type: object, required: [a, b], properties: {a, b, c}` → TS object with `a: T1; b: T2; c?: T3`
OpenAPI `oneOf: [...]` → TS union `T1 | T2 | T3`
OpenAPI `nullable: true` → TS `T | null`
OpenAPI `enum: [a, b, c]` → TS literal union `'a' | 'b' | 'c'`

### What to drop from OpenAPI

- `x-*` extensions unless they convey contract-relevant info
- Example payloads (specs are shape, not examples)
- Verbose descriptions on every field (keep only what's non-obvious)

If the source OpenAPI is auto-generated from code (FastAPI, NestJS, Spring), prefer reverse-engineering from the *code* (`references/from-code.md`) over migrating from the generated OpenAPI. The code carries more intent than its OpenAPI projection.

## Source format: AsyncAPI

Same shape as OpenAPI but for events. Map:

| AsyncAPI element | specship section |
|---|---|
| `channels.<name>.subscribe.message` | Contract surface → Events → consume |
| `channels.<name>.publish.message` | Contract surface → Events → produce |
| `components.messages.<id>.payload` | Event schema |
| `channels.<name>.bindings.kafka.partitionKey` | Partition key field |

## Source format: BDD `.feature` files (Cucumber, SpecFlow, pytest-bdd)

BDD files are *behaviour* specs. They map cleanly to acceptance criteria but not to contract surface.

### Mapping

```gherkin
Feature: Notification preferences
  As a customer
  I want to control notification channels
  So that I receive only relevant messages

  Scenario: GET returns current preferences
    Given the customer has email notifications enabled
    When they request their preferences
    Then the response contains email channel with enabled=true
```

becomes:

```markdown
## Intent

Customers control which channels they receive notifications on, so they receive only relevant messages.

## Acceptance criteria

### Backend
- [ ] GET returns current preferences (when customer has email enabled, response contains email channel with enabled=true)
```

For the Contract surface section, BDD files don't give you enough. Either:
- Combine with code reverse-engineering (Scenario C in SKILL.md), OR
- Mark Contract surface as `[needs review — please complete; BDD scenarios don't describe HTTP shape]`

### When to keep `.feature` files alongside the spec

If the team is actively using BDD, don't delete the `.feature` files — they're the runnable acceptance tests. Reference them from the spec's "Tests required" section:

```markdown
## Tests required

- See `features/notifications.feature` for the runnable BDD scenarios
```

## Source format: Confluence-style markdown / Notion exports

These are usually long, prose-heavy, multi-purpose. Migration is the most lossy of any source format.

### Decision per source section

| Source content | Target |
|---|---|
| "Background", "Problem", "Why" sections | Intent (compressed to 2-4 sentences) |
| "Requirements", numbered requirements | Acceptance criteria |
| "API design", "Endpoints" section | Contract surface |
| "Data model", "Schemas" section | Contract surface → Shared types |
| "Out of scope", "Non-goals" | Non-goals |
| "Open questions", "TODO" sections | Open questions |
| Architecture diagrams, sequence diagrams | Extract to `docs/architecture.md`, link from Notes |
| Implementation plan, task breakdown | DROP — this is project planning, not contract |
| "FAQ" sections | DROP or extract to a separate FAQ doc |
| Change history, edit log | DROP — git provides this |
| Stakeholder discussion threads | DROP — historical, not contract |

### Confluence-specific quirks

- Confluence often has inline tables that span huge widths — re-flow them as markdown tables (or, if data-heavy, extract to a separate file).
- Confluence inserts auto-generated TOC at the top — drop it; markdown rendering can re-generate.
- Confluence "info macros" (⚠️ note, info, warning) — preserve the content; drop the macro wrapper.

### Handle staleness

If the doc has a "last modified" date older than 6 months, surface that in the spec's Notes:

```markdown
## Notes

Migrated from `docs/notifications-design.md`, last edited 2024-11-03 (18 months
old at time of migration). Specific items that may be stale:
  - Auth mechanism described as "JWT bearer"; verify if still accurate
  - Mentioned "v2 of payment API" — confirm version still current
```

## Source format: JIRA tickets / Linear issues

JIRA tickets are *requirements* not specs. They describe a unit of work, not a contract.

### When to migrate

- The ticket has detailed acceptance criteria → those become spec acceptance criteria
- The ticket has a long technical description → that becomes Intent (compressed)
- The ticket has comments resolving open questions → those go into Notes
- The ticket links to a design doc → migrate from the design doc (richer source)

### What to drop

- Status, priority, assignee, sprint info — drop
- Comment threads about scheduling, blockers, dependencies — drop
- Screenshots — extract to a separate `docs/` if essential, else drop
- Subtask lists — drop; these are project management

### Citing the source

Put the JIRA ticket ID in the spec's metadata:

```markdown
**Ticket:** NOTIF-42
```

And in Notes:

```markdown
## Notes

Migrated from JIRA NOTIF-42 (originally raised 2024-09-12).
Subsequent comments NOTIF-42#23 and NOTIF-42#31 resolved the open
questions about idempotency — see acceptance criteria below.
```

## Source format: Other spec frameworks

### GitHub Spec Kit (`specify` / `.specify/`)

Spec Kit produces `constitution.md`, `spec.md`, `plan.md`, `tasks.md`. Map:

| Spec Kit file | specship target |
|---|---|
| `.specify/memory/constitution.md` | Merge into `CLAUDE.md` via the `claude-md-architect` skill (not this skill) |
| `specs/<feature>/spec.md` | New `specs/<date>-<feature>.md` in specship format |
| `specs/<feature>/plan.md` | DROP — specship doesn't separate plan from spec |
| `specs/<feature>/tasks.md` | Acceptance criteria (each task becomes a `- [ ]`) |
| `specs/<feature>/checklists/manual-testing.md` | Tests required section |

Spec Kit's "constitution → spec → plan → tasks → implement" pipeline collapses into specship's "spec → contract → work" pipeline. The phase separation between plan and tasks is dropped; specship's plan-mode in `/work` covers the same purpose.

### BMAD-METHOD

BMAD produces brief-PRD-architecture-stories cascading documents. Map:

| BMAD doc | specship target |
|---|---|
| Brief | DROP or compress to Intent (1-2 sentences) |
| PRD | Intent + Non-goals + Acceptance criteria |
| Architecture | Extract to `docs/architecture.md`, link from Notes |
| Story | One spec per story |
| Epic | DROP — specship doesn't model epics; cross-spec relationships go in Notes |

### Kiro

Kiro's spec format (Requirements/Design/Tasks) maps similarly to Spec Kit. The Requirements section is the main input for Intent + Acceptance criteria; Design is mostly Contract surface.

### Tessl

Tessl uses Markdown specs with structured frontmatter. Most fields map directly:

| Tessl frontmatter | specship target |
|---|---|
| `title` | Spec title |
| `description` | Intent |
| `accept` (array of acceptance assertions) | Acceptance criteria |
| `inputs`, `outputs` | Contract surface (HTTP endpoints if web service; types if library) |

Tessl is the closest in spirit to specship — migration is usually mechanical.

## After migration

Regardless of source format, every migrated spec gets:

- Status: `draft-reverse-engineered`
- Metadata field `Reverse-engineered from:` listing the source paths
- `[needs review]` flags on any section where the source didn't clearly fit specship's shape
- A Notes section describing what was dropped and why

The user reviews, refines, and promotes to `draft` (or `contract-locked` if `/contract` runs against it). The skill never auto-promotes.

## Drop list (always drop, from any source)

- Tool-specific metadata (sprint, status, ticket lifecycle states)
- Stakeholder name lists
- Change history (git provides this)
- "What this isn't" sections written defensively (rewrite as Non-goals only if concrete)
- AI-generated boilerplate ("This document was created with the help of AI...")
- Self-referential meta-commentary about the spec's own structure
- Approval signatures and dates (the audit trail is in version control, not the spec content)

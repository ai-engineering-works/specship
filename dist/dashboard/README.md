# specship dashboard

A single-file, static HTML read-only dashboard for visualising the specship
ledger. Senior management can see aggregate signal; senior engineers can
drill from business intent down to individual decisions and commits.

## What it shows

**Level 1 — all business intents (specs, fixes, investigations) in one list**
- Aggregate metrics: total intents, sessions, wall time, coverage failures
- Friction signals: diagnostic observations with suggested actions
- Filterable by status (active / done) or kind (spec / fix / investigation)

**Level 2 — single intent detail**
- Header with status, kind, ticket, opened-at
- Workflow timeline: ticket → spec/fix/investigation → contract → work → review → commits
- Tabs: Decisions (with human verdicts), Coverage measurements, Drift findings,
  Lessons encoded, Claude metrics

**Level 3 — artifact metadata viewer**
- Shows the ledger's view of a specific spec/fix/investigation file
- The dashboard does not read file contents — open the .md in your editor

## How to open it

The dashboard installs at `.specship/dashboard/dashboard.html`. It reads from
`../ledger/events.jsonl` (relative path). Three ways to view it:

### Easiest: local HTTP server (works in any browser)

```bash
cd .specship
python3 -m http.server 8765
# Open http://localhost:8765/dashboard/dashboard.html
```

### Alternative: file:// URL with file picker

```bash
open .specship/dashboard/dashboard.html
# Then click "Choose events.jsonl" and select .specship/ledger/events.jsonl
```

`file://` URLs can't fetch sibling files due to browser security; the file
picker is the workaround.

### Air-gapped / offline

The dashboard has zero network dependencies — no CDN, no fonts loaded
over the network, no remote scripts. It works offline in any modern browser.

## What is NOT shown today

The "Claude metrics" tab is a placeholder. specship v0.10.0 does not yet
capture per-query token counts, model used per query, or cost. These will
be added by a future `tokens_consumed` event type (planned for v0.11.0).
The dashboard is designed so those panels become populated automatically
once the events exist.

Other deliberate non-features:
- No write capabilities (use `/review-decisions` to mark verdicts; the
  dashboard surfaces what exists)
- No git diff rendering (use GitHub or your IDE)
- No multi-repo aggregation (one ledger, one repo)
- No file content rendering (open the .md in your editor for that)

## Reading the friction signals

The signals panel surfaces patterns from the ledger that suggest where
specship could deliver more value. Examples you may see:

- "3 specs in draft >7 days" → either start `/work` or close the spec
- "5+ decisions logged per spec" → Contract Surface may be under-specified
- "Coverage failures with bypasses" → review the policy in CLAUDE.md
- "Resolved investigations, no lessons encoded" → the learning loop isn't
  closing

These are diagnoses, not metrics. They're meant to prompt a conversation,
not generate a report.

## What runs the dashboard

It's a single `.html` file (~46 KB). Open it. There's no service to maintain,
no build step, no package to install. The HTML embeds:
- All CSS (light + dark mode)
- A minimal markdown-style renderer for artifact metadata
- JSONL parsing and in-memory model in pure JS (no SQL.js, no IndexedDB)

The ledger is JSONL, append-only, ~10 KB per 50 events. Even a multi-year
repo will read in under a second.

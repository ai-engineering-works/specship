---
description: List and search specship artifacts (specs, fixes, investigations, QA) by title, ticket ID, kind, or status. Read-only convenience for discovery within Claude Code without leaving the chat.
argument-hint: [specs|fixes|investigations|qa|all|recent|<query>] [--status <s>] [--all]
recommended-model: sonnet  # sonnet — see CLAUDE.md
---

# /show — List or Search Artifacts

You are running a read-only discovery query against the specship ledger. Help the user find a spec, fix, or investigation without leaving the Claude Code chat.

## What this command does

- Lists artifacts of a given kind (or all kinds) from the indexer
- Searches by title, ticket ID, or filename substring
- Filters by status if requested
- Prints compact, scannable output the user can copy paths from

This command does NOT:
- Read artifact contents (use `view` on a path you find here)
- Modify the ledger or any files
- Search the body text of artifacts (use `grep -ril '<pattern>' specs/ fixes/ investigations/` for that)
- Log events (this is a convenience, not a workflow step)

## Inputs

The user has invoked: $ARGUMENTS

Parse the arguments with these rules:

**First positional argument** (kind or query):
- If it's one of `specs`, `fixes`, `investigations`, `qa`, `all`, `recent` → it's a kind filter
- Otherwise → treat as a search query (and search across all kinds)

**Second positional argument** (when first is a kind):
- Free-text search query within that kind

**Flags**:
- `--status <s>`: filter by current_status (e.g., `signed-off`, `done`, `in-progress`, `draft`)
- `--all`: show ALL matching rows, not just the top 30

**Examples**:
- `/show specs` — all specs, most recent first
- `/show specs subscription` — specs whose title or ticket_id contains "subscription"
- `/show fixes --status done` — completed fixes only
- `/show TICKET-247` — any artifact with this ticket ID
- `/show all unicode` — search "unicode" across specs/fixes/investigations
- `/show recent` — last 20 artifacts touched
- `/show qa` — list QA artifacts (regressions and scenarios)

## How to query the ledger

Use the SQLite indexer at `.specship/ledger/index.db`. The `artifacts` table has path/kind/status/timestamps; titles and ticket_ids live in the `events` table's `raw_json` column and can be extracted via `json_extract()`.

The canonical query for listing specs/fixes/investigations:

```sql
SELECT
    a.path,
    a.kind,
    a.current_status,
    a.last_updated,
    json_extract(e.raw_json, '$.ticket_id') AS ticket_id,
    json_extract(e.raw_json, '$.title')     AS title
FROM artifacts a
LEFT JOIN events e
    ON e.artifact_created_path = a.path  -- pseudo; see note below
WHERE a.kind IN ('spec', 'fix', 'investigation')
ORDER BY a.last_updated DESC
```

Important: the `events` table joins to artifacts by the `path` field which is stored inside `raw_json` (not in the `artifact` column for `artifact_created` events — that's the historical field-name drift documented in HOW-TO-LOG.md). The actual join needs to extract the path from raw_json. A working query:

```sql
SELECT
    a.path,
    a.kind,
    a.current_status,
    a.last_updated,
    (SELECT json_extract(e.raw_json, '$.ticket_id')
       FROM events e
       WHERE e.event_type = 'artifact_created'
         AND json_extract(e.raw_json, '$.path') = a.path
       LIMIT 1) AS ticket_id,
    (SELECT json_extract(e.raw_json, '$.title')
       FROM events e
       WHERE e.event_type = 'artifact_created'
         AND json_extract(e.raw_json, '$.path') = a.path
       LIMIT 1) AS title
FROM artifacts a
WHERE a.kind IN ('spec', 'fix', 'investigation')
ORDER BY a.last_updated DESC
```

For QA artifacts, query `qa_artifacts` instead of `artifacts` (same join pattern using `qa_artifact_created` events).

Run via:

```bash
python3 .specship/ledger/specship_ledger.py query "<sql>"
```

The output is tab-separated. Parse it back into rows you can format for the user.

## Step-by-step

1. **Parse the arguments** per the rules above. Decide:
   - `kinds`: which kinds to filter to (default: `['spec', 'fix', 'investigation']`)
   - `query`: the search substring (default: none)
   - `status`: the status filter (default: none)
   - `limit`: 30 unless `--all`

2. **Build the SQL**:
   - Start from the base query above
   - If `query` is set, add `AND (LOWER(json_extract(e.raw_json,'$.title')) LIKE '%<lq>%' OR LOWER(json_extract(e.raw_json,'$.ticket_id')) LIKE '%<lq>%' OR LOWER(a.path) LIKE '%<lq>%')`. Note: SQLite LIKE is case-sensitive by default for ASCII; use LOWER() on both sides.
   - If `status` is set, add `AND a.current_status = '<status>'`
   - If kind is `recent`, omit kind filter and `LIMIT 20` (regardless of `--all`)
   - For `qa` kind, query the `qa_artifacts` table instead

3. **Run the query**. If it fails (e.g., index.db missing), tell the user to run `python3 .specship/ledger/specship_ledger.py rebuild-index` first.

4. **Format the output**. Compact columnar text:

```
Found <N> artifacts<, top <limit> shown if truncated>

  by kind:    <counts>
  by status:  <counts>

TICKET-XXX  kind        status        path                                          title
TICKET-YYY  kind        status        path                                          title
```

Column widths: ticket_id 10-12 chars, kind 6, status 14, path variable (longest in result set, max 50), title variable. If a column overflows, truncate with ellipsis.

If `query` was set, mention what was matched: `(searched: title, ticket_id, path)`.

5. **Suggest next actions**. End with one line:

```
To view a file: paste the path. To act on it: /qa, /work, /ship take the path directly.
For body-text search across all artifacts: grep -ril '<pattern>' specs/ fixes/ investigations/
```

## Edge cases

- **No `.specship/ledger/index.db` found**: tell the user this looks like a repo without specship installed, or the index needs rebuilding. Don't fail loudly.

- **Index exists but no artifacts match**: tell the user clearly. Suggest: maybe loosen the filter, or try `/show all` to see everything.

- **Index has 0 events**: this is a fresh install. Tell the user: "No artifacts yet — run `/spec`, `/fix`, or `/investigate` to create one."

- **A search query that looks like a ticket ID** (`TICKET-247`, `BUG-882`, `[A-Z]+-\d+`): match it case-insensitively against ticket_id field specifically, not just title. People often type "247" expecting it to find "TICKET-247".

- **The user types `/show foo bar baz`** with multiple words: treat as a single search phrase across all kinds. Don't try to be clever.

- **Status filter that doesn't exist**: tell the user the valid status values from the result set (or the standard ones: `draft`, `in-progress`, `signed-off`, `contract-locked`, `ready-for-review`, `done`).

## What to output (concrete)

For a successful query, output ONLY:

1. One-line header with total count (and "top N shown" if truncated)
2. A two-line breakdown (by kind, by status) — skip if results are 5 or fewer
3. Blank line
4. Compact table of results
5. Blank line
6. One-line footer with the suggestion to grep for body search (only if no `query` was supplied)

Do NOT:
- Wrap the output in code fences
- Add explanatory prose
- List markdown-formatted bullet points
- Suggest editing the artifacts

The user asked for discovery, not commentary. Give them the data.

## Examples of expected output

`/show specs` →

```
Found 12 specs

  by status: 7 done · 3 signed-off · 2 in-progress

TICKET-247  spec  signed-off    specs/2026-04-15-notif-prefs.md          Customer notification preferences
TICKET-156  spec  done          specs/2026-04-20-csv-export.md           Monthly statement CSV export
TICKET-201  spec  in-progress   specs/2026-05-02-bulk-actions.md         Bulk subscription actions
...
```

`/show fixes csv` →

```
Found 2 fixes matching "csv"

TICKET-882  fix   done          fixes/2026-04-20-fix-csv-unicode.md      CSV export breaks on unicode names
TICKET-919  fix   done          fixes/2026-05-01-fix-csv-empty-row.md    CSV export emits empty trailing row

(searched: title, ticket_id, path)
```

`/show TICKET-247` →

```
Found 1 artifact matching "TICKET-247"

TICKET-247  spec  signed-off    specs/2026-04-15-notif-prefs.md          Customer notification preferences
```

`/show recent` →

```
Recent 20 artifacts (most recently updated first)

TICKET-201  spec  in-progress   specs/2026-05-17-bulk-actions.md         Bulk subscription actions
TICKET-882  fix   done          fixes/2026-05-15-fix-csv-unicode.md      CSV export breaks on unicode names
...
```

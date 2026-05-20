---
description: Surface decisions logged by /work (and other commands) for human review. Lists recent unreviewed decisions, lets the user mark each as accepted, rejected, or needs-redo, and records the review verdict back to the ledger. The original decision logs are append-only — review verdicts are layered on top, not destructive.
argument-hint: [<spec-or-fix-path>] [--since DATE] [--unreviewed]
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /review-decisions — Human-in-Loop Decision Review

You are presenting decisions Claude made during `/work` (and other commands) for human review. The decisions are already in the ledger; this command is the review affordance — it surfaces them, lets the user mark verdicts, and records the verdicts back to the ledger.

This command exists because **decisions made silently inside `/work` are easy to miss in code review.** When Claude picks one library over another, handles an edge case the spec didn't specify, or chooses a test pattern, the spec doesn't capture it but the ledger does. Without an explicit review step, the audit trail records *what* was decided without recording *whether the human agreed*.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"review-decisions command"** section. Log `session_start`, one `decision_reviewed` event per verdict the user assigns, and `session_end`.

## When to use this command

Run `/review-decisions` regularly — once per spec before declaring it `ready-for-review`, or weekly as a standing retrospective. The longer decisions go un-reviewed, the harder it is to remember the context.

Specifically use it:
- **Before promoting a spec to `signed-off`** — review decisions made during execution
- **Before merging a feature branch** — review decisions in the diff scope
- **Weekly retrospective** — review the past week's accumulated decisions across all specs
- **After a bug surfaces** — re-review decisions related to the bug's scope; maybe Claude made a choice that turned out wrong

Do NOT use it:
- During `/work` itself — that's a different mode; if you need to intervene mid-execution, halt `/work` and run it again with explicit guidance
- For trivial mechanical choices Claude logged out of paranoia — the right response is to **tighten `/work`'s decision-logging trigger**, not to mark hundreds of trivial entries reviewed

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- Optional first positional argument: path to a spec or fix file — scope the review to decisions tied to that artifact
- Optional `--since YYYY-MM-DD`: only show decisions logged on or after that date (default: last 14 days)
- Optional `--unreviewed`: show only decisions that don't yet have a review verdict (default: show all in the time window, marked by current verdict)

If no arguments: show unreviewed decisions from the last 14 days across all artifacts. This is the default daily-use behaviour.

## Pre-flight

1. **Confirm the ledger is installed and populated.** Read `.specship/ledger/index.db`. If it doesn't exist, run `python3 .specship/ledger/specship_ledger.py rebuild-index` first.

2. **Query the decisions:**

   ```bash
   python3 .specship/ledger/specship_ledger.py query "
       SELECT decision_id, ts, session_id, artifact, summary, rationale, accepted,
              review_verdict, reviewer_note, reviewed_at
       FROM decisions
       WHERE ts >= '<since>'
         <if artifact-scoped: AND artifact = '<path>'>
         <if --unreviewed: AND review_verdict IS NULL>
       ORDER BY ts DESC
   "
   ```

   If the query returns zero rows, tell the user honestly:

   ```
   No decisions to review in <window>.

   If you expected decisions but see none, either:
     - /work hasn't run on this artifact yet, or
     - /work ran but Claude judged none of its choices were non-obvious
       enough to log (this is plausible if the spec was tightly specified).

   To see all decisions ever logged, regardless of review status:
     python3 .specship/ledger/specship_ledger.py query "SELECT * FROM decisions ORDER BY ts DESC LIMIT 20"
   ```

3. **Read the ledger's `decisions` table schema.** The `review_verdict` column is one of `null` (unreviewed), `accepted`, `rejected`, `needs-redo`. The `reviewer_note` column is free-text.

## Stage 1: Present decisions for review

For each decision, format like this:

```
Decision #1
───────────
  Logged: 2026-05-10 14:23 UTC (4 hours into /work session)
  Artifact: specs/2026-05-08-notif-prefs.md
  Session: 7f2e544d... (work, scope=backend)

  Decision: Use jsonschema-rs (Rust binding) over jsonschema (pure Python)
            for spec validation in the backend.

  Rationale: jsonschema-rs is ~50x faster on our payload sizes. The pure
             Python lib is more permissive on edge-cases (e.g. format='uri'),
             but the spec's contract surface only uses the strict subset
             of JSON Schema, so the speed wins.

  Original mark from Claude: accepted

  Current review verdict: <unreviewed | accepted | rejected | needs-redo>
```

Use whatever rendering fits — markdown with rule lines is fine, plain prose is fine. Keep it under one screen per decision; if the rationale is long, truncate with "…" and offer to show full text on request.

Group decisions by artifact when there are 5+ across multiple artifacts. Otherwise show in reverse-chronological order.

If the user provided an artifact path and there are 10+ decisions, show the 5 most recent + a count of remainder, and offer pagination:

```
Showing 5 of 17 unreviewed decisions on specs/2026-05-08-notif-prefs.md.
Continue with: /review-decisions specs/2026-05-08-notif-prefs.md --since 2026-04-26
```

## Stage 2: Collect verdicts from the user

After presenting, prompt the user with their options. The default interaction:

```
For each decision, give a verdict:

  accept #1   — agreed; record as accepted, no follow-up
  reject #2   — disagreed; record as rejected. The decision stands in
                the code but the review trail captures the disagreement.
                Use this when the choice was wrong but the cost of redoing
                it now is higher than the cost of accepting it.
  redo #3     — disagreed and want to fix. Record as needs-redo. After this
                command, run /work with explicit guidance against the
                decision (e.g., /work specs/foo.md --override "use Decimal,
                not float, for all money fields").
  skip        — defer; leave unreviewed. The decision stays in the queue
                for next time.
  note #N <text> — attach a free-text note to decision N (works with any
                   verdict; useful for "we need to revisit this in Q3").

You can chain: "accept #1 #2, reject #3, redo #4 note 'do this before launch'"
```

Wait for the user. Do not assume verdicts. Do not bulk-accept silently — that defeats the purpose of the review.

## Stage 3: Record verdicts

For each verdict the user provided:

1. **Update the `decisions` table** with the verdict, note, and timestamp:

   ```bash
   python3 .specship/ledger/specship_ledger.py query "
       UPDATE decisions
       SET review_verdict = '<accepted|rejected|needs-redo>',
           reviewer_note = '<note or null>',
           reviewed_at = '<now-iso>',
           reviewed_session = '<this session_id>'
       WHERE decision_id = '<decision_id>'
   "
   ```

2. **Log a `decision_reviewed` event** to the JSONL ledger (so the audit trail captures the act of reviewing, not just the final state):

   ```bash
   log decision_reviewed session_id="\"$SID\"" \
       decision_id="\"<decision_id>\"" \
       verdict="\"<accepted|rejected|needs-redo>\"" \
       reviewer_note="\"<note or empty>\""
   ```

The ledger update is via SQL on the index DB; the JSONL log entry is the durable event. **If the SQLite index is ever rebuilt from the JSONL, the `decision_reviewed` events must re-populate the `decisions` table columns.** This is handled by the indexer in `specship_ledger.py` — it's where the "JSONL is source of truth" property earns its keep.

## Stage 4: Report

After all verdicts are recorded, tell the user:

```
Review complete:
  Accepted:   N
  Rejected:   N
  Needs redo: N
  Skipped:    N (still unreviewed)
  Notes:      N

Next actions:
  - <for each needs-redo decision: spell out the override prompt for /work>
  - Commit the review verdicts: `git add .specship/ledger/events.jsonl &&
    git commit -m "review: N decisions on specs/<file>.md"`
  - Query the audit trail anytime:
    python3 .specship/ledger/specship_ledger.py query "
        SELECT artifact, summary, review_verdict, reviewer_note
        FROM decisions WHERE review_verdict IS NOT NULL
        ORDER BY reviewed_at DESC
    "
```

If any decisions were marked `needs-redo`, **do not** auto-spawn `/work`. The user re-invokes manually with the override they want. This preserves the boundary: review is review, execution is execution.

## What this command does NOT do

- Does NOT modify any specs, fixes, code, or contract artifacts
- Does NOT auto-redo decisions marked `needs-redo` — the user re-invokes `/work` with the override
- Does NOT silently bulk-accept — every verdict is an explicit user action
- Does NOT mark decisions older than the time window — they're still queryable, just not in this session's display
- Does NOT alter the original `decision_logged` events — verdicts are layered on top as `decision_reviewed` events; the original log is append-only

## Anti-patterns

- **Rubber-stamping** — accepting every decision without reading rationale. If you're doing this, either Claude is over-logging (tighten the `/work` trigger) or the review is performative. Stop and address the root cause.
- **Reviewing too late** — decisions reviewed weeks after the fact lose context. If you can't remember why something was decided, you can't validly approve or reject it. Aim to review before merge, not after.
- **Treating `rejected` as `needs-redo`** — they're distinct. `rejected` means "the decision stands but the trail records disagreement" (typically used when the cost of redoing exceeds the cost of accepting). `needs-redo` means "fix this before merge." Mixing them muddies the audit trail.

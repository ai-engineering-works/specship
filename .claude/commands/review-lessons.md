---
description: Surface pending lesson candidates captured by /capture-lessons for human review. For each, the user can promote it (hands off to /encode-lesson --from-candidate), dismiss it (records lesson_dismissed), or leave it pending. Mirrors /review-decisions — append-only, verdicts layered on top, never destructive.
argument-hint: [--min-confidence high|medium|low] [--cluster]
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /review-lessons — Review and Triage Lesson Candidates

You are presenting lesson candidates the `/capture-lessons` command recorded, so the human
can decide which become durable invariants. This is the review affordance between automatic
capture and the deliberate `/encode-lesson` promotion. Like `/review-decisions`, it is
append-only: you never delete candidate events; verdicts are layered as new events.

## Observability ledger

This command logs to the specship ledger. Follow `.specship/ledger/HOW-TO-LOG.md` — the
**"review-lessons command"** section. Log `session_start`, one `lesson_dismissed` per
dismissed candidate, and `session_end`. Promotions are logged by `/encode-lesson` itself
(as `lesson_promoted`), not here.

## Inputs

The user invoked this with: $ARGUMENTS

Parse:
- `--min-confidence <high|medium|low>`: hide candidates below this confidence. Default: show all.
- `--cluster`: group the listing by the curator's most recent `lessons_curated` clusters.

## Pre-flight

Fetch pending candidates (status still `captured`):

```bash
python3 .specship/lessons/lessons_query.py pending ${MIN_CONFIDENCE:+--min-confidence $MIN_CONFIDENCE}
```

This returns a JSON list sorted by confidence desc. If `--cluster` was passed, also read the
latest curator digest to group related candidates:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT raw_json FROM events WHERE event_type = 'lessons_curated'
    ORDER BY ts DESC LIMIT 1
"
```

If there are no pending candidates, tell the user "No pending lesson candidates" and stop.

## Present

For each candidate (grouped by cluster theme when `--cluster` and a cluster covers it):

```
Pending lesson candidates (N):

[cluster: tooling — 3 related, consider consolidating]
  1. [tooling, high] <lesson_text>
     evidence: "<evidence_quote>"
     from: <source_command> <source_artifact>   id: <candidate_id>

  2. ...

Standalone:
  4. [preference, medium] <lesson_text>   id: <candidate_id>

For each, choose: promote <n> | dismiss <n> [reason] | skip <n>
You can also: promote all-in-cluster <theme> | dismiss-all-below low
```

Wait for the user. Do not triage unilaterally.

## Apply verdicts

### Promote

For each candidate the user promotes, hand off to `/encode-lesson`:

> Run `/encode-lesson --from-candidate <candidate_id>` for candidate <id>.

`/encode-lesson` performs the human-gated CLAUDE.md write with all its anti-bloat
guardrails, and logs both `lesson_encoded` and `lesson_promoted` (the latter folds the
candidate's status to `promoted`). You do NOT log `lesson_promoted` here — `/encode-lesson`
owns that.

If the user wants several promoted, run `/encode-lesson --from-candidate` once per id.

### Dismiss

For each dismissed candidate:

```bash
python3 .specship/ledger/specship_ledger.py log lesson_dismissed \
    candidate_id="\"<id>\"" \
    reason="\"<short reason, or 'noise'>\"" \
    session_id="\"$SID\"" \
    --quiet
```

### Skip

Leave pending — no event. It will resurface next review, and the curator will eventually
decay it if never actioned.

## Report and close

```
Reviewed N candidate(s):
  Promoted:  <ids>  → /encode-lesson handled the CLAUDE.md writes
  Dismissed: <ids>
  Left pending: <ids>

Run `python3 .specship/ledger/specship_ledger.py rebuild-index` to refresh the index,
then the dismissed/promoted candidates drop out of the pending list.
```

Log `session_end` with `outcome="completed"`.

## What this command does NOT do

- Does NOT write to CLAUDE.md — promotion delegates to `/encode-lesson`.
- Does NOT delete or edit candidate events — dismissals are append-only.
- Does NOT decay candidates — that is the curator's job.
- Does NOT capture new candidates — that is `/capture-lessons`.

---
description: Scan the current/just-ended session for lessons — user corrections, confirmed approaches, stated preferences, and decisions that surprised the user — and record up to 3 as lesson candidates in the ledger. Candidates are NOT invariants; they are reviewed later via /review-lessons and promoted (if worthy) via /encode-lesson. Idempotent per session.
argument-hint: [--session-id <id>] [--source <command>]
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /capture-lessons — Capture Lesson Candidates From a Session

You are scanning a finished (or finishing) session for lessons worth remembering, and
recording each as a *candidate* in the specship ledger. Candidates are low-stakes: they do
NOT modify CLAUDE.md. They accumulate until a human reviews them via `/review-lessons` and
promotes the worthy ones via `/encode-lesson --from-candidate`. Capture liberally but
honestly — a bad candidate costs only a later dismissal, but a motherhood statement is pure
noise and must be dropped.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in
`.specship/ledger/HOW-TO-LOG.md` — the **"capture-lessons command"** section. Log
`session_start`, one `lesson_candidate` event per captured lesson (≤3), and `session_end`.

## Inputs

The user (or the SessionEnd hook) invoked this with: $ARGUMENTS

Parse:
- `--session-id <id>`: the session being scanned. If omitted, use the current session id.
- `--source <command>`: what triggered capture (`/work`, `/ship`, `/fix`, or
  `session-end-hook`). Default `session-end-hook`.

## Idempotency pre-flight (MANDATORY)

Before capturing anything, check whether this session already has candidates:

```bash
python3 .specship/lessons/lessons_query.py has-candidates "<session-id>"
```

If it prints `yes`, this session was already captured (e.g. the `/work` end-step ran, and
now the SessionEnd hook is firing too). In that case, capture only lessons that are clearly
NOT near-duplicates of what is already recorded — query the existing candidates first:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT candidate_id, lesson_text FROM lesson_candidates WHERE session_id = '<session-id>'
"
```

If everything you would capture is already represented, stop and report "already captured."

## What counts as a lesson

Scan the session transcript for these four signals:

1. **Correction** — the user told Claude its approach was wrong ("no, not like that", "stop
   doing X", "that's not what I asked"). The lesson is what to do instead.
2. **Confirmed approach** — the user explicitly endorsed a non-obvious choice ("yes, exactly",
   "perfect, keep doing that"). The lesson is the validated approach.
3. **Stated preference** — the user expressed a durable working/style preference.
4. **Surprising decision** — Claude made a non-obvious call the spec didn't cover and it
   turned out to matter.

## The "is it checkable?" filter (reuse from /encode-lesson)

For each candidate lesson, draft it in invariant form (a directive, under 30 words) and ask:
*could a future reader tell whether this was respected?* If not, DROP it — do not record it.
Motherhood statements ("write good code", "be careful") are noise. This is the same bar
`/encode-lesson` applies; candidates that can't clear it will never be promotable anyway.

## Capture

Record at most 3 candidates (the highest-signal ones). For each, compute a stable id:

```bash
# candidate_id = first 7 chars of sha256(lesson_text + session_id)
python3 -c "import hashlib,sys; print(hashlib.sha256((sys.argv[1]+sys.argv[2]).encode()).hexdigest()[:7])" "<lesson_text>" "<session-id>"
```

Then log:

```bash
python3 .specship/ledger/specship_ledger.py log lesson_candidate \
    candidate_id="\"<id>\"" \
    lesson_text="\"<invariant-form draft>\"" \
    lesson_type="\"<architectural|module-specific|tooling|command-specific|preference>\"" \
    evidence_quote="\"<short verbatim quote that triggered it>\"" \
    source_command="\"<from --source>\"" \
    source_artifact="\"<spec/fix path or empty>\"" \
    confidence="\"<high|medium|low>\"" \
    session_id="\"<session-id>\"" \
    --quiet
```

## Report

Tell the user concisely:

```
Captured N lesson candidate(s) from session <id>:

1. [<type>, <confidence>] <lesson_text>   (id: <id>)
2. ...

These are candidates, not invariants. Review them with /review-lessons; promote the
worthy ones with /encode-lesson --from-candidate <id>.
```

If nothing cleared the checkable bar, say "No durable lessons in this session" and capture
nothing. Capturing zero is a valid, common outcome — most sessions teach nothing new.

## What this command does NOT do

- Does NOT modify CLAUDE.md or any invariant (only `/encode-lesson` does).
- Does NOT capture more than 3 candidates per run.
- Does NOT re-capture near-duplicates already recorded for the session.
- Does NOT promote, dismiss, or decay candidates — those are `/review-lessons` and the curator.

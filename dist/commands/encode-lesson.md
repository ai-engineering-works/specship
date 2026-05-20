---
description: Promote a lesson learned from an investigation (and optionally its fix) into a durable invariant in CLAUDE.md (or a nested CLAUDE.md, or a skill's gotchas, or a command prompt). Closes the learning loop so future /work sessions inherit the lesson without anyone having to remember to apply it. The investigation file is preserved unchanged; only the destination artifact is edited.
argument-hint: <investigations/<file>.md> [--fix fixes/<file>.md] [--dest <path>]
recommended-model: opus  # sonnet | opus — see CLAUDE.md for guidance
---

# /encode-lesson — Promote Investigation Findings into Durable Invariants

You are encoding a lesson learned from an investigation into a durable invariant — something Claude (and humans) will read on future sessions and apply automatically. This closes the loop between *we shipped a fix* and *we changed how we work so this class of bug can't happen the same way again*.

This command is the most consequential one in specship: every invariant added here will be read by every future `/spec`, `/work`, `/contract`, and `/fix` invocation. Bloat the invariants and you slow Claude down. Encode the wrong abstraction and you mislead. Take this seriously.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"encode-lesson command"** section. Log `session_start`, `lesson_encoded` when the invariant is added (with destination path and a content hash), and `session_end`.

## When to use this command

Use `/encode-lesson` when:
- An investigation has closed with `closed-resolved` status AND the fix has shipped
- You've observed the fix held in production (or in the relevant environment) for at least one cycle — premature encoding bakes in lessons that themselves turn out wrong
- The bug class is one that could recur in a *different shape* — i.e., the lesson generalises beyond the specific code that was fixed
- You've genuinely learned something new about the system, not just "we forgot to do X"
- A lesson candidate from `/capture-lessons` has been reviewed via `/review-lessons` and the
  human chose to promote it (`--from-candidate <id>`) — the candidate path does not require a
  formal investigation, but every other guardrail in this command still applies.

Do NOT use `/encode-lesson` when:
- The fix is a one-off (typo, copy-paste error, environment-specific) — generalising one-offs produces noise
- The investigation closed as `closed-not-reproducible` or `closed-external` — there's no system-level lesson to encode
- You haven't yet observed the fix hold — wait at least one normal usage cycle
- The lesson is already covered by an existing invariant — go re-read CLAUDE.md before proposing a new one

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: path to a `investigations/*.md` file
- Optional `--fix fixes/<file>.md`: the fix that resolved this investigation (helps inform what changed)
- Optional `--dest <path>`: explicit destination artifact for the invariant (skip the classification step)
- Optional `--from-candidate <candidate_id>`: promote a lesson candidate captured by
  `/capture-lessons` instead of starting from an investigation. When present, the first
  positional investigation argument becomes optional — the candidate's `lesson_text`,
  `lesson_type`, `evidence_quote`, and `source_artifact` stand in for the investigation's
  root-cause material.

If the investigation path is missing, ask which investigation. If multiple investigations are recent and resolved, list them.

## Pre-flight

0. **If `--from-candidate <id>` was provided**, this is the candidate-sourced path. Skip the
   investigation-status gate (steps 1-2 below) and instead read the candidate from the ledger:

   ```bash
   python3 .specship/ledger/specship_ledger.py query "
       SELECT candidate_id, lesson_text, lesson_type, evidence_quote,
              source_command, source_artifact, status
       FROM lesson_candidates WHERE candidate_id = '<id>'
   "
   ```

   - If the candidate does not exist, stop: "no such candidate <id>".
   - If its `status` is not `captured` (already promoted/dismissed/decayed), stop and tell the
     user the current status — do not re-promote.
   - Use the candidate's `lesson_text` as the Stage 1 draft lesson, its `lesson_type` for the
     Stage 2 classification, and its `source_artifact` as the linkback source. Then continue
     at Stage 1 with the human-approval gate fully intact.

   The investigation-sourced path (steps 1-2) is unchanged for invocations without
   `--from-candidate`.

1. **Read the investigation file.** Verify status is `closed-resolved`. If status is anything else, stop and tell the user:
   - `open` / `root-cause-identified` / `stalled` → "investigation isn't closed yet"
   - `closed-not-reproducible` / `closed-external` → "no system-level lesson to encode for this outcome"
   - `closed-resolved` → proceed

2. **Read the fix file** (if `--fix` was provided, or if the investigation references one).

3. **Read all CLAUDE.md files** in the repo. Use `find . -name CLAUDE.md -not -path './node_modules/*' -not -path './.git/*' -not -path './_generated/*'`. There may be a root CLAUDE.md and nested ones in subdirectories.

4. **Read all `.claude/skills/*/SKILL.md` files** if any exist locally, and all `.claude/commands/*.md` files. These are also candidate destinations for lessons.

5. **Read the ledger** to check whether a `lesson_encoded` event has already been logged against this investigation:
   ```bash
   python3 .specship/ledger/specship_ledger.py query "
       SELECT path, ts FROM events
       WHERE event_type = 'lesson_encoded'
         AND artifact = '<investigation-path>'
   "
   ```
   If there's already a lesson encoded from this investigation, surface that to the user and ask whether they want to add another or stop.

## Stage 1: Extract candidate lesson(s) from the investigation

Read the investigation's "Root cause" and "Affected scope" sections, plus the fix's "What was wrong" and "Root cause" sections if available. Draft 1-3 candidate lessons, each as a single sentence in invariant form.

A good invariant:
- Is a directive, not a description: "Never X without verifying Y" not "X can fail when Y is unmet"
- Is checkable: a human (or Claude) reading the codebase can tell whether it's been respected
- Is general beyond the specific instance: "always check connection pool size before bulk writes" generalises; "fix the bug in NotificationService line 47" does not
- Is short: under 30 words. If you can't compress it, the lesson isn't crisp enough yet
- Is honest: it admits when it's a heuristic rather than a hard rule

Examples of good invariants (the kind that compound):

> - When emitting Kafka events that affect customer-visible state, always include the customer ID in the partition key — keyless partitioning produced the duplicate-delivery incident on 2026-03-15.
> - All `pandas.read_csv` calls on files >100MB must specify `dtype=` explicitly — type inference on large files exhausted memory in the Q2 incident.
> - Any code path that handles money MUST use `Decimal`, not `float`. No exceptions, including "just for the comparison".

Examples of bad invariants (avoid):

> - Be careful with Kafka. ← not checkable, not specific
> - Write good code. ← directive but empty
> - Don't break things. ← non-actionable
> - The NotificationService.send_email method should handle the case where the user has no email address by returning early instead of throwing. ← too specific; a fix-comment, not an invariant

For each candidate lesson, also identify which type it is:

- **Architectural** — belongs in root CLAUDE.md (touches multiple parts of the system)
- **Module-specific** — belongs in a nested CLAUDE.md if one exists for that module
- **Tooling gotcha** — belongs in the relevant skill's "Gotchas" section (e.g., `claude-md-architect`, `spec-reverse-engineer`)
- **Command-specific** — belongs in a slash command's prompt (e.g., a recurring `/work` failure mode)

## Stage 2: Classify destination

For each candidate lesson, determine the right destination artifact. Present this to the user as a structured choice:

```
Investigation: investigations/<file>.md
Root cause: <one-line summary>

Candidate lessons:

1. <lesson 1 text>
   Type: <architectural | module-specific | tooling | command-specific>
   Proposed destination: <path>
   <if module-specific or command-specific: short reason>

2. <lesson 2 text>
   Type: <...>
   Proposed destination: <path>

Which lessons to encode, and to which destinations? You can:
  - Approve as proposed: type "all" or list the numbers
  - Reject one: list numbers to skip
  - Override destination: tell me the actual destination path
  - Refine wording: paste the version you want
```

Wait for the user. Do not make this decision unilaterally — invariants are a long-lived burden, the user has to live with them.

## Stage 3: Insertion

For each approved lesson:

### If destination is a CLAUDE.md file

Find the "Non-negotiable invariants" section. Append the new invariant as a list item. After the invariant, add an HTML comment with the linkback:

```markdown
## Non-negotiable invariants

- [existing invariants...]
- <new invariant text>
  <!-- from investigations/<file>.md
       fix: fixes/<file>.md
       encoded: 2026-05-12 -->
```

If the section heading is "## Non-negotiables" or "## Invariants" or some other variant, use the existing heading. Do not rename.

If the file has no "Non-negotiable invariants" section (rare but possible), insert one immediately after the "## What this codebase is" section.

### If destination is a SKILL.md

Find the "## Gotchas" or "## Common pitfalls" section. If neither exists, add a "## Gotchas" section near the end of the skill body (but before any "## Reference files" section).

Append the new lesson as a list item with the linkback comment.

### If destination is a slash command

Find the "## What not to do" section (most commands have one). Append the new pitfall as a list item with the linkback comment.

If the command file doesn't have such a section, propose one to the user before inserting — modifying command prompts has higher blast radius than modifying CLAUDE.md.

### Common to all destinations

Compute a stable identifier for the lesson — a short hash of the lesson text — and embed it in the linkback comment:

```markdown
- <invariant>
  <!-- specship:lesson:abc1234
       from: investigations/<file>.md
       fix: fixes/<file>.md
       encoded: 2026-05-12 -->
```

This identifier is what the ledger records (in the `lesson_encoded` event's `lesson_id` field). Future audits can answer "which lessons have we encoded? where do they live? which investigation each came from?" by querying:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT lesson_id, destination_path, source_investigation, encoded_at
    FROM events
    WHERE event_type = 'lesson_encoded'
"
```

(The schema relies on the projecting code in `specship_ledger.py` knowing about `lesson_encoded`'s extra fields. That's already wired in.)

## Stage 4: Cross-reference back to the investigation

After insertion, append a section to the investigation file documenting that a lesson was encoded:

```markdown
## Lesson encoded

- <lesson text>
- Destination: <path>
- Lesson ID: <stable hash>
- Encoded: 2026-05-12
```

This makes the investigation discoverable when someone later reads it, and is the audit-trail-side counterpart to the linkback comment in the destination artifact. Both directions of the cross-reference are now navigable.

Log the ledger event:

```bash
python3 .specship/ledger/specship_ledger.py log lesson_encoded \
    session_id="\"$SID\"" \
    artifact="\"<investigation-path>\"" \
    lesson_id="\"<stable-hash>\"" \
    destination_path="\"<path>\"" \
    source_investigation="\"<investigation-path>\"" \
    source_fix="\"<fix-path-or-null>\"" \
    --quiet
```

If this promotion came from `--from-candidate <id>`, ALSO log the candidate's terminal event
so its status folds to `promoted`:

```bash
python3 .specship/ledger/specship_ledger.py log lesson_promoted \
    candidate_id="\"<id>\"" \
    lesson_id="\"<stable-hash>\"" \
    destination_path="\"<path>\"" \
    session_id="\"$SID\"" \
    --quiet
```

## Stage 5: Report and close

Tell the user:

```
Encoded N lesson(s):

1. <lesson 1>
   → <destination 1>
   ID: <hash 1>

2. <lesson 2>
   → <destination 2>
   ID: <hash 2>

Cross-reference appended to: investigations/<file>.md
Ledger event logged: lesson_encoded × N

Next: commit the changes. The diff will touch <destination paths> and the
investigation file. The pre-commit hook will accept the commit since the
investigation file is staged (no new spec/fix needed).

The lesson is now live. The next time you run /spec, /work, /contract, or
/fix on this codebase, Claude will read the updated CLAUDE.md and apply
this invariant.
```

Log session_end with outcome="completed".

## Anti-patterns to refuse

If the user pushes you to encode something that violates the discipline of this command, push back. Specifically:

- **Generic motherhood statements** ("write good tests", "be careful with PII") — refuse. Tell the user: *"This isn't checkable. What specific check would future Claude perform to know whether this invariant has been respected?"*
- **Lessons from non-resolved investigations** — refuse. The investigation must have status `closed-resolved`. Tell the user to wait until the fix has held.
- **Lessons that duplicate existing invariants** — refuse and point to the existing one. If the user thinks the existing one is incomplete, edit the existing one rather than adding a new one.
- **Lessons that would make CLAUDE.md exceed 200 lines** — refuse. CLAUDE.md is the constitution; if it grows unbounded, no one reads it. Tell the user to either (a) consolidate existing invariants first or (b) promote the lesson to a nested CLAUDE.md.
- **More than 3 lessons from one investigation** — push back hard. If one investigation produces 5 lessons, the investigation found 5 things wrong with how you work. That's a culture/process issue, not 5 invariants. Ask the user to pick the most important 1-2 and document the rest as deferred.

## What this command does NOT do

- Does NOT change the investigation's status (it remains `closed-resolved`)
- Does NOT modify any specs, fixes, or `_generated/` artifacts
- Does NOT commit the changes — the user reviews the diff and commits
- Does NOT enforce that the new invariant is followed retroactively — `/check` will flag existing drift but won't auto-fix
- Does NOT propose lessons unilaterally without user approval
- Does NOT delete or modify existing invariants (only appends new ones)

## Why this command exists

In a regulated environment, the question regulators ask is not "did you have a bug?" — every system has bugs. The question is "did you learn from it?" The post-mortem produces the audit-trail answer to that question. `/encode-lesson` produces the *system-trail* answer: the codebase itself now carries the lesson, and future work will inherit it without anyone having to remember to apply it.

Goldman's framing applies directly: "productionize safe, observable agents and maintain the infrastructure of observability and guardrails." This command is part of the guardrail infrastructure. Without it, lessons stay in retrospective meeting notes and decay. With it, they accumulate in the constitution where Claude reads them every session.

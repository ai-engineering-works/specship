---
description: Create a fix artifact for a bug against an existing spec. Classifies the bug (code wrong, spec wrong, requirement evolved, spec silent) and produces a fix file under fixes/. The original spec is never overwritten — fixes carry their own history. Optional --hot flag for urgent fixes. Optional --from-investigation flag to pre-populate root cause from a completed investigation.
argument-hint: <ticket-id-or-short-description> [--against specs/<file>.md] [--hot] [--from-investigation investigations/<file>.md]
recommended-model: opus  # sonnet | opus — see CLAUDE.md for guidance
---

# /fix — Resolve a Bug Against an Existing Spec

You are creating a fix artifact for a bug. A fix is a short-form spec that lives in `fixes/`, references an existing spec, and captures *what was wrong* and *what changed*. The original spec is preserved as historical truth — fixes do not overwrite specs.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"fix command"** section. Logging is best-effort and silent. Log `artifact_created` for the fix file with its Case classification, and for Cases 2 and 4, also log `artifact_created` for the superseding spec and `artifact_updated` for the original spec.

## Why fixes are a separate artifact

Bug fixes break the assumption that "the spec is the contract". Four sub-cases each need different handling:

1. **Code was wrong, spec was right** — code didn't match its own contract. The fix updates code only. Spec unchanged.
2. **Spec was wrong, code was reasonable** — the contract itself had a defect. The fix supersedes the spec (new spec version created), and either code or spec must change to align.
3. **Requirement evolved** — neither was "wrong" originally; the world changed. This isn't a fix; it's a new spec. `/fix` will redirect you to `/spec` in this case.
4. **Spec was silent, behaviour emerged** — production revealed a constraint the spec didn't mention. The fix amends the spec by superseding it with one that includes the new constraint.

`/fix` asks the user to classify the bug into one of these cases on entry. The case determines what happens next.

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: ticket ID (e.g. `INC-789`) or short description of the bug
- Optional `--against specs/<file>.md`: the spec this bug is against. If omitted, ask the user (with a list of recent specs as candidates).
- Optional `--hot`: signals this is an urgent fix. Compresses the interaction but does NOT bypass any check. Documented below.
- Optional `--from-investigation investigations/<file>.md`: pre-populate the fix's "Root cause" and "What was wrong" sections from a completed investigation. The investigation file must have status `root-cause-identified`.

If the ticket ID matches an incident ID format (configurable; common examples: `INC-`, `P1-`, `HOTFIX-`), automatically assume `--hot` and confirm with the user.

If `--from-investigation` is passed but the investigation file's status is not `root-cause-identified`, stop and tell the user to complete the investigation first.

## Pre-flight

1. **Read `CLAUDE.md`** for invariants and conventions.
2. **Read the referenced spec.** Verify it exists. If status is `draft` or `in-progress`, this isn't a fix — the work hasn't been signed off yet. Tell the user to finish `/work` first and re-run `/fix` only against `ready-for-review`, `signed-off`, or `done` specs.
3. **Check for existing fixes against this spec.** Look in `fixes/` for any file matching `*-against-<spec-slug>.md`. If multiple fixes already exist, list them — the user may be duplicating work.

## Classify the bug

Ask the user to classify the bug. Prefer using `ask_user_input_v0` so the four cases are visible buttons:

```
What kind of bug is this?

  [Code didn't match spec]      Case 1 — code was wrong
  [Spec itself was wrong]       Case 2 — spec was wrong
  [Requirement has changed]     Case 3 — new requirement, not a fix
  [Spec was silent on this]     Case 4 — missing constraint
```

If `--hot` and the user has already described the bug clearly enough to classify, you may classify on their behalf and confirm: *"Reading this as Case 1 (code didn't match spec). Confirm?"*

### Case 3 redirect

If the user picks Case 3, stop and tell them: *"This is a new requirement, not a bug fix. Run `/spec` to create a new spec, optionally referencing `specs/<original>.md` in the Notes section to record the evolution."* Do not create a fix file.

## Draft the fix file

Create `fixes/YYYY-MM-DD-<slug>-against-<spec-slug>.md`:

```markdown
# Fix: <short title>

**Ticket:** <id or "none">
**Against spec:** specs/<original-spec>.md
**Case:** <1 | 2 | 4>
**Status:** draft
**Created:** YYYY-MM-DD
**Urgent:** <yes if --hot, otherwise omit>
**Investigation:** <investigations/<file>.md if --from-investigation, otherwise omit>

## What was wrong

<2-4 sentences. Specifically: what did the system do, what should it have done,
and how was it discovered (incident, customer report, internal find)?
If --from-investigation, pre-populate from the investigation file's
"What was observed" section.>

## Root cause

<One paragraph. Honest. "We assumed X, but Y was true under condition Z."
If --from-investigation, pre-populate from the investigation file's
"Root cause" section.

If the root cause isn't yet understood, STOP — don't draft a Resolution.
Either:
  - Use `/investigate` first to find the root cause, then run `/fix --from-investigation`
  - Mark "Under investigation" and pause the fix until the investigation completes

Fixes without verified root cause encode the same mistake forever.>

## Resolution

<For Case 1: which code is wrong and how it should change. The original spec is
authoritative; this section just says how to make code match.>

<For Case 2 or 4: which part of the spec was wrong/silent and how the new spec
should read. Pasted draft of the corrected Contract surface section, if applicable.>

## Acceptance criteria

<Mechanically verifiable. Each criterion must be backed by a test case during
`/work`: `/work` will not mark this fix `ready-for-review` until every criterion
maps to a passing test (or carries a recorded not-testable justification). The
regression test below is the test for the bug-recurrence criterion.>

- [ ] <criterion 1>
- [ ] <criterion 2>

## Regression test required

<Yes/no. If yes, describe the test that would have caught this. Add to test plan.
Regression tests for fixes are non-optional unless the fix is purely cosmetic.>

- [ ] <test description>

## Files likely to change

<Scope-grouped if the underlying spec was full-stack.>

### Backend
- `src/...`

### Frontend
- `src/...`

### Spec changes (Case 2 or 4 only)
- `specs/<new-version-of-spec>.md` (to be created — supersedes original)

## Open questions

<Block /work if any remain.>

- <question, or "none">
```

## Case-specific actions

### Case 1: code was wrong

No spec changes needed. After saving the fix file:

1. Tell the user: *"Fix file saved at fixes/<file>. Next: run `/work fixes/<file>.md` (no scope flag needed if the fix is single-scope; otherwise use `--scope`)."*
2. `/work` will treat the fix file like a spec for execution purposes. It will tick the fix's acceptance criteria, add `§ref:fixes/<file>` comments in changed code, and run verification.

### Case 2 or 4: spec was wrong / spec was silent

Spec mutation is required. The original spec is **preserved**; a new version is created.

1. Create a new spec at `specs/YYYY-MM-DD-<original-slug>-v2.md` (or `-v3` if v2 already exists).
2. The new spec:
   - Starts as a copy of the original
   - Adds a `**Supersedes:** specs/<original-spec>.md` field in metadata
   - Updates the Contract surface section (for Case 2) or adds the missing constraints (for Case 4) per the fix's "Resolution" section
   - Status: `draft`
3. The original spec gets a `**Superseded by:** specs/<new-spec>.md` line added to its metadata. Otherwise the original is untouched — its content is historical truth.
4. The fix file's "Spec changes" section is updated with the new spec's path.
5. Tell the user: *"Spec was wrong/silent. Created new spec at `specs/<new>.md` superseding `specs/<original>.md`. Next: edit the new spec to confirm the corrected Contract surface, run `/contract specs/<new>.md` to regenerate artifacts, then `/work fixes/<file>.md` (or `/work specs/<new>.md` if you'd rather drive from the spec)."*

The fix file is the audit record of *why* the spec changed. The new spec is the contract going forward. Both are committed together.

## --hot mode

If the user passed `--hot` or the ticket looks like an incident:

1. **Compress questions.** Make best-effort classification, confirm in one line, don't ask follow-ups unless genuinely blocked.
2. **Skip optional sections** in the fix file ("Open questions", "Files likely to change" can be left as `[to be filled by /work]`).
3. **Allow Status: emergency** as a valid status, distinct from `draft`. This is visible in `git log` for audit.
4. **Still run all gates.** Pre-commit hook still enforces fix-linkage. `/work` still runs `/check` post-flight. Regression test still required (the resolution paragraph can defer the test itself, but the acceptance criterion that asserts the test exists is non-optional).
5. **Emit a stronger commit-message reminder.** *"Emergency fixes must reference fixes/<file>.md in the commit message AND include a follow-up TODO if the regression test was deferred."*

The compression saves minutes, not hours. It does not buy you a way to skip the audit trail.

## After drafting

1. Save the fix file.
2. If Case 2 or 4, save the new spec file with `Supersedes` metadata, and update the original's metadata with `Superseded by`.
3. Show the user the path(s) created and a one-line summary of the case and resolution plan.
4. State the next command:
   - Case 1: `/work fixes/<file>.md`
   - Case 2 or 4: edit `specs/<new>.md` → `/contract specs/<new>.md` → `/work fixes/<file>.md`
5. List any open questions.
6. Do NOT execute any code or make any other file changes.

## Capture lessons (auto)

Before closing, capture any durable lessons from this session so they are not lost. Run:

> `/capture-lessons --session-id $SID --source /fix`

This records at most 3 lesson candidates (corrections, confirmed approaches, preferences,
surprising decisions) to the ledger. It is idempotent — if the SessionEnd hook also fires,
it will not double-record. Candidates are NOT invariants; they are reviewed later via
`/review-lessons`. If the session taught nothing durable, `/capture-lessons` records nothing,
which is the common case. Do not block the command's completion on this step.

## What not to do

- Do not modify the original spec's content (Cases 2 and 4 create a *new* spec; the original keeps its content with only a `Superseded by` field appended).
- Do not redirect bug fixes through `/spec` — that loses the bug context. Fixes have their own artifact for a reason.
- Do not skip root cause analysis. A fix without a root cause is a guess. If the root cause is genuinely unknown, mark "Under investigation" and stop — don't draft a resolution.
- Do not skip the regression test acceptance criterion, even in `--hot` mode. The test itself can be deferred to a follow-up; the criterion cannot.
- Do not invent classification. If the user can't classify (genuinely ambiguous), ask the user one targeted question rather than guessing.
- Do not bypass the pre-commit hook. Emergency commits use `git commit --no-verify` with audit visibility, not workflow shortcuts.

---
description: Detect drift between a spec and the code in its scope. Reports ticked criteria with no code trace, code changes with no spec coverage, and stale contract artifacts. Invoked automatically by /work on entry and exit; can also be run manually.
argument-hint: <path-to-spec-file> [--scope backend|frontend] [--deep]
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /check — Detect Spec-vs-Code Drift

You are running drift detection between a spec and the code in its scope. This command produces a report; it does not modify any files. It is invoked automatically by `/work` on entry and on completion, and can also be invoked manually by the user when they suspect drift.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"check command"** section. Logging is best-effort and silent. Log a `drift_detected` event for each finding (with severity and which check it was from), and `session_end` always with outcome `completed` since /check is read-only.

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: path to a spec file under `specs/`
- Optional `--scope backend|frontend`: limits the check to one scope (default: check all scopes covered by the spec)
- Optional `--deep`: run the expensive code-implies-spec check in addition to fast checks

If the spec path is missing, ask which spec to check.

## Read context

1. Read `CLAUDE.md` for invariants and verification commands.
2. Read the spec file completely, including metadata block, acceptance criteria, contract surface section, files likely to change, and any execution notes from prior `/work` runs.
3. If the spec has a `Contract hash` field, find the contract artifacts under `_generated/` and read their headers.

## The four drift checks

### Check 1: Contract hash freshness (fast, always)

Only applies if the spec has a `Contract hash` field.

The hash is computed over the **normalised content of the Contract surface section only**, not the whole spec file. See `/contract` for the normalisation steps. Re-applying the same normalisation here is essential — otherwise edits to the spec's status, Contract artifacts list, or any other metadata will trigger false hash mismatches.

Steps:

1. Extract and normalise the Contract surface section using the same rules `/contract` documents:
   - Extract everything between `## Contract surface` and the next `##` heading
   - Strip HTML comments (`<!-- ... -->`)
   - Trim trailing whitespace from each line
   - Collapse 2+ blank lines to one
   - Strip leading/trailing blank lines
   - Ensure exactly one trailing `\n`
2. Compute `sha256` of the normalised content.
3. Compare to the `Contract hash` field in the spec's metadata block.
4. Compare both to the `SPEC HASH` line in each `_generated/` artifact's header.

**Possible outcomes:**
- All three match → contract is fresh
- Computed hash differs from `Contract hash` field → spec metadata is stale (rare; usually means someone hand-edited the field) — flag and ask user
- `Contract hash` field differs from artifact `SPEC HASH` → spec's Contract surface was edited since `/contract` was last run; `/contract` must be re-run
- Recorded hashes differ between artifacts (e.g. one file says `a3f2...`, another says `b4e1...`) → a previous `/contract` run failed midway; `/contract` must be re-run to restore consistency
- Spec has no Contract surface section but has `Contract hash` field → spec was mutated incorrectly; flag

### Check 2: Ticked-criterion traceability (fast, always)

For each acceptance criterion in the spec marked `- [x]`:

- Scan the spec's "Execution notes" section for the file paths the work touched.
- For each file mentioned, verify it still exists.
- Grep for `§ref:specs/<this-spec-filename>` in each file (or whatever traceability convention `CLAUDE.md` specifies).

**Possible outcomes:**
- Every ticked criterion has at least one file with a matching `§ref` → traceable
- Ticked criterion has no traceable code → the criterion was either ticked incorrectly or the code was reverted; flag and ask user

### Check 3: Code-without-spec-coverage (fast, always)

Compute `git diff HEAD` (or compare against the last commit referenced in spec's execution notes).

For each changed file under `src/`, `lib/`, or `app/`:

- Check whether it contains a `§ref:specs/<this-spec-filename>` comment.
- If not, check whether it appears in the spec's "Files likely to change" section.

**Possible outcomes:**
- All changed files have either a `§ref` or are listed in spec → covered
- Changed files have neither → either work happened outside the spec (drift) or the spec is incomplete; flag with the file list

### Check 4: Code-implies-spec divergence (slow, only with `--deep` or on resume)

Skip unless `--deep` is set or the spec status is `in-progress` AND the file modification times suggest a gap (more than a day since last execution note).

For each file in the spec's "Files likely to change" that has been modified:

- Read the file.
- For the relevant scope (backend or frontend), extract observable surface:
  - Backend: route handlers, request/response shapes, validation rules, emitted events
  - Frontend: API call sites, expected response shapes, displayed fields
- Compare to the spec's Contract surface section (if present) or to acceptance criteria.

**Possible outcomes:**
- Observable surface matches spec → consistent
- Surface diverges → flag specific divergence (e.g. "Spec says endpoint returns `{ status, data }`, code returns `{ result, payload }`")

This check is best-effort and AI-judgment-based. Report findings as "suspected divergence" rather than definitive — false positives are expected. The user adjudicates.

## Pact verification (full-stack backend scope only)

If `--scope backend` and `_generated/pact/` exists:

- Look for a Pact verification command in `CLAUDE.md` or in the project's build files.
- If found, mention it in the report as a recommended next step. Do not run it from `/check` — it may be slow and require infrastructure (broker, running services). `/work` is the place that runs it as part of post-flight verification.

## Report format

Produce a concise structured report. Example shape:

```markdown
# Drift report — specs/2026-05-12-notif-prefs.md

**Scope checked:** backend
**Mode:** fast (use --deep for code-vs-spec divergence)
**Generated:** 2026-05-12 14:30 SGT

## Check 1: Contract hash
✓ Spec hash matches recorded hash (a3f2c...)
✓ All _generated/ artifacts have matching hash

## Check 2: Ticked-criterion traceability
✓ 4 of 4 ticked criteria have traceable code

## Check 3: Code without spec coverage
⚠ 1 file changed without §ref:
  - src/backend/notif_helper.py
    → either add §ref:specs/2026-05-12-notif-prefs.md, or
      add this file to the spec's "Files likely to change"

## Check 4: Code-implies-spec divergence
(skipped — pass --deep to run)

## Suggested actions
1. Resolve the untraced file in Check 3
2. If everything else is intact, /work can resume safely
```

If all checks pass green, the report should be one or two lines:

```markdown
# Drift report — specs/2026-05-12-notif-prefs.md
✓ No drift detected (backend scope, fast checks)
```

## Behaviour when invoked from /work

When `/work` invokes `/check` internally on entry:
- Run checks 1, 2, 3 only (fast set)
- If any check fails red, surface the failure and let `/work` decide whether to halt or ask the user
- If checks fail yellow (warnings only), include them in the plan presented to the user

When `/work` invokes `/check` internally on completion:
- Run checks 1, 2, 3 (fast set) plus check 4 in non-deep mode (only files known to have been touched in this session)
- Surface anything flagged before marking spec as `ready-for-review`

## What not to do

- Do not modify any files. `/check` is read-only.
- Do not auto-fix drift. Surface it; let the user or `/work` decide.
- Do not run check 4 by default — it's slow and noisy. Only on `--deep` or on resume.
- Do not silence warnings. False positives are cheap; missed drift is expensive.
- Do not invoke Pact verification or other external test tools — those belong in `/work` post-flight.

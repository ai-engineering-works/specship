---
description: Investigate a failure (compile error, runtime error, test failure, production incident, broken CI) and produce an investigation file. The investigation captures evidence, hypotheses, and the root cause once found, then feeds into /fix. Use when you've observed a failure but don't yet know its cause.
argument-hint: <short-description-or-ticket-id> [--reproduces-locally] [--production]
recommended-model: opus  # sonnet | opus — see CLAUDE.md for guidance
---

# /investigate — Structured Failure Investigation

You are running a structured investigation of a failure. The output is an investigation file under `investigations/` that captures what you observed, what you tried, what you ruled out, and (eventually) the root cause. Once the root cause is known, the investigation feeds directly into `/fix`.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"investigate command"** section. Logging is best-effort and silent. Log `artifact_created` when the investigation file is saved (with severity P1/P2/P3/unknown), `artifact_updated` when status transitions (open → root-cause-identified, stalled, closed-*), and `session_end` with outcome.

## When to use this vs other commands

| Situation | Right command |
|---|---|
| Compile error in code you just wrote during `/work` | Stay in `/work` — it iterates on verification failures |
| You've observed a failure but don't know why | `/investigate` |
| You know the root cause and want to fix it | `/fix` (skip `/investigate`) |
| Trivial compile error in code outside `/work` (typo, missing import) | Just fix it — `--no-verify` commit |
| Production incident requiring formal incident response | Your incident response process; `/investigate` is a complement, not a replacement |

Investigation is the **discovery phase**. Fix is the **resolution phase**. Keep them distinct or the audit trail conflates "what we learned" with "what we did".

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: a ticket ID (e.g. `INC-911`) or short description of the failure
- Optional `--reproduces-locally`: signals you can reproduce on a dev machine (changes the strategy below)
- Optional `--production`: signals this is from a production system (raises the urgency and the audit bar)

If the argument is missing, ask what's being investigated.

## Pre-flight

1. **Read `CLAUDE.md`** for invariants and verification commands.
2. **Check for an existing investigation** of the same failure. Look in `investigations/` for files with related keywords. If an active investigation already exists, ask whether to continue it or open a new one.
3. **If this is a recurrence**, search past investigations and fixes (`investigations/` and `fixes/`) for the same symptoms. A recurring failure means the previous fix didn't address the root cause — note this in the new investigation.

## Draft the investigation file

Create `investigations/YYYY-MM-DD-<slug>.md`:

```markdown
# Investigation: <short title>

**Ticket:** <id or "none">
**Status:** open
**Severity:** <P1 | P2 | P3 | unknown>
**Production:** <yes if --production, otherwise omit>
**Reproduces locally:** <yes | no | unknown>
**Started:** YYYY-MM-DD
**Investigator:** <user identifier, or "team">

## What was observed

<Specific, concrete. What broke. What error message, what symptoms, what
time, on what environment. Quote error messages verbatim — don't summarise
them. Stack traces in fenced code blocks.>

## Reproduction

<How to reproduce the failure. If --reproduces-locally, write the steps
that work on your machine. If not, write what's known about when it
occurs (specific user, specific time, specific input).>

```bash
# Exact commands or steps to reproduce
```

## Initial hypotheses

<List 2-5 candidate causes ranked by likelihood. For each, note what
evidence would support or rule it out.>

1. **<hypothesis>** — would be supported by: <evidence>; would be ruled out by: <evidence>
2. **<hypothesis>** — would be supported by: <evidence>; would be ruled out by: <evidence>

## Investigation log

<Append-only chronological log. Each entry: timestamp, what you did,
what you saw, what you concluded. Don't rewrite history — append.>

### YYYY-MM-DD HH:MM
<entry>

## Evidence

<Things you found that are relevant to root cause: log excerpts, git blame
results, related commits, similar past incidents, test outputs, profiles.
Treat this as the case file's exhibit list.>

### Logs
```
<log excerpts>
```

### Related commits
- `<sha>` — <short description, why relevant>

### Related past investigations/fixes
- `investigations/<file>.md` — <relevance>
- `fixes/<file>.md` — <relevance>

## Ruled out

<Hypotheses that have been investigated and disproven. Important for the
audit trail: shows you didn't just guess.>

- **<hypothesis>** — ruled out because: <reason>

## Root cause

<Initially blank. Fill in when you've actually identified the cause.
This section is the bridge to /fix — its content becomes the fix file's
"Root cause" section.>

[under investigation]

## Affected scope

<Once root cause is known: which specs, fixes, or unspec'd code is affected.
Determines what /fix will need to do.>

- Spec(s) affected: <list, or "none">
- Fix(es) related: <list, or "none">
- Unspec'd code affected: <list, or "none — covered by specs only">

## Conclusion

<Initially blank. One of:
  - "Root cause identified — see Root cause section. Resolving via /fix."
  - "Not reproducible after N attempts. Closing without fix. Will reopen if recurs."
  - "Caused by external dependency change (e.g. upstream API breaking). No code fix; resolved by <action>."
  - "Caused by environmental issue (e.g. expired cert, full disk). No code fix; resolved by <action>.">

## Notes

<Free-form. Anything that doesn't fit elsewhere.>
```

## Strategy by failure type

### Compile error

1. Quote the exact compiler message in "What was observed".
2. Reproduction is usually trivial — `mvn compile` / `npm run build` / `tsc --noEmit`.
3. Hypotheses are usually narrow: missing import, type mismatch, version skew, breaking change in dependency.
4. Investigation often takes minutes. If it does, complete `/investigate` quickly and chain to `/fix`.

### Runtime error (test failure)

1. Quote the test name, failing assertion, and full stack trace.
2. Try to reproduce locally if not already (`--reproduces-locally`).
3. Bisect if relevant: `git bisect` between last-known-good and HEAD.
4. Check whether the test is flaky (run 10x; if it fails inconsistently, that's a different class of issue — flakiness is a workflow gap not addressed here, note it and continue).

### Runtime error (production)

1. **Tighten the audit trail.** Set `--production` so the investigation file marks status visibly.
2. Capture logs/traces before they age out.
3. Look for related deployments — what changed recently?
4. Identify customer impact scope.
5. Be careful about "fix forward" vs "rollback first" — investigation should inform the decision, not be skipped to enable it.

### Broken CI

1. Compare the failing CI run with the last passing one.
2. Check whether the failure is in our code or in CI infrastructure (cache, runner image, secrets rotation, upstream service).
3. If CI infra: not a code bug; close the investigation with an environmental cause.
4. If our code: continue normally.

### Cannot reproduce

If you can't reproduce after a reasonable effort:

1. Log everything you tried in "Investigation log".
2. Note the threshold (e.g. "tried 20 invocations, all succeeded").
3. Close with "Not reproducible after N attempts" in Conclusion.
4. Add to "Ruled out" what's NOT the cause.
5. Recommend monitoring / alerts so a recurrence is caught with more signal.

Closing an investigation as "not reproducible" is a valid outcome. It's better than a guessed fix that addresses the wrong cause.

## When investigation finds root cause

When you identify the root cause:

1. Fill in the "Root cause" section concretely.
2. Fill in "Affected scope".
3. Set status to `root-cause-identified`.
4. Set conclusion to "Root cause identified — see Root cause section. Resolving via /fix."
5. Tell the user: *"Investigation complete. Run `/fix <ticket> --against <affected-spec> --from-investigation investigations/<file>.md` to create the fix. The fix's Root cause and Resolution sections will be pre-populated from this investigation."*

## When investigation hits a wall

If you've genuinely exhausted hypotheses and can't progress:

1. Set status to `stalled`.
2. List concretely what you'd need to progress: better logs, customer access, repro environment, expert input.
3. Tell the user what's blocking and what you need.

A stalled investigation is NOT a failure — it's a clear signal of what's missing. Don't pad with speculation to feel productive.

## Status values

- `open` — actively being worked
- `root-cause-identified` — ready to feed into `/fix`
- `stalled` — blocked on external input
- `closed-not-reproducible` — exhausted reproduction attempts
- `closed-external` — caused by something outside the codebase (infra, dependency, etc.)
- `closed-resolved` — fix shipped and confirmed; investigation archived

`closed-resolved` is set after the `/fix` is signed off, not during investigation.

## Pre-commit hook interaction

The pre-commit hook accepts `investigations/*.md` linkage in the same way it accepts `specs/*.md` and `fixes/*.md`. So a commit that adds an investigation file passes the Wall.

## What not to do

- Do not start writing a fix during `/investigate`. The investigation produces evidence and a root cause; the fix is a separate artifact via `/fix`.
- Do not invent a root cause to close the investigation faster. "Under investigation" or "stalled" are valid states.
- Do not delete entries from "Investigation log". It's append-only — even wrong hypotheses are useful for the audit trail and for whoever investigates the next similar bug.
- Do not skip `/investigate` for non-trivial bugs just because `/fix` exists. Fixes without recorded investigation lose the "what we learned" record.
- Do not run `/investigate` for trivial compile errors you can fix in 30 seconds. Just fix them and commit with `--no-verify` if there's no spec to reference. Investigation has overhead; reserve it for things that warrant the audit trail.

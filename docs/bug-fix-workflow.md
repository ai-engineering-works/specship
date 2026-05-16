# Bug-Fix Workflow — Worked Examples

This document walks through the four bug-fix cases the workflow handles, showing the actual commands and artifacts for each.

The general principle: **the original spec is preserved as historical truth, fixes carry their own audit trail, and spec mutations create new versions rather than overwrites.**

---

## Case 1: Code was wrong, spec was right

**Scenario:** Original spec `specs/2026-04-10-notif-prefs.md` says GET /notifications/preferences should return an empty array when no preferences exist. Production reports a 500 error in this case — code is throwing a `NullPointerException`. The spec is correct; the code is wrong.

### Commands

```
/fix INC-789 --against specs/2026-04-10-notif-prefs.md
```

User classifies as Case 1. `/fix` produces:

```
fixes/2026-05-12-null-prefs-against-notif-prefs.md
```

Key fields:
- **Case:** 1
- **What was wrong:** code throws NPE when no preferences exist
- **Root cause:** missing null-check in `NotificationService.getPreferences()`
- **Resolution:** initialise `preferences` to empty list when DB returns null
- **Regression test required:** yes — `getPreferences_whenNoneExist_returnsEmptyList`

Then:

```
/work fixes/2026-05-12-null-prefs-against-notif-prefs.md
```

`/work` reads the fix, also reads `specs/2026-04-10-notif-prefs.md` (the original contract — still authoritative), produces a plan, executes:
- Adds null-check in `NotificationService.getPreferences()`
- Writes the regression test
- Adds `§ref:fixes/2026-05-12-null-prefs-against-notif-prefs.md` to changed lines

Status of original spec: **unchanged** (still `ready-for-review` or `signed-off`).
Status of fix file: `ready-for-review`.

### What got committed

```
fixes/2026-05-12-null-prefs-against-notif-prefs.md
src/backend/notifications/NotificationService.java     (modified)
src/backend/notifications/NotificationServiceTest.java (added test)
```

The pre-commit hook sees the staged `fixes/*.md` file — linkage satisfied.

---

## Case 2: Spec was wrong, code was reasonable

**Scenario:** Original spec says `frequency` field is optional on `NotificationPreference`. Code persists it as nullable. Customers report that preferences without a frequency silently default to "instant" — surprising and undocumented. Discussion concludes: frequency should always be required with no implicit default.

The original spec was the bug. The contract itself needs to change.

### Commands

```
/fix BUG-432 --against specs/2026-04-10-notif-prefs.md
```

User classifies as Case 2. `/fix` produces:

```
fixes/2026-05-12-frequency-required-against-notif-prefs.md
specs/2026-05-12-notif-prefs-v2.md     <-- NEW, supersedes original
```

The new spec is a copy of the original with two changes:
- Metadata adds `**Supersedes:** specs/2026-04-10-notif-prefs.md`
- Contract surface `Shared types` updates `frequency?:` to `frequency:` (no longer optional)

The original spec gets a single metadata line appended:
- `**Superseded by:** specs/2026-05-12-notif-prefs-v2.md`

Otherwise the original spec's content is **untouched** — it's the historical record.

### Then re-run contract compilation

```
/contract specs/2026-05-12-notif-prefs-v2.md
```

`/contract` notices this is a re-compile (artifacts for the same slug exist). It detects a **breaking change** (required field added) and STOPS, asking the user to confirm:

```
Breaking change detected in specs/2026-05-12-notif-prefs-v2.md:

  ! NotificationPreference.frequency: optional → required

This will break existing clients that send NotificationPreference without
a frequency value. Proceed? (yes/no)
```

User confirms `yes`. New artifacts written with `info.version: 2.0.0`.

### Then implement

```
/work fixes/2026-05-12-frequency-required-against-notif-prefs.md --scope backend
/work fixes/2026-05-12-frequency-required-against-notif-prefs.md --scope frontend
```

Each scope's `/work`:
- Reads the fix file (bug context)
- Reads `specs/2026-05-12-notif-prefs-v2.md` (the new contract)
- Updates `_generated/`-importing code to require frequency
- Adds migration handling (legacy data without frequency gets a default applied during read, with deprecation warning)
- Regression test asserts that new submissions without frequency are rejected
- `§ref:fixes/...` AND `§ref:specs/2026-05-12-notif-prefs-v2.md` on changed lines

### What got committed

```
fixes/2026-05-12-frequency-required-against-notif-prefs.md
specs/2026-05-12-notif-prefs-v2.md
specs/2026-04-10-notif-prefs.md                                  (only "Superseded by" added)
_generated/openapi/notif-prefs.yaml                              (version bump 1.x → 2.0.0)
_generated/types/notif-prefs.ts
_generated/types/notif-prefs.py
_generated/pact/web-client-notifications-service.json
src/backend/notifications/NotificationService.java
src/backend/notifications/MigrationHelper.java                   (new — handles legacy data)
src/frontend/pages/preferences.tsx
... tests ...
```

The audit trail tells the full story:
- Original spec (April) describes the original contract
- "Superseded by" pointer shows when and why the contract evolved
- Fix file (May) explains the bug and root cause
- New spec (May) is the current contract going forward

---

## Case 3: Requirement has changed

**Scenario:** Customer success requests that notification preferences support a snooze window (e.g. "don't notify between 22:00 and 07:00"). Neither the spec nor the code "was wrong" — this is genuinely new functionality.

### What happens

```
/fix SNOOZE-001 --against specs/2026-04-10-notif-prefs.md
```

User classifies as Case 3. `/fix` **stops** and says:

> This is a new requirement, not a bug fix. Run `/spec` to create a new spec, optionally referencing `specs/2026-04-10-notif-prefs.md` in the Notes section to record the evolution.

No fix file is created. The user runs:

```
/spec SNOOZE-001
```

Which creates a normal new spec. The new spec's Notes section can reference the old spec for context, but it's a forward-looking spec, not a bug-fix artifact.

This is the correct behaviour: bug fixes have specific shape (root cause analysis, regression test, deviation from prior contract). Treating new requirements as fixes pollutes the bug audit trail.

---

## Case 4: Spec was silent, behaviour emerged

**Scenario:** Original spec doesn't mention ordering of preferences in the response. Code happens to return them in insertion order. Production discovers a UI bug where preferences appear to "jump" because the backend doesn't actually guarantee order — under concurrent updates, response order varies.

The spec didn't say what should happen. The code wasn't "wrong" — it had no rule to follow. But the *correct* behaviour (now identified) is "ordered by channel alphabetically".

### Commands

```
/fix UX-555 --against specs/2026-04-10-notif-prefs.md
```

User classifies as Case 4. `/fix` produces:

```
fixes/2026-05-12-pref-ordering-against-notif-prefs.md
specs/2026-05-12-notif-prefs-v2.md     <-- NEW, supersedes original
                                            (or v3 if v2 from Case 2 already exists)
```

The new spec's Contract surface is amended in the Compatibility notes section:

```markdown
### Compatibility notes

- **Ordering:** the `preferences` array in GET responses is ordered by
  `channel` ascending. Clients may rely on this order.
```

This is an **additive** constraint (clients that didn't rely on order still work; clients that did rely on insertion order will be fine because ordering was undefined anyway). `/contract` flags it as additive, no breaking change.

### Then

```
/contract specs/2026-05-12-notif-prefs-v2.md
/work fixes/2026-05-12-pref-ordering-against-notif-prefs.md --scope backend
```

Frontend scope work only needed if the frontend has to enforce or display order; otherwise skip.

---

## The --hot path (emergency fixes)

For genuine incidents where the cycle of `/fix → /contract → /work backend → /work frontend → commit` is too slow:

```
/fix INC-911 --against specs/2026-04-10-notif-prefs.md --hot
```

Or, if the ticket ID matches `INC-*`, `P1-*`, or `HOTFIX-*`, `--hot` is auto-applied.

What `--hot` does:
- Compresses classification (best-effort, confirm in one line)
- Allows `Status: emergency` distinct from `draft`
- Skips optional sections in the fix file
- Strengthens commit-message reminders for any deferred follow-ups

What `--hot` does NOT do:
- Skip the pre-commit hook (still requires fix-linkage)
- Skip `/check` drift detection
- Skip the regression test acceptance criterion (the test itself can be deferred; the criterion that asserts it cannot)
- Skip Pact verification on backend
- Bypass any audit trail

Save minutes, don't bypass governance. If you need to bypass the pre-commit hook, use `git commit --no-verify` — it's visible in `git log` for after-the-fact review, which is the correct accountability mechanism.

---

## Summary: which artifact carries what

| Artifact | Lifetime | Mutability | Audit role |
|---|---|---|---|
| Original spec | Forever (committed at first sign-off) | Append-only metadata (Superseded by ...) | "What we said we were building" |
| Superseding spec (v2, v3) | Forever | Same as original spec | "What we're building now" |
| Fix file | Forever | Append execution notes during /work | "Why the contract evolved or why code drifted" |
| Generated artifacts | Live | Replaced by /contract; never hand-edited | "The actual contract surface, current version" |

The pre-commit hook accepts linkage to either a spec or a fix file. The `/work` command accepts either as input. Everything else is the same workflow.

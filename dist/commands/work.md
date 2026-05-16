---
description: Execute work against a spec file OR a fix file. For full-stack specs/fixes, takes a --scope argument (backend or frontend) and stays within that scope. Runs drift detection on entry and exit, and Pact provider tests on backend completion if artifacts exist.
argument-hint: <path-to-spec-or-fix-file> [--scope backend|frontend]
recommended-model: opus  # sonnet | opus — see CLAUDE.md for guidance
---

# /work — Execute Against a Spec or Fix

You are executing work defined by either a spec file (`specs/*.md`) or a fix file (`fixes/*.md`). Both are contracts. You do not invent work that isn't in the input artifact; you do not skip work that is. For full-stack work, you operate within ONE scope per invocation.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"work command"** section. Logging is best-effort and silent. Generate a session UUID at the start and include the scope. Log drift_detected for each /check finding, verification_ran for each test invocation, coverage_measured if CLAUDE.md declares a Coverage policy, and session_end with completion outcome. **If a parent_session_id was passed in $ARGUMENTS (i.e., this /work was spawned by /ship), include it in session_start so the ledger can correlate parent and child.**

### When to log a `decision_logged` event

Log a decision **every time** you made a choice the spec did not dictate AND a reasonable engineer might have chosen differently. The threshold is: *would a code reviewer want to see this choice flagged?*

Concrete triggers — log a decision when:

1. **You picked one library, framework, or pattern over alternatives.** Example: "Chose `jsonschema-rs` (Rust binding) over `jsonschema` (pure Python) for spec validation — 50× faster on our payload sizes, and we only use the strict subset."
2. **You handled an edge case the spec was silent on.** Example: "Spec didn't specify behaviour on null email addresses; chose to skip the notification silently rather than raising. Rationale: matches the existing `/messages` endpoint's behaviour."
3. **You modified or skipped a verification step from CLAUDE.md.** Example: "Skipped the `ruff check` step because the file is generated; verified with `mypy` only."
4. **You diverged from a pattern used elsewhere in the codebase.** Example: "Used pydantic `model_validator` instead of `field_validator` because we need cross-field validation; existing code uses field-only validators throughout."

**Do NOT** log a decision for:
- Mechanical choices (naming a variable, choosing an import order)
- Choices the spec's Acceptance criteria directly dictated
- Verification commands explicitly listed in CLAUDE.md (those are policy, not decisions)
- Stylistic choices the formatter would normalise anyway

When in doubt, log it — over-logging is easier to filter than under-logging is to reconstruct. But if you find yourself logging more than ~5 decisions per spec, the spec was probably under-specified; flag that to the user in your post-flight summary.

### Decision logging skeleton

```bash
DECISION_ID=$(python3 .specship/ledger/specship_ledger.py log decision_logged \
    session_id="\"$SID\"" \
    artifact="\"$SPEC_PATH\"" \
    summary='"<one-sentence what was chosen>"' \
    rationale='"<one-sentence why this option over alternatives>"' \
    accepted=true --quiet)
# DECISION_ID is captured so the post-flight summary can reference it
```

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: path to a spec file or fix file
- Optional `--scope backend` or `--scope frontend`
- Optional `--plan-only` — do pre-flight and produce a plan, then STOP. Write the plan to `.specship/plans/<session-id>.md` and exit. Used by `/ship` to capture plans for combined human approval before parallel execution.
- Optional `--from-plan <path>` — read a previously-drafted plan from the given path. Skip pre-flight and planning. Execute directly. Used by `/ship` after the human approves the plans from `--plan-only` runs.
- Optional `--parent-session-id <uuid>` — propagated by `/ship` so child events correlate to the orchestration.

**The two flags `--plan-only` and `--from-plan` are mutually exclusive.** If both are passed, refuse with an error.

**Direct invocations (no flag) keep the existing behaviour**: do pre-flight, draft a plan, present it inline, wait for the user to approve, then execute. This is the human-in-the-loop default.

If the path is missing (and `--from-plan` is also missing), ask which artifact to work on.

## Determine artifact type

Look at the path:
- Begins with `specs/` → **spec mode**. Standard behaviour.
- Begins with `fixes/` → **fix mode**. Variations described in each section below.

If the path is somewhere else, ask the user to confirm.

## Pre-flight

### Step 1: Read context
- Read `CLAUDE.md` at the repo root. Every invariant applies. If absent, warn and stop.
- Read the input file (spec or fix) completely.
- **Fix mode**: also read the spec referenced by the fix's `Against spec:` field. The spec defines the original contract; the fix defines the deviation and resolution.

### Step 2: Status and scope checks

**Spec mode:**
- Verify spec status is `draft`, `in-progress`, or `contract-locked` (not `done`, `signed-off`, `ready-for-review`, or `draft-reverse-engineered`).
  - If status is `draft-reverse-engineered`: STOP. Tell the user: *"This spec was generated by the spec-reverse-engineer skill and hasn't been reviewed. Search the file for `[needs review]` markers, resolve them, then change the status to `draft` before re-running `/work`."*
- Verify all "Open questions" are closed.
- Determine working scope:
  - `backend-only` spec → scope is `backend`
  - `frontend-only` spec → scope is `frontend`
  - `full-stack` spec → `--scope` is **required**; if missing, ask

**Fix mode:**
- Verify fix status is `draft`, `in-progress`, or `emergency` (not `signed-off` or `done`).
- Verify "Root cause" section is not "Under investigation" — if it is, stop and tell the user to complete the analysis first.
- Verify "Open questions" are closed.
- Verify the regression test acceptance criterion is present (do NOT verify the test exists yet — that's part of execution; just verify the criterion is in the fix).
- Determine working scope from the *referenced spec's* scope:
  - Original spec was `backend-only` → fix scope is `backend`
  - Original spec was `frontend-only` → fix scope is `frontend`
  - Original spec was `full-stack` → `--scope` is **required**
- Fix mode rule: if the fix is Case 2 or Case 4 AND the new superseding spec exists, verify it has been through `/contract` (status `contract-locked`). If not, stop and tell the user to run `/contract specs/<new-spec>.md` first.

### Step 3: Run /check (drift detection)
Invoke the `/check` command internally:
- Pass the spec path and the working scope
- Use fast mode (no `--deep`)
- If the spec status is `in-progress` (resumed work), use `--deep`

Read the resulting drift report and act on it:
- **Check 1 fails** (contract hash mismatch — see `/contract` for how hashes are computed over the normalised Contract surface section) → STOP. Tell user to run `/contract`.
- **Check 2 fails** (ticked criteria with no traceable code) → STOP. Ask user whether to untick the criteria or restore the code.
- **Check 3 fails** (changed files with no spec coverage) → WARN. Include in the plan; ask user to confirm these changes are intentional.
- **Check 4 flags** (suspected divergence, on resume) → WARN. Include in the plan; ask user to adjudicate.

### Step 4: Contract artifact check (full-stack only)
- If spec has Contract surface section but no `_generated/` artifacts → STOP. Tell user to run `/contract`.
- Confirm the spec's `Contract hash` matches the artifacts (this is redundant with Check 1 but is a defence-in-depth).

If any pre-flight step fails, stop. Do not proceed to planning.

## Plan first

**Branch on mode:**

### Mode A — `--from-plan <path>` (orchestrated execution)

You were invoked by `/ship` after the human approved a previously-drafted plan. Skip pre-flight (it ran during `--plan-only`) and skip planning entirely.

1. Read the plan file at the given path. It contains the scope, source artifact, files to modify, verification commands, expected decisions, and any warnings the human reviewed.
2. Update artifact status to `in-progress`.
3. Log a `plan_executing` event with the plan's `plan_id` (encoded in the plan file's frontmatter).
4. Skip directly to **Execute** below — do NOT re-present the plan. The human already approved it.
5. If the plan file is missing, malformed, or the `plan_id` doesn't match a `plan_approved` event in the ledger, REFUSE. Tell the orchestrator: "Cannot execute from plan: plan not found / not approved." This is a safety check — `/work --from-plan` must never execute a plan that wasn't first approved.

### Mode B — `--plan-only` (orchestrated planning)

You were invoked by `/ship` to produce a plan for a separate human-approval step. After pre-flight passes:

1. Identify scope's surface area (same logic as Mode C below).
2. Draft the plan content (same fields as Mode C).
3. Generate a `plan_id` (UUID) and write the plan to `.specship/plans/<plan_id>.md` with the following structure:

   ```markdown
   ---
   plan_id: <uuid>
   session_id: <your session uuid>
   scope: <backend|frontend|single>
   source_artifact: <spec or fix path>
   drafted_at: <ISO timestamp>
   ---

   # Plan for <scope> — <source_artifact>

   ## Order of acceptance criteria
   <list>

   ## Files to create or modify
   <list with file paths>

   ## Tests to add or update
   <list>

   ## Decisions you expect to make
   <list — give the human a heads-up about choices Claude expects to encounter,
    so they can flag concerns upfront rather than at /review-decisions time>

   ## Verification commands
   <list — what you'll run during execution>

   ## Warnings from drift check
   <if any>

   ## Invariants from CLAUDE.md that apply
   <list>
   ```

4. Log `plan_drafted` to the ledger:
   ```bash
   log plan_drafted session_id="\"$SID\"" \
       plan_id="\"$PLAN_ID\"" \
       scope="\"<backend|frontend|single>\"" \
       source_artifact="\"<spec-or-fix-path>\"" \
       plan_path="\".specship/plans/$PLAN_ID.md\"" \
       files_to_modify='[...]' \
       estimated_decisions=<int>
   ```
5. **STOP.** Do NOT execute. Return to the parent (the `/ship` orchestrator) with the plan_id and plan_path. Tell the parent: "Plan drafted at .specship/plans/<plan_id>.md. Awaiting orchestrator's approval gate."
6. Log `session_end` with `outcome="plan-only"`.

### Mode C — direct invocation (default — human-in-the-loop)

After pre-flight passes (no orchestrator involved):

1. Update artifact status to `in-progress` (spec file in spec mode, fix file in fix mode).

2. Identify scope's surface area:
   - **Backend scope** — read backend acceptance criteria, backend "Files likely to change", backend tests, and the contract artifacts you will *implement* (server-side stubs, validation rules). You are the contract producer.
   - **Frontend scope** — read frontend acceptance criteria, frontend "Files likely to change", frontend tests, and the contract artifacts you will *consume* (TS types, API client stubs). You are the contract consumer.

3. **Fix mode addition:** include the fix's "Resolution" section in your plan. The resolution describes specifically what changes. If the resolution disagrees with the referenced spec (or its superseding version), the spec wins — the resolution is a plan, the spec is the contract.

4. Produce a plan covering:
   - Order in which you'll address THIS scope's acceptance criteria
   - Files in THIS scope you'll create or modify
   - Tests in THIS scope you'll write or update (in fix mode, include the regression test explicitly)
   - Generated artifacts you'll import (read-only)
   - Invariants from `CLAUDE.md` that constrain the approach
   - Any warnings from the drift check that affect the plan
   - Decisions you expect to make during execution (forewarn the user)

5. Present the plan and **wait for approval** before executing.

## Execute

Reached after:
- Mode A: `--from-plan` (no approval needed — already given before this session ran)
- Mode B: never (Mode B stops before execution)
- Mode C: human approved the plan inline

1. Work through THIS scope's acceptance criteria in order.
2. Tick checkboxes as criteria complete (scope-prefixed for clarity).
3. **Import generated types and schemas — do not redefine them.** Re-declaring is how drift starts.
4. **Do not write code in the other scope.** If you find yourself outside scope, stop.
5. Add traceability comments per `CLAUDE.md` convention:
   - **Spec mode:** `§ref:specs/<filename>`
   - **Fix mode:** `§ref:fixes/<filename>` (the fix carries the bug context, which is what the audit trail needs to see)
   - If the fix Case is 2 or 4 and a new superseding spec exists, ALSO add `§ref:specs/<new-spec>` on lines that implement the new contract
6. Run scope-relevant verification commands periodically (not the full suite — that's post-flight).
7. **Fix mode addition:** as part of execution, write the regression test described in the fix's "Regression test required" section. Verify it fails against the buggy behaviour first, then passes after the fix. If you can't reproduce the bug to write a failing test, stop and ask the user.
8. Stop and ask if you hit something the artifact doesn't cover. Do not invent.

### Mid-flight compile or test failures

Compile errors and test failures are expected during iteration — not the same class as boundary violations.

1. **Read the error carefully.** Quote the exact compiler/test message in your reasoning, don't summarise.
2. **Fix and retry, within reason.** Iterate up to ~3 attempts on the same failure within a `/work` session. The discipline is: each attempt should be a different hypothesis, not the same change tried again.
3. **If the failure persists after ~3 attempts, escalate.** Stop iterating and tell the user:
   *"I've tried 3 approaches for <error>; none worked. Suggestions:
     (a) `/investigate` to capture this as a structured investigation — useful if the cause isn't obvious
     (b) take over manually for this specific bug
     (c) confirm the spec/acceptance criterion is right; the failure may indicate the spec is wrong"*
4. **Don't disable tests, skip assertions, or relax invariants to make failures pass.** That's spec violation disguised as a fix. If a test seems wrong, stop and ask the user — the test may have been intentional or may need to change as part of the spec.

The line between "expected iteration" and "I should stop and investigate" is: roughly 3 attempts, or any time you find yourself reaching for `@Disabled`, `it.skip`, `# noqa`, or "let me just remove this check".

### Mid-flight boundary violations

If you discover the contract is wrong (missing field, wrong type, missing endpoint):

1. **Stop.** Do not work around it. Do not extend the contract locally.
2. Tell the user exactly what's wrong.
3. Suggest:
   - **Spec mode:** *"Edit the spec's Contract surface section, then re-run `/contract`, then re-invoke `/work`."*
   - **Fix mode:** *"This looks like Case 2 (spec was wrong) rather than what the fix classified. Consider stopping this `/work`, re-running `/fix` to upgrade to Case 2, and creating a superseding spec."*
4. Wait.

## Post-flight

When all acceptance criteria in THIS scope are ticked:

### Step 1: Full verification suite
Run the verification commands from `CLAUDE.md`'s "How to verify work is done" section, filtered to this scope.

### Step 2: Pact verification (backend scope, if artifacts exist)
If `--scope backend` AND `_generated/pact/` contains files:
- Locate the Pact verification command (check `CLAUDE.md`, then check `pom.xml`/`build.gradle`/`package.json` for Pact-related tasks).
- Run it. The Pact stubs in `_generated/pact/` define what the frontend expects; this verification proves the backend delivers it.
- If Pact verification fails, the backend has produced something that diverges from the contract. STOP. Surface the failure. The user must either fix the backend to match the contract OR edit the spec, re-run `/contract`, and re-verify.

### Step 3: Run /check again (post-completion drift detection)
Invoke `/check` with the working scope. This catches:
- New files created during work that don't carry `§ref` traceability
- Contract artifacts that changed during the session (someone re-ran `/contract` in parallel)
- Code-implies-spec divergence (cheap version, only files we touched)

If anything flags, surface it before marking ready-for-review.

### Step 3.5: Coverage measurement (if CLAUDE.md declares a Coverage policy)

Check whether CLAUDE.md contains a `## Coverage policy` section. If not, skip this step — the project hasn't opted in to coverage gating. If yes, this step is mandatory and its outcome can block status advancement.

**Workflow:**

1. **Run the project's coverage tool.** The exact command comes from the `**Tool**:` line in the Coverage policy section. Typical examples:
   - Python: `pytest --cov=src --cov-report=json --cov-report=term`
   - JavaScript/TypeScript: `npm test -- --coverage --coverageReporters=lcov`
   - Go: `go test -coverprofile=coverage.out ./... && gocov convert coverage.out > coverage.json`

2. **Run the coverage checker:**

   ```bash
   COV_RESULT=$(python3 .specship/coverage/coverage-check.py --base origin/main)
   COV_PASSED=$(echo "$COV_RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['passed'])")
   ```

   The checker reads the policy from CLAUDE.md, parses the coverage report, computes **delta coverage** (coverage of lines this session changed), and returns structured JSON.

3. **Log the measurement to the ledger** regardless of outcome:

   ```bash
   log coverage_measured session_id="\"$SID\"" \
       artifact="\"$ARTIFACT_PATH\"" \
       tool="\"<from result>\"" \
       metric="\"line\"" \
       line_pct=<from result> \
       branch_pct=<from result or null> \
       delta_pct=<from result> \
       project_pct=<from result> \
       files_measured=<from result> \
       threshold_delta=<from result> \
       threshold_project=<from result> \
       passed=<from result> \
       excluded_paths='[...]'
   ```

4. **If `passed == false`**: do NOT advance status to `ready-for-review` in Step 4. Instead:

   - Surface the failure to the user with concrete detail. Format:
     ```
     Coverage below threshold.

     Delta coverage:   75.0%  (threshold 90.0%)  ← gating
     Project coverage: 82.5%  (floor     80.0%)

     Lines you wrote that aren't covered by tests:

       src/notif/service.py:
         - lines 47, 48, 52 (the null-email branch in send_notification)

       src/notif/repository.py:
         - lines 31, 32 (the get-or-create path in find_by_user)

     Suggestions:
       - Add a test for send_notification with email=None
       - Add a test for find_by_user when no existing row matches

     Status stays in-progress. Re-run /work after adding tests, or commit
     with --no-verify to bypass (bypass will be logged separately).
     ```

   - Status stays `in-progress`. The user fixes coverage and re-runs `/work`, or bypasses deliberately.
   - DO NOT auto-generate the missing tests. Suggesting tests is helpful; writing them without the user's explicit instruction is the failure mode that turns coverage into ceremony. Tests that exist purely to lift a number poison the audit trail.

5. **If the coverage checker errors** (no report found, tool failed to parse), surface the error and treat as `passed=false` for safety. Status does not advance.

### Step 4: Update artifact status

**Spec mode:**
- `backend-only` or `frontend-only` spec → status to `ready-for-review`
- `full-stack` spec with only this scope complete → add `Backend complete: YYYY-MM-DD` (or `Frontend complete: ...`) to metadata; status stays `in-progress`
- `full-stack` spec with the other scope's marker already present → status to `ready-for-review`

**Fix mode:**
- Single-scope fix → status to `ready-for-review`
- Full-stack fix with only this scope complete → add scope-complete marker; status stays `in-progress`
- Full-stack fix with both scopes complete → status to `ready-for-review`
- If the fix is Case 2 or 4 with a superseding spec, ALSO advance that spec through the normal status progression (treat the spec as if /work had been run against it directly — `contract-locked` → `in-progress` → `ready-for-review` once execution touches files under its scope).

### Step 5: Append execution notes

**Spec mode:** add `## Execution notes (backend)` or `## Execution notes (frontend)` to the spec.

**Fix mode:** add `## Execution notes (backend)` / `## Execution notes (frontend)` to the **fix file**. The fix file is the canonical execution record for the bug — not the spec. If Case 2 or 4 advanced a superseding spec, also add a brief execution notes section to that spec referencing the fix.

Either way, the execution notes include:
- Final list of files changed in this scope
- Deviations from plan and why
- Follow-ups not covered
- Drift findings from post-flight `/check`, if any
- **Fix mode addition:** confirmation that the regression test was written and that it fails against the pre-fix code (described, not necessarily re-run)

### Step 6: Tell the user
- If `ready-for-review` → suggest review and commit
- If still `in-progress` → tell the user the other scope is outstanding and what to run
- **Fix mode addition:** if the fix is `--hot` or status was `emergency`, surface any deferred follow-ups loudly (e.g. "regression test was added inline — confirm coverage in CR" or "monitoring alert not yet configured").

**Decisions made this session.** If you logged any `decision_logged` events during this `/work` invocation, surface them in the post-flight summary. Format:

```
Decisions logged this session (N):
  1. <summary> — rationale: <rationale>
  2. <summary> — rationale: <rationale>
  ...

Review them before promoting the spec to signed-off:
  /review-decisions <spec-path>
```

If N == 0, mention that explicitly:

```
No decisions logged this session — execution stayed within the spec's
explicit boundaries.
```

This block is the discoverability bridge: it puts decisions in front of the user immediately, instead of relying on them remembering to run `/review-decisions` later. If decisions exceed 5, also flag that the spec was probably under-specified:

```
Note: N decisions is high. The spec was probably under-specified — consider
tightening Acceptance criteria or Open questions before the next /work run.
```

## What not to do

- Do not commit code. The human commits, after review. The pre-commit hook enforces spec/fix-linkage.
- Do not modify the spec's acceptance criteria or contract surface mid-flight. If wrong, stop and ask.
- Do not modify the fix's classification mid-flight. If you realise the case is different, stop and re-run `/fix`.
- Do not modify files in `_generated/`. Read-only inputs from `/contract`.
- Do not work across scopes in one invocation.
- Do not skip drift checks because "the previous session was mine". Re-running on a stale spec/fix is the most common drift cause.
- Do not skip Pact verification because "tests pass locally". The Pact stub is what the frontend expects; deviating from it is drift.
- Do not skip the regression test in fix mode. The test can be inline rather than perfect, but it must exist.
- Do not work on an artifact whose status is `signed-off` or `done`. Open a new fix or spec for follow-ups.
- Do not re-declare types from `_generated/`. Import them.

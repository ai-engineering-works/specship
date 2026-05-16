---
description: Orchestrate a full-stack spec through /contract, parallel /work (backend + frontend via subagents using a two-phase plan-then-execute pattern), and final /check. The orchestrator runs in the main session; subagents work in isolated contexts. Catches up to the Stripe/Wiz/Rakuten parallel-agent pattern for full-stack work, while preserving the human-in-the-loop plan approval that /work enforces in direct invocation.
argument-hint: <path-to-spec-file>
recommended-model: opus  # sonnet | opus — see CLAUDE.md for guidance
---

# /ship — Orchestrate a Full-Stack Spec to Completion

You are orchestrating a full-stack spec through the entire specship pipeline in a single command: contract compilation, then a two-phase parallel backend + frontend execution via subagents, then drift detection. This command saves the user from running `/contract → /work --scope backend → /work --scope frontend → /check` manually as four separate sessions.

You are NOT doing the implementation work yourself. You delegate to subagents.

## Why two-phase

`/work` is designed with a plan-approval gate that requires human review before code changes. When `/work` runs as a subagent inside `/ship`, that gate has no human in the subagent's context — so the subagent would either stall (blocking the orchestration) or silently bypass the safety check.

`/ship` resolves this by splitting Stage 2 into **plan-only** dispatch (both subagents draft plans in parallel and return them) and **execute** dispatch (after the orchestrator presents both plans to the human for combined approval, approved-scope subagents execute in parallel). One human approval covers both scopes. The audit trail records the approval as `plan_approved` events.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"ship command"** section. Generate one parent session UUID for this `/ship` invocation. Each subagent receives its own session UUID via its prompt; log `subagent_spawned` before dispatch with the child UUID and the phase (`plan` or `execute`), `plan_drafted` events come from the planning subagents, `plan_approved` events come from the orchestrator after the human's verdict, and `subagent_completed` after each subagent returns.

## When to use this command

Use `/ship` when:
- The spec is full-stack (has both backend and frontend acceptance criteria)
- The Contract surface is finalised (the user has reviewed the spec's contract section)
- Backend and frontend work can proceed in parallel (i.e., neither side needs the other's implementation to finish first)

Do NOT use `/ship` when:
- The spec is backend-only or frontend-only — run `/work` directly
- The Contract surface has open questions — finalise the spec first
- The user wants to review contract artifacts before any code is written — run `/contract` standalone first, then `/ship` after review (which will detect contract-locked status and skip re-compilation)
- The work involves a fix (`fixes/*.md`) — `/ship` is for greenfield specs only; fixes are usually single-scope and don't benefit from parallel execution

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: path to a spec file under `specs/`

If the path is missing, ask which spec to ship.

## Pre-flight

1. **Read `CLAUDE.md`** for invariants, project type, and verification commands.

2. **Validate the spec:**
   - Status must be one of: `draft`, `in-progress`, `contract-locked`
   - Scope must be `full-stack` — if not, refuse and tell the user to run `/work` directly with the appropriate scope
   - "Open questions" section must be empty (or contain only resolved items)
   - "Contract surface" section must be non-empty

   If any check fails, stop and tell the user what needs to change. Log `session_end` with `outcome="blocked"`.

3. **Read `.specship/ledger/HOW-TO-LOG.md`** if not already loaded.

4. **Generate the parent session UUID** and log `session_start` with `command="ship"`.

## Stage 1: Contract compilation

Run `/contract` directly in this session (do NOT delegate to a subagent — the operation is cheap, deterministic, and the orchestrator needs the result to be in its own context for downstream decisions).

If the spec is already `contract-locked` AND the contract surface hash hasn't changed since the last compilation:
- Skip re-compilation
- Tell the user: "Contract already locked at <hash> — skipping /contract."

Otherwise, run the full `/contract` flow:
- Compile Contract surface to `_generated/`
- Update spec status to `contract-locked`
- Log artifact events per the contract command's logging block

If `/contract` blocks (e.g., breaking change detected, hash mismatch on re-run), surface this to the user and stop. Log `session_end` with `outcome="blocked"`. Do NOT proceed to Stage 2.

## Stage 2: Two-phase parallel work via subagents

`/work` is designed with a plan-approval gate that fires before execution — a safety property that requires human review before code changes happen. When `/work` runs as a subagent inside `/ship`, that gate would fire inside the subagent's context where no human is present.

**The fix: split Stage 2 into a planning sub-phase and an execution sub-phase, with one combined human approval in between.** This preserves the safety property (a human approves before any code changes) AND keeps the parallelism benefit (both plans are drafted concurrently, both executions run concurrently).

### Stage 2a — Plan-only dispatch

**Spawn two subagents in parallel using the Task tool. Issue both Task invocations in the same response — Claude Code will execute them concurrently.**

For each scope (backend, frontend):

1. Generate a child session UUID:
   ```bash
   CHILD_SID_BACKEND=$(python3 -c "import uuid; print(uuid.uuid4())")
   CHILD_SID_FRONTEND=$(python3 -c "import uuid; print(uuid.uuid4())")
   ```

2. Log the spawn (before dispatching):
   ```bash
   log subagent_spawned session_id="\"$PARENT_SID\"" \
       child_session_id="\"$CHILD_SID_BACKEND\"" \
       command='"work"' scope='"backend"' phase='"plan"'
   log subagent_spawned session_id="\"$PARENT_SID\"" \
       child_session_id="\"$CHILD_SID_FRONTEND\"" \
       command='"work"' scope='"frontend"' phase='"plan"'
   ```

3. Dispatch both subagents via Task tool, **in the same response**:

   **Task 1 — Backend plan subagent prompt:**

   ```
   Execute the /work slash command in --plan-only mode against this spec:

   spec: <full-path-to-spec>
   scope: backend
   parent_session_id: <CHILD_SID_BACKEND>
   flags: --plan-only

   Constraints:
   - Run /work's pre-flight (status checks, drift check) but STOP after drafting
     the plan. Do NOT execute. Do NOT modify any files in src/ or tests/.
   - Write the plan to .specship/plans/<plan_id>.md per /work's --plan-only spec.
   - Log plan_drafted to the ledger.
   - Return the plan_id, plan_path, and a short summary (files-to-modify count,
     test additions count, estimated decisions count) to the orchestrator.

   Use the /work slash command's full prompt for instructions. Do not invent
   new behaviour.
   ```

   **Task 2 — Frontend plan subagent prompt:** Same structure with `scope: frontend` and `<CHILD_SID_FRONTEND>`.

4. **Wait for both Tasks to return with their plans.** Both subagents stop at the planning gate. Neither has modified any code.

5. Log each plan's completion:
   ```bash
   log subagent_completed session_id="\"$PARENT_SID\"" \
       child_session_id="\"$CHILD_SID_BACKEND\"" \
       outcome='"plan-drafted"' phase='"plan"'
   # same for frontend
   ```

### Stage 2b — Combined human approval

Read both plan files (one for backend, one for frontend). Present them to the human as a single combined approval:

```
Two plans ready for review. Approve, reject, or request changes for each.

═══════════════════════════════════════════════════════════════════════════
Backend plan — .specship/plans/<backend_plan_id>.md
  Files to modify: <count> · Tests to add: <count> · Decisions expected: <count>

  Order of criteria:
  1. <criterion 1>
  2. <criterion 2>
  ...

  Files:
  - <path 1>
  - <path 2>

  Decisions to expect:
  - <one-line summary>
  - <one-line summary>

  Warnings: <if any>

═══════════════════════════════════════════════════════════════════════════
Frontend plan — .specship/plans/<frontend_plan_id>.md
  [same structure]

═══════════════════════════════════════════════════════════════════════════
Approve which? Type one of:
  approve both              (proceed to execution for both scopes)
  approve backend           (execute backend only; leave frontend unchanged)
  approve frontend          (execute frontend only)
  reject both               (stop /ship entirely; status stays contract-locked)
  request changes <scope>   (give feedback; /ship exits, user re-runs after change)
```

Wait for the user's response. Log each plan's verdict:

```bash
log plan_approved session_id="\"$PARENT_SID\"" \
    plan_id="\"$BACKEND_PLAN_ID\"" \
    scope='"backend"' \
    verdict='"<approved|rejected|changes-requested>"' \
    reviewer_note='"<if any>"'
# same for frontend
```

**If both rejected or changes-requested**: STOP. Log `session_end` with `outcome="blocked"`. Tell the user: "Both plans rejected. /ship halted. Status remains contract-locked. Re-run after addressing feedback."

**If exactly one approved**: continue to Stage 2c with only that scope. The other scope's spec criteria stay unticked; surface this in Stage 4 reporting.

### Stage 2c — Execute approved plans

For each plan that was approved, dispatch a fresh subagent in `--from-plan` mode. **Issue all approved-scope Task invocations in the same response** for parallelism.

For each approved scope:

1. Generate a new child session UUID (the planning subagent's session is closed):
   ```bash
   CHILD_SID_BACKEND_EXEC=$(python3 -c "import uuid; print(uuid.uuid4())")
   ```

2. Log spawn:
   ```bash
   log subagent_spawned session_id="\"$PARENT_SID\"" \
       child_session_id="\"$CHILD_SID_BACKEND_EXEC\"" \
       command='"work"' scope='"backend"' phase='"execute"' \
       plan_id="\"$BACKEND_PLAN_ID\""
   ```

3. Dispatch via Task:

   ```
   Execute the /work slash command in --from-plan mode:

   spec: <full-path-to-spec>
   scope: backend
   parent_session_id: <CHILD_SID_BACKEND_EXEC>
   flags: --from-plan .specship/plans/<backend_plan_id>.md

   Constraints:
   - Read the plan file. Validate that a plan_approved event exists for this
     plan_id (if not, REFUSE).
   - Execute per the plan. Do NOT re-plan, do NOT present a new plan to anyone.
     The human already approved this plan.
   - Run scope's verification commands, coverage gate, /check post-flight.
   - Tick acceptance criteria, log decisions inline, update status.
   - Return summary: files modified, tests added, decisions logged, coverage
     measured, any blockers.
   ```

4. **Wait for both execution Tasks to return.** Both have actually modified code in their respective scopes.

5. Log each completion:
   ```bash
   log subagent_completed session_id="\"$PARENT_SID\"" \
       child_session_id="\"$CHILD_SID_BACKEND_EXEC\"" \
       outcome='"<completed|blocked|abandoned>"' phase='"execute"'
   ```

### What if one execution fails and the other succeeds?

Same handling as the original /ship design:
- **Both completed cleanly** → proceed to Stage 3
- **One blocked, one completed** → DO NOT auto-revert the completed work. Tell the user which side blocked and why; the user decides whether to fix the blocker or roll back. Log `session_end` with `outcome="partial"`.
- **Both blocked** → tell the user both sides need attention. Log `session_end` with `outcome="blocked"`.

Do NOT try to "fix" a subagent's failure yourself in the orchestrator. The boundary matters; the user needs visibility into which subagent failed for which reason.

## Stage 3: Combined drift check

Once both subagents return, run `/check` directly in the orchestrator session (not via subagent — `/check` is cheap and read-only, and the orchestrator's context is the right place for the final report).

`/check` runs across all scopes covered by the spec. Report any drift findings to the user.

If `/check` finds drift after both subagents reported completion, this is a real bug — the subagents claimed work was done but the verification disagrees. Surface this directly:

> Both backend and frontend subagents reported completion, but /check found drift:
>
> [drift findings]
>
> This is a discrepancy worth investigating. The subagents may have ticked criteria without code traces, or contract artifacts may have stale references. Consider running /investigate against this discrepancy.

## Stage 4: Report and close

Tell the user:

```
/ship completed for specs/<file>.md.

Contract: <new | unchanged from previous lock>
Backend:  <files-modified count>, <tests-added count>, outcome=<completed|blocked>
Frontend: <files-modified count>, <tests-added count>, outcome=<completed|blocked>
Drift check: <clean | N findings>

Next: commit each scope independently (one commit per scope is cleaner than a
combined commit). Reference the spec in each commit message:

  git commit -m "backend: <description> §ref:specs/<file>.md"
  git commit -m "frontend: <description> §ref:specs/<file>.md"

When both are merged and acceptance is confirmed, the spec is ready for status
update to signed-off (manual — /ship does not auto-promote).
```

Log `session_end` with overall outcome:
- `completed` — both subagents completed AND /check is clean
- `partial` — one or both subagents completed but /check found drift, OR one blocked
- `blocked` — both subagents blocked or contract compilation refused

## What /ship does NOT do

- Does NOT commit code automatically. The user reviews each subagent's output and commits manually. This preserves the pre-commit Wall as the audit gate.
- Does NOT promote spec status beyond `contract-locked` → `ready-for-review`. Promotion to `signed-off` is a manual user act after acceptance.
- Does NOT run cross-scope tests (e.g., end-to-end tests that hit both backend and frontend). Those are the user's responsibility — `/ship` cannot tell what the user's e2e test command is without explicit configuration in CLAUDE.md.
- Does NOT retry failed subagents. If a subagent blocks, the human resolves the blocker, then re-runs `/ship` (which will skip `/contract` if hash is unchanged, re-dispatch the subagents).
- Does NOT spawn more than two subagents. If the spec has additional scopes (e.g., a "data-pipeline" scope), `/ship` falls back to sequential execution for the extras. Three+ parallel subagents lose more in coordination overhead than they gain in parallelism for typical full-stack work.

## Discipline check

If you find yourself doing implementation work in the orchestrator session — writing code, modifying files in src/ — you have lost the boundary. STOP. The orchestrator dispatches and reports; it does not implement. Spawn the appropriate subagent or stop and ask the user.

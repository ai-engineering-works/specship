# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0.

## [Unreleased]

### Removed — bundled single-file dashboard

The bundled dashboard (`dist/dashboard/dashboard.html`, `open-dashboard.sh`, README)
has been removed. Dashboards now live in the standalone **specship-dashboard** repo,
which reads `.specship/ledger/events.jsonl` across repos and renders richer,
multi-repo analytics. Consequences:
- `install.sh` no longer creates `.specship/dashboard/` or installs the dashboard
  (install steps renumbered 1/9–9/9).
- `sync-local.sh` / `verify-sync.sh` no longer sync or check the dashboard.
- The e2e harness (`tests/e2e/`) dropped its dashboard render checks (the Playwright
  `dashboard_check.mjs`, the `test_dashboard.sh` self-test, the per-tier `#data-status`
  cross-checks, and the `--no-dashboard` flag).
- Passing mentions of "the dashboard" in `/qa`, `/show`, and the QA authoring guide
  were reworded to reference the ledger.

### Changed — inline y/n handoff between commands (no command-pasting)

`/spec`, `/fix`, and `/investigate` now offer to continue to the next step with a
single confirmation (Enter = yes) instead of printing a command for the user to
copy-paste:
- `/spec` → `/work` (single-scope) or `/contract` (full-stack). The `/work` offer
  notes the sonnet→opus model split so the user can decline and run it in a fresh
  session.
- `/fix` → `/work` (Case 1). Case 2/4 offer `/contract` on the new spec first, since
  it needs a human edit before `/work`.
- `/investigate` → `/fix`, pre-filling `--against` and `--from-investigation` so the
  user only classifies the bug Case rather than retyping the whole command.
On yes the next slash command is executed in the same session; on no the explicit
command is shown as before. `/ship` already used a y/n-style approval and is unchanged.

### Changed — test-per-acceptance-criterion gate in `/work` and `/fix`

`/work` now requires a test case for every acceptance criterion (the scenarios the
plan identifies), not just an overall test list:
- **Plan:** the freeform "Tests to add or update" plan section is now "Tests per
  acceptance criterion" — each criterion maps to at least one test (`criterion →
  test file::test name`), or carries an explicit justification if genuinely not
  unit-testable.
- **Execution:** for each criterion, write its test first (confirm it fails for the
  right reason), then implement until it passes. A criterion's checkbox is not ticked
  until its mapped test exists and passes (or a not-testable justification stands).
- **Post-flight:** new Step 3.4 gate — every in-scope criterion must map to a passing
  test (or a standing justification) before status advances to `ready-for-review`;
  otherwise status stays `in-progress` and the gap is surfaced. This is distinct from
  the Step 3.5 coverage gate (line coverage of changed lines): 3.4 verifies that each
  criterion is *intentionally* tested, not that a coverage number was hit.
- `/fix` inherits this through `/work` (it executes fixes), and its acceptance-criteria
  template now states the requirement; the mandatory regression test is the test for
  the bug-recurrence criterion.

### Added — Auto-lessons continual-learning loop

Added the automatic-capture half of a learning loop, feeding the existing /encode-lesson
promotion path:
- `/capture-lessons` — records ≤3 lesson candidates per session (SessionEnd hook + end of
  /work,/ship,/fix); idempotent per session.
- `dist/lessons/curate.py` — LLM-free hourly curator: decay + token-overlap clustering + digest.
- `/review-lessons` — triage affordance (promote/dismiss/skip), mirrors /review-decisions.
- `/encode-lesson --from-candidate <id>` — promote a candidate without a formal investigation,
  guardrails intact.
- Five new ledger event types projected into a `lesson_candidates` table.
- Candidates never auto-write to CLAUDE.md; only the human-gated /encode-lesson does.

Spec: specs/2026-05-20-auto-lessons-continual-learning.md

### Added — QA artifact subsystem (`/qa`, `/show`)

Correctness specifications that outlive any one implementation. Unit tests written during
`/work` verify "did Claude exercise this code"; QA artifacts verify "does the system honor
the intent" and survive refactors because they live alongside specs/fixes, not in the code.

- **`/qa <intent>`** — authors three artifact kinds via a structured interview, each tracing
  back to a parent spec or fix:
  - **Regression** — a frozen input/output pair captured at fix time; append-only by
    convention, with a mandatory `parent_fix`. The documented correction pattern is
    retire + re-create, never mutate an approved artifact.
  - **Scenario** — a given/when/then path derived from a spec's Contract Surface and
    Acceptance Criteria; one file per scenario under `scenarios/<spec-slug>/`.
  - **Property** — an invariant plus an input-space DSL; the generator produces many inputs
    and shrinks failures to a minimal counterexample. Stateless only in v1.
- **Test generators** under `dist/qa-generators/` compile artifacts into runnable tests under
  `tests/regression/`, `tests/scenario/`, `tests/property/` — targeting pytest or Jest. Each
  generated file carries an `# AUTO-GENERATED` header, a `§qa:` linkback, and a content hash.
- **Playwright e2e** — scenario and regression artifacts for frontend-touching specs can carry
  a `ui_action:` block (semantic-locator DSL + `test.use({ video: 'on' })`), emitting an
  additional `.spec.ts` under `tests/e2e/`. Property artifacts deliberately don't support it.
- **`/show`** — read-only discovery of specs, fixes, investigations, and QA artifacts by
  title, ticket ID, kind, or status, without leaving the chat.
- New QA templates under `dist/templates/` (`regression`, `scenario`, `property`) and the
  authoring guide `dist/templates/HOW-TO-AUTHOR-QA.md`.
- Ledger support for `qa_artifact_created`, `qa_artifact_updated`, `qa_tests_generated`, and
  `qa_waiver_granted` events, plus a `qa_waivers` table.
- **Advisory pre-commit QA checks** — new `dist/hooks/qa-check.py`, invoked best-effort by the
  pre-commit hook and installed to `.specship/hooks/qa-check.py`. It warns (never blocks) when
  (a) a commit edits the `Input` or `Expected output` of an already-approved regression artifact
  (append-only), and (b) a generated test drifts from its source artifact — a test modified
  without its artifact, or an artifact modified without its `generated_test` being regenerated.
  Drift is detected by staging membership rather than the embedded content hash, because `/qa`
  rewrites artifact frontmatter after the hash is stamped. The Wall itself stays pure-bash; this
  layer reuses `python3` (already required by the coverage gate) and no-ops if it is unavailable.

Note: this subsystem is partially landed. The `/qa` and `/show` prompts, generators, templates,
ledger schema, and the advisory pre-commit checks above are in place. Still not wired into the
command files: the mandatory `Invariants` section in `/spec`, and the `/ship` Stage 0 QA gate
that consumes `qa_waivers`.

Docs: dist/templates/HOW-TO-AUTHOR-QA.md

### Added — v0.12.0 (renamed from attest to specship)

**This is a brand change, not a behaviour change.** Everything attest did, specship does — same commands, same ledger, same workflow. The audit trail under the old name is preserved exactly. Only the names, paths, and binaries change.

Why the rename: the old name "attest" emphasized the act of certification (every artifact attests to something). That framing was accurate but passive — attestation is something you stamp after the fact. "specship" captures the active discipline the workflow actually enforces: take a spec, ship the code, every step traceable. The workflow IS the spec-to-ship pipeline. The name now matches the verb.

**What renamed**:
- The product itself: `attest` → `specship`
- The runtime directory: `.attest/` → `.specship/`
- The ledger binary: `attest_ledger.py` → `specship_ledger.py`
- The bash helpers: `attest_log`, `attest_session_id`, `attest_summary`, `attest_rebuild_index` → `specship_log`, `specship_session_id`, etc.
- The design archive: `ATTEST-DESIGN.md` → `SPECSHIP-DESIGN.md`
- The plans directory (added v0.11.0): `.attest/plans/` → `.specship/plans/`
- The dashboard install path: `.attest/dashboard/` → `.specship/dashboard/`

**What did NOT rename**:
- The nine slash commands: `/spec`, `/contract`, `/work`, `/check`, `/fix`, `/investigate`, `/ship`, `/encode-lesson`, `/review-decisions` — unchanged.
- The JSONL event schema: `event_type` values (`session_start`, `plan_drafted`, `coverage_measured`, etc.) are unchanged. Old ledgers are forward-compatible.
- The skill names: `claude-md-architect` and `spec-reverse-engineer` — unchanged.
- The Wall's behaviour: same six acceptance scenarios.
- The pre-commit hook's gate logic.
- Hash mechanism, breaking-change detection, coverage gate, two-phase `/ship` orchestration — all unchanged.
- Historical CHANGELOG entries: entries below v0.12.0 keep the original "attest" name because that's an honest record of when those changes happened.

**Migration for existing installs**:

A one-time migration script lives at `scripts/migrate-from-attest.sh`. It renames `.attest/` → `.specship/` in your repo, renames the ledger binary, updates the pre-commit hook references, and updates the `.gitignore` entries. The ledger contents (`events.jsonl`) are preserved byte-for-byte — every historical event, session, decision, plan, and coverage measurement stays intact under the new path.

```bash
# In the specship distribution repo:
./scripts/migrate-from-attest.sh /path/to/your/target/repo

# Then re-install the renamed binaries:
./scripts/install.sh /path/to/your/target/repo

# Then commit in the target repo:
cd /path/to/your/target/repo
git add .specship .gitignore
git rm --cached -r .attest 2>/dev/null || true
git commit -m "migrate from attest to specship"
```

**Safety**:
- `install.sh` refuses to run on a repo that still has `.attest/` present. You must migrate first. This prevents the failure mode where someone runs install over an attest install and ends up with a confusing parallel state (two ledgers, two helper trees, hook pointing at the old binary). Explicit migration is auditable; auto-detection-magic is not.
- The migration script keeps backups of any file it modifies (e.g. `.git/hooks/pre-commit.pre-specship.bak`).

**What I deliberately did NOT do**:
- I did not rewrite historical CHANGELOG entries. v0.6.x through v0.11.0 happened to a product called attest. Pretending otherwise loses information. The version-history portions of SPECSHIP-DESIGN.md likewise refer to "attest" where they describe past decisions, with a top-of-file note about the rename.
- I did not bundle a legacy-symlink so that `attest_ledger.py` keeps working as an alias for `specship_ledger.py`. Symlinks-as-aliases hide reality from audit tools (which file is being run?) and slowly defeat the rename. If you have automation that hardcodes `attest_ledger.py` somewhere external to the install (CI workflow elsewhere, monitoring), update that automation as a deliberate change.

### Added — v0.11.0 (two-phase /ship orchestration)

**Bug fix from real-ticket use**. The first time `/ship` ran on a real bank ticket, both subagents stalled after their drift checks with "I have a plan, do you approve?" — `/work`'s plan-approval gate fired inside the subagent context where no human was present, and the orchestrator had no way to surface the question. `/ship` was non-functional under the v0.10.0 design. This release fixes that.

**The architectural change**: `/ship` Stage 2 is split into a planning sub-phase and an execution sub-phase, with one combined human approval in between. The audit trail records the approval as `plan_approved` events.

- **`/work` gains two flags**:
  - `--plan-only` — do pre-flight, draft a plan, write it to `.specship/plans/<plan_id>.md`, log `plan_drafted`, exit. Used by `/ship` to capture plans for combined approval.
  - `--from-plan <path>` — read a previously-drafted plan, validate that a `plan_approved` event exists for the plan_id, skip pre-flight and planning, execute directly. Used by `/ship` after approval. **Safety property**: refuses to execute plans that don't have a corresponding `plan_approved` event in the ledger.
  - Direct invocation (no flag) unchanged — drafts plan inline, waits for human approval, executes.

- **`/ship` Stage 2 rewrite**:
  - **Stage 2a (plan dispatch)**: spawns both `/work --plan-only` subagents in parallel. Both draft plans and exit without modifying any code.
  - **Stage 2b (combined approval)**: orchestrator reads both plans, presents them to the human as one combined approval. Options: `approve both | approve <scope> | reject both | request changes <scope>`. Partial approval is a first-class outcome — `/ship` will execute approved scopes only.
  - **Stage 2c (execute dispatch)**: spawns fresh `/work --from-plan` subagents in parallel for each approved scope.

- **Three new ledger event types** projecting into a new `plans` table:
  - `plan_drafted` — emitted by `/work --plan-only`; fields: plan_id, parent_session_id, scope, source_artifact, plan_path, files_to_modify (JSON array), estimated_decisions
  - `plan_approved` — emitted by `/ship` after human verdict; fields: plan_id, scope, verdict (approved/rejected/changes-requested), reviewer_note. Layered onto existing plans row via UPDATE.
  - `plan_executing` — emitted by `/work --from-plan` at start of execution; layered onto plans row.

- **Plans are transient**. `.specship/plans/*.md` is now gitignored on install. Plan files are handoff between subagents; the audit-relevant facts live in the ledger.

- **Dashboard updates**:
  - L2 workflow timeline gains a "plan review" stage between contract and work, shown only for intents that used `/ship`
  - New friction signal #7: surfaces plans drafted but not yet approved (the exact symptom of the v0.10.0 deadlock if a session got interrupted mid-`/ship`)

- **HOW-TO-LOG.md** updated with `/work --plan-only`, `/work --from-plan`, and the updated `/ship` event sequence.

- **`specship_ledger.py summary`** now includes a "`/ship` plan approvals" block showing total drafted, approved, rejected, changes-requested, pending, and executed counts.

### Migration from v0.10.x

- Re-run `./scripts/install.sh /path/to/your/repo` to install the updated commands and add `.specship/plans/` to gitignore.
- **Existing data is unaffected.** The `plans` table is created on next `rebuild-index`; before any plan events exist, it's empty. Sessions logged under v0.10.0's old `/ship` design (which never completed) remain in the ledger as orphaned `subagent_spawned` events without matching `subagent_completed` — these are visible in the dashboard as in-progress and can be ignored or cleaned by archiving the affected session_ids.
- The fix is fully backwards-compatible for the 9 other commands and for direct `/work` invocation. Only `/ship` and the two new `/work` flags are new behaviour.

### Design notes

A few decisions worth recording explicitly (full context in SPECSHIP-DESIGN.md §3.13):

- **Why not an `--auto-approve` flag on `/work`?** Inconsistent gate behaviour in a regulated workflow is its own audit risk. The audit answer to "did the AI's plan get human approval?" should be the same regardless of whether `/work` was invoked directly or via `/ship`.
- **Why not sequential degradation?** Loses the main reason `/ship` exists (parallelism) without fixing the underlying mismatch.
- **Why are plans gitignored?** They're transient handoffs between subagents within a single `/ship` invocation. The audit-relevant facts (what was planned, what was approved, what was executed) are in the ledger. Committing plans would add noise without audit value.
- **Why partial approval is a first-class outcome.** "Approve backend, reject frontend" is a real review verdict, not a degenerate case. `/ship` executes the approved scope; the rejected scope's spec criteria stay unticked, the spec status doesn't advance. The user re-runs `/ship` after addressing the rejected scope.

### Added — v0.10.0 (test coverage gate)

**Coverage policy as a first-class invariant.**

Test coverage is enforced as a three-gate pipeline that reuses specship's existing primitives. The gating metric is **delta coverage** (percentage of lines added or modified in this session that are covered by tests) — answering the audit-relevant question "did the AI-generated code come with adequate tests?". Project-wide coverage is tracked alongside as informational.

- **New: `dist/coverage/coverage-check.py`** — measures and parses coverage reports. Reads policy from CLAUDE.md (`## Coverage policy` section), supports both coverage.py JSON and lcov formats, computes delta coverage by intersecting `git diff` line ranges with covered/uncovered lines from the report. Returns structured JSON for downstream consumers. Verified against 5 scenarios: below threshold, above threshold, no CLAUDE.md policy, missing report, lcov input — all classify correctly.

- **`/work` post-flight Step 3.5** — runs the coverage check after drift detection, before status promotion. Logs `coverage_measured` to the ledger regardless of pass/fail. If delta coverage is below threshold, status stays `in-progress` and the user sees the specific uncovered lines (file:line detail) with concrete suggestions. **Does NOT auto-generate tests** — that's the failure mode that turns coverage into ceremony.

- **Pre-commit hook coverage gate** — `_check_coverage_gate` helper that reads the most recent `coverage_measured` event from the ledger and blocks the commit if it failed. Soft block (`--no-verify` bypassable, bypasses logged). Runs `rebuild-index` first so the gate sees the latest events (adds ~200ms to commits with the policy active; no cost when CLAUDE.md doesn't declare a policy).

- **New ledger event type: `coverage_measured`**. Projects into a new `coverage` table with columns for tool, metric (line/branch/both), line_pct, branch_pct, delta_pct, project_pct, files_measured, threshold_delta, threshold_project, passed, excluded_paths. Surfaced in the `summary` command output with a "Coverage measurements" block (pass/fail counts, averages) and a "Recent coverage failures" block (top 5 failures with timestamps and gap detail).

- **CLAUDE.md template** has a new "Coverage policy" section with 7 fields: Metric, Threshold, Project floor, Tool, Report path, Excluded paths, Bypass policy. Removing this section from a project's CLAUDE.md disables coverage gating entirely (no enforcement, no warnings). The Excluded paths field defaults to `_generated/**, tests/**, migrations/**` so generated code and test code don't count toward the denominator.

- **install.sh** detects whether CLAUDE.md declares a policy at install time and surfaces guidance accordingly. Coverage helper installs to `.specship/coverage/coverage-check.py` (executable). Step count went from 7 to 8.

### Design notes (the explicit non-choices)

A few decisions made deliberately rather than by default:

- **Delta coverage gates, project coverage is informational.** A regulator's question is "did this AI-generated code come with adequate tests" — answered by delta. Many teams' CI gates on project (drop-from-baseline). specship captures both per measurement so the audit story remains coherent across the divergence.
- **The pre-commit gate is bypassable.** Same `--no-verify` mechanism as the linkage gate. Consistency in a regulated workflow matters; inconsistent gate behavior creates its own audit risk. Bypasses are logged separately as `gate_bypassed` events.
- **No auto-test-generation.** When coverage is below threshold, `/work` surfaces uncovered lines with concrete suggestions but does NOT write the tests. Tests-that-exist-purely-to-lift-a-number poison the audit trail; better to surface the gap and let humans (or a deliberate `/work` re-invocation) decide.
- **No new coverage tool.** specship does not implement coverage measurement. It runs the team's existing tool (pytest --cov, jest --coverage, go test -coverprofile, etc.) and parses the output. The team's coverage configuration stays in the team's coverage tool config (.coveragerc, jest.config.js, etc.) — specship just declares the threshold and parses the result.
- **The hook reads the ledger; it does NOT re-run coverage.** Re-running coverage inside a git hook would make commits painfully slow. The assumption is that `/work` or `/fix` measured coverage in its post-flight; the hook reads that recent measurement. If no measurement exists, the hook warns but allows (failing-safe, since the absence of measurement is a `/work` problem, not a commit-time problem). CI re-runs coverage authoritatively against a clean checkout.

### Migration from v0.9.x

- Re-run `./scripts/install.sh /path/to/your/repo` to install the coverage helper and the updated hook.
- **Coverage gating is opt-in.** Existing projects without a `## Coverage policy` section in CLAUDE.md see zero change. To enable, add the section using the format in the new `CLAUDE.md.template`.
- Existing ledger data is unaffected. The new `coverage` table is created on next `rebuild-index`; before any coverage events exist, it's empty.

### Added — v0.9.0 (human-in-loop review, model pinning, explicit scope)

**Critique 4 closed: human-in-loop decision log.**

- **New: `/review-decisions` command.** Surfaces decisions Claude logged during `/work` (and other commands) for human review. Lists recent unreviewed decisions, lets the user mark each as `accepted | rejected | needs-redo` with an optional free-text note, and records the verdict to the ledger.
- **Extended `decisions` table** with four new columns: `review_verdict`, `reviewer_note`, `reviewed_at`, `reviewed_session`. The original `decision_logged` events remain append-only; verdicts are layered on top via `decision_reviewed` events. The audit trail captures both Claude's decisions and the human's reaction to them.
- **New ledger event type `decision_reviewed`.** Indexer uses `INSERT…ON CONFLICT DO UPDATE` on `decision_id` to layer verdicts onto the original decision rows.
- **`/work` tightened.** Decision-logging trigger now lists 4 concrete situations that demand a log (library/pattern choice, edge-case handling, verification step modification, divergence from codebase pattern) and 4 explicit non-triggers (mechanical choices, spec-dictated actions, CLAUDE.md-policy actions, formatter-normalised choices). Post-flight Step 6 now surfaces "decisions logged this session" inline, with a flag if the count exceeds 5 (signal that the spec was under-specified).
- **Soft-reject design.** `rejected` and `needs-redo` are deliberately distinct. `rejected` records disagreement but the code stands. `needs-redo` requires the user to re-invoke `/work` with an override. The command does NOT auto-spawn `/work` on `needs-redo` verdicts.
- **Summary output** now shows both Claude's original mark and the human review mark per decision, plus an aggregated "Decision reviews:" block.

**Critique 10 closed: model-version pinning.**

- **New `recommended-model` frontmatter field** on every slash command. Values: `sonnet` or `opus`. Advisory, not enforced — Claude Code uses whatever model the user has selected, but the field documents intent for regulated environments.
- Per-command recommendations established: `/spec`, `/contract`, `/check`, `/review-decisions` recommend sonnet (textual + judgment work). `/work`, `/ship`, `/fix`, `/investigate`, `/encode-lesson` recommend opus (heavy execution, hypothesis generation, high-stakes abstraction).
- **CLAUDE.md template** has a new "Recommended model" section explaining the convention and listing the per-command split. Self-hosted CLAUDE.md updated to match.
- **NOT added: a model-regression eval suite.** That's premature — the right time to add evals is after empirical signal from real ticket use surfaces which commands are most model-sensitive. Building speculative evals before that is the failure mode the grilling document warned against.

**Critique 11 closed: explicit scope statement.**

- **New README section "Scope — what specship is, and what it isn't"** placed immediately after Quick Start. Table of 10 adjacent concerns with the canonical tool to use instead: LangGraph/CrewAI/AutoGen (general agent frameworks), GitHub/Gerrit (code review), Apigee/Kong (API gateways), LangSmith/Arize (full observability platforms), PagerDuty (incident management), Bazel/Nx (monorepo build), and others.
- **Removed stale "five things" claim** from the README intro. The system is now nine commands, two skills, one pre-commit hook, observability ledger, and contract helpers — calling that "five things" was straightforwardly wrong.
- The scope statement is structured to make scope-creep arguments fail cleanly: each adjacent concern names a real, well-known tool that does that job better than specship could.

### Why now
The grilling review identified these three critiques together because they share an asymmetric impact: each is small in code surface but large in adoption-readiness. Critique 4 makes audit trails complete (Claude's decisions + human verdicts). Critique 10 makes outputs reproducible under model upgrades. Critique 11 prevents the framework from being expected to do things it doesn't. All three reduce friction for the "do I trust this enough to deploy in production?" decision.

### Migration from v0.8.x
- Re-run `./scripts/install.sh /path/to/your/repo` to install the new command.
- Existing decisions in the ledger gain four new nullable columns; running `rebuild-index` migrates cleanly.
- The new frontmatter field is invisible to Claude Code's slash-command UI but documents intent. No behaviour change required from existing users.

### Added — v0.8.0 (learning loop + structural contract integrity)

**Critique 5 closed: closure loop from investigations to invariants.**

- **New: `/encode-lesson` command.** Promotes a lesson learned from a resolved investigation into a durable invariant. Accepts an investigation file (status must be `closed-resolved`) and optionally a fix file. Extracts 1-3 candidate lessons, classifies each as architectural / module-specific / tooling / command-specific, proposes a destination (root CLAUDE.md, nested CLAUDE.md, skill gotchas, or command prompt), and after user approval inserts the invariant with a linkback comment.
- Each encoded lesson carries a **stable lesson ID** (short hash of the lesson text) embedded in both the destination artifact and the ledger entry, so audit queries can trace any invariant back to the investigation it came from.
- The investigation file gets a "Lesson encoded" section appended for bidirectional cross-reference.
- New ledger table: `lessons (lesson_id, ts, session_id, destination_path, source_investigation, source_fix, lesson_text)`.
- New event type: `lesson_encoded`.
- Explicit anti-patterns the command refuses: motherhood statements, lessons from unresolved investigations, lessons duplicating existing invariants, lessons that would push CLAUDE.md past 200 lines, more than 3 lessons per investigation.
- Summary output now includes a "Lessons encoded" section.

**Critique 6 closed: structural breaking-change detection.**

- **New: `dist/contract/breaking-change-check.sh`** — bash wrapper that uses `oasdiff` when available, falls back to a built-in Python detector when not. Outputs structured JSON describing whether changes are additive or breaking with line-by-line details.
- **New: `dist/contract/breaking-change-fallback.py`** — built-in Python detector that catches the most common breaking changes: removed endpoints, removed fields, type changes, new required fields, removed enum values, removed response statuses, required-parameter additions. Verified against five OpenAPI diff scenarios.
- **`/contract` command updated** to invoke the structural check on re-compile, replacing the previous manual-classification prose with a concrete tool invocation. The classification still drives the same decision (additive → proceed silently; breaking → require user confirmation), but now produced by tooling rather than judgement.
- New ledger event type: `breaking_change_detected`, logged on every re-compile (both breaking and clean outcomes). Projects to a new `breaking_changes` table for time-series queries.
- **install.sh** detects whether `oasdiff` is on PATH at install time and surfaces the recommendation to install it for full coverage. The fallback works without `oasdiff`; it's a graceful degradation, not a hard dependency.
- Summary output now includes a "Breaking-change checks" section showing the breaking/clean ratio per tool.

### Why now
The grilling review identified these two critiques together because they share a structural property: **both close loops that specship previously left open.**
- Critique 5: lessons learned from incidents previously stayed in retrospective notes and decayed. `/encode-lesson` makes them durable.
- Critique 6: the hash mechanism detected *that* contracts changed but not *what kind*. The structural diff classifies the change semantically.

Together they raise specship's compliance posture: an MAS AIRG examiner asking "show me how you learn from incidents" and "show me how you detect contract changes that affect consumers" now has concrete artefacts to inspect (the `lessons` table, the `breaking_changes` table) rather than relying on team assertions.

### Migration from v0.7.x
- Re-run `./scripts/install.sh /path/to/your/repo` to install the new command and contract helpers.
- Install script will detect whether `oasdiff` is on PATH and warn if it isn't. The fallback works without it.
- Existing specs, fixes, investigations, and ledger data are unaffected. The ledger schema gains two new tables; running `rebuild-index` migrates cleanly.

### Added — v0.7.0 (observability + orchestration)

**Critique 1 closed: observability ledger.**

- **New: `.specship/ledger/` directory** with two storage layers:
  - JSONL at `.specship/ledger/events.jsonl` — append-only source of truth, committed to git for audit portability
  - SQLite at `.specship/ledger/index.db` — derived query index, gitignored, rebuildable at any time from the JSONL
- **`specship_ledger.py`** CLI with five subcommands: `log` (append event), `rebuild-index` (regenerate SQLite from JSONL), `query <sql>` (run SQL against the index), `summary [--since DATE]` (human-readable digest), `export-csv <output.csv>` (export to CSV for BI tools / dashboards).
- **`ledger.sh`** bash helper exposing `specship_log`, `specship_session_id`, `specship_summary`, `specship_rebuild_index` functions for scripts and hooks to call without invoking Python directly.
- **`HOW-TO-LOG.md`** central reference for command-specific logging patterns. Each command's prompt has a short ~3-line reference block pointing to this doc (progressive disclosure — keeps individual commands compact).
- **All seven commands** now log to the ledger: session_start at entry, session_end at exit with outcome (completed / blocked / abandoned), and command-specific intermediate events (artifact_created, drift_detected, decision_logged, verification_ran, subagent_spawned, subagent_completed).
- **Pre-commit hook** logs `gate_passed` and `gate_blocked` events when the ledger is installed. Best-effort; never breaks the hook if logging fails.
- **12 known event types** covering the full specship lifecycle. Unknown event types are stored raw in JSONL but skipped from the specialised SQLite tables (forward-compatibility).
- **install.sh** creates `.specship/ledger/` in the target repo, installs the three ledger files, and appends the SQLite index files to .gitignore.

**Critique 2 closed: `/ship` orchestrator.**

- **New: `/ship <spec>` command.** Orchestrates a full-stack spec end-to-end in a single invocation:
  1. Stage 1: runs `/contract` directly (cheap, deterministic)
  2. Stage 2: spawns two Task subagents in parallel — one running `/work --scope backend`, one running `/work --scope frontend` — each in an isolated context window
  3. Stage 3: runs `/check` to verify combined drift state
  4. Stage 4: reports combined outcome to the user
- Subagents inherit `parent_session_id` for ledger correlation, so the JSONL captures the full parent → children → completion tree.
- Discipline preserved: `/ship` does NOT commit code, does NOT promote spec status beyond `contract-locked`, does NOT retry failed subagents, and does NOT spawn more than two subagents (scope explosion mitigates parallelism gain).
- Refuses gracefully when the spec is not full-stack, when "Open questions" are unresolved, or when the Contract surface is empty.

### Why now
The Critique 1 review identified observability as specship's biggest gap relative to leading-org practice (LangSmith, Arize Phoenix, MLflow patterns) and the MAS AIRG inventory requirement. Critique 2 identified `/ship`-style orchestration as the productivity baseline established by Stripe (10K-line migration in 4 days), Wiz (50K-line library in 20 hours), Rakuten (24→5 day cycle). Both gaps are now closed.

### Migration from v0.6.x
- Re-run `./scripts/install.sh /path/to/your/repo` to install the ledger and the `/ship` command.
- The ledger starts logging on the next slash command invocation; previous activity is not retroactively reconstructed.
- The pre-commit hook is backward-compatible: if `.specship/ledger/` doesn't exist, the hook works as before with no logging.
- Existing specs, fixes, and investigations are unaffected.

### Added
- **New command: `/investigate`**. Structured investigation of failures (compile errors, runtime errors, test failures, broken CI, production incidents). Produces an investigation file under `investigations/` capturing observed symptoms, reproduction steps, hypotheses, ruled-out causes, evidence, and the root cause once found. The investigation file feeds into `/fix` via the new `--from-investigation` flag.
- **`/fix --from-investigation <file>` flag.** Pre-populates the fix file's "What was wrong" and "Root cause" sections from a completed investigation. Refuses to run if the investigation status is not `root-cause-identified`.
- **`/work` iteration discipline for compile/test failures.** Explicit guidance: iterate up to ~3 attempts with different hypotheses, then stop and escalate. Never disable tests, skip assertions, or relax invariants to make failures pass.
- **Pre-commit hook accepts `investigations/*.md` linkage** in addition to `specs/` and `fixes/`. A commit that touches `src/` and stages an investigation file passes the Wall.
- **New directory: `investigations/`**. Created by `install.sh`. Verified by the 6-scenario hook test in CI.

### Why this addition
Runtime errors and broken builds are the most common bug shape, and the previous workflow had no first-class place for the *investigation phase*. `/fix` required a known root cause, but most bugs start unknown. Without `/investigate`, the discovery phase lived in Slack threads and got lost. The trigger for adding this command: every real bug fix in practice starts with an investigation that the workflow previously hid.

### Added (previous)
- **New skill: `spec-reverse-engineer`**. Produces specship spec files from existing material: source code (Python, Java, TypeScript, others), OpenAPI/AsyncAPI definitions, BDD `.feature` files, Confluence/Notion-style design docs, or specs from other frameworks (GitHub Spec Kit, BMAD, Kiro, Tessl). Designed for adoption on existing codebases — most users don't start greenfield.
- Three reference files for the new skill: `from-code.md` (per-language extraction rules), `from-docs.md` (source-format migration tables), `examples.md` (three worked migrations: Spring Boot + tests, OpenAPI YAML, Confluence-style design doc).
- New spec status: `draft-reverse-engineered`. Distinct from `draft` to prevent accidentally running `/work` or `/contract` against an unreviewed reverse-engineered spec.
- README section: "Adopting specship on an existing codebase".

### Changed
- `install.sh` now installs both skills (`claude-md-architect` and `spec-reverse-engineer`) under `~/.claude/skills/`, plus the six commands (including the new `/investigate`).
- `sync-local.sh` and `verify-sync.sh` updated for the second skill and the new command.
- CI line-count check loops over both skills.
- Pre-commit hook updated for 6-scenario coverage (spec, fix, investigation, no-linkage, ref-in-code, bypass).

### Changed
- **Renamed project** from `two-commander` to `specship`. The old name was baggage from the source paper (the Two-Commander blog post) that proposed two human roles managing an agent fleet. That framing turned out to be rhetorical — what the workflow actually does is *specship*: every artifact (spec, contract, fix, §ref, commit) carries an attestation of something. The new name reflects the mechanism, not the metaphor.
- Updated all user-facing references (README, install messages, skill docstrings, template names) to use `specship`. Historical attribution to the Two-Commander source paper is preserved in the README's "Why this design, and what it isn't" section.

### Migration from `two-commander`
- Repo URL changes: `git clone https://github.com/<you>/specship.git`
- The `Two-Commander template` is now the `specship template`. The template shape itself is unchanged.
- Slash commands (`/spec`, `/contract`, `/work`, `/check`, `/fix`) are unchanged.
- Existing CLAUDE.md files using the template need no changes — only the name of the format changed, not its structure.

## [0.6.0] — 2026-05-12

### Added
- **Nested CLAUDE.md support** in `claude-md-architect` skill (Mode 4: Hierarchy)
  - Discovers all CLAUDE.md files in a repo, excluding `node_modules/`, `.git/`, `_generated/`
  - Audits root + nested for duplication and conflict
  - Designs new nested files for module boundaries — and refuses when boundaries don't warrant them
  - Splits a bloated root into root + nested
- New reference file: `nested-template.md` (lighter shape, ≤100 line cap)
- New reference file: `hierarchy-examples.md` with three worked examples
- README guidance on token reduction levers, with explicit rejection of caveman compression for command prompts

### Changed
- Root `CLAUDE.md.template` now documents the three token-reduction options (nested files, `@path` imports, plain references) with their tradeoffs
- `claude-md-architect` skill description widened to trigger on nested-CLAUDE.md and monorepo queries

## [0.5.0] — 2026-05-12

### Added
- **Bug-fix workflow** with `/fix` command
  - Four-case classification (code wrong / spec wrong / requirement changed / spec silent)
  - Fix artifacts in `fixes/` directory, separate from `specs/`
  - Spec versioning via supersession (originals preserved, never overwritten)
  - `--hot` mode for emergency fixes (compresses interaction, preserves all gates)
- `docs/bug-fix-workflow.md` with worked examples of all four cases
- Pre-commit hook now accepts `fixes/*.md` linkage in addition to `specs/*.md`

### Changed
- `/work` accepts either spec or fix files as input
- `§ref` traceability comments distinguish `§ref:specs/` vs `§ref:fixes/`

## [0.4.0] — 2026-05-12

### Fixed
- **Critical: hash mechanism bug.** Previous versions hashed the entire spec file, breaking immediately after `/contract` mutated the spec. Now hashes the normalised Contract surface section only.
- 8 other completeness issues in `/contract`: vague generation strategy, hand-waved Pact stubs, no idempotency contract, no breaking-change detection, no language detection, no partial-failure recovery, ambiguous slug filenames, unclear Pact pair naming, missing version bump rules

### Added
- Reference Python implementation `dist/commands/contract_hash.py`
- Test fixtures verifying hash stability across spec mutations
- Atomic write protocol for `_generated/` (staging directory)
- Per-language type-file shape rules (TS / Python / Java / Go / JS)
- CLAUDE.md fields: `Backend language`, `Frontend language`, `Contract pair name`

## [0.3.0] — 2026-05-12

### Added
- `/check` command for drift detection
- Drift checks wired into `/work` pre-flight and post-flight
- Pact provider verification in `/work --scope backend` post-flight
- `Project type` field in `CLAUDE.md` for scope defaulting

## [0.2.0] — 2026-05-12

### Added
- `/contract` command for full-stack work
- `--scope backend|frontend` argument on `/work`
- Contract surface section in spec template

## [0.1.0] — 2026-05-12

Initial release: `/spec`, `/work`, pre-commit hook, `claude-md-architect` skill.

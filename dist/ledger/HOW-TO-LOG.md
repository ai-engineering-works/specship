# HOW-TO-LOG — ledger event patterns per command

Reference for slash commands. Each command's prompt points here. Patterns are silent and best-effort: ledger failures must never break a command.

## Universal pattern

Every command:

1. At entry, generate a session UUID and log `session_start`.
2. Log significant in-flight events (artifact_created, gate_blocked, drift_detected, etc.).
3. At the end, log `session_end` with one of these outcomes:
   - `completed` — the command did what it set out to do
   - `blocked` — a pre-flight check or gate refused the command
   - `abandoned` — the command halted because of missing context or user input

Skeleton (every command starts with this):

```bash
SID=$(python3 -c "import uuid; print(uuid.uuid4())")
LEDGER=.specship/ledger/specship_ledger.py
log() { python3 "$LEDGER" log "$@" --quiet 2>/dev/null || true; }

log session_start session_id="\"$SID\"" command='"<this-command-name>"' \
    args='[<arguments>]'
```

And ends with this (substituting the correct outcome):

```bash
log session_end session_id="\"$SID\"" outcome='"completed"'
```

**Important:**
- Do not surface ledger output to the user
- Do not mention logging in your visible response
- If `.specship/ledger/specship_ledger.py` does not exist, skip silently — the command still runs

## Per-command patterns

### `/spec` command

Events to log:
- `session_start` (universal pattern, command="spec")
- `artifact_created` when the spec file is saved:
  ```bash
  log artifact_created session_id="\"$SID\"" \
      path='"<spec-path>"' kind='"spec"' status='"draft"'
  ```
- `session_end` with outcome

### `/contract` command

Events to log:
- `session_start` (command="contract")
- `gate_blocked` if pre-flight check fails (e.g., placeholders remaining):
  ```bash
  log gate_blocked session_id="\"$SID\"" command='"contract"' \
      artifact='"<spec-path>"' reason='"<short-reason>"'
  ```
- `breaking_change_detected` whenever the structural diff check runs (re-compile path):
  ```bash
  log breaking_change_detected session_id="\"$SID\"" \
      artifact='"<openapi-path>"' \
      tool='"<oasdiff|fallback|none>"' \
      breaking=<true|false> \
      findings_count=<integer>
  ```
  Log this for both breaking and clean outcomes — the event records that the check ran. Over time, the ratio of breaking vs clean indicates how often the team ships contract-breaking changes.
- `artifact_created` once per generated file (OpenAPI, types, Pact stubs):
  ```bash
  log artifact_created session_id="\"$SID\"" \
      path='"<generated-path>"' kind='"contract-artifact"'
  ```
- `artifact_updated` for the spec (status changes to contract-locked):
  ```bash
  log artifact_updated session_id="\"$SID\"" \
      path='"<spec-path>"' status='"contract-locked"'
  ```
- `session_end` with outcome (completed or blocked)

### `/work` command

Events to log:
- `session_start` with scope:
  ```bash
  log session_start session_id="\"$SID\"" command='"work"' \
      artifact_path='"<spec-or-fix-path>"' \
      scope='"<backend|frontend|backend-only|frontend-only>"' \
      parent_session_id='"<parent-SID-if-spawned-by-ship-else-null>"'
  ```
- `drift_detected` for each fast-check failure or warning (from `/check` invocation):
  ```bash
  log drift_detected session_id="\"$SID\"" \
      artifact='"<spec-path>"' check='"<which-check>"' \
      severity='"<red|yellow>"' detail='"<short-detail>"'
  ```
- `gate_blocked` if pre-flight refuses (contract stale, criteria untraced, etc.)
- `decision_logged` for non-obvious choices during execution:
  ```bash
  log decision_logged session_id="\"$SID\"" \
      artifact='"<spec-path>"' \
      summary='"<one-line-decision>"' \
      rationale='"<short-rationale>"' \
      accepted=true
  ```
- `verification_ran` for each verification command executed:
  ```bash
  log verification_ran session_id="\"$SID\"" \
      command_run='"<e.g. pytest tests/>"' \
      passed=true
  ```
- `coverage_measured` once, in post-flight, if CLAUDE.md declares a Coverage policy:
  ```bash
  log coverage_measured session_id="\"$SID\"" \
      artifact='"<spec-or-fix-path>"' \
      tool='"<from coverage-check output>"' \
      metric='"line"' \
      line_pct=<float> \
      branch_pct=<float or null> \
      delta_pct=<float> \
      project_pct=<float> \
      files_measured=<int> \
      threshold_delta=<float> \
      threshold_project=<float> \
      passed=<true|false> \
      excluded_paths='["_generated/**", "tests/**", ...]'
  ```
  Log this REGARDLESS of pass/fail outcome — the event records that a measurement was taken, which is itself the audit-relevant fact. If passed=false, /work must NOT advance status to ready-for-review.

- `artifact_updated` when status advances (in-progress, ready-for-review)
- `session_end` with outcome

### `/check` command

Events to log:
- `session_start` (command="check")
- `drift_detected` for each finding:
  ```bash
  log drift_detected session_id="\"$SID\"" \
      artifact='"<path>"' check='"<check1|check2|check3|check4>"' \
      severity='"<red|yellow|green>"' detail='"<short>"'
  ```
- `session_end` with outcome="completed" (always, since /check is read-only)

### `/fix` command

Events to log:
- `session_start` (command="fix")
- `artifact_created` for the fix file:
  ```bash
  log artifact_created session_id="\"$SID\"" \
      path='"<fix-path>"' kind='"fix"' status='"draft"' \
      against_spec='"<spec-path>"' case='<1|2|4>'
  ```
- `artifact_created` for the superseding spec (Case 2 or 4)
- `artifact_updated` for the original spec (Superseded by metadata)
- `session_end` with outcome

### `/investigate` command

Events to log:
- `session_start` (command="investigate")
- `artifact_created` for the investigation file:
  ```bash
  log artifact_created session_id="\"$SID\"" \
      path='"<investigation-path>"' kind='"investigation"' \
      status='"open"' severity='"<P1|P2|P3|unknown>"'
  ```
- `artifact_updated` when status changes (to root-cause-identified, stalled, etc.)
- `session_end` with outcome

### `/ship` command (orchestrator)

Events to log:
- `session_start` (command="ship", artifact_path=spec)
- `subagent_spawned` for each plan-phase subagent dispatched (phase='plan'):
  ```bash
  log subagent_spawned session_id="\"$SID\"" \
      child_session_id='"<expected-child-SID>"' \
      command='"work"' scope='"<backend|frontend>"' phase='"plan"'
  ```
- (Inside each plan subagent, `/work --plan-only` emits a `plan_drafted` event — the orchestrator does not log this itself.)
- `subagent_completed` for each plan-phase subagent (outcome='plan-drafted')
- `plan_approved` for each plan after the human's verdict:
  ```bash
  log plan_approved session_id="\"$SID\"" \
      plan_id='"<plan-uuid>"' \
      scope='"<backend|frontend>"' \
      verdict='"<approved|rejected|changes-requested>"' \
      reviewer_note='"<short>"'
  ```
- `subagent_spawned` for each execute-phase subagent (phase='execute', plan_id=<approved plan>):
  ```bash
  log subagent_spawned session_id="\"$SID\"" \
      child_session_id='"<expected-child-SID>"' \
      command='"work"' scope='"<backend|frontend>"' phase='"execute"' \
      plan_id='"<plan-uuid>"'
  ```
- `subagent_completed` for each execute-phase subagent
- `session_end` with overall outcome

### `/work --plan-only` (mode B)

`/work` in plan-only mode emits exactly one event after pre-flight and planning:
```bash
log plan_drafted session_id="\"$SID\"" \
    plan_id='"<uuid>"' \
    parent_session_id='"<parent-from-/ship>"' \
    scope='"<backend|frontend|single>"' \
    source_artifact='"<spec-or-fix-path>"' \
    plan_path='".specship/plans/<plan-id>.md"' \
    files_to_modify='[...]' \
    estimated_decisions=<int>
```
Followed by `session_end` with `outcome='plan-only'`. No coverage, no verification, no commits — the subagent stopped before execution.

### `/work --from-plan` (mode A)

`/work` in from-plan mode emits `plan_executing` once at the start of execution:
```bash
log plan_executing session_id="\"$SID\"" plan_id='"<uuid>"'
```
Then proceeds with the usual /work events (drift, decisions, coverage, etc.). No additional plan event is needed at the end — the standard `session_end` covers it.

### `/encode-lesson` command

Events to log:
- `session_start` (command="encode-lesson", artifact_path=investigation)
- `lesson_encoded` once per lesson actually inserted (after user approval):
  ```bash
  log lesson_encoded session_id="\"$SID\"" \
      artifact='"<investigation-path>"' \
      lesson_id='"<short-stable-hash>"' \
      destination_path='"<CLAUDE.md | path/to/nested/CLAUDE.md | path/to/SKILL.md | path/to/command.md>"' \
      source_investigation='"<investigation-path>"' \
      source_fix='"<fix-path or null>"' \
      lesson_text='"<the actual invariant text>"'
  ```
  The `lesson_id` should be a short stable hash of the lesson text (e.g., first 7 chars of SHA-256). It MUST be embedded in the destination artifact's linkback comment so future audits can correlate ledger entries with where the lesson actually lives.

- `artifact_updated` for the investigation file (its "Lesson encoded" section was appended):
  ```bash
  log artifact_updated session_id="\"$SID\"" \
      path='"<investigation-path>"' lessons_appended=<count>
  ```
- `session_end` with outcome="completed" if any lesson was encoded, "abandoned" if the user rejected all candidates.

### `/capture-lessons` command

Log `session_start`, then one `lesson_candidate` per captured lesson (≤3), then `session_end`.

```bash
python3 .specship/ledger/specship_ledger.py log lesson_candidate \
    candidate_id="\"$CID\"" lesson_text="\"...\"" lesson_type="\"tooling\"" \
    evidence_quote="\"...\"" source_command="\"/work\"" source_artifact="\"\"" \
    confidence="\"high\"" session_id="\"$SID\"" --quiet
```

### `/review-lessons` command

Log `session_start`, one `lesson_dismissed` per dismissed candidate, `session_end`.
Promotions are logged by `/encode-lesson` (as `lesson_promoted`), not here.

```bash
python3 .specship/ledger/specship_ledger.py log lesson_dismissed \
    candidate_id="\"$CID\"" reason="\"noise\"" session_id="\"$SID\"" --quiet
```

### Curator (`curate.py`)

Emits `lesson_decayed` per expired candidate and one `lessons_curated` digest per run. The
curator logs these itself; no command authoring is needed. Query the latest digest with:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT ts, raw_json FROM events WHERE event_type='lessons_curated' ORDER BY ts DESC LIMIT 1
"
```

### `/review-decisions` command

Events to log:
- `session_start` (command="review-decisions", optionally artifact_path)
- `decision_reviewed` once per verdict the user assigns:
  ```bash
  log decision_reviewed session_id="\"$SID\"" \
      decision_id='"<the decision_id from the original decision_logged event>"' \
      verdict='"<accepted | rejected | needs-redo>"' \
      reviewer_note='"<free-text or empty string>"'
  ```
  The `decision_id` MUST match an existing `decision_logged` event's `event_id`. The indexer projects this event into the `decisions` table via `INSERT…ON CONFLICT DO UPDATE` on the `decision_id` column, layering the verdict onto the original row.

- `session_end` with outcome:
  - `completed` — at least one verdict was recorded
  - `abandoned` — user reviewed but assigned no verdicts (no-op session)

This command does NOT log `artifact_updated` events — it doesn't modify any markdown artifacts. The state change is entirely in the ledger.

## Hook events

The pre-commit hook can also log, when committing in a repo with the ledger installed:

```bash
# Inside .git/hooks/pre-commit, after the block/pass decision is made:
LEDGER="$(git rev-parse --show-toplevel)/.specship/ledger/specship_ledger.py"
if [[ -f "$LEDGER" ]]; then
    if [[ <commit was bypassed with --no-verify> ]]; then
        python3 "$LEDGER" log gate_bypassed --quiet 2>/dev/null || true
    elif [[ <commit was blocked> ]]; then
        python3 "$LEDGER" log gate_blocked reason='"no-linkage"' --quiet 2>/dev/null || true
    fi
fi
```

(The hook's bypass detection is approximate — `--no-verify` causes the hook to not run at all, so `gate_bypassed` is logged separately by a `post-commit` hook that detects bypassed commits via the absence of the previous `gate_passed` event. This is best-effort.)

## Querying the ledger

Once events accumulate, query the SQLite index for reports:

```bash
# Sessions in the last week, by command and outcome
python3 .specship/ledger/specship_ledger.py query "
    SELECT command, outcome, COUNT(*) AS n
    FROM sessions
    WHERE started_at >= date('now', '-7 days')
    GROUP BY command, outcome
    ORDER BY n DESC
"

# Drift findings per artifact
python3 .specship/ledger/specship_ledger.py query "
    SELECT artifact, check_, severity, COUNT(*) AS n
    FROM events
    WHERE event_type = 'drift_detected'
    GROUP BY artifact, check_, severity
"

# Human-readable summary
python3 .specship/ledger/specship_ledger.py summary

# Summary for the last 30 days only
python3 .specship/ledger/specship_ledger.py summary --since 2026-04-12

# Export sessions table to CSV for spreadsheets / BI tools
python3 .specship/ledger/specship_ledger.py export-csv sessions.csv --table sessions
```

## What NOT to log

- Personal data (names, emails) — only artifact paths, command names, outcomes
- File contents — only paths
- Verbose stack traces in event fields — keep `detail` under 500 chars
- Verbose Claude reasoning — that lives in the artifact files themselves, not the ledger

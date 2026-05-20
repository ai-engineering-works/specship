---
description: Author QA artifacts (regression, scenario, and property artifacts) for a spec, fix, or investigation. Conducts a structured interview, drafts artifacts under regressions/, scenarios/, or properties/, and generates runnable test files under tests/regression/, tests/scenario/, tests/property/, and tests/e2e/ (for frontend-touching scenarios and regressions).
argument-hint: <intent-path> [--from-fix fixes/<file>.md] [--regression-only] [--scenarios-only] [--properties-only] [--no-e2e]
recommended-model: opus  # sonnet | opus — see CLAUDE.md for guidance
---

# /qa — Author QA Artifacts for an Intent

You are conducting a QA artifact authoring workflow. QA artifacts are correctness specifications that outlive any one implementation — they live alongside specs/fixes/investigations and carry the intent's verifiable assertions.

**v0.13.3 scope**: regression, scenario, and property artifacts are all supported. Frontend-touching scenarios and regressions can additionally carry a `ui_action` block that generates a Playwright e2e test with video recording. Stateful property tests are out of scope.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **`/qa` command** section. Logging is best-effort and silent. Log `session_start`, `qa_artifact_created` for each artifact, `qa_artifact_updated` when approved, `qa_tests_generated` for generated test files, and `session_end`.

## Why QA artifacts are a separate workflow

- **Unit tests** (written during `/work`) verify "did Claude exercise the code I wrote."
- **QA artifacts** verify "does the system honor the business intent."

These are different correctness claims. Unit tests pass when the implementation is internally consistent; QA artifacts pass when the implementation matches the user-facing contract. Both are required for confidence. specship enforces both via the `/ship` Stage 0 gate (QA artifacts exist) and the coverage gate (unit tests exist).

## QA author role

`/qa` is intended to be run by a **separate QA author** from the spec author. The spec author has the implementation context; the QA author has independent perspective on edge cases, regression scenarios, and what could go wrong.

In small teams where one person plays both roles, that's fine — just run `/qa` with a fresh mindset, deliberately stepping back from the spec's framing.

## Inputs

The user has invoked this command with: $ARGUMENTS

Parse:
- First positional argument: path to the intent — must be a spec, fix, or investigation file (`specs/...`, `fixes/...`, or `investigations/...`).
- Optional `--from-fix fixes/<file>.md`: shortcut for the common case where `/qa` is being invoked at the end of `/fix` to create a regression artifact for the just-fixed bug. Auto-populates from the fix's repro section.
- Optional `--regression-only`: skip property and scenario sections entirely (currently the default in Phase 1 — provided for forward-compatibility).

If the path doesn't exist, stop with a clear error. If the path is to a spec with status `draft` or `in-progress`, refuse: QA artifacts are authored against signed-off specs.

## Pre-flight

1. **Read `CLAUDE.md`** for invariants and conventions. Look for language/test-framework hints — typical patterns include "Backend: Python/pytest/hypothesis" or "Frontend: TypeScript/Jest/fast-check". Record what you find.
2. **Read the intent file.** Note: title, status, contract surface (for specs), affected fields/endpoints, classification (for fixes).
3. **Check existing QA artifacts for this intent.** Search `regressions/` for files whose frontmatter has `parent_fix:` or `parent_spec:` matching the intent path. List them.
4. **Identify the test framework.** If CLAUDE.md states it explicitly, use that. Otherwise, ask the user via `ask_user_input_v0`:

```
Which test framework does this codebase use for backend tests?

  [Python / pytest]
  [TypeScript / Jest]
  [Other — I'll skip test generation]
```

Record the framework decision — it determines which generator runs.

## Phase 3: Property artifacts

Properties capture invariants — assertions that hold across ALL valid inputs, not just specific scenarios. Where scenarios verify "the happy path works," properties verify "the system never violates this rule."

### When to invoke the properties flow

The properties interview runs in two cases:

- **Direct invocation on a spec**: `/qa <spec-path>` — runs after the scenarios interview (or instead, if the user is focused on invariants).
- **Explicitly requested**: `/qa <spec-path> --properties-only` to skip both regressions and scenarios.

When invoked with `--regression-only` or `--scenarios-only`, skip this entire section.

### Properties interview

The interview has three parts.

**Part 1: Read the spec's Invariants section.** This section is mandatory in `/spec` (added in v0.13.0). It enumerates invariants the system must satisfy. Extract each one.

If the spec has NO Invariants section, or the section is empty: politely refuse this part. Tell the user: "Phase 3 properties draw from the spec's Invariants section. This spec has none. Either edit the spec to add invariants, or skip this part." Do NOT invent invariants — they need human-authored intent.

**Part 2: Propose candidate property artifacts.** For each invariant from the spec:

1. Draft a property artifact:
   - `property_id`: short hash
   - `parent_spec`: the spec path
   - `language` / `generator`: from CLAUDE.md detection (python/hypothesis or typescript/fast-check)
   - `action`: structured block describing the call being tested (matches the spec's Contract Surface)
   - `generators`: declarative DSL forms, one per input field. Derive from Contract Surface field types. See the DSL forms below.
   - `invariant.prose`: the invariant in plain language
   - `invariant.expression`: an executable Python expression that evaluates the invariant. THIS IS THE HARDEST PART — translate the prose to code carefully.
   - `max_examples`: default 100, bump to 200-500 for security-sensitive invariants

2. Present each draft via `ask_user_input_v0`. The QA author should review every property carefully:

```
Property: <invariant>
Draft expression: <code>
Generators: <DSL forms>

Approve, edit, or reject?
  [Approve]
  [Edit expression]      # most common
  [Edit generators]      # second most common
  [Edit both]
  [Reject — invariant not testable as a stateless property]
```

3. On approval, write the artifact to `properties/<spec-slug>/<property-slug>.md` and log `qa_artifact_created` with kind=property, parent_intent=spec-path.

### The generator DSL (cheat sheet for drafting)

| DSL form | Use for |
|----------|---------|
| `int(min: M, max: N)` | bounded integers |
| `float(min: M, max: N)` | bounded floats |
| `string(min_len: M, max_len: N)` | arbitrary text fields |
| `enum[a, b, c]` | finite value sets (tier, status, role) |
| `bool` | boolean flags |
| `date(min: D, max: D)` | dates |
| `list(of: <sub>, min_len: M, max_len: N)` | arrays |
| `optional(<sub>)` | nullable fields |

Stay within the supported forms. If a field can't be expressed cleanly (e.g., requires regex constraints), use the closest broader form and add an `input_filter` to narrow.

### Drafting the invariant expression

The expression is in Python syntax. Available variables:
- Each key from `generators:` (the generated input)
- `actual` — what the action returned
- `actual_status`, `actual_body` — when action.type == http
- `request_payload` — when there are multiple generator fields

Translation patterns by invariant shape:

| Prose invariant | Likely expression |
|----------------|-------------------|
| "X is always returned" | `actual['X'] is not None` |
| "X is always one of A, B, C" | `actual['X'] in ('A', 'B', 'C')` |
| "successful response echoes X" | `actual_status != 201 or actual_body['X'] == request_payload['X']` |
| "X is unique across responses" | NOT stateless — refuse, suggest a regression instead |
| "X is always >= 0" | `actual['X'] >= 0` |
| "errors return 4xx" | `actual_status < 400 or actual_status < 500` |

If the user's invariant doesn't map cleanly to a stateless expression, push back honestly. Multi-step invariants belong in scenarios or future stateful properties; cross-request invariants (uniqueness, ordering) don't fit Phase 3.

### Part 3: Generate runnable tests

For each approved property:

1. Determine language and generator from frontmatter
2. Run the appropriate generator:
   - `.specship/qa-generators/property-pytest.py` for python/hypothesis
   - `.specship/qa-generators/property-jest.py` for typescript/fast-check
3. The generator writes a test file to `tests/property/`
4. The generated file carries AUTO-GENERATED header, content hash, and §qa back-link
5. Log `qa_tests_generated`
6. Tell the user: "Generated `tests/property/test_<...>.py`. The DSL was translated to hypothesis/fast-check strategies automatically. The call site is stubbed — wire it up and remove the `pytest.skip()` (or `test.skip()`)."

If the generator fails (DSL parse error, missing fields, unsupported form): surface the error clearly with the offending field name. Don't write a half-baked test.

### v0.13.2 explicitly excludes

- Stateful property tests (multi-step state machines via RuleBasedStateMachine or fast-check model-based)
- Cross-property invariants (e.g., "after running properties P1, P2, P3 in sequence, this holds")
- Generators beyond the nine DSL forms above
- Custom user-supplied generator code

If a user requests any of these, explain the limit honestly and suggest either restating the invariant as a stateless property or capturing it as a scenario.

## Phase 1: Regression artifacts

This is the core of the Phase 1 workflow.

### If `--from-fix` was passed

You're being invoked at the end of `/fix`. The fix is fresh; the human is still in context. Auto-draft a regression artifact:

1. Read the fix file. Extract:
   - The bug description (from the "What was wrong" section)
   - The repro steps or trigger input (from "Reproduction" or equivalent section)
   - The fix description (from "What changed")
2. Draft ONE regression artifact:
   - `regression_id`: short hash of the fix path + timestamp (use bash `uuidgen | cut -c1-8` or equivalent)
   - File name: `regressions/<today>-<slug-from-fix>-<reg_id_suffix>.md`
   - Frontmatter populated: `parent_fix`, `language`, `generator`, `authored_by` (ask the user), `authored_at` (today's ISO date), `status: draft`
   - Body sections:
     - **Why this regression exists** — synthesize from the fix narrative
     - **Input** — extract from repro steps
     - **Expected output** — what the system should produce AFTER the fix
3. Present the draft to the user via `ask_user_input_v0`:

```
Here's the regression artifact I've drafted from <fix-path>. Does the
Input and Expected output capture the bug correctly?

  [Approve as drafted]
  [Edit before approving]
  [Reject — this fix doesn't need a regression artifact]
```

If the user wants to edit, walk them through each section in turn. Be specific: "The Input section currently shows X. What should it be?" — don't ask vague "any changes?" questions.

If approved or edited-then-approved:
- Write the file to `regressions/...`
- Log `qa_artifact_created` with kind=regression, parent_intent=fix-path
- Log `qa_artifact_updated` with status=approved (these can be the same session)
- Continue to test generation (next section)

If rejected: log a `decision_logged` event with the reason. Don't create the file. Tell the user that `/ship` will refuse to proceed without QA artifacts unless a waiver is granted.

### If invoked directly on a spec/investigation (no --from-fix)

The interview is more involved. Walk through:

1. **Identify candidate regressions.** Search `fixes/` for files whose frontmatter `against:` (or whose first paragraph) mentions the spec. List them with brief descriptions. Ask the user which ones should have regression artifacts.

2. **For each chosen fix, auto-draft a regression** using the procedure above.

3. **Ask if there are bugs the team knows about that don't yet have fix artifacts** — sometimes a regression is captured before the fix is formal. If yes, draft a regression with `parent_fix: <to-be-created>` and warn the user that the regression's verification will fail until the fix exists.

### Test generation

For each approved regression artifact:

1. Read the artifact's `language` and `generator` frontmatter fields.
2. Call the integration test generator. The generators live at:
   - `.specship/qa-generators/regression-pytest.py` (for `language: python`, `generator: pytest`)
   - `.specship/qa-generators/regression-jest.py` (for `language: typescript`, `generator: jest`)
3. The generator takes the artifact path as input and writes a test file to `tests/regression/`.
4. **If the regression has a `ui_action:` block** (the original bug had a UI manifestation), ALSO run `.specship/qa-generators/regression-playwright.py` to generate an e2e regression test under `tests/e2e/`. The generated test guards against the same bug at the UI level and records video on every run.

   For regressions specifically: before drafting the `ui_action` block, ask the user "Did this bug have a UI manifestation, or is it backend-only?" If backend-only, skip the ui_action block entirely.

5. The generated test files MUST carry an auto-generated header:

```python
# AUTO-GENERATED by specship /qa. Do not edit by hand.
# §qa:<artifact-path>
# To change this test, edit the source artifact and re-run /qa.
# Content hash: <hash-of-the-artifact-content>
```

6. Log `qa_tests_generated` per generated file (so an integration test + e2e test produces two events).

7. Show the user the generated test paths: "Generated `tests/regression/test_<...>.py` (unit) and, if applicable, `tests/e2e/<...>.spec.ts` (Playwright). Run once to confirm they work."

If a generator fails (e.g., the artifact's Input section can't be unambiguously translated to a fixture), surface the error to the user. Don't write a half-baked test. Either ask the user to clarify the artifact, or skip generation and tell them the artifact is approved but needs manual test code.

## Phase 2: Scenario artifacts

Scenarios capture given/when/then sequences that verify paths through the system. Where regressions guard against past bugs, scenarios verify that paths-the-spec-promised actually work.

### When to invoke the scenarios flow

The scenarios interview runs in two cases:

- **Direct invocation on a spec**: `/qa <spec-path>` without `--from-fix`. The natural QA-author flow for a new spec.
- **Explicitly requested**: `/qa <spec-path> --scenarios-only` to skip the regressions question entirely.

When invoked with `--regression-only`, skip this entire section.

When invoked with `--from-fix`, scenarios are typically not the focus (regression is). But mention at the end: "Phase 2 also supports scenario artifacts. If this fix exposed a path that should be more broadly tested, you can run `/qa <spec-path> --scenarios-only` against the parent spec."

### Scenarios interview

The interview proceeds in four parts.

**Part 1: Read the spec's Contract Surface and Acceptance criteria.** Extract:
- Endpoints, function calls, or event topics described
- Happy paths called out in Acceptance criteria
- Error cases mentioned (validation failures, auth failures, etc.)
- Idempotency, retry, or concurrency notes

**Part 2: Propose candidate scenarios.** From what you extracted, propose 5-12 candidate scenarios. Each should cover ONE path. Examples:
- Happy path: valid request → expected success
- Validation failure: invalid input → 400 with specific error code
- Auth failure: missing token → 401
- Resource not found: invalid ID → 404
- Idempotency: repeat request → same response, no duplicate side effect
- Concurrency: simultaneous requests → expected consistency outcome
- Edge case: empty/maximum/boundary inputs → expected behavior

Present them as a list to the user via `ask_user_input_v0`:

```
I've drafted these candidate scenarios from the spec. Which should we author?
  [multi-select]
  - Happy path for valid gold tier subscribe
  - Validation: invalid tier rejected with 400
  - Auth: missing token returns 401
  - Idempotency: duplicate subscribe returns same subscription
  - Edge: empty advisor_id returns 400
  ...
  - None of these / I want to add my own
```

**Part 3: Draft each chosen scenario.** For each scenario:

1. Auto-draft the artifact with structured frontmatter:
   - `scenario_id`: short hash from spec path + scenario slug
   - `parent_spec`: the spec path
   - `language` and `generator`: from CLAUDE.md detection (Phase 1 already established this)
   - `authored_by`: ask if unknown
   - `authored_at` and `last_synced_to_spec_at`: today's ISO date
   - `action`: structured block describing the call (type, method, endpoint, OR module/function, OR topic, OR command)
   - `setup`: list of preconditions, derived from spec context
   - `expectations`: list of observable outcomes, derived from the relevant Acceptance criterion

2. Draft the markdown body (Why, Given, When, Then) in parallel narrative form.

3. Save the artifact to `scenarios/<spec-date-slug>/<scenario-slug>.md`. The spec-date-slug matches the spec's filename (minus `.md`). The scenario-slug is a short human-readable id.

4. Log `qa_artifact_created` with kind=scenario, parent_intent=spec-path.

5. Present the draft to the user briefly:

```
Drafted scenarios/<spec-slug>/<scenario>.md. Approve, edit, or reject?
  [Approve]
  [Edit before approving]
  [Reject — this scenario isn't needed]
```

If approved: log `qa_artifact_updated` with status=approved. Proceed to test generation (next part).

If edit: walk through each frontmatter field that needs revision, then re-show the diff. Don't ask vague questions — be specific about which field is changing and what to.

If reject: log a `decision_logged` with the reason. Don't write the file.

**Part 3.5: Optional UI flow for e2e Playwright generation.**

After approving the scenario draft but BEFORE running test generation, check whether the scenario is user-facing. Signals:

1. **The spec's scope** (from its frontmatter): `frontend-only` or `full-stack` → user-facing.
2. **CLAUDE.md mentions a frontend stack** (React, Vue, Angular, Next.js, etc.) → likely user-facing somewhere.
3. **Was `--no-e2e` passed?** → skip this part regardless.

If user-facing AND not `--no-e2e`, ask via `ask_user_input_v0`:

```
Is this scenario user-facing? If yes, I'll draft a `ui_action` block to generate
a Playwright e2e test with video recording.

  [Yes — add UI flow]
  [No — skip; this scenario is backend/API only]
```

If yes, conduct a mini-interview to populate the `ui_action` block:

1. **start_url** — the URL the user starts at. Often derivable from the spec's UI section or the endpoint in the existing action block. If unclear, ask.
2. **steps** — the user actions in order. For each, ask in natural language ("what does the user click next?") and translate to the DSL form (`click: button:Subscribe`, `fill: label:Email, value: ...`, etc.).
3. **expect** — what the user sees after the flow completes. Use `url_matches`, `visible`, `not_visible`, `text_contains` as appropriate.
4. Draft the YAML block, show it to the user, confirm.

Selector vocabulary (favor semantic locators):

| DSL prefix | Playwright call | When to use |
|------------|-----------------|-------------|
| `text:<t>` | `getByText('<t>')` | Visible text content |
| `button:<n>` | `getByRole('button', {name})` | Buttons by accessible name |
| `link:<n>` | `getByRole('link', {name})` | Links by accessible name |
| `label:<t>` | `getByLabel('<t>')` | Form fields by their `<label>` |
| `testid:<id>` | `getByTestId('<id>')` | Test IDs (if the team uses them) |
| `placeholder:<t>` | `getByPlaceholder('<t>')` | Inputs by placeholder |
| `heading:<t>` | `getByRole('heading', {name})` | Headings |
| no prefix | `locator('<raw-css>')` | Last resort — raw CSS |

Always prefer the semantic locators. Tests using `getByLabel('Email')` survive UI refactors that change CSS class names; tests using `.input-email` break on every refactor.

**Part 4: Generate runnable tests.** For each approved scenario:

1. Determine language and generator from frontmatter.
2. Run the appropriate integration generator:
   - `.specship/qa-generators/scenario-pytest.py` for `language: python`, `generator: pytest`
   - `.specship/qa-generators/scenario-jest.py` for `language: typescript`, `generator: jest`
3. The integration generator writes a test file to `tests/scenario/`.
4. **If the scenario has a `ui_action:` block** (set in Part 3.5), ALSO run `.specship/qa-generators/scenario-playwright.py` to generate a Playwright e2e test under `tests/e2e/`. The generated test includes `test.use({ video: 'on' })` so every run records video.
5. Each generated file carries the auto-generated header and §qa back-link.
6. Log `qa_tests_generated` per file — separate events for the integration and Playwright tests (so they show as two outputs in the dashboard).
7. Tell the user: "Generated `tests/scenario/test_<...>.py` (integration) and, if applicable, `tests/e2e/<...>.spec.ts` (Playwright). The setup and call site are stubbed — wire them up to your test infrastructure, remove the `pytest.skip()` / `test.skip()` lines, and run."

If the generator fails on a specific scenario, surface the error and skip that one. Don't fail the whole batch.

### Phase 2 explicitly excludes

If the user asks you to author a property artifact: explain that property workflows are coming in Phase 3 (v0.13.2). Do NOT attempt to draft them — the generator DSL for properties hasn't shipped, and half-built property tests are misleading.

## Edge cases

- **The intent file is a spec with no fix history.** Regression artifacts are nominally fix-derived. If the user wants a regression against a spec that has never had a bug, ask them why. Sometimes this is legitimate ("we want to lock in this current behavior as a regression test against future drift") — accept it, set `parent_spec` instead of `parent_fix`, note the rationale in "Why this regression exists."

- **The user wants to retire an existing regression.** Don't do this through `/qa`. Tell them: edit the artifact directly, change `status:` to `retired`, add `retired_at` and `retired_reason`. The retirement is an audit-relevant act and should be a deliberate edit, not a command-driven flow.

- **The user wants to update a previously-approved regression's Input or Expected output.** Refuse. Regression artifacts are append-only. The correct procedure (per HOW-TO-AUTHOR-QA.md): retire the existing one, create a new one with a back-link.

- **The user wants to update a scenario's `expectations` because the test is failing.** Push back. Failing scenarios mean either (a) the code regressed (fix the code) or (b) the spec genuinely changed (sync the scenario to the new spec and bump `last_synced_to_spec_at`). Updating expectations to match broken behavior is the failure mode this whole workflow exists to prevent.

- **The spec has many possible scenarios (20+) and the user wants to author them all.** Push back. Authoring 20+ scenarios at once produces a wall of similar artifacts that don't get reviewed thoughtfully. Suggest authoring the 5-8 most important scenarios first, ship, and add more scenarios as gaps are discovered in real use.

- **A scenario's action is something the generator doesn't recognize (e.g., a websocket handshake).** Generate the stub anyway, but mark the action_type as `unknown`. The generated test will carry comments noting that the call site is not auto-generated; the human wires it up directly.

- **The auto-drafted regression doesn't match the bug well.** This is the most common case. Don't paper over it. Tell the user: "The fix's repro section doesn't have a clean input/output pair. I need you to provide one." Then walk them through it section by section.

## What to output

At the end of the command:

```
QA artifacts created for <intent-path>:
  - regressions/<file-1>.md  →  tests/regression/test_<file-1>.py
  - regressions/<file-2>.md  →  tests/regression/test_<file-2>.py

Next:
  1. Run `pytest tests/regression/test_<file-1>.py` to verify the generated test passes
  2. `/ship` can now proceed on <intent-path>
```

If no artifacts were created (user rejected all, or there was nothing to author):

```
No QA artifacts created for <intent-path>.

If you intend to /ship this intent without QA artifacts, you'll need a waiver:

  python3 .specship/ledger/specship_ledger.py log qa_waiver_granted \
      target_intent='"<intent-path>"' \
      waiver_granted_by='"<your-tech-lead>"' \
      reason='"<why-the-waiver-is-justified>"' \
      target_resolution_date='"<YYYY-MM-DD-by-when-QA-will-be-added>"'

Waivers are spec-scoped, audit-logged, and surface on the dashboard until
the QA artifacts are added.
```

## Cross-cutting reminders

- Logging is best-effort. If the ledger isn't reachable, continue without it.
- Don't write test files outside `tests/regression/`, `tests/scenario/`, or `tests/property/`. These are the only acceptable destinations.
- Don't modify the source intent file (the spec/fix/investigation). `/qa` reads them, never writes to them.
- If the user is unsure whether a regression is needed, lean toward yes. The cost of an extra regression test is low; the cost of a missing one is high.

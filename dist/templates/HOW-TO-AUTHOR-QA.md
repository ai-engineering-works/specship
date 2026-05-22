# How to author QA artifacts

QA artifacts capture **correctness specifications** that outlive any one
implementation. Where unit tests live with the code and verify "did Claude
exercise this function," QA artifacts live alongside specs and verify "does
the system honor the intent."

specship v0.13.0 Phase 1 supports **regression artifacts**. Property and
scenario artifacts are coming in later phases.

## Regression artifacts

A regression artifact is a **frozen input/output pair** captured at the
moment a bug is fixed. Its job: ensure that specific bug never returns.

### Key properties

- **Append-only**. Once approved, the input and expected output are frozen.
  Never edited in response to a future test failure. If the test fails, fix
  the code or retire the artifact — but the artifact's contents don't change.
- **One regression per file**. Multi-bug regressions are split into multiple
  files. This makes retirement clean: if one of the bugs becomes irrelevant,
  retire its file alone.
- **Trace back to a fix**. The `parent_fix:` frontmatter field is mandatory.
  This is the auditability claim: every regression points to the original
  bug it guards against, and that fix points to the investigation (if any)
  that found the bug.

### Authoring flow

In specship, regression artifacts are authored via the `/qa` command, not by
hand. The flow is:

1. Engineer completes `/fix` for a bug.
2. `/fix`'s final step prompts: "Create a regression artifact for this fix?"
3. If yes, `/qa` is invoked (or runs inline) and:
   - Auto-drafts a regression artifact from the fix's repro section
   - Conducts a short interview with the QA author to confirm the input,
     expected output, and side-effect assertions
   - Approves the artifact (logs `qa_artifact_updated`, status=approved)
   - Generates the runnable test file via the test generator
   - Logs `qa_tests_generated` with the test file path

Manual authoring is permitted but discouraged. Use the template at
`dist/templates/regression.md.template` if doing it by hand.

### File naming

`regressions/<date>-<short-slug>-<reg-id-suffix>.md`

Examples:
- `regressions/2026-03-15-csv-unicode-9b21.md`
- `regressions/2026-04-02-subscription-tier-validation-a3f7.md`

The date is the date the regression was authored (typically same day as fix).
The slug describes what's being guarded. The suffix is the last 4 chars of
the regression's UUID, to prevent name collisions.

### Required frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `regression_id` | yes | Short ID, last 4-12 chars of a UUID |
| `parent_fix` | yes | Path to the fix this guards against |
| `parent_spec` | no | Path to spec, if the bug had a known spec source |
| `status` | yes | `draft`, `approved`, `retired` |
| `language` | yes | `python` or `typescript` |
| `generator` | yes | `pytest` or `jest` |
| `authored_by` | yes | Name/handle of the QA author |
| `authored_at` | yes | ISO-8601 date |

### Required body sections

- **Why this regression exists** — 2-4 sentences. What failure mode does this
  guard against? If the test fails six months from now, what does that tell
  us about the system?
- **Input** — the exact input that triggered the bug. Code block.
- **Expected output** — what the system must produce after the fix. Code
  block. Includes both the response/return value AND any observable side
  effects (events, DB rows, webhooks).
- **Verification command** — the exact command the team runs to verify.
  Typically the generated pytest/jest invocation.

### Append-only enforcement

The pre-commit hook will warn (not refuse) if you modify a previously-approved
regression artifact's Input or Expected output sections. To make a true
correction in those sections, the recommended pattern is:

1. Retire the existing regression (set `status: retired`, add `retired_reason`).
2. Create a new regression with the correct input/output and a back-link to
   the retired one.

This preserves audit history. The retired regression stays in the repo as a
historical record.

### Retirement

A regression should be retired (NOT deleted) when:
- The feature it guards is genuinely removed from the product.
- The bug it guards against is impossible to trigger anymore due to a
  structural change (e.g., the entire input path is gone).

A regression should **NOT** be retired just because:
- It's flaky. (Fix the flakiness or the underlying race condition.)
- It's slow. (Optimize the test, or move it to a slower CI stage.)
- It's annoying. (That's exactly when it's most valuable.)

Retirement requires:
1. `status: retired` in frontmatter
2. `retired_at: <ISO-date>`
3. `retired_reason: <explanation>` — must be substantive, not "no longer needed"

## Scenario artifacts

A scenario artifact is a **given/when/then sequence** describing one path
through the system. Where regressions guard against a specific past bug,
scenarios verify that paths-the-spec-promised actually work.

### Key properties

- **One scenario per file**. A spec typically has 5-15 scenarios (happy path,
  validation failures, auth failures, idempotency, edge cases). Each goes in
  its own file. This makes review burden manageable, retirement clean, and
  the per-spec scenario count meaningful.
- **Grouped by source spec**. Scenarios live under
  `scenarios/<spec-date-slug>/<scenario-slug>.md`. Browsing the directory
  for a spec shows its full test plan at a glance.
- **Mutable when the spec changes; not mutable to paper over failures.**
  If the source spec gains a new field or error case, the matching scenarios
  evolve. But if a scenario fails because the code regressed, the fix is to
  fix the code — not to weaken the assertion.
- **Trace back to a spec**. The `parent_spec:` frontmatter field is
  mandatory. The audit claim: every scenario points to the contract it
  verifies.

### Authoring flow

1. Run `/qa <spec-path>` after the spec is signed off.
2. Claude reads the spec's Contract Surface and Acceptance Criteria, then
   proposes a list of scenarios derived from them.
3. For each proposed scenario, the QA author reviews and either approves
   as-drafted, edits, or rejects.
4. Approved scenarios are written to `scenarios/<spec-slug>/`.
5. The test generator emits a pytest or Jest test file per scenario into
   `tests/scenario/`.
6. The generated test carries an AUTO-GENERATED header and links back to
   its source artifact.

### File naming

`scenarios/<spec-date-slug>/<scenario-slug>.md`

The spec-date-slug matches the source spec's filename without the `.md`
extension. The scenario-slug is a short human description of what's being
tested.

Examples:
- `scenarios/2026-05-20-statement-export/happy-path-csv-export.md`
- `scenarios/2026-05-20-statement-export/invalid-date-range-rejected.md`
- `scenarios/2026-05-20-statement-export/auth-missing-401.md`

### Required frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `scenario_id` | yes | Short ID, last 4-12 chars of a UUID |
| `parent_spec` | yes | Path to the spec this verifies |
| `status` | yes | `draft`, `approved`, `generated`, `retired` |
| `language` | yes | `python` or `typescript` |
| `generator` | yes | `pytest` or `jest` |
| `authored_by` | yes | Name/handle of the QA author |
| `authored_at` | yes | ISO-8601 date |
| `last_synced_to_spec_at` | yes | ISO-8601 date — last time this was reconciled with the spec |
| `action` | yes | Structured action under test (see below) |
| `setup` | yes | List of preconditions (free-form strings) |
| `expectations` | yes | List of observable outcomes (each becomes one assertion) |

### Structured `action`

The `action` block tells the generator what call to make:

```yaml
action:
  type: http                    # http | function | event | command
  method: POST                  # for http
  endpoint: /subscribe          # for http; or function/topic/command for others
  # body and headers can be in the body's Given section, not in frontmatter
```

For other types:

```yaml
action:
  type: function
  module: myapp.subscriptions
  function: create_subscription

action:
  type: event
  topic: subscriptions.requested

action:
  type: command
  command: ./scripts/run-batch.sh
```

### Structured `expectations`

Each expectation in the list becomes one assertion in the generated test.
Common patterns:

```yaml
expectations:
  - http_status: 201
  - response_body_contains:
      tier: gold
  - side_effect: "subscription.created event published"
  - db_row_exists: "subscriptions table contains row with customer_id=cust-123"
  - error_code: VALIDATION_FAILED       # for sad paths
  - response_time_ms_under: 500         # for performance assertions
```

Free-form expectations (any string the generator doesn't recognize) become
docstring assertions — the test stub mentions them as a TODO for the human.

### Required body sections

- **Why this scenario exists** — 2-4 sentences. What capability does this
  prove works?
- **Given** — narrative of preconditions, matching the `setup` frontmatter.
- **When** — narrative of the action, with concrete payload if applicable.
- **Then** — narrative of expected outcomes, matching `expectations`.

The frontmatter is the machine-readable contract; the body is the human
review surface. Both should agree. If they drift, the human review surface
wins — fix the frontmatter to match.

### Retirement

A scenario should be retired (NOT deleted) when:
- The capability it tests is genuinely removed from the product.
- The endpoint/function/event no longer exists.

A scenario should NOT be retired because:
- It's flaky.
- It's slow.
- It's failing. (Failing scenarios mean the system regressed or the
  scenario needs syncing — figure out which, don't retire.)

Retirement requires:
1. `status: retired`
2. `retired_at: <ISO-date>`
3. `retired_reason: <substantive explanation>`

## Optional UI flow for e2e Playwright tests (scenarios + regressions only)

Scenario and regression artifacts can optionally include a `ui_action:` block in their frontmatter. When present, the test generator produces an **additional** Playwright e2e test under `tests/e2e/` alongside the unit/integration test. Backend-only artifacts simply omit the block — nothing changes.

Property artifacts do NOT support `ui_action`. Property tests generate many inputs (100+) and running each through a real browser would be prohibitively slow. If a property maps to a UI flow, capture it as a scenario with `ui_action` instead.

### When to add ui_action

- The artifact is for a **frontend-touching** spec (scope = `frontend-only` or `full-stack`)
- The scenario describes a **user-facing flow** (clicks, form submissions, navigation)
- For regressions: the original bug had a **UI manifestation** the user could see

### The `ui_action` schema

```yaml
ui_action:
  start_url: <url-the-user-starts-at>
  steps:
    - <step-action>: <selector>
      value: <only-for-fill-and-select>
    - <step-action>: <selector>
    ...
  expect:
    - <expectation-key>: <value>
    - <expectation-key>: <value>
    ...
```

### Step vocabulary

| Step | DSL form | Generated Playwright code |
|------|----------|---------------------------|
| Navigate to URL | `navigate: <url>` | `await page.goto('<url>')` |
| Click element | `click: <selector>` | `await <locator>.click()` |
| Fill input | `fill: <selector>`<br>`value: <text>` | `await <locator>.fill('<text>')` |
| Select option | `select: <selector>`<br>`value: <option>` | `await <locator>.selectOption('<option>')` |
| Wait for element | `wait_for: <selector>` | `await <locator>.waitFor()` |
| Check checkbox | `check: <selector>` | `await <locator>.check()` |
| Uncheck checkbox | `uncheck: <selector>` | `await <locator>.uncheck()` |
| Press key | `press: <key>` | `await page.keyboard.press('<key>')` |

### Expectation vocabulary

| Expectation | DSL form | Generated Playwright assertion |
|-------------|----------|--------------------------------|
| URL matches | `url_matches: <path>` | `await expect(page).toHaveURL('<path>')` |
| URL matches regex | `url_matches: /<pattern>/` | `await expect(page).toHaveURL(new RegExp(...))` |
| Element visible | `visible: <selector>` | `await expect(<loc>).toBeVisible()` |
| Element not visible | `not_visible: <selector>` | `await expect(<loc>).not.toBeVisible()` |
| Page contains text | `text_contains: <text>` | `await expect(page.locator('body')).toContainText(...)` |
| Page title matches | `title_contains: <text>` | `await expect(page).toHaveTitle(new RegExp(...))` |
| Element has value | `value_equals:`<br>` selector: <s>`<br>` value: <v>` | `await expect(<loc>).toHaveValue('<v>')` |
| Element count | `count:`<br>` selector: <s>`<br>` n: <n>` | `await expect(<loc>).toHaveCount(<n>)` |

### Selector vocabulary

Selectors use a prefix syntax that maps to Playwright's semantic locators. Strongly prefer semantic locators over raw CSS — they survive UI refactors:

| Prefix | Maps to | Use for |
|--------|---------|---------|
| `text:Welcome home` | `page.getByText('Welcome home')` | Visible text content |
| `button:Save` | `page.getByRole('button', { name: 'Save' })` | Buttons by accessible name |
| `link:Home` | `page.getByRole('link', { name: 'Home' })` | Links by accessible name |
| `heading:Step 2` | `page.getByRole('heading', { name: 'Step 2' })` | Headings |
| `label:Email` | `page.getByLabel('Email')` | Form fields by their `<label>` |
| `testid:submit-btn` | `page.getByTestId('submit-btn')` | Test IDs (if the team uses `data-testid`) |
| `placeholder:Search...` | `page.getByPlaceholder('Search...')` | Inputs by placeholder text |
| `title:Tooltip text` | `page.getByTitle('Tooltip text')` | Elements with `title=` attribute |
| `alt:Logo` | `page.getByAltText('Logo')` | Images by alt text |
| `.btn-primary` (no prefix) | `page.locator('.btn-primary')` | **Last resort** — raw CSS or XPath |

### Video recording

Every generated Playwright test starts with:

```typescript
test.use({ video: 'on' });
```

This records video for every test run, saving to Playwright's standard `test-results/` directory. CI can upload these as artifacts. If you'd rather record only on failure (saves disk space in successful runs), edit your `playwright.config.ts` to set `video: 'retain-on-failure'` globally — the per-test `video: 'on'` override will still record, so if you want to *disable* per-test video, remove the `test.use(...)` line from the generated test (note: this counts as a hand edit and the pre-commit hook will warn).

### Example

A scenario that verifies the gold tier subscribe flow end-to-end:

```yaml
ui_action:
  start_url: /signup
  steps:
    - select: label:Tier
      value: gold
    - fill: label:Advisor ID
      value: adv-77
    - click: button:Subscribe
  expect:
    - url_matches: /subscribe/success
    - visible: text:Welcome to gold tier
    - not_visible: button:Subscribe
```

Generates a `.spec.ts` file using `getByLabel`, `getByRole`, `getByText` calls with `test.use({ video: 'on' })` at the top. The test starts with `test.skip()` — remove that after verifying selectors match the real UI.

### Common authoring mistakes

- **Using raw CSS selectors when semantic ones exist.** `.subscribe-btn` breaks when the class is renamed; `button:Subscribe` survives.
- **Missing `value` field on fill/select.** The generator emits a comment, not a working step. Add the value.
- **Asserting on internal state.** Playwright tests can only see what the user sees. Don't write expectations like `db_row_exists` — those belong in the scenario's `expectations` (integration test). UI expectations are about what's rendered.
- **Adding `ui_action` to property artifacts.** Properties don't support it. Capture as a scenario instead.

A property artifact declares an **invariant** plus a description of the input
space over which the invariant must hold. The test generator (hypothesis for
Python, fast-check for TypeScript) produces many concrete input cases, runs
the action, and asserts the invariant on each. Failures shrink to a minimal
counterexample.

### Key properties

- **One invariant per file.** A spec typically has 3-8 distinct invariants in
  its Invariants section. Each becomes its own property file.
- **Grouped by source spec.** Properties live under
  `properties/<spec-date-slug>/<property-slug>.md`.
- **Stateless only (v1).** Property tests in this phase test a single action.
  Multi-step state-machine invariants (Hypothesis's `RuleBasedStateMachine`
  or fast-check's model-based testing) are out of scope. If an invariant
  needs N operations, it's stateful — restate it stateless, capture it as a
  scenario, or wait for a future phase.
- **Mutable when the spec changes; not mutable to weaken failures.** Same
  rule as scenarios: if a property fails, fix the code or sync the property
  to a deliberately changed spec.
- **Trace back to a spec.** The `parent_spec:` frontmatter field is mandatory.
  Each property points to the spec's Invariants section it derives from.

### Authoring flow

1. `/qa <spec-path>` reads the spec's Invariants section.
2. For each invariant, Claude proposes:
   - A draft property artifact with the invariant restated as both prose
     and an executable expression
   - A generator declaration in the DSL (see below) derived from the
     Contract Surface
3. The QA author reviews each. The most-edited fields are typically the
   `invariant.expression` (because translating prose to a code expression
   is the hardest part) and the `generators` block (because the Contract
   Surface doesn't always state input bounds).
4. Approved properties are written under `properties/<spec-slug>/`.
5. The test generator emits a hypothesis or fast-check test under
   `tests/property/`.

### File naming

`properties/<spec-date-slug>/<property-slug>.md`

Examples:
- `properties/2026-05-20-subscriptions/tier-always-echoed.md`
- `properties/2026-05-20-subscriptions/subscription-id-unique.md`
- `properties/2026-05-20-subscriptions/no-negative-balance.md`

### Required frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `property_id` | yes | Short ID |
| `parent_spec` | yes | Path to the spec this verifies |
| `status` | yes | `draft`, `approved`, `generated`, `retired` |
| `language` | yes | `python` or `typescript` |
| `generator` | yes | `hypothesis` or `fast-check` |
| `authored_by` | yes | Name/handle |
| `authored_at` | yes | ISO-8601 |
| `last_synced_to_spec_at` | yes | ISO-8601 |
| `max_examples` | no | Default 100. Hypothesis/fast-check will generate this many inputs per run |
| `action` | yes | Same shape as scenario action (http/function/event) |
| `generators` | yes | Map of input field name → DSL form |
| `invariant` | yes | Object with `prose` and `expression` fields |
| `input_filter` | no | Python expression to filter out invalid inputs |

### The generator DSL

The DSL declares the input space. Each entry under `generators:` is one
input field, expressed as a DSL form. The test generator translates each
form to a hypothesis strategy or fast-check arbitrary.

**Supported forms (v1)**:

| DSL form | Example |
|----------|---------|
| `int(min: M, max: N)` | `count: int(min: 0, max: 1000)` |
| `float(min: M, max: N)` | `rate: float(min: 0.0, max: 1.0)` |
| `string(min_len: M, max_len: N)` | `id: string(min_len: 1, max_len: 50)` |
| `enum[a, b, c]` | `tier: enum[bronze, silver, gold]` |
| `bool` | `active: bool` |
| `date(min: D1, max: D2)` | `start: date(min: 2020-01-01, max: 2030-12-31)` |
| `list(of: <sub>, min_len: M, max_len: N)` | `tags: list(of: string(min_len: 1, max_len: 20), min_len: 0, max_len: 5)` |
| `optional(<sub>)` | `advisor_id: optional(string(min_len: 1, max_len: 50))` |
| `dict(k: <sub>, ...)` | nested objects — rarely needed at top level since each field is already a separate entry |

**Not supported in v1 (deliberate)**:
- Regex-constrained strings — too easy to write generators that never produce
  valid inputs the action accepts, causing the property to never fail for
  the right reason
- Recursive structures
- Custom user-supplied generators
- Cross-field dependencies — if field B depends on field A, use `input_filter`
  to skip invalid combinations rather than generating them

### The invariant expression

The invariant is expressed in two parts:
- `prose`: human-readable description, surfaces in failure messages
- `expression`: an executable expression that must evaluate to truthy for
  every generated input

The expression is written in Python syntax. For TypeScript artifacts, the
generator translates it to JavaScript:
- `==` becomes `===`, `!=` becomes `!==`
- `and` / `or` / `not` become `&&` / `||` / `!`
- `None` / `True` / `False` become `null` / `true` / `false`
- Snake_case variables (`actual_status`, `actual_body`, `request_payload`)
  become camelCase (`actualStatus`, `actualBody`, `requestPayload`)
- `x in (a, b, c)` becomes `[a, b, c].includes(x)`

**Variables available in the expression**:
- Each key from `generators:` — the generated input value
- `actual` — what the action returned (most-recent function return value or
  HTTP response body)
- `actual_status` — HTTP status code (if action.type == http)
- `actual_body` — HTTP response body (if action.type == http)
- `request_payload` — the multi-field input dict (when generators has
  multiple fields)

**Examples**:
- `actual_status == 201` — every input produces a 201
- `actual_status != 201 or actual_body['tier'] == request_payload['tier']` —
  if successful, response echoes tier exactly
- `actual['id'] not in seen_ids` — uniqueness (requires `seen_ids` from
  fixture setup; advanced)
- `actual['balance'] >= 0` — balance never negative

### Input filter

If some generated inputs are known-invalid and the action will always reject
them with 400 (or raise), the property would fail for the wrong reason. Use
`input_filter` to skip those cases:

```yaml
input_filter: "len(customer_id) >= 1 and tier != ''"
```

Hypothesis's `assume()` and fast-check's `fc.pre()` handle this — the
framework silently discards inputs that fail the filter, generating more
until `max_examples` is reached.

Use sparingly. Heavy filtering means the generator is too loose; tighten
the DSL forms instead.

### Required body sections

- **Why this property exists** — 2-4 sentences. What invariant violation
  would this catch?
- **Invariant (prose)** — restate the invariant prose with detail.
- **Input space** — narrative description of what's being generated.
- **Notes / limitations** — optional. Especially noting if there are known
  edge cases this property doesn't cover.

### Retirement

A property should be retired (NOT deleted) when:
- The capability it tests is genuinely removed.
- The invariant is no longer believed to hold (this is a big deal — document
  the reason carefully).

A property should NOT be retired because:
- It found a counterexample. (That's success! Fix the code.)
- It's slow. (Reduce `max_examples` or move to a slower CI stage.)
- It's flaky. (Properties shouldn't be flaky — investigate.)

Retirement requires:
1. `status: retired`
2. `retired_at`, `retired_reason`
3. Keep file as historical record

## Where generated tests land

Generated test files go into `tests/regression/`, `tests/scenario/`, or
`tests/property/` alongside any hand-written tests. Each generated file
carries an `# AUTO-GENERATED` header and a `§qa:` comment linking back to
its source artifact:

```python
# AUTO-GENERATED by specship /qa. Do not edit by hand.
# §qa:regressions/2026-03-15-csv-unicode-9b21.md
# To change this test, edit the source artifact and re-run /qa.
# Content hash: abc123...
```

The pre-commit hook (via the advisory `.specship/hooks/qa-check.py` helper)
warns when a generated test drifts from its source artifact. The signal is
staging membership, not the content hash — a legitimate change always stages
the artifact and its regenerated test together, so the hook flags two
asymmetries: a generated test modified without its source artifact, and an
artifact modified without its recorded `generated_test` being regenerated.
The warning is advisory and never blocks the commit. To intentionally modify
a generated test, either:
- Edit the source artifact and re-run `/qa` (preferred), or
- Remove the auto-generated header to claim manual ownership.

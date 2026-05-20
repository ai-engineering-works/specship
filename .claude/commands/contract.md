---
description: Compile a spec's Contract surface section into concrete API artifacts under _generated/. Produces OpenAPI, typed schemas in the backend and frontend languages, Pact stubs, and a diff report. Hash-locks the contract so /work can detect drift. Idempotent — safe to re-run.
argument-hint: <path-to-spec-file>
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /contract — Compile the Contract Surface

You are compiling the Contract surface section of a spec into concrete artifacts that frontend and backend `/work` invocations will both consume. The artifacts are the boundary between the two scopes. Both sides build *against the artifacts*, not against the spec prose. This command must be:

- **Deterministic** — same spec input produces same artifact output, bit-for-bit
- **Idempotent** — re-running on an unchanged spec produces zero diffs
- **Atomic in spirit** — either succeeds fully or leaves the previous state untouched

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"contract command"** section. Logging is best-effort and silent. Generate a session UUID at the start; use it consistently. Log artifact_created for each generated file, and log the spec's status update to contract-locked.

## Inputs

The user has invoked this command with: $ARGUMENTS — a path to a spec file under `specs/`.

If the argument is missing, ask the user which spec to compile.

## Pre-flight checks

### 1. Read the spec and verify shape
- Status is `draft` or `in-progress` (not `contract-locked`, `ready-for-review`, `signed-off`, `done`, or `draft-reverse-engineered`)
  - Exception: if status is `contract-locked`, the user is re-running. Proceed but treat as a re-compile (see "Re-compile handling" below).
  - If status is `draft-reverse-engineered`: STOP. Tell the user: *"This spec hasn't been reviewed since the spec-reverse-engineer skill produced it. Resolve all `[needs review]` markers and change the status to `draft` before running `/contract`."*
- A `## Contract surface` section exists and is non-empty.
- All "Open questions" are closed.
- No placeholder markers (`[fill in]`, `TODO`, `<...>`) remain in the Contract surface section. If any remain, stop and tell the user which ones.

### 2. Read `CLAUDE.md` for project conventions
Look specifically for:
- **`Project type`** field (set under "What this codebase is")
- **`Backend language`** — if absent, sniff from repo: `pom.xml`/`build.gradle` → `java`; `pyproject.toml`/`requirements.txt` → `python`; `go.mod` → `go`; `package.json` with server framework → `typescript`. If still ambiguous, ask the user once.
- **`Frontend language`** — if absent, sniff: presence of `tsconfig.json` → `typescript`; `package.json` without TS → `javascript`; `index.html` only → none; absent entirely → none. Ask if ambiguous.
- **`Contract pair name`** — the Pact consumer/provider pair, e.g. `web-client / notifications-service`. If absent, derive a default (`<frontend-app-name> / <backend-service-name>` from package metadata) and ask the user to confirm and add to `CLAUDE.md`.

### 3. Stop on failure
Any pre-flight failure halts the command. Do not produce partial artifacts.

## Compute the contract hash

The contract hash is the canonical fingerprint of the contract surface. It is recorded in two places:
1. As a `Contract hash` field in the spec's metadata block (top of file)
2. As a `SPEC HASH` line in the header comment of every generated artifact

`/work` compares (1) to (2) to detect drift. If they differ, the contract is stale.

### Hash input definition

The hash is computed over the *normalised content of the Contract surface section only*, not the whole spec file. This is critical: `/contract` also updates the spec's metadata (status, contract hash field, Contract artifacts list), so hashing the whole file would create a self-referential mismatch.

Normalisation steps, in order, applied to the raw markdown of the section:
1. Extract everything between `## Contract surface` and the next top-level `##` heading (exclusive of both).
2. Strip HTML comments (`<!-- ... -->` blocks, including multi-line ones).
3. Trim trailing whitespace from each line.
4. Collapse any run of 2+ blank lines to a single blank line.
5. Strip leading and trailing blank lines.
6. Ensure file ends with exactly one `\n`.

Compute `sha256` of the resulting bytes (UTF-8). Truncate to 16 hex characters for display; use the full 64 in the spec metadata field. The display form is what goes in artifact headers.

Document the normalisation steps inline in the spec's "Contract hash" field so the convention is visible to anyone reading:

```markdown
**Contract hash:** a3f2c4e8b1d5...
<!-- sha256 of normalised Contract surface section (see /contract command docs) -->
```

## Determine the artifact set

Walk the Contract surface section. For each subsection present, produce the corresponding artifacts:

| Spec subsection | Artifacts to produce |
|---|---|
| HTTP endpoints | `_generated/openapi/<slug>.yaml`; `_generated/types/<slug>.<frontend-ext>`; `_generated/types/<slug>.<backend-ext>` |
| Events | `_generated/schemas/<topic-slug>.json` (or `.avsc` if `CLAUDE.md` specifies Avro); event type files in both languages |
| Shared types | included in the type files above; no separate artifact |
| Contract tests | `_generated/pact/<consumer>-<provider>.json` |

Subsections that are absent in the spec produce no artifacts. Do not produce empty files.

### Filename slug rules
- `<slug>` is the spec filename without the date prefix and `.md` extension. `specs/2026-05-12-notif-prefs.md` → slug `notif-prefs`.
- `<topic-slug>` is the topic name with `.` replaced by `-`. Topic `ncbs.gl.events` → slug `ncbs-gl-events`.
- File extensions:
  - TypeScript backend or frontend → `.ts`
  - JavaScript → `.js` (with JSDoc type comments)
  - Python → `.py`
  - Java → `.java` (one file per top-level type; group into a package directory)
  - Go → `.go`

## Generate each artifact

For each artifact, produce content deterministically. No timestamps, no random IDs, no machine-specific paths in the output.

### Common header

Every generated file starts with a header comment in the file's native comment syntax:

```
GENERATED FROM specs/<spec-filename>.md
SPEC HASH: <16-char-truncated-hash>
DO NOT EDIT BY HAND — re-run /contract specs/<spec-filename>.md to regenerate
```

In YAML this is `#` comments; in TS/Java/Go `//`; in Python `#`.

### OpenAPI (`_generated/openapi/<slug>.yaml`)

Produce an OpenAPI 3.0.3 document:
- `info.title` from the spec's first-line title
- `info.version` is `1.0.0` for first compile; on re-compile, see "Re-compile handling" below
- `paths` derived from each `#### METHOD path` block in the spec's HTTP endpoints subsection
- `components.schemas` from request/response shapes and from the Shared types subsection
- Each schema's field constraints (required, max, min, pattern, format) lifted from the spec's annotations

If the spec's request/response JSON sketches include shorthand like `"string, required, max 255"`, parse them:
- `string, required, max 255` → `{ type: string, maxLength: 255 }` and `required: [fieldName]` at the object level
- `'email' | 'sms' | 'push'` → `{ type: string, enum: [email, sms, push] }`
- `string | null` → `{ type: string, nullable: true }`

If a shape is genuinely ambiguous, stop and ask the user — do not guess.

### Type files

TypeScript types are the canonical type representation since TS is the most expressive of the common targets. Produce TS first, then translate to other languages.

- **TypeScript** (`.ts`): one `export type` per top-level type. Use union types for enums (`'email' | 'sms' | 'push'`). Use `?:` for optional fields, `| null` for nullable.
- **Python** (`.py`): use Pydantic v2 models (`from pydantic import BaseModel`). Use `Literal['email', 'sms', 'push']` for enums. `Optional[T]` for nullable.
- **Java** (`.java`): one Java record per type, in a package matching the slug (e.g. `package generated.notif_prefs;`). Use `enum` for enums. `@Nullable` for nullable. Generate one file per top-level type and place under `_generated/types/java/<slug>/`.
- **Go** (`.go`): structs with json tags. Use string-typed constants for enums.
- **JavaScript** (`.js`): export-only JSDoc typedefs, no runtime code.

### Event schemas (`_generated/schemas/<topic-slug>.<ext>`)

- Default `.json` (JSON Schema). Use Avro `.avsc` only if `CLAUDE.md` declares Avro.
- Include topic name, partition key, ordering guarantees as schema annotations or top-level fields per the chosen format.
- Generate matching event type files in both backend and frontend languages alongside.

### Pact stubs (`_generated/pact/<consumer>-<provider>.json`)

Generate Pact V3 contract JSON:
- `consumer.name` from the Contract pair name in `CLAUDE.md`
- `provider.name` likewise
- `interactions[]` — one per HTTP endpoint, each with:
  - `description`: from the spec's "Purpose" line
  - `request`: method, path, expected headers, body matching rules derived from request schema
  - `response`: status, body matching rules derived from response schema
- `metadata.pactSpecification.version: "3.0.0"`

These stubs are *runnable* by Pact provider verification. `/work --scope backend` will execute them as part of post-flight.

If the spec has no HTTP endpoints (events-only contract), skip Pact generation — it's HTTP-specific.

## Re-compile handling

If the spec status is already `contract-locked` (or `in-progress` with existing `_generated/` artifacts for this slug):

### 1. Read the previous artifacts
Before writing anything, read every existing artifact for this slug into memory. These are the "before" state.

### 2. Generate the new artifacts into memory
Compute the new artifact set as plain content, not yet written to disk.

### 3. Compute the structural diff

Run the breaking-change checker against the previous OpenAPI artifact and the new (in-memory) one. Stage the new artifact to a temp file first:

```bash
# Write the new artifact to a temp file for diffing
NEW_TMP=$(mktemp --suffix=.json)
# (Write the in-memory new OpenAPI content to $NEW_TMP — JSON or YAML, the
# checker accepts both)

# Path to the existing OpenAPI artifact (most repos have one per service)
OLD=_generated/openapi/<slug>.yaml  # or .json

# Locate the checker (installed alongside the ledger by install.sh)
CHECKER=.specship/contract/breaking-change-check.sh
if [[ ! -x "$CHECKER" ]]; then
    # Fallback to the in-tree path if running on the self-hosted repo
    CHECKER=dist/contract/breaking-change-check.sh
fi

RESULT=$(bash "$CHECKER" "$OLD" "$NEW_TMP")
rm -f "$NEW_TMP"

# Parse the JSON result
echo "$RESULT" | python3 -m json.tool   # for the user to see
TOOL=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['tool'])")
BREAKING=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['breaking'])")
```

The checker uses `oasdiff` if it's installed on the user's PATH (gold-standard OpenAPI breaking-change detection). Otherwise it falls back to a built-in Python detector that catches the most common breaking changes: removed endpoints, removed fields, type changes, new required fields, removed enum values, removed response statuses, required-parameter additions. The fallback is "good enough to refuse a silently breaking change" but recommend `oasdiff` in user-facing output for full coverage.

The checker's output is a JSON object:
```json
{
  "tool": "oasdiff" | "fallback" | "none",
  "breaking": true | false,
  "additive": true | false,
  "summary": "<one-line summary>",
  "details": ["<line-by-line findings>", ...]
}
```

For reference, the manual classification heuristics the checker implements:

| Change | Category |
|---|---|
| New endpoint, new field, new event, new optional field | additive |
| Removed endpoint, removed field, removed event | breaking |
| Type narrowed (e.g. `string \| null` → `string`) | breaking |
| Type widened (e.g. `string` → `string \| null`) | additive |
| Enum value added | additive |
| Enum value removed | breaking |
| Required field added | breaking |
| Required field made optional | additive |
| Field renamed | breaking (two operations: removed + added) |
| Header comment change only (hash update) | cosmetic |

### 4. Decide what to do

Branch on the checker's `breaking` field:

- **`breaking: false` AND no structural changes** (`details` is empty, hash differs but no semantic diff) → spec edit didn't change the contract semantically. Update artifacts (to refresh hashes) and proceed silently.
- **`breaking: false` AND additive details present** → proceed. Mention the additions in the diff report.
- **`breaking: true`** → STOP before writing artifacts to their final paths. Show the user the full list of breaking changes from `details` and ask for explicit confirmation (`Proceed with breaking changes? yes/no`). Do not write artifacts until the user types `yes`.

Always log the result to the ledger:

```bash
log breaking_change_detected session_id="\"$SID\"" \
    artifact="\"$OLD\"" \
    tool="\"$TOOL\"" \
    breaking="$BREAKING" \
    findings_count="$(echo $RESULT | python3 -c 'import sys,json; print(len(json.load(sys.stdin)[\"details\"]))')"
```

This is logged for both breaking and non-breaking outcomes — the event records that a structural check ran. The ledger will accumulate a history of how often breaking vs additive changes ship, which the team can review periodically.

If the checker's `tool` is `"fallback"`, surface this to the user in the diff report:

> Structural check used the built-in fallback detector. Install `oasdiff`
> (`go install github.com/oasdiff/oasdiff@latest`) for full OpenAPI 3.x
> breaking-change coverage.

Mention this once, not on every invocation — the goal is informing, not nagging.

### 5. Version bump
On any structural change (additive or breaking), increment `info.version` in the OpenAPI doc:
- Additive only → bump minor (`1.0.0` → `1.1.0`)
- Any breaking → bump major (`1.0.0` → `2.0.0`)
- Hash-only → unchanged

## Atomic write protocol

To avoid leaving `_generated/` in a half-state if something fails mid-write:

1. Write all new artifact content into a staging directory: `_generated/.staging-<slug>/`.
2. After all files write successfully, verify each (see Verification below).
3. Only after verification passes, move staging files into place, overwriting previous artifacts.
4. Remove the staging directory.
5. If any step fails, leave previous `_generated/` untouched and delete staging.

This makes `/contract` recoverable. A failed run leaves the prior contract intact; the user can fix the spec and retry.

## Verification

After writing artifacts, run mechanical checks:

| Check | When |
|---|---|
| OpenAPI lint (use `spectral lint` if installed, or `openapi-spec-validator`, or built-in YAML parse + structural check) | Always when OpenAPI was produced |
| TypeScript compile (`tsc --noEmit <file>`) | If `tsc` is on PATH and TS was produced |
| Python parse (`python -m py_compile <file>`) | If Python was produced |
| Java parse | Skip — Java needs full compile context. Defer to `/work --scope backend`. |
| JSON Schema validate | If event schemas were produced |
| Pact JSON validate (must parse, must have V3 fields) | If Pact stubs were produced |

If any verification fails:
- Leave the `.staging-<slug>/` directory in place
- Report the failure clearly
- Do not update the spec
- Do not promote staging to `_generated/`

## Update the spec (only on full success)

After all artifacts are written and verified:

1. Add or update the metadata block at the top of the spec:
   ```markdown
   **Status:** contract-locked
   **Contract hash:** <full 64-char hash>
   ```
2. Add or replace a `## Contract artifacts` section near the end of the spec, listing the full file paths produced.
3. Save the spec.

The spec file's content changes here, but the *Contract surface section* (the hashed region) does NOT change. So the hash recorded in the artifacts still matches the recomputed hash of the section. This is the correctness property the normalisation step buys.

## Output to user

After success, show:

```
✓ Contract compiled for specs/2026-05-12-notif-prefs.md
  Hash: a3f2c4e8b1d5...
  Version: 1.0.0 (or n.n.n on re-compile)

Artifacts written:
  _generated/openapi/notif-prefs.yaml
  _generated/types/notif-prefs.ts
  _generated/types/notif-prefs.py
  _generated/pact/web-client-notifications-service.json

Diff vs previous compile:
  + Added: GET /notifications/preferences
  + Added: type NotificationPreference
  (or: "No previous compile — initial version")

Next: /work specs/2026-05-12-notif-prefs.md --scope backend
      /work specs/2026-05-12-notif-prefs.md --scope frontend
```

On breaking changes, the diff section is more prominent and requires user confirmation before the output above is produced.

## What not to do

- Do not generate artifacts for subsections the spec didn't include.
- Do not modify the spec's Contract surface section. The spec is input; artifacts are output.
- Do not hand-edit anything in `_generated/`. If a file looks wrong, the spec is wrong.
- Do not generate business logic — only contract surface.
- Do not skip the hash or use a non-deterministic hash input.
- Do not include timestamps, machine names, or random IDs in artifact content.
- Do not write artifacts directly to `_generated/` — always stage first.
- Do not proceed past a breaking change without explicit user confirmation.
- Do not invoke external compiler scripts. This workflow stands alone.

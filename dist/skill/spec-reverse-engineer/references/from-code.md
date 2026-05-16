# Extracting specs from source code

How to derive `specship` spec sections from source code. The goal is to fill each spec section using the highest-reliability signals available, mark the rest as `[needs review]`.

## Section-by-section extraction guide

### `## Intent`

Best sources (in order):
1. README sections in the module/package describing purpose
2. Top-of-file docstrings or javadoc
3. Class/module-level documentation

If none exists:
- Derive from the public API names (class names, top-level function names)
- Limit to 1-2 sentences describing the *observable* behaviour, not implementation
- Mark `[needs review — purpose inferred from API names, not documented]`

**Do NOT**: invent business context like "improves customer experience" or "supports compliance with regulation X". If those aren't documented, omit them.

### `## Acceptance criteria`

Best source: **the test files**. This is the highest-fidelity signal you have.

- Each test function name typically encodes an acceptance criterion
- `test_should_return_empty_list_when_no_preferences_exist` → `- [x] Returns empty list when no preferences exist`
- `test_putPreferences_with_invalid_channel_returns_400` → `- [x] PUT /preferences rejects unknown channels with 400`
- Use `[x]` (already met) for criteria derived from passing tests
- Use `[ ]` (open) only if the user explicitly wants the spec to drive new work

For full-stack scope, group test-derived criteria by which side they test (backend tests → Backend, e2e/Cypress tests → Frontend, contract tests → Cross-cutting).

If no tests exist:
- Derive criteria from observable behaviour (route handlers, validation, return types)
- Mark each criterion `[needs review — no test backs this; please add a regression test]`

### `## Contract surface`

This is the section reverse-engineering does *best*, because it's the most code-traceable.

**HTTP endpoints — extract from:**

- **Spring Boot:** `@GetMapping`, `@PostMapping`, etc. on controllers. Method signatures give request and response types. `@Valid` annotations identify validation. `@PathVariable`, `@RequestParam`, `@RequestBody` identify parameter sources.
- **FastAPI:** `@router.get(...)`, `@router.post(...)`. Pydantic models in parameters and return types are direct schema definitions.
- **Express/NestJS:** `app.get`, `router.post`; for NestJS, controller decorators (`@Controller`, `@Get`).
- **Flask:** `@app.route("/path", methods=["GET"])`.
- **Django REST:** `ViewSet` classes with `list`/`create`/`retrieve` methods, or function-based views.

For each endpoint, produce:

```markdown
#### `<METHOD> <path>`

- **Purpose:** <from docstring/javadoc; else from method name; else [needs review]>
- **Request body:** <from Pydantic model / DTO class / @RequestBody type>
- **Response 200:** <from return type / serializer>
- **Error envelope:** <from `@ExceptionHandler` / FastAPI exception_handlers / Express error middleware>
- **Auth:** <from `@PreAuthorize` / FastAPI Depends() / middleware>
```

If the auth model isn't obvious from the code, mark `[needs review]`.

**Events — extract from:**

- Kafka producer code (look for `KafkaTemplate.send`, `producer.send`)
- Avro schemas under `src/main/avro` or `schemas/`
- Schema Registry references

For each topic, produce:

```markdown
#### Topic: `<topic.name>`
- **Direction:** produce | consume
- **Schema:** <from the Avro file path, or from the DTO type being produced>
- **Partition key:** <from `ProducerRecord` key arg, or default>
- **Ordering guarantees:** [needs review — not derivable from code alone]
```

Ordering guarantees almost never appear in code — they're operational assumptions. Mark for review.

**Shared types — extract from:**

- Type definitions used in BOTH the backend response and the frontend client
- Pydantic models, Java DTOs, TypeScript types/interfaces
- If a type is only used in one place, it's not a "shared type" — skip it

Use TypeScript as the canonical representation in the spec (per the standard specship contract surface format), even if neither side is written in TS. The spec is for humans and for `/contract`, not for direct import.

### `## Non-goals`

Almost never derivable from code. Leave blank with `[fill in — not derivable from existing code]` and ask the user.

The one exception: if you see explicit "not implemented yet" markers (`raise NotImplementedError`, `throw new NotImplementedException`, TODO comments), those are non-goals.

### `## Files likely to change`

For a reverse-engineered spec covering existing code, this section serves as a *map* of what's covered rather than a forward prediction. Rename mentally to "Files covered by this spec":

```markdown
## Files covered by this spec

### Backend
- `src/backend/notifications/NotificationController.java`
- `src/backend/notifications/NotificationService.java`
- `src/backend/notifications/dto/NotificationPreference.java`

### Frontend
- `src/frontend/pages/preferences.tsx`
- `src/frontend/api/notifications.ts`
```

This map is what `/check` will use to know which files this spec governs.

### `## Tests required`

For reverse-engineered specs, this becomes "Tests that exist":

- List existing test files and roughly what they cover
- Identify *gaps* — acceptance criteria that have no test backing them
- Mark gap rows `[needs review — no test backs criterion N]`

### `## Open questions`

Reverse-engineered specs almost always have open questions. Use this section to surface them:

- Auth model unclear?
- Error handling inconsistent?
- One endpoint returns different shapes under different conditions?

Each open question is a real research item for the user.

### `## Notes`

Append a "Reverse-engineering notes" subsection:

```markdown
## Notes

### Reverse-engineering notes

- Generated 2026-05-12 from the source files listed in metadata
- Confidence: high for endpoint shapes (extracted from controllers); medium for acceptance criteria (extracted from tests); low for non-goals (none documented)
- Watch out for: <any specific weirdness encountered, e.g. "endpoint Z has different behaviour in dev vs prod per env-var DEV_MODE">
```

## Language-specific extraction notes

### Python

- **Type hints** are the primary signal. Functions without type hints are harder to reverse-engineer; mark `[needs review — function has no type hints]`.
- **Pydantic models** translate directly to shared types. Use `model.schema()` mentally to get the JSON schema shape.
- **FastAPI** is the friendliest framework for this — its OpenAPI generation already captures most of what specship needs. If `app.openapi()` is available, run it and use the result as the primary input.
- **Django** routing is in `urls.py`; views can be class- or function-based; serializers (DRF) are the schema source.
- **Decorators matter.** `@router.get(..., response_model=X)` is a goldmine.

### Java

- **Spring annotations** carry most of the contract surface: `@RequestMapping`, `@Valid`, `@RequestBody`, `@ResponseStatus`, `@ExceptionHandler`.
- **Java records** (since Java 14) are explicit DTOs — use them directly as shared types.
- **Lombok** complicates extraction (fields are implicit). Look at `@Data`, `@Value`, `@Builder` classes and treat the field declarations as the type definition.
- **`javax.validation` annotations** (`@NotNull`, `@Size`, `@Pattern`) give field-level constraints.

### TypeScript / JavaScript

- **NestJS** has the strongest decorator metadata — use it like Spring.
- **Express** without TypeScript is low-signal — only the route paths are obvious, and even response shapes need to be inferred from response builders.
- **Zod schemas** translate directly to TypeScript types and OpenAPI schemas.
- **tRPC** has procedure definitions that are nearly spec-shaped already.
- If the frontend uses an API client generated from OpenAPI, the generated types ARE the contract — use them directly.

### Other languages (Go, Rust, Ruby, etc.)

Apply the same principles: find the route declarations, the type definitions, the validation, and the test assertions. Mark anything not directly derivable as `[needs review]`. The skill doesn't need to be expert in every language; honest uncertainty is better than confident wrongness.

## Test extraction patterns

Some test patterns map especially cleanly to acceptance criteria:

| Test name pattern | Spec line |
|---|---|
| `test_should_X_when_Y` | `- [x] X when Y` |
| `test_X_returns_Y` | `- [x] X returns Y` |
| `test_invalid_X_returns_400` | `- [x] Invalid X returns 400` |
| `test_X_idempotent` | `- [x] X is idempotent` |
| `test_X_raises_Y` | `- [x] X raises Y on <derived condition>` |

For BDD-style tests (`Given X, When Y, Then Z`), the `Then` clauses become acceptance criteria directly.

For property-based tests (Hypothesis, fast-check, jqwik), the property statements ARE acceptance criteria:
- `@given(st.integers())` + assertion → "for any integer, <assertion>"

## What you'll never get from code

Be honest about these limits in the produced spec:

- **Why** this code was written (motivation, business goals)
- **What was considered and rejected** (alternatives, trade-offs)
- **What's deliberately not done yet** (non-goals)
- **Operational expectations** (SLA, throughput targets, ordering guarantees)
- **Cross-cutting policy** (audit emission, regulatory compliance) unless explicitly coded

For these, leave `[needs review]` flags and let the user fill from their head or from runbooks.

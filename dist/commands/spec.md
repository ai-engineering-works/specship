---
description: Draft a spec file from a ticket description or rough intent. The spec becomes the contract for the work. For full-stack changes, captures the API contract surface explicitly.
argument-hint: <ticket-id-or-short-description>
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /spec — Draft a Spec File

You are drafting a spec file that will serve as the contract for a piece of work. The spec is a markdown file in `specs/` with a date-slug filename. It captures intent and acceptance criteria *before* code is written. For full-stack changes, it ALSO captures the API contract surface, which becomes the boundary between frontend and backend execution.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in `.specship/ledger/HOW-TO-LOG.md` — specifically the **"spec command"** section. Logging is best-effort and silent (never surface ledger errors to the user, never mention logging in your visible response). Generate a session UUID at the start; use it consistently throughout this command's execution.

## Inputs

The user has invoked this command with: $ARGUMENTS

Treat the argument as either:
- A JIRA-style ticket ID (e.g. `SGEN-1234`) — if so, ask the user to paste the ticket description if it isn't already in context
- A short description of the work — if so, use it as the seed and ask for any missing context

## Read the constitution first

Before drafting, read `CLAUDE.md` at the repo root if it exists. The spec must respect every invariant listed there. Look specifically for the `Project type:` field — it determines the scope defaulting behaviour below. If `CLAUDE.md` does not exist, mention this to the user and suggest running the `claude-md-architect` skill to create one.

## Classify the scope

Use this decision tree, in order:

1. **Read `Project type` from `CLAUDE.md`** (under the "What this codebase is" section).
   - If `Project type: backend-only` → default scope is `backend-only`. Use this without asking unless the description clearly involves UI.
   - If `Project type: frontend-only` → default scope is `frontend-only`. Use this without asking unless the description clearly involves backend or API changes.
   - If `Project type: full-stack` → use heuristics below to pick scope per ticket.
   - If `Project type: library` → default scope is `full-stack` for any change touching the public API; backend-only otherwise.
   - If `Project type` is missing → ask the user once for this ticket, and suggest they add the field to `CLAUDE.md`.

2. **For full-stack or library projects, apply heuristics from the ticket description:**
   - Mentions an endpoint, route, controller, API, schema, or event → likely `full-stack`
   - Mentions UI, component, page, screen, styling, button, form → likely `full-stack` if backend change also implied, else `frontend-only`
   - Mentions pipeline, batch, consumer, producer, infrastructure → likely `backend-only`
   - Mentions internal refactor, performance, no external observable change → match the layer being refactored
   - Ambiguous → ask the user with the candidates.

3. **Final scope values** (one of):
   - `backend-only` — no UI changes
   - `frontend-only` — no backend changes
   - `full-stack` — crosses UI/API boundary OR changes API/event contracts that have downstream consumers

The scope determines whether a "Contract surface" section is included in the spec. Full-stack tickets MUST have a contract surface section. Backend-only or frontend-only tickets MAY have one if the change touches an externally-consumed API or event.

## Draft the spec

Create a file at `specs/YYYY-MM-DD-<slug>.md` (today's date, kebab-case slug from the description). Use the following structure. **Include the Contract surface section only for `full-stack` scope or when explicitly needed.**

```markdown
# <Short title>

**Ticket:** <ticket id or "none">
**Status:** draft
**Scope:** <backend-only | frontend-only | full-stack>
**Created:** YYYY-MM-DD

## Intent

<2-4 sentences describing what should be true after this change.
Plain language, business-outcome oriented.>

## Acceptance criteria

<Mechanically verifiable checkboxes. Group by scope side if full-stack.>

### Backend
- [ ] <criterion>

### Frontend
- [ ] <criterion>

### Cross-cutting
- [ ] <criterion>

## Contract surface
<!-- Include this section ONLY if scope is full-stack or the change touches
     an externally-consumed API or event. Otherwise OMIT the whole section. -->

### HTTP endpoints

<For each new or changed endpoint:>

#### `<METHOD> <path>`

- **Purpose:** <one line>
- **Request body:** <schema sketch or "none">
  ```json
  {
    "fieldName": "string, required, max 255",
    "...": "..."
  }
  ```
- **Response 200:**
  ```json
  {
    "...": "..."
  }
  ```
- **Error envelope:** <inherit project standard, or specify>
- **Auth:** <e.g. "bearer token", "session cookie", "none">

### Events
<If Kafka or event-bus events are produced or consumed:>

#### Topic: `<topic.name>`
- **Direction:** produce | consume
- **Schema:** <Avro/JSON sketch or schema registry reference>
- **Partition key:** <field name or "none">
- **Ordering guarantees:** <e.g. "per-customer ordering required">

### Shared types
<Types that must match exactly between frontend and backend.
Frontend will be generated from this; backend will validate against this.>

```typescript
// Sketch in TS, even if backend is Java/Python — TS is the most precise
// way to communicate the shape. Generated artifacts will produce the
// equivalent in the target language.
type NotificationPreference = {
  channel: 'email' | 'sms' | 'push';
  enabled: boolean;
  frequency?: 'instant' | 'daily' | 'weekly';
};
```

### Compatibility notes
<Breaking change? Deprecation timeline? Versioning approach?>

- <e.g. "Additive only — no breaking changes to existing fields">
- <e.g. "Deprecates v1; consumers migrate by 2026-06-01">

## Non-goals

<What this change explicitly does NOT do.>

- <non-goal>

## Files likely to change

<Group by scope side if full-stack.>

### Backend
- `src/...`

### Frontend
- `src/...`

### Generated (do not hand-edit)
- `_generated/openapi/<feature>.yaml`
- `_generated/types/<feature>.ts`

## Tests required

### Backend
- <test>

### Frontend
- <test>

### Contract tests
- <e.g. "Pact consumer test for GET /notifications, asserting response shape">

## Open questions

<Anything the spec can't resolve. Must be closed before /contract or /work.>

- <question, or "none">

## Notes

<Free-form context. Optional.>
```

For `backend-only` or `frontend-only` scopes, omit the per-side grouping in Acceptance criteria, Files likely to change, and Tests required — use flat lists instead. Keep the structure simple when the scope is simple.

## After drafting

1. Save the file.
2. Show the user the path, the scope, and a one-line summary.
3. **If the spec has a Contract surface section, scan it for placeholders** (`[fill in]`, `TODO`, `<...>` markers) and call them out. Tell the user: *"Contract surface has N unresolved placeholders. Fill them in before running `/contract`."*
4. List any open questions you flagged — these block `/contract` and `/work`. If any remain unresolved (or the Contract surface still has placeholders), do NOT offer to continue below; tell the user to resolve them first.
5. **Offer to continue — Enter defaults to yes.** When nothing blocks the next step, ask the user whether to proceed now instead of making them retype a command. Treat `y`/`yes`/empty input as yes and `n`/`no` as no:
   - **`backend-only` / `frontend-only`:** ask *"Proceed to `/work` on this spec now? [Y/n] (`/work` is recommended on opus — press n to run it in a fresh session if you want the model split.)"* On yes, execute the `/work` slash command against this spec path in this session. On no, tell the user: *"Run `/work <spec-path>` when ready."*
   - **`full-stack`:** ask *"Proceed to `/contract` on this spec now? [Y/n]"* (same recommended model — no model-split caveat). On yes, execute the `/contract` slash command against this spec path in this session; its own closing step offers the `/ship` (orchestrated) or `/work` continuation. On no, tell the user: *"Next: `/contract <spec-path>`, then `/ship <spec-path>` (orchestrated) or `/work --scope backend` + `/work --scope frontend`."*
6. Do NOT execute any code or make any other changes until the user confirms a continuation above.

## What not to do

- Do not invent acceptance criteria the user didn't imply. Unclear → "Open questions".
- Do not start implementing. This command produces a spec, nothing else.
- Do not invent contract details (field names, types) the user didn't supply or imply. Ask, or leave a TODO marker the user must resolve.
- Do not include a Contract surface section for backend-only or frontend-only scopes unless the change genuinely touches an externally-consumed contract.
- Do not invent ticket IDs.

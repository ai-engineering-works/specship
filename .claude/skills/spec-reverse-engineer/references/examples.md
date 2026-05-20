# Reverse-engineering examples

Concrete walkthroughs of converting existing material into specship specs.

---

## Example 1: From a Spring Boot controller + tests (code only)

### Inputs

`src/backend/notifications/NotificationController.java`:
```java
@RestController
@RequestMapping("/notifications/preferences")
public class NotificationController {

    @Autowired
    private NotificationService service;

    @GetMapping
    @PreAuthorize("isAuthenticated()")
    public ResponseEntity<PreferencesResponse> get(@AuthenticationPrincipal User user) {
        return ResponseEntity.ok(new PreferencesResponse(service.getPreferences(user.getId())));
    }

    @PutMapping
    @PreAuthorize("isAuthenticated()")
    public ResponseEntity<PreferencesResponse> put(
        @AuthenticationPrincipal User user,
        @Valid @RequestBody PreferencesRequest body) {
        service.savePreferences(user.getId(), body.preferences());
        return ResponseEntity.ok(new PreferencesResponse(body.preferences()));
    }
}

public record NotificationPreference(
    @NotNull Channel channel,
    boolean enabled,
    Frequency frequency
) {}

public enum Channel { EMAIL, SMS, PUSH }
public enum Frequency { INSTANT, DAILY, WEEKLY }
```

`src/backend/notifications/NotificationControllerTest.java`:
```java
@Test void get_whenNoPreferences_returnsEmptyList() { ... }
@Test void get_whenPreferencesExist_returnsAll() { ... }
@Test void put_withInvalidChannel_returns400() { ... }
@Test void put_persistsThePreferences() { ... }
@Test void get_unauthenticated_returns401() { ... }
```

### Output: `specs/2026-05-12-notification-preferences-reverse-engineered.md`

```markdown
# Notification preferences (reverse-engineered)

**Ticket:** none
**Status:** draft-reverse-engineered
**Scope:** backend-only
**Created:** 2026-05-12
**Reverse-engineered from:**
  - `src/backend/notifications/NotificationController.java`
  - `src/backend/notifications/NotificationControllerTest.java`

## Intent

Customers can view and update their notification preferences across email,
SMS, and push channels, with configurable delivery frequency.
[needs review — purpose inferred from API and entity names; no business
documentation found]

## Acceptance criteria

### Backend
- [x] GET returns empty list when customer has no preferences
- [x] GET returns all preferences when customer has them
- [x] PUT with invalid channel value returns 400
- [x] PUT persists the provided preferences
- [x] Unauthenticated requests return 401

## Contract surface

### HTTP endpoints

#### `GET /notifications/preferences`

- **Purpose:** Return current notification preferences for the authenticated customer
- **Request body:** none
- **Response 200:**
  ```json
  {
    "preferences": "array of NotificationPreference"
  }
  ```
- **Error envelope:** [needs review — no explicit @ExceptionHandler found in scope]
- **Auth:** authenticated user (Spring `@PreAuthorize("isAuthenticated()")`)

#### `PUT /notifications/preferences`

- **Purpose:** Replace notification preferences for the authenticated customer
- **Request body:**
  ```json
  {
    "preferences": "array of NotificationPreference, required (@Valid)"
  }
  ```
- **Response 200:** same shape as GET
- **Error envelope:** 400 on validation failure (Spring default)
- **Auth:** authenticated user

### Shared types

```typescript
type NotificationPreference = {
  channel: 'email' | 'sms' | 'push';   // from Channel enum
  enabled: boolean;
  frequency: 'instant' | 'daily' | 'weekly';  // from Frequency enum
                                              // [needs review — record has no
                                              // @Nullable; appears required, but
                                              // confirm whether legacy data may
                                              // have null frequency]
};
```

### Compatibility notes

[needs review — no version annotation in code; compatibility expectations
not derivable. Confirm whether this endpoint is consumed externally.]

## Non-goals

[needs review — no Non-goals section in source. Common candidates to consider:
- Notification content templating?
- Delivery scheduling?
- Per-recipient customisation?]

## Files covered by this spec

### Backend
- `src/backend/notifications/NotificationController.java`
- `src/backend/notifications/NotificationService.java` (inferred from @Autowired)
- `src/backend/notifications/dto/NotificationPreference.java`
- `src/backend/notifications/dto/PreferencesRequest.java`
- `src/backend/notifications/dto/PreferencesResponse.java`

## Tests that exist

- `src/backend/notifications/NotificationControllerTest.java` — 5 tests covering all 5 acceptance criteria
- [needs review — no integration tests found. Consider whether service-layer
  unit tests should also be linked here.]

## Open questions

- What's the error envelope when 500 errors occur? Not derivable from controller alone.
- Is there a soft delete on preferences, or is replacement total?
- Are preferences scoped per tenant or only per user?
- What's the rate limit?

## Notes

### Reverse-engineering notes

- Generated 2026-05-12 from the source files listed in metadata.
- Confidence: HIGH for endpoint shapes (Spring annotations are unambiguous),
  HIGH for acceptance criteria (5 tests map directly), MEDIUM for shared types
  (records are explicit but nullable annotations missing), LOW for non-goals
  (none documented).
- §ref:specs comments NOT added to source files. Recommend adding them when
  this spec is promoted to draft, via a follow-up /fix.
```

### What the user does next

1. Search for `[needs review]` → 6 flags. Resolve each (most can be confirmed quickly).
2. Add §ref:specs comments to the four source files when ready.
3. Change status to `draft`.
4. The spec is now usable for future /work invocations and /check drift detection.

---

## Example 2: From an OpenAPI YAML (doc only)

### Input

`docs/api/v2/notifications.yaml`:
```yaml
openapi: 3.0.3
info:
  title: Notification Preferences API
  version: 2.1.0
  description: Customers manage notification channel preferences.
paths:
  /notifications/preferences:
    get:
      security: [{ bearerAuth: [] }]
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PreferencesResponse'
    put:
      security: [{ bearerAuth: [] }]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/PreferencesRequest'
      responses:
        '200':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PreferencesResponse'
        '400':
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
components:
  schemas:
    NotificationPreference:
      type: object
      required: [channel, enabled]
      properties:
        channel:
          type: string
          enum: [email, sms, push]
        enabled:
          type: boolean
        frequency:
          type: string
          enum: [instant, daily, weekly]
          nullable: true
    PreferencesRequest:
      type: object
      required: [preferences]
      properties:
        preferences:
          type: array
          items: { $ref: '#/components/schemas/NotificationPreference' }
    PreferencesResponse:
      type: object
      properties:
        preferences:
          type: array
          items: { $ref: '#/components/schemas/NotificationPreference' }
```

### Output (abbreviated): `specs/2026-05-12-notification-preferences-api-v2-reverse-engineered.md`

The translation is mostly mechanical. Highlights:

- **Intent** is taken verbatim from `info.description` (1 sentence — confirm it's enough)
- **Contract surface → HTTP endpoints** translated 1:1 from `paths`
- **Shared types** translated to TypeScript:
  ```typescript
  type NotificationPreference = {
    channel: 'email' | 'sms' | 'push';
    enabled: boolean;
    frequency?: 'instant' | 'daily' | 'weekly' | null;
  };
  ```
- **Compatibility notes** records the OpenAPI version (`2.1.0`)
- **Acceptance criteria** is `[needs review]` — OpenAPI alone doesn't carry behaviour assertions
- **Non-goals**, **Open questions** are `[needs review]`

The user must combine this with tests or BDD scenarios to fill Acceptance criteria, or accept that this is a contract-surface-only spec for now and back-fill criteria later.

---

## Example 3: From a Confluence-style markdown design doc (doc only)

### Input

`docs/specs/notification-preferences-design.md` (4800 words, abbreviated):

```markdown
# Notification Preferences — Design Document

Last updated: 2024-08-15 by Selva
Status: In Review

## 1. Background

Customer Success has been receiving frequent complaints from customers who
are overwhelmed by notification volume. We've also heard from the compliance
team that certain notifications (e.g. marketing) require explicit opt-in
under PDPA regulations applicable to our Singapore customer base.

## 2. Goals

- Allow customers to control which channels receive which notifications
- Support PDPA opt-in requirement for marketing notifications
- Allow customer to adjust notification frequency

## 3. Non-goals

- Notification content templating (separate project)
- Per-recipient customisation within a tenant
- Real-time delivery (asynchronous is fine)

## 4. Personas

[long section about user personas — drop]

## 5. User stories

[8 user stories — extract as acceptance criteria]

## 6. API Design

[detailed endpoint specs — translate to Contract surface]

## 7. Data Model

[ER diagram and table definitions — extract; data model definitions go
into Contract surface > Shared types, ER diagram extracts to architecture.md]

## 8. Implementation phases

[phased rollout plan — DROP, this is project management not spec]

## 9. Migration plan

[DROP — this is project management]

## 10. Open questions

- How do we handle existing customers with no preferences set?
- Do preference changes require an audit log entry?
- What's the retention policy for preference history?

## 11. Stakeholders

[DROP — this is project management]

## 12. References

[link list — extract to Notes if any link is critical]

## Appendix A: Survey results

[DROP — historical context]

## Appendix B: Competitive analysis

[DROP]
```

### Output: `specs/2026-05-12-notification-preferences-reverse-engineered.md`

```markdown
# Notification preferences (reverse-engineered)

**Ticket:** none
**Status:** draft-reverse-engineered
**Scope:** full-stack
**Created:** 2026-05-12
**Reverse-engineered from:**
  - `docs/specs/notification-preferences-design.md` (last edited 2024-08-15,
    21 months old — verify currency)

## Intent

Customers control which notification channels receive which notifications,
and at what frequency. The system supports PDPA opt-in for marketing
notifications under Singapore regulation.

## Acceptance criteria

### Backend
- [ ] Customer can fetch their current preferences
- [ ] Customer can update channel preferences (email/SMS/push)
- [ ] Customer can update frequency preferences (instant/daily/weekly)
- [ ] Marketing notifications require explicit opt-in (PDPA)
- [ ] Preference changes are audited [needs review — open question in source doc]

### Frontend
- [ ] Preferences page renders current state
- [ ] Toggle updates persist on save
- [ ] PDPA opt-in checkbox displayed prominently for marketing channel

## Contract surface

[Contract surface translated from source doc section 6, abbreviated for example]

## Non-goals

- Notification content templating (separate project)
- Per-recipient customisation within a tenant
- Real-time delivery (asynchronous acceptable)

## Files likely to change

[needs review — source doc is design-stage; current implementation
 location not derivable. Recommend running this skill in Scenario C mode
 with the code as the additional input.]

## Tests required

- [ ] Backend tests for each acceptance criterion above
- [ ] Frontend test for PDPA opt-in display
- [needs review — no existing tests cited in source doc]

## Open questions

- How do we handle existing customers with no preferences set?
  (from source doc section 10)
- Do preference changes require an audit log entry?
  (from source doc section 10; acceptance criterion above conditional on this)
- What's the retention policy for preference history?
  (from source doc section 10)

## Notes

### Reverse-engineering notes

Migrated from `docs/specs/notification-preferences-design.md` on 2026-05-12.

DROPPED from source (with reasons):
  - Section 4 (Personas) — not contract content
  - Section 8 (Implementation phases) — project management
  - Section 9 (Migration plan) — project management
  - Section 11 (Stakeholders) — project management
  - Appendix A (Survey results) — historical context
  - Appendix B (Competitive analysis) — not contract content

EXTRACTED elsewhere:
  - Section 7 ER diagram → recommend extracting to `docs/architecture.md`
    (not yet done by this skill — manual step)

STALENESS WARNING:
  - Source doc last edited 2024-08-15 (21 months ago).
  - Verify current accuracy of: API design (section 6), data model (section 7),
    PDPA regulatory requirements (compliance landscape changes).
```

### What the user does next

1. Verify currency of the 21-month-old source — likely needs significant updates.
2. Resolve the open questions (which are real research items).
3. If running on real code too, re-invoke this skill in Scenario C mode with both the doc AND the code paths to fill the gaps.
4. Manually extract the ER diagram to `docs/architecture.md`.
5. Add `§ref:specs/...` comments to the relevant code files (likely needs `/fix` for each affected module).

---

## Lessons across the three examples

- **Code alone** gives you contract surface and acceptance criteria; weak on intent and non-goals
- **OpenAPI alone** gives you contract surface; nothing else
- **Design docs alone** give you intent and non-goals; weak on whether code matches
- **Combining sources** (Scenario C) is the path to a high-quality reverse-engineered spec

The skill should encourage Scenario C whenever both signals are available. Single-source specs are starting points, not finished artifacts.

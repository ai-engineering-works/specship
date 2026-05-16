# Notification preferences

**Ticket:** NOTIF-42
**Status:** contract-locked
**Scope:** full-stack
**Created:** 2026-05-12
**Contract hash:** WILLBEFILLED

## Intent

Customers want to control which channels they receive notifications on.

## Acceptance criteria

### Backend
- [ ] GET endpoint returns preferences
- [ ] PUT endpoint persists changes

### Frontend
- [ ] Preferences page displays current channels
- [ ] Toggle updates server

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
- **Auth:** session cookie

#### `PUT /notifications/preferences`

- **Purpose:** Replace notification preferences for the authenticated customer
- **Request body:**
  ```json
  {
    "preferences": "array of NotificationPreference, required"
  }
  ```
- **Response 200:** same shape as GET
- **Auth:** session cookie

### Shared types

```typescript
type NotificationPreference = {
  channel: 'email' | 'sms' | 'push';
  enabled: boolean;
  frequency?: 'instant' | 'daily' | 'weekly';
};
```

### Compatibility notes

- Additive only — no existing endpoints touched

## Non-goals

- Notification content templating

## Files likely to change

### Backend
- `src/backend/notifications/`

### Frontend
- `src/frontend/pages/preferences.tsx`

## Tests required

- Pact consumer test for GET, PUT

## Open questions

- none

## Notes

## Contract artifacts

- `_generated/openapi/notif-prefs.yaml`
- `_generated/types/notif-prefs.ts`
- `_generated/types/notif-prefs.py`
- `_generated/pact/web-client-notifications-service.json`

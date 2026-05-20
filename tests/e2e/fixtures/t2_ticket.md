# DEMO-2: subscribe endpoint (full-stack)

Full-stack change. The backend exposes one HTTP endpoint and the web client
calls it.

Contract surface (be explicit):
- `POST /subscribe`
  - request body: `{ "advisor_id": string, "tier": "bronze"|"silver"|"gold" }`
  - response 201: `{ "subscription_id": string, "tier": string }`
  - response 400 when `tier` is not one of the allowed values

Backend in `src/app.py`, web client call in `web/app.js`.

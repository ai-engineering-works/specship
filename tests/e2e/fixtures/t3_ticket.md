# DEMO-3: statement export (full-stack) + known defect

Full-stack change. Add `POST /export` that accepts
`{ "from": "YYYY-MM-DD", "to": "YYYY-MM-DD" }` and returns
`200 { "rows": number, "format": "csv" }`. When `from` is after `to`, the
endpoint MUST return `400`.

Known defect to investigate and fix during the workflow: the date-range
validation is inverted, so `from > to` returns `200` instead of `400`.

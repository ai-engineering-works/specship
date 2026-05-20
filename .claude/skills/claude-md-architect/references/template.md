# Project Constitution

<!--
This file is the constitution for AI-assisted work in this repo.
It is read automatically by Claude Code at the start of every session.

Keep it under 200 lines. If it grows beyond that, you have THREE options
(in order of preference):

1. Push content into a NESTED CLAUDE.md under a specific module/package
   (e.g. `frontend/CLAUDE.md`, `services/api/CLAUDE.md`). Nested files
   load only when Claude reads files in that subtree — saves tokens at
   session start. See the claude-md-architect skill, Mode 4.

2. Reference a separate file with @path syntax (e.g. `@docs/architecture.md`).
   Imported files load alongside this one at launch, so this does NOT
   save tokens — it only improves organization.

3. Extract to a referenced file linked from "Where things live"
   (e.g. `See docs/architecture.md`). Claude reads on demand only when
   asked. This DOES save tokens but loses automatic loading.

Update protocol: every section is append-only in spirit. Lessons go
into "Non-negotiable invariants" — never delete an invariant, only
clarify it. PRs that change this file get reviewed like code.
-->

## What this codebase is

<!--
2-4 sentences. Concrete. Name the business domain, the runtime shape,
and the upstream/downstream systems. A new engineer should know what
this thing does after reading this section.

Example:
SGEN batch pipeline that consumes NCBS Kafka events, applies GL
posting rules under MAS AIRG controls, and writes posted journals
to OFPC tables. Upstream: NCBS topic `ncbs.gl.events`. Downstream:
OFPC MariaDB. Runs nightly under Airflow.
-->

[fill in]

**Project type:** [pick one — used by `/spec` to default scope]
<!--
- `backend-only`   — pure backend service or pipeline. /spec defaults to backend-only scope.
- `frontend-only`  — pure UI. /spec defaults to frontend-only scope.
- `full-stack`     — has both backend and frontend; cross-stack work is common.
                     /spec asks scope per ticket, defaulting to full-stack for any work
                     that touches API surfaces or events.
- `library`        — a library or SDK consumed by other projects. Contract surface is
                     the public API; /spec treats every public-API change as full-stack
                     and recommends /contract.
-->

<!--
The next three fields are read by /contract. Omit them entirely if Project type
is backend-only or frontend-only AND you never expect to use /contract.
-->

**Backend language:** [one of: `python`, `java`, `typescript`, `go`, or `none`]
<!-- /contract uses this to choose backend type file extensions and shapes. -->

**Frontend language:** [one of: `typescript`, `javascript`, or `none`]
<!-- /contract uses this to choose frontend type file extensions and shapes. -->

**Contract pair name:** [e.g. `web-client / notifications-service`]
<!-- /contract uses this to name the consumer and provider in generated Pact stubs.
     Format: `<consumer> / <provider>`. Omit if no HTTP endpoints are in scope. -->

## Non-negotiable invariants

<!--
The hard rules. Things that, if violated, break the system, the
audit trail, or the regulatory posture. Append-only. Every entry
should be traceable to a real incident, regulation, or design
decision — not aspirational hygiene.

Format: short imperative, optionally with a §ref or incident ID.
-->

- [fill in — e.g. "Multi-character delimiters use `~|~`, never `|`. §ref:DELIM-001"]
- [fill in — e.g. "All Kafka consumers handle recoverable vs unrecoverable error tiers explicitly. §ref:KAFKA-ERR-001"]
- [fill in — e.g. "Never delete rows from audit tables (`audit_*`). Soft-delete only."]

## Conventions worth following

<!--
The softer "we usually do it this way" guidance. Violations here are
discussable, not blocking. Keep this short — if a convention matters
enough to enforce, promote it to an invariant.
-->

- [fill in — e.g. "Type hints required on all public functions"]
- [fill in — e.g. "Tests colocated with code under `tests/` mirroring `src/`"]
- [fill in — e.g. "Use `§ref:` comments to link code to spec sections"]

## How to verify work is done

<!--
The mechanical checks that prove a change is complete. If a human
can run these and the result is green, the work is done. No
judgment calls.
-->

- [fill in — e.g. "`pytest tests/` passes"]
- [fill in — e.g. "`mypy src/` clean"]
- [fill in — e.g. "`ruff check src/` clean"]
- [fill in — e.g. "New code in `src/` has a corresponding spec in `specs/`"]

## Where things live

<!--
A short map of the repo. Optional but high-value for AI assistance —
Claude works much better when it knows the layout up front and
doesn't have to discover it.
-->

- `src/` — production code
- `tests/` — test code, mirrors src/
- `specs/` — spec files for non-trivial changes (see `/spec` command)
- `runbooks/` — operational procedures
- [fill in others]

## Domain glossary

<!--
Acronyms and project-specific terms a new engineer (or an AI) won't
know. Keep entries to one line.
-->

- [fill in — e.g. "NCBS — New Core Banking System, upstream of SGEN"]
- [fill in — e.g. "OFPC — Output Financial Posting Cache, downstream"]
- [fill in — e.g. "§ref — traceability comment linking code to spec"]

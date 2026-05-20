# Auto-lessons: continual learning loop

**Ticket:** none
**Status:** draft
**Scope:** library (tooling) — no runtime API surface; the shared interface is the ledger event vocabulary in "Ledger event surface" below
**Created:** 2026-05-20

<!--
Brainstormed via superpowers:brainstorming. Ports the automatic-capture half
of the Hermes-agent / auto-didact learning loop into specship, feeding the
existing deliberate /encode-lesson promotion path. No Contract-surface section:
this repo has no runtime HTTP/event API (see CLAUDE.md). The ledger event
vocabulary is the cross-command interface and is specified explicitly.
-->

## Intent

specship already has the *deliberate promotion* half of a learning loop: `/encode-lesson`
takes a `closed-resolved` investigation and, with human approval, writes a checkable
invariant into CLAUDE.md (or a skill's gotchas, or a command prompt). It is conservative
by design — high bar, anti-bloat guardrails, audit-trail-first.

What specship lacks is the *automatic capture* half. The everyday learnings — the user
correcting Claude mid-`/work` ("no, not that"), confirming an approach ("yes, exactly,
keep doing that"), or stating a preference — evaporate today because they never rise to a
formal investigation and so can never reach `/encode-lesson`.

This feature adds that capture half plus a curator and a review affordance, all
ledger-native, **without** weakening specship's discipline: captured lessons land in a
*candidate buffer* (the ledger), never directly in CLAUDE.md. Only the existing
human-gated `/encode-lesson` promotes a candidate into a durable invariant.

The loop:

```
SessionEnd hook ─┐
                 ├─→ /capture-lessons → lesson_candidate events   (capture; in-session; LLM)
end of /work,    ─┘        │
/ship, /fix                │
                           ▼
   hourly cron → curate.py → cluster + decay + digest             (curator; NO LLM)
                           │
                           ▼
              /review-lessons → promote │ dismiss                 (review; human-gated)
                                   │ promote
                                   ▼
        /encode-lesson --from-candidate → CLAUDE.md invariant     (existing machinery)
```

## Acceptance criteria

### Capture (`/capture-lessons`)
- [ ] New command `dist/commands/capture-lessons.md` (recommended-model: sonnet) scans the
      current/just-ended session for: user corrections, confirmed approaches, stated
      preferences, and decisions that surprised the user.
- [ ] Emits at most 3 `lesson_candidate` ledger events per session (matches the
      `/encode-lesson` "max 3 from one source" rule).
- [ ] Each candidate carries an invariant-form draft, a `lesson_type`, a short
      `evidence_quote`, `source_command`, `source_artifact`, and a `confidence`.
- [ ] Refuses to capture motherhood statements — reuses `/encode-lesson`'s "is it
      checkable?" test. A non-checkable observation is dropped, not stored.
- [ ] **Idempotent per session:** before capturing, queries the ledger for existing
      `lesson_candidate` events with the same `session_id`; if any exist, it dedupes
      (does not emit a near-duplicate of an already-captured candidate). This matters
      because BOTH the SessionEnd hook and the `/work`/`/ship`/`/fix` end-step can fire
      for the same session.
- [ ] Runs in two ways: (a) automatically via a SessionEnd hook wired into the host's
      `.claude/settings.json` by `install.sh` (covers all sessions); (b) as an appended
      capture stage at the end of `/work`, `/ship`, and `/fix` (covers the high-signal
      commands even when the host did not wire the hook).

### Curator (`dist/lessons/curate.py`, hourly, NO LLM)
- [ ] Pure-Python, deterministic, no network and no model calls. Reads the committed
      ledger JSONL, projects candidate statuses.
- [ ] Decays candidates older than `lessons.decay_days` (default 30) that have no terminal
      event (`lesson_promoted` / `lesson_dismissed`) by emitting `lesson_decayed`.
- [ ] Clusters pending candidates by `lesson_type` + token-overlap heuristic. When a
      cluster size reaches `lessons.cluster_threshold` (default 3), names the theme in the
      digest as a *suggestion* to consolidate (it never consolidates anything itself).
- [ ] Emits one `lessons_curated` digest event per run with `candidates_seen`, `clusters`,
      `decayed_ids`, and a human-readable `digest_text`.
- [ ] Scheduling is host-managed: `dist/lessons/curate.sh` is a thin wrapper; `install.sh
      --with-cron` appends the hourly crontab line, otherwise `install.sh` prints the
      suggested one-liner for the user to add manually.

### Review (`/review-lessons`)
- [ ] New command `dist/commands/review-lessons.md` (recommended-model: sonnet) mirrors
      `/review-decisions`: surfaces pending candidates (status folded from the ledger),
      grouped by the curator's clusters when available.
- [ ] For each candidate the user can: **promote** (hands off to
      `/encode-lesson --from-candidate <id>`), **dismiss** (emits `lesson_dismissed` with a
      reason), or leave pending.
- [ ] Append-only: review never deletes candidate events; verdicts are layered as new
      events, exactly as `/review-decisions` layers `decision_reviewed`.

### Promotion (`/encode-lesson` extension)
- [ ] `dist/commands/encode-lesson.md` accepts a new `--from-candidate <candidate_id>`
      input source. When present, it reads the candidate's `lesson_candidate` event instead
      of requiring a `closed-resolved` investigation file.
- [ ] All existing `/encode-lesson` guardrails remain intact for the candidate path:
      human approval gate, checkable-only, ≤200-line CLAUDE.md ceiling, ≤3 lessons,
      duplicate-invariant refusal.
- [ ] On successful promotion it emits `lesson_promoted` (linking `candidate_id` →
      the encoded `lesson_id` and `destination_path`) in addition to the existing
      `lesson_encoded` event.

## Ledger event surface

These five new event types are the cross-command interface. They are appended to the
committed JSONL log; the SQLite index is rebuildable. `specship_ledger.py` must register
each type and its projecting fields.

```
lesson_candidate
  candidate_id      str   # stable short hash of (lesson_text + session_id)
  lesson_text       str   # invariant-form draft, < 30 words
  lesson_type       str   # architectural | module-specific | tooling | command-specific | preference
  evidence_quote    str   # short verbatim quote from the session that triggered it
  source_command    str   # e.g. "/work", "/fix", "session-end-hook"
  source_artifact   str   # spec/fix path if applicable, else ""
  confidence        str   # high | medium | low
  session_id        str

lesson_dismissed
  candidate_id      str
  reason            str
  session_id        str

lesson_promoted
  candidate_id      str
  lesson_id         str   # the /encode-lesson stable hash of the encoded invariant
  destination_path  str   # where the invariant was written
  session_id        str

lesson_decayed
  candidate_id      str
  age_days          int
  run_id            str   # the curator run that decayed it

lessons_curated
  run_id            str
  candidates_seen   int
  clusters          json  # [{theme, candidate_ids[]}]
  decayed_ids       json  # [candidate_id, ...]
  digest_text       str
```

**Status projection.** A candidate's current status is folded from its events:
`captured` (a `lesson_candidate` with no terminal event) → terminal `{promoted | dismissed
| decayed}`. `/review-lessons` shows `captured`-only as "pending". This is the same
fold pattern `/review-decisions` uses for `decision_reviewed`.

## Non-goals

- **No auto-write to CLAUDE.md.** Candidates never become invariants without the
  human-gated `/encode-lesson`. This is the single most important boundary — it preserves
  specship's conservative invariant discipline.
- **No LLM in the curator.** Clustering is a heuristic (type + token overlap); decay is
  age arithmetic. Keeps the hourly job cheap, portable, deterministic, and testable.
- **No daemon shipped by specship.** Scheduling is the host's cron. specship ships the
  script and the suggested crontab line; it does not run a background process itself.
- **No new storage spine.** Candidates live in the existing ledger, not a separate store.
- **No transcript re-scanning by the hourly job.** Capture happens only in-session (where
  the transcript is in-context). The curator operates purely on already-captured
  candidate events.
- **No change to `/encode-lesson`'s investigation path.** The investigation-sourced flow is
  untouched; `--from-candidate` is an additive second source.
- **No retroactive enforcement.** Promoted invariants apply going forward; existing drift
  is surfaced by `/check`, not auto-fixed here.

## Invariants

- A `lesson_candidate` is never edited or deleted; its lifecycle is expressed only by
  appended terminal events. (Ledger is append-only.)
- `/capture-lessons` is idempotent per `session_id` — re-running it on a session that
  already has candidates does not create near-duplicates.
- The curator (`curate.py`) makes no network calls and invokes no model. A run with no
  pending candidates is a no-op that still emits `lessons_curated` with `candidates_seen: 0`.
- `dist/` remains the source of truth; `.claude/` is re-synced and `verify-sync.sh` must
  pass at commit time.
- No new file under `dist/` exceeds 500 lines without a documented reason. If
  `curate.py` or a command body approaches the limit, detail moves into a `references/`
  file or `dist/lessons/HOW-IT-WORKS.md`.
- New commands carry a `recommended-model` frontmatter field (sonnet for both
  `/capture-lessons` and `/review-lessons`).

## Files likely to change

### New
- `dist/commands/capture-lessons.md` — capture command prompt
- `dist/commands/review-lessons.md` — review command prompt
- `dist/lessons/curate.py` — hourly LLM-free curator (decay + cluster + digest)
- `dist/lessons/curate.sh` — thin cron wrapper (`set -euo pipefail`)
- `dist/lessons/HOW-IT-WORKS.md` — author/operator doc for the loop
- `dist/hooks/session-end-capture.json` — settings.json snippet (`SessionEnd → /capture-lessons`) that install.sh merges into the host config

### Modified
- `dist/commands/encode-lesson.md` — add the `--from-candidate <id>` input source + the `lesson_promoted` ledger event
- `dist/ledger/specship_ledger.py` — register the five new event types and their projecting fields
- `dist/ledger/HOW-TO-LOG.md` — document the new events under per-command sections for `/capture-lessons`, `/review-lessons`, and the curator
- `scripts/install.sh` — scaffold `.specship/lessons/`, copy `dist/lessons/*`, optionally wire the SessionEnd hook + cron (`--with-cron`), and print the manual crontab one-liner otherwise
- `CLAUDE.md` (specship's own) — add `dist/lessons/` and the new commands to "Where things live"; add the new `lessons.*` config keys to the glossary
- `CHANGELOG.md` — new version entry describing the auto-lessons loop
- `.claude/` — regenerated copy of all changed `dist/` files (via `scripts/sync-local.sh`)

### Generated (do not hand-edit)
- `.specship/ledger/index.db` — rebuilt from JSONL; never committed

## Tests required

- `python3 -c "import py_compile; py_compile.compile('dist/lessons/curate.py', doraise=True)"` — curator syntax
- `bash -n dist/lessons/curate.sh` — wrapper syntax
- Fixture test: feed `curate.py` a synthetic ledger containing `lesson_candidate` events of
  varying ages and types; assert (a) candidates older than `decay_days` with no terminal
  event are decayed, (b) candidates with a terminal event are NOT decayed, (c) a cluster of
  ≥`cluster_threshold` same-type overlapping candidates appears in the digest, (d) a run
  with zero pending candidates emits `lessons_curated` with `candidates_seen: 0` and
  performs no decay.
- Ledger smoke test extended: `specship_ledger.py log lesson_candidate ...` then
  `rebuild-index` succeeds and the new event projects its fields.
- Idempotency test: simulate two `/capture-lessons` runs on the same `session_id` (via the
  ledger query the command relies on) and assert the second run would dedupe — expressed as
  a unit test of the dedup query/helper, since the command body itself is an LLM prompt.
- Markdown well-formedness on `dist/commands/capture-lessons.md`,
  `dist/commands/review-lessons.md`, `dist/lessons/HOW-IT-WORKS.md` (no broken links to
  non-existent reference files).
- `scripts/verify-sync.sh` passes after `.claude/` is re-synced.

## Open questions

1. **Cluster heuristic detail.** Token-overlap (Jaccard over normalized tokens) vs. shared
   `source_artifact` vs. both. Default proposal: group by `lesson_type`, then within a type
   merge candidates whose normalized-token Jaccard ≥ 0.5. Tunable via `lessons.cluster_*`
   config. Resolve during implementation against the fixture.
2. **SessionEnd hook payload.** Confirm Claude Code's `SessionEnd` hook can invoke a slash
   command (`type: prompt`, `prompt: "/capture-lessons"`) the way auto-didact does, and that
   the just-ended transcript is available to that final turn. If not available in the host's
   Claude Code version, the `/work`/`/ship`/`/fix` end-step path still provides coverage.
3. **Confidence usage.** Whether `/review-lessons` should hide `low`-confidence candidates by
   default or just sort them last. Default proposal: show all, sort by confidence desc, and
   let `--min-confidence` filter.

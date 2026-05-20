# Auto-lessons — how the continual-learning loop works

specship learns from finished sessions without anyone having to remember to write things
down, while keeping the conservative discipline of `/encode-lesson` intact.

## The loop

1. **Capture** (`/capture-lessons`, model: sonnet) — runs automatically at SessionEnd (via a
   hook the installer wires into `.claude/settings.json`) and at the end of `/work`, `/ship`,
   `/fix`. Scans the session for corrections, confirmed approaches, preferences, and
   surprising decisions; records ≤3 `lesson_candidate` events. Idempotent per session.
2. **Curate** (`.specship/lessons/curate.sh`, hourly cron, NO model) — decays candidates older
   than `--decay-days` (default 30) that were never actioned, clusters similar pending
   candidates by type + token overlap, and emits a `lessons_curated` digest. Pure stdlib,
   deterministic, offline.
3. **Review** (`/review-lessons`, model: sonnet) — surfaces pending candidates; you promote,
   dismiss, or skip each.
4. **Promote** (`/encode-lesson --from-candidate <id>`) — the existing human-gated path that
   writes a durable invariant into CLAUDE.md (or a skill/command), with all its anti-bloat
   guardrails.

## Why candidates never touch CLAUDE.md directly

CLAUDE.md is the constitution; every invariant there is read on every future session. If
capture wrote there directly it would bloat instantly. Candidates are a staging buffer; only
the deliberate, human-gated `/encode-lesson` promotes them. The buffer self-cleans via decay.

## Storage

Everything is ledger-native (`.specship/ledger/events.jsonl`). Candidate status
(`captured → promoted | dismissed | decayed`) is folded into the `lesson_candidates` table by
`specship_ledger.py`. There is no separate store.

## Config knobs (curator CLI flags)

- `--decay-days N` (default 30) — age after which an un-actioned candidate decays.
- `--cluster-threshold N` (default 3) — cluster size that earns a consolidation suggestion.
- `--jaccard F` (default 0.5) — token-overlap threshold for clustering within a type.

## Verifying the install

```bash
python3 .specship/lessons/selftest.py   # ALL PASS
```

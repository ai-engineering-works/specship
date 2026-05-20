# Auto-lessons Continual-Learning Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the automatic-capture half of a learning loop to specship — capture lesson candidates from finished sessions, curate them hourly (LLM-free), review them, and promote the worthy ones into CLAUDE.md via the existing `/encode-lesson`.

**Architecture:** Everything is ledger-native. Capture commands emit `lesson_candidate` events; the ledger projects them (with folded status) into a new `lesson_candidates` table exactly as it already folds `decision_reviewed` verdicts onto `decisions`. Testable projection + curation logic lives in two stdlib-only Python helpers (`lessons_query.py`, `curate.py`); the command prompts (`.md`) stay thin and shell out to those helpers. No daemon, no model calls in the curator, no auto-write to CLAUDE.md.

**Tech Stack:** Python 3 stdlib only (sqlite3, json, argparse, hashlib, difflib), bash 4+, the existing `dist/ledger/specship_ledger.py`. No pytest — tests are a stdlib `selftest.py` runner over synthetic fixtures, matching specship's `contract_hash.py` / `coverage-check.py` convention.

**Spec reference:** `specs/2026-05-20-auto-lessons-continual-learning.md`.

**Repo conventions that bind this plan:**
- `dist/` is the source of truth; `.claude/` is a generated copy. After editing `dist/`, run `./scripts/sync-local.sh`, and `./scripts/verify-sync.sh` must pass. Commit `dist/` AND `.claude/` together.
- No file under `dist/` exceeds 500 lines without a documented reason.
- New commands carry a `recommended-model` frontmatter field.
- Commits touching `dist/` must reference a spec/fix or the pre-commit Wall blocks them. Reference `specs/2026-05-20-auto-lessons-continual-learning.md` in every dist-touching commit.
- The ledger JSONL (`events.jsonl`) is committed; the SQLite index (`index.db`) is rebuildable and gitignored.

---

## File Structure

**New (all under `dist/`, the source of truth):**

| Path | Responsibility |
|---|---|
| `dist/lessons/lessons_query.py` | Stdlib projection helpers over the ledger index: `pending_candidates()`, `candidate_status(id)`, `session_has_candidates(session_id)`. The single DRY home for candidate-projection logic; imported by `curate.py` and shelled-to by the command prompts. |
| `dist/lessons/curate.py` | LLM-free hourly curator: decay (age arithmetic) + cluster (type + token-overlap Jaccard) + emit `lessons_curated` digest. Imports `lessons_query`. |
| `dist/lessons/curate.sh` | Thin `set -euo pipefail` cron wrapper that locates the repo root and runs `curate.py`. |
| `dist/lessons/selftest.py` | Stdlib fixture-driven self-test for `lessons_query.py` + `curate.py`. Builds a synthetic ledger in a temp dir, asserts decay/cluster/dedup behavior. Runnable via `python3 dist/lessons/selftest.py`. |
| `dist/lessons/HOW-IT-WORKS.md` | Operator/author doc for the loop. |
| `dist/commands/capture-lessons.md` | Capture command prompt (sonnet). |
| `dist/commands/review-lessons.md` | Review command prompt (sonnet). |
| `dist/hooks/session-end-capture.json` | `SessionEnd → /capture-lessons` settings.json snippet that `install.sh` merges into the host config. |

**Modified:**

| Path | Change |
|---|---|
| `dist/ledger/specship_ledger.py` | Register 5 new event types; add `lesson_candidates` table to `SCHEMA_SQL`; add 5 `index_event` branches. |
| `dist/ledger/HOW-TO-LOG.md` | Document the new events under new `/capture-lessons`, `/review-lessons`, and curator sections. |
| `dist/commands/encode-lesson.md` | Add `--from-candidate <id>` input source + emit `lesson_promoted`. |
| `scripts/install.sh` | Scaffold `.specship/lessons/`, copy `dist/lessons/*`, optional `--with-cron` + SessionEnd hook wiring, print manual crontab one-liner otherwise. |
| `CLAUDE.md` | Add `dist/lessons/` + new commands to "Where things live"; add verify steps; add `lessons.*` to glossary. |
| `CHANGELOG.md` | New version entry. |
| `.claude/**` | Regenerated via `sync-local.sh`. |

---

## Tasks

### Task 1 — Ledger: register event types + `lesson_candidates` table

**Files:**
- Modify: `dist/ledger/specship_ledger.py`

- [ ] **Step 1: Add the 5 event types to `KNOWN_EVENT_TYPES`**

In `dist/ledger/specship_ledger.py`, find the `KNOWN_EVENT_TYPES` set (ends around the `qa_waiver_granted` entry). Add before the closing brace:

```python
    "lesson_candidate",         # /capture-lessons recorded a lesson candidate
    "lesson_dismissed",         # /review-lessons rejected a candidate
    "lesson_promoted",          # a candidate was promoted via /encode-lesson --from-candidate
    "lesson_decayed",           # curate.py expired an un-actioned candidate
    "lessons_curated",          # curate.py completed a curator run
```

- [ ] **Step 2: Add the `lesson_candidates` table to `SCHEMA_SQL`**

In the `SCHEMA_SQL` string, after the existing `lessons` table block (the `CREATE INDEX ... ix_lessons_investigation` line), add:

```sql
CREATE TABLE IF NOT EXISTS lesson_candidates (
    candidate_id     TEXT PRIMARY KEY,
    ts               TEXT NOT NULL,
    session_id       TEXT,
    lesson_text      TEXT,
    lesson_type      TEXT,
    evidence_quote   TEXT,
    source_command   TEXT,
    source_artifact  TEXT,
    confidence       TEXT,
    status           TEXT,    -- 'captured' | 'promoted' | 'dismissed' | 'decayed'
    terminal_ts      TEXT,    -- when it left 'captured'
    terminal_detail  TEXT     -- reason (dismissed) | lesson_id (promoted) | run_id (decayed)
);

CREATE INDEX IF NOT EXISTS ix_lesson_cand_status ON lesson_candidates(status);
CREATE INDEX IF NOT EXISTS ix_lesson_cand_session ON lesson_candidates(session_id);
CREATE INDEX IF NOT EXISTS ix_lesson_cand_type ON lesson_candidates(lesson_type);
```

- [ ] **Step 3: Add `index_event` branches for the 5 types**

In `index_event(...)`, after the `elif et == "lesson_encoded":` block (ends at the `)` closing that `conn.execute`), add:

```python
    elif et == "lesson_candidate":
        conn.execute(
            "INSERT INTO lesson_candidates "
            "(candidate_id, ts, session_id, lesson_text, lesson_type, "
            " evidence_quote, source_command, source_artifact, confidence, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'captured') "
            "ON CONFLICT(candidate_id) DO NOTHING",
            (
                event.get("candidate_id"), ts, session_id,
                event.get("lesson_text"), event.get("lesson_type"),
                event.get("evidence_quote"), event.get("source_command"),
                event.get("source_artifact"), event.get("confidence"),
            ),
        )
    elif et == "lesson_dismissed":
        conn.execute(
            "INSERT INTO lesson_candidates (candidate_id, ts, status, terminal_ts, terminal_detail) "
            "VALUES (?, ?, 'dismissed', ?, ?) "
            "ON CONFLICT(candidate_id) DO UPDATE SET "
            "  status = 'dismissed', terminal_ts = excluded.terminal_ts, "
            "  terminal_detail = excluded.terminal_detail",
            (event.get("candidate_id"), ts, ts, event.get("reason")),
        )
    elif et == "lesson_promoted":
        conn.execute(
            "INSERT INTO lesson_candidates (candidate_id, ts, status, terminal_ts, terminal_detail) "
            "VALUES (?, ?, 'promoted', ?, ?) "
            "ON CONFLICT(candidate_id) DO UPDATE SET "
            "  status = 'promoted', terminal_ts = excluded.terminal_ts, "
            "  terminal_detail = excluded.terminal_detail",
            (event.get("candidate_id"), ts, ts, event.get("lesson_id")),
        )
    elif et == "lesson_decayed":
        conn.execute(
            "INSERT INTO lesson_candidates (candidate_id, ts, status, terminal_ts, terminal_detail) "
            "VALUES (?, ?, 'decayed', ?, ?) "
            "ON CONFLICT(candidate_id) DO UPDATE SET "
            "  status = 'decayed', terminal_ts = excluded.terminal_ts, "
            "  terminal_detail = excluded.terminal_detail",
            (event.get("candidate_id"), ts, ts, event.get("run_id")),
        )
    elif et == "lessons_curated":
        # Digest event — kept in the events table only (no projection table).
        pass
```

Note the terminal branches use `INSERT ... ON CONFLICT DO UPDATE` so a verdict still lands even if the originating `lesson_candidate` hasn't been indexed yet (partial rebuild), mirroring the existing `decision_reviewed` stub pattern.

- [ ] **Step 4: Verify the module compiles**

Run: `python3 -c "import py_compile; py_compile.compile('dist/ledger/specship_ledger.py', doraise=True)"`
Expected: no output (success).

- [ ] **Step 5: Smoke-test the new events end-to-end**

```bash
cd "$(mktemp -d)" && git init -q && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py log lesson_candidate \
    candidate_id='"abc1234"' lesson_text='"Always pin dtype on big CSVs"' \
    lesson_type='"tooling"' confidence='"high"' session_id='"s1"' --quiet && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py rebuild-index && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py query \
    "SELECT candidate_id, status FROM lesson_candidates"
```
Expected: prints a row `abc1234 | captured` (or equivalent). Then in the same temp dir:

```bash
python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py log lesson_dismissed \
    candidate_id='"abc1234"' reason='"duplicate"' --quiet && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py rebuild-index && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py query \
    "SELECT candidate_id, status, terminal_detail FROM lesson_candidates"
```
Expected: `abc1234 | dismissed | duplicate`.

- [ ] **Step 6: Commit**

```bash
git add dist/ledger/specship_ledger.py
git commit -m "feat(ledger): lesson_candidate event types + projection (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 2 — `lessons_query.py` projection helpers

**Files:**
- Create: `dist/lessons/lessons_query.py`
- Create: `dist/lessons/selftest.py` (first assertions)

- [ ] **Step 1: Write the failing self-test**

Create `dist/lessons/selftest.py`:

```python
#!/usr/bin/env python3
"""Stdlib self-test for the auto-lessons helpers. Run: python3 dist/lessons/selftest.py

Builds a synthetic specship ledger in a temp dir, exercises lessons_query.py
and curate.py against it, and asserts behavior. No pytest, no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE.parent / "ledger" / "specship_ledger.py"


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _write_events(ledger_dir: Path, events: list[dict]) -> None:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    with open(ledger_dir / "events.jsonl", "w", encoding="utf-8") as f:
        for i, e in enumerate(events):
            e.setdefault("event_id", f"evt{i}")
            f.write(json.dumps(e) + "\n")


def _rebuild(repo: Path) -> None:
    subprocess.run([sys.executable, str(LEDGER), "rebuild-index"], cwd=repo, check=True,
                   capture_output=True)


def test_pending_candidates_excludes_terminal():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".git").mkdir()
        ledger_dir = repo / ".specship" / "ledger"
        _write_events(ledger_dir, [
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "c1",
             "lesson_text": "L1", "lesson_type": "tooling", "session_id": "s1", "confidence": "high"},
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "c2",
             "lesson_text": "L2", "lesson_type": "tooling", "session_id": "s1", "confidence": "low"},
            {"ts": _iso(0), "event_type": "lesson_dismissed", "candidate_id": "c2", "reason": "noise"},
        ])
        _rebuild(repo)
        sys.path.insert(0, str(HERE))
        import lessons_query
        pending = lessons_query.pending_candidates(repo)
        ids = {c["candidate_id"] for c in pending}
        assert ids == {"c1"}, f"expected only c1 pending, got {ids}"
        print("PASS test_pending_candidates_excludes_terminal")


def test_session_has_candidates():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".git").mkdir()
        ledger_dir = repo / ".specship" / "ledger"
        _write_events(ledger_dir, [
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "c1",
             "lesson_text": "L1", "lesson_type": "tooling", "session_id": "sX", "confidence": "high"},
        ])
        _rebuild(repo)
        sys.path.insert(0, str(HERE))
        import lessons_query
        assert lessons_query.session_has_candidates(repo, "sX") is True
        assert lessons_query.session_has_candidates(repo, "sY") is False
        print("PASS test_session_has_candidates")


def main() -> int:
    test_pending_candidates_excludes_terminal()
    test_session_has_candidates()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the self-test to verify it fails**

Run: `python3 dist/lessons/selftest.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'lessons_query'`.

- [ ] **Step 3: Write `lessons_query.py`**

Create `dist/lessons/lessons_query.py`:

```python
#!/usr/bin/env python3
"""Projection helpers over the specship ledger's lesson_candidates table.

The single DRY home for candidate-projection logic. Imported by curate.py and
shelled-to by the /capture-lessons and /review-lessons command prompts.

CLI:
  python3 lessons_query.py pending [--min-confidence LEVEL]   # JSON list of pending candidates
  python3 lessons_query.py has-candidates <session_id>        # prints "yes"/"no"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _repo_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    while p != p.parent:
        if (p / ".git").exists() or (p / ".specship").exists():
            return p
        p = p.parent
    return (start or Path.cwd()).resolve()


def _db(repo: Path) -> sqlite3.Connection:
    db = repo / ".specship" / "ledger" / "index.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def pending_candidates(repo: Path | None = None, min_confidence: str | None = None) -> list[dict]:
    """All candidates still in 'captured' status, sorted by confidence desc then ts."""
    repo = repo or _repo_root()
    conn = _db(repo)
    rows = conn.execute(
        "SELECT candidate_id, ts, session_id, lesson_text, lesson_type, "
        "       evidence_quote, source_command, source_artifact, confidence "
        "FROM lesson_candidates WHERE status = 'captured'"
    ).fetchall()
    conn.close()
    out = [dict(r) for r in rows]
    floor = _CONFIDENCE_RANK.get(min_confidence or "", 0)
    if floor:
        out = [c for c in out if _CONFIDENCE_RANK.get(c.get("confidence") or "", 0) >= floor]
    out.sort(key=lambda c: (-_CONFIDENCE_RANK.get(c.get("confidence") or "", 0), c.get("ts") or ""))
    return out


def candidate_status(repo: Path | None, candidate_id: str) -> str | None:
    repo = repo or _repo_root()
    conn = _db(repo)
    row = conn.execute(
        "SELECT status FROM lesson_candidates WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    conn.close()
    return row["status"] if row else None


def session_has_candidates(repo: Path | None, session_id: str) -> bool:
    repo = repo or _repo_root()
    conn = _db(repo)
    row = conn.execute(
        "SELECT 1 FROM lesson_candidates WHERE session_id = ? LIMIT 1", (session_id,)
    ).fetchone()
    conn.close()
    return row is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_pending = sub.add_parser("pending")
    p_pending.add_argument("--min-confidence", default=None)
    p_has = sub.add_parser("has-candidates")
    p_has.add_argument("session_id")
    args = ap.parse_args()

    if args.cmd == "pending":
        print(json.dumps(pending_candidates(min_confidence=args.min_confidence), indent=2))
    elif args.cmd == "has-candidates":
        print("yes" if session_has_candidates(None, args.session_id) else "no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the self-test to verify it passes**

Run: `python3 dist/lessons/selftest.py`
Expected: `PASS test_pending_candidates_excludes_terminal`, `PASS test_session_has_candidates`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add dist/lessons/lessons_query.py dist/lessons/selftest.py
git commit -m "feat(lessons): projection helpers + self-test harness (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 3 — Curator: decay logic

**Files:**
- Create: `dist/lessons/curate.py` (decay only; clustering added in Task 4)
- Modify: `dist/lessons/selftest.py` (add decay assertions)

- [ ] **Step 1: Add the failing decay self-test**

Append to `dist/lessons/selftest.py`, before `def main()`:

```python
def test_decay_expires_old_pending_only():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".git").mkdir()
        ledger_dir = repo / ".specship" / "ledger"
        _write_events(ledger_dir, [
            # old + pending -> should decay
            {"ts": _iso(40), "event_type": "lesson_candidate", "candidate_id": "old",
             "lesson_text": "old one", "lesson_type": "tooling", "session_id": "s1", "confidence": "low"},
            # old + already dismissed -> must NOT decay
            {"ts": _iso(40), "event_type": "lesson_candidate", "candidate_id": "olddone",
             "lesson_text": "done", "lesson_type": "tooling", "session_id": "s1", "confidence": "low"},
            {"ts": _iso(39), "event_type": "lesson_dismissed", "candidate_id": "olddone", "reason": "x"},
            # recent + pending -> must NOT decay
            {"ts": _iso(2), "event_type": "lesson_candidate", "candidate_id": "fresh",
             "lesson_text": "fresh", "lesson_type": "tooling", "session_id": "s1", "confidence": "high"},
        ])
        _rebuild(repo)
        sys.path.insert(0, str(HERE))
        import importlib, curate
        importlib.reload(curate)
        result = curate.run(repo, decay_days=30, cluster_threshold=3, jaccard=0.5)
        _rebuild(repo)
        import lessons_query
        statuses = {c_id: lessons_query.candidate_status(repo, c_id)
                    for c_id in ("old", "olddone", "fresh")}
        assert statuses["old"] == "decayed", statuses
        assert statuses["olddone"] == "dismissed", statuses
        assert statuses["fresh"] == "captured", statuses
        assert "old" in result["decayed_ids"], result
        print("PASS test_decay_expires_old_pending_only")
```

And add `test_decay_expires_old_pending_only()` to `main()` before the `print("\nALL PASS")` line.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 dist/lessons/selftest.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate'`.

- [ ] **Step 3: Write `curate.py` with decay logic**

Create `dist/lessons/curate.py`:

```python
#!/usr/bin/env python3
"""LLM-free hourly curator for auto-lessons.

Reads the specship ledger, decays stale un-actioned candidates, clusters
pending candidates by type + token overlap, and emits a lessons_curated
digest event. No network, no model calls, deterministic.

CLI:
  python3 curate.py [--decay-days N] [--cluster-threshold N] [--jaccard F]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lessons_query  # noqa: E402

LEDGER = HERE.parent / "ledger" / "specship_ledger.py"


def _repo_root(start: Path | None = None) -> Path:
    return lessons_query._repo_root(start)


def _age_days(ts: str) -> float:
    try:
        then = datetime.fromisoformat(ts)
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400.0


def _log(repo: Path, event_type: str, **fields) -> None:
    args = [sys.executable, str(LEDGER), "log", event_type]
    for k, v in fields.items():
        args.append(f"{k}={json.dumps(v)}")
    args.append("--quiet")
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


def run(repo: Path | None = None, *, decay_days: int = 30,
        cluster_threshold: int = 3, jaccard: float = 0.5) -> dict:
    repo = repo or _repo_root()
    run_id = str(uuid.uuid4())[:8]
    pending = lessons_query.pending_candidates(repo)

    # --- decay ---
    decayed_ids: list[str] = []
    for c in pending:
        if _age_days(c.get("ts") or "") > decay_days:
            _log(repo, "lesson_decayed", candidate_id=c["candidate_id"],
                 age_days=int(_age_days(c.get("ts") or "")), run_id=run_id)
            decayed_ids.append(c["candidate_id"])

    # survivors after decay are the cluster input
    survivors = [c for c in pending if c["candidate_id"] not in decayed_ids]
    clusters = _cluster(survivors, cluster_threshold, jaccard)

    digest = _digest_text(len(pending), decayed_ids, clusters)
    _log(repo, "lessons_curated", run_id=run_id, candidates_seen=len(pending),
         clusters=clusters, decayed_ids=decayed_ids, digest_text=digest)

    return {"run_id": run_id, "candidates_seen": len(pending),
            "decayed_ids": decayed_ids, "clusters": clusters, "digest_text": digest}


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _cluster(candidates: list[dict], threshold: int, jaccard: float) -> list[dict]:
    """Group same-type candidates whose token-Jaccard >= jaccard. Return clusters of size >= threshold."""
    by_type: dict[str, list[dict]] = {}
    for c in candidates:
        by_type.setdefault(c.get("lesson_type") or "untyped", []).append(c)

    clusters: list[dict] = []
    for ltype, group in by_type.items():
        used: set[str] = set()
        for i, seed in enumerate(group):
            if seed["candidate_id"] in used:
                continue
            members = [seed]
            seed_tok = _tokens(seed.get("lesson_text"))
            for other in group[i + 1:]:
                if other["candidate_id"] in used:
                    continue
                ot = _tokens(other.get("lesson_text"))
                union = seed_tok | ot
                sim = (len(seed_tok & ot) / len(union)) if union else 0.0
                if sim >= jaccard:
                    members.append(other)
            if len(members) >= threshold:
                for m in members:
                    used.add(m["candidate_id"])
                clusters.append({
                    "theme": ltype,
                    "candidate_ids": [m["candidate_id"] for m in members],
                })
    return clusters


def _digest_text(seen: int, decayed: list[str], clusters: list[dict]) -> str:
    lines = [f"Curator run: {seen} pending candidate(s) seen."]
    if decayed:
        lines.append(f"Decayed {len(decayed)} stale candidate(s): {', '.join(decayed)}.")
    for cl in clusters:
        lines.append(
            f"Theme '{cl['theme']}': {len(cl['candidate_ids'])} related candidates "
            f"({', '.join(cl['candidate_ids'])}) — consider one consolidated invariant."
        )
    if not decayed and not clusters:
        lines.append("No decay, no clusters above threshold.")
    return " ".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decay-days", type=int, default=30)
    ap.add_argument("--cluster-threshold", type=int, default=3)
    ap.add_argument("--jaccard", type=float, default=0.5)
    args = ap.parse_args()
    result = run(decay_days=args.decay_days, cluster_threshold=args.cluster_threshold,
                 jaccard=args.jaccard)
    print(result["digest_text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 dist/lessons/selftest.py`
Expected: all prior PASS lines plus `PASS test_decay_expires_old_pending_only`, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add dist/lessons/curate.py dist/lessons/selftest.py
git commit -m "feat(lessons): LLM-free curator decay logic (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 4 — Curator: clustering assertions + `curate.sh` wrapper

**Files:**
- Modify: `dist/lessons/selftest.py` (add clustering + zero-pending assertions)
- Create: `dist/lessons/curate.sh`

- [ ] **Step 1: Add the failing clustering self-tests**

Append to `dist/lessons/selftest.py`, before `def main()`:

```python
def test_cluster_groups_similar_same_type():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".git").mkdir()
        ledger_dir = repo / ".specship" / "ledger"
        # three tooling candidates all about "contract hash mismatch", high overlap
        _write_events(ledger_dir, [
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "h1",
             "lesson_text": "contract hash mismatch blocks work command",
             "lesson_type": "tooling", "session_id": "s1", "confidence": "high"},
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "h2",
             "lesson_text": "contract hash mismatch blocks work again",
             "lesson_type": "tooling", "session_id": "s2", "confidence": "high"},
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "h3",
             "lesson_text": "contract hash mismatch blocks work each time",
             "lesson_type": "tooling", "session_id": "s3", "confidence": "high"},
            # an unrelated preference candidate, different type, must not join
            {"ts": _iso(1), "event_type": "lesson_candidate", "candidate_id": "p1",
             "lesson_text": "user prefers terse commit messages",
             "lesson_type": "preference", "session_id": "s4", "confidence": "medium"},
        ])
        _rebuild(repo)
        sys.path.insert(0, str(HERE))
        import importlib, curate
        importlib.reload(curate)
        result = curate.run(repo, decay_days=30, cluster_threshold=3, jaccard=0.5)
        assert len(result["clusters"]) == 1, result["clusters"]
        cluster = result["clusters"][0]
        assert cluster["theme"] == "tooling"
        assert set(cluster["candidate_ids"]) == {"h1", "h2", "h3"}, cluster
        print("PASS test_cluster_groups_similar_same_type")


def test_zero_pending_is_noop_with_event():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".git").mkdir()
        (repo / ".specship" / "ledger").mkdir(parents=True)
        (repo / ".specship" / "ledger" / "events.jsonl").write_text("")
        _rebuild(repo)
        sys.path.insert(0, str(HERE))
        import importlib, curate
        importlib.reload(curate)
        result = curate.run(repo)
        assert result["candidates_seen"] == 0, result
        assert result["decayed_ids"] == [], result
        assert result["clusters"] == [], result
        print("PASS test_zero_pending_is_noop_with_event")
```

Add both function calls to `main()` before `print("\nALL PASS")`.

- [ ] **Step 2: Run to verify the new tests fail or pass**

Run: `python3 dist/lessons/selftest.py`
Expected: the clustering logic was already written in Task 3, so these should PASS immediately. If `test_cluster_groups_similar_same_type` fails on the Jaccard boundary, inspect the printed similarity — the three `h*` texts share ≥5 of ~7 tokens (Jaccard ≥ 0.6), comfortably above 0.5. If it still fails, the bug is in `_cluster`; fix it in `curate.py` and re-run.

- [ ] **Step 3: Write the cron wrapper `curate.sh`**

Create `dist/lessons/curate.sh`:

```bash
#!/usr/bin/env bash
# curate.sh — hourly auto-lessons curator wrapper (host cron entry point).
#
# Add to crontab for hourly runs:
#   0 * * * * cd /path/to/repo && .specship/lessons/curate.sh >> .specship/lessons/curate.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/curate.py" "$@"
```

Make executable:

```bash
chmod +x dist/lessons/curate.sh
```

- [ ] **Step 4: Verify wrapper syntax + full self-test**

Run: `bash -n dist/lessons/curate.sh && python3 dist/lessons/selftest.py`
Expected: no bash syntax error; `ALL PASS` from the self-test.

- [ ] **Step 5: Commit**

```bash
git add dist/lessons/curate.py dist/lessons/curate.sh dist/lessons/selftest.py
git commit -m "feat(lessons): curator clustering tests + cron wrapper (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 5 — `/capture-lessons` command prompt

**Files:**
- Create: `dist/commands/capture-lessons.md`

- [ ] **Step 1: Write the command prompt**

Create `dist/commands/capture-lessons.md`:

```markdown
---
description: Scan the current/just-ended session for lessons — user corrections, confirmed approaches, stated preferences, and decisions that surprised the user — and record up to 3 as lesson candidates in the ledger. Candidates are NOT invariants; they are reviewed later via /review-lessons and promoted (if worthy) via /encode-lesson. Idempotent per session.
argument-hint: [--session-id <id>] [--source <command>]
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /capture-lessons — Capture Lesson Candidates From a Session

You are scanning a finished (or finishing) session for lessons worth remembering, and
recording each as a *candidate* in the specship ledger. Candidates are low-stakes: they do
NOT modify CLAUDE.md. They accumulate until a human reviews them via `/review-lessons` and
promotes the worthy ones via `/encode-lesson --from-candidate`. Capture liberally but
honestly — a bad candidate costs only a later dismissal, but a motherhood statement is pure
noise and must be dropped.

## Observability ledger

This command logs to the specship ledger. Follow the patterns in
`.specship/ledger/HOW-TO-LOG.md` — the **"capture-lessons command"** section. Log
`session_start`, one `lesson_candidate` event per captured lesson (≤3), and `session_end`.

## Inputs

The user (or the SessionEnd hook) invoked this with: $ARGUMENTS

Parse:
- `--session-id <id>`: the session being scanned. If omitted, use the current session id.
- `--source <command>`: what triggered capture (`/work`, `/ship`, `/fix`, or
  `session-end-hook`). Default `session-end-hook`.

## Idempotency pre-flight (MANDATORY)

Before capturing anything, check whether this session already has candidates:

```bash
python3 .specship/lessons/lessons_query.py has-candidates "<session-id>"
```

If it prints `yes`, this session was already captured (e.g. the `/work` end-step ran, and
now the SessionEnd hook is firing too). In that case, capture only lessons that are clearly
NOT near-duplicates of what is already recorded — query the existing candidates first:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT candidate_id, lesson_text FROM lesson_candidates WHERE session_id = '<session-id>'
"
```

If everything you would capture is already represented, stop and report "already captured."

## What counts as a lesson

Scan the session transcript for these four signals:

1. **Correction** — the user told Claude its approach was wrong ("no, not like that", "stop
   doing X", "that's not what I asked"). The lesson is what to do instead.
2. **Confirmed approach** — the user explicitly endorsed a non-obvious choice ("yes, exactly",
   "perfect, keep doing that"). The lesson is the validated approach.
3. **Stated preference** — the user expressed a durable working/style preference.
4. **Surprising decision** — Claude made a non-obvious call the spec didn't cover and it
   turned out to matter.

## The "is it checkable?" filter (reuse from /encode-lesson)

For each candidate lesson, draft it in invariant form (a directive, under 30 words) and ask:
*could a future reader tell whether this was respected?* If not, DROP it — do not record it.
Motherhood statements ("write good code", "be careful") are noise. This is the same bar
`/encode-lesson` applies; candidates that can't clear it will never be promotable anyway.

## Capture

Record at most 3 candidates (the highest-signal ones). For each, compute a stable id:

```bash
# candidate_id = first 7 chars of sha256(lesson_text + session_id)
python3 -c "import hashlib,sys; print(hashlib.sha256((sys.argv[1]+sys.argv[2]).encode()).hexdigest()[:7])" "<lesson_text>" "<session-id>"
```

Then log:

```bash
python3 .specship/ledger/specship_ledger.py log lesson_candidate \
    candidate_id="\"<id>\"" \
    lesson_text="\"<invariant-form draft>\"" \
    lesson_type="\"<architectural|module-specific|tooling|command-specific|preference>\"" \
    evidence_quote="\"<short verbatim quote that triggered it>\"" \
    source_command="\"<from --source>\"" \
    source_artifact="\"<spec/fix path or empty>\"" \
    confidence="\"<high|medium|low>\"" \
    session_id="\"<session-id>\"" \
    --quiet
```

## Report

Tell the user concisely:

```
Captured N lesson candidate(s) from session <id>:

1. [<type>, <confidence>] <lesson_text>   (id: <id>)
2. ...

These are candidates, not invariants. Review them with /review-lessons; promote the
worthy ones with /encode-lesson --from-candidate <id>.
```

If nothing cleared the checkable bar, say "No durable lessons in this session" and capture
nothing. Capturing zero is a valid, common outcome — most sessions teach nothing new.

## What this command does NOT do

- Does NOT modify CLAUDE.md or any invariant (only `/encode-lesson` does).
- Does NOT capture more than 3 candidates per run.
- Does NOT re-capture near-duplicates already recorded for the session.
- Does NOT promote, dismiss, or decay candidates — those are `/review-lessons` and the curator.
```

- [ ] **Step 2: Verify markdown frontmatter parses**

Run: `python3 -c "import sys; t=open('dist/commands/capture-lessons.md').read(); assert t.startswith('---'); fm=t.split('---',2)[1]; assert 'recommended-model:' in fm and 'description:' in fm; print('frontmatter OK')"`
Expected: `frontmatter OK`.

- [ ] **Step 3: Commit**

```bash
git add dist/commands/capture-lessons.md
git commit -m "feat(commands): /capture-lessons prompt (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 6 — `/review-lessons` command prompt

**Files:**
- Create: `dist/commands/review-lessons.md`

- [ ] **Step 1: Write the command prompt**

Create `dist/commands/review-lessons.md`:

```markdown
---
description: Surface pending lesson candidates captured by /capture-lessons for human review. For each, the user can promote it (hands off to /encode-lesson --from-candidate), dismiss it (records lesson_dismissed), or leave it pending. Mirrors /review-decisions — append-only, verdicts layered on top, never destructive.
argument-hint: [--min-confidence high|medium|low] [--cluster]
recommended-model: sonnet  # sonnet | opus — see CLAUDE.md for guidance
---

# /review-lessons — Review and Triage Lesson Candidates

You are presenting lesson candidates the `/capture-lessons` command recorded, so the human
can decide which become durable invariants. This is the review affordance between automatic
capture and the deliberate `/encode-lesson` promotion. Like `/review-decisions`, it is
append-only: you never delete candidate events; verdicts are layered as new events.

## Observability ledger

This command logs to the specship ledger. Follow `.specship/ledger/HOW-TO-LOG.md` — the
**"review-lessons command"** section. Log `session_start`, one `lesson_dismissed` per
dismissed candidate, and `session_end`. Promotions are logged by `/encode-lesson` itself
(as `lesson_promoted`), not here.

## Inputs

The user invoked this with: $ARGUMENTS

Parse:
- `--min-confidence <high|medium|low>`: hide candidates below this confidence. Default: show all.
- `--cluster`: group the listing by the curator's most recent `lessons_curated` clusters.

## Pre-flight

Fetch pending candidates (status still `captured`):

```bash
python3 .specship/lessons/lessons_query.py pending ${MIN_CONFIDENCE:+--min-confidence $MIN_CONFIDENCE}
```

This returns a JSON list sorted by confidence desc. If `--cluster` was passed, also read the
latest curator digest to group related candidates:

```bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT raw_json FROM events WHERE event_type = 'lessons_curated'
    ORDER BY ts DESC LIMIT 1
"
```

If there are no pending candidates, tell the user "No pending lesson candidates" and stop.

## Present

For each candidate (grouped by cluster theme when `--cluster` and a cluster covers it):

```
Pending lesson candidates (N):

[cluster: tooling — 3 related, consider consolidating]
  1. [tooling, high] <lesson_text>
     evidence: "<evidence_quote>"
     from: <source_command> <source_artifact>   id: <candidate_id>

  2. ...

Standalone:
  4. [preference, medium] <lesson_text>   id: <candidate_id>

For each, choose: promote <n> | dismiss <n> [reason] | skip <n>
You can also: promote all-in-cluster <theme> | dismiss-all-below low
```

Wait for the user. Do not triage unilaterally.

## Apply verdicts

### Promote

For each candidate the user promotes, hand off to `/encode-lesson`:

> Run `/encode-lesson --from-candidate <candidate_id>` for candidate <id>.

`/encode-lesson` performs the human-gated CLAUDE.md write with all its anti-bloat
guardrails, and logs both `lesson_encoded` and `lesson_promoted` (the latter folds the
candidate's status to `promoted`). You do NOT log `lesson_promoted` here — `/encode-lesson`
owns that.

If the user wants several promoted, run `/encode-lesson --from-candidate` once per id.

### Dismiss

For each dismissed candidate:

```bash
python3 .specship/ledger/specship_ledger.py log lesson_dismissed \
    candidate_id="\"<id>\"" \
    reason="\"<short reason, or 'noise'>\"" \
    session_id="\"$SID\"" \
    --quiet
```

### Skip

Leave pending — no event. It will resurface next review, and the curator will eventually
decay it if never actioned.

## Report and close

```
Reviewed N candidate(s):
  Promoted:  <ids>  → /encode-lesson handled the CLAUDE.md writes
  Dismissed: <ids>
  Left pending: <ids>

Run `python3 .specship/ledger/specship_ledger.py rebuild-index` to refresh the index,
then the dismissed/promoted candidates drop out of the pending list.
```

Log `session_end` with `outcome="completed"`.

## What this command does NOT do

- Does NOT write to CLAUDE.md — promotion delegates to `/encode-lesson`.
- Does NOT delete or edit candidate events — dismissals are append-only.
- Does NOT decay candidates — that is the curator's job.
- Does NOT capture new candidates — that is `/capture-lessons`.
```

- [ ] **Step 2: Verify frontmatter**

Run: `python3 -c "t=open('dist/commands/review-lessons.md').read(); assert t.startswith('---'); fm=t.split('---',2)[1]; assert 'recommended-model:' in fm and 'description:' in fm; print('frontmatter OK')"`
Expected: `frontmatter OK`.

- [ ] **Step 3: Commit**

```bash
git add dist/commands/review-lessons.md
git commit -m "feat(commands): /review-lessons prompt (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 7 — `/encode-lesson --from-candidate` extension

**Files:**
- Modify: `dist/commands/encode-lesson.md`

- [ ] **Step 1: Extend the Inputs section**

In `dist/commands/encode-lesson.md`, find the `## Inputs` section (it currently parses a
positional investigation path, `--fix`, and `--dest`). Add a new bullet to the parse list:

```markdown
- Optional `--from-candidate <candidate_id>`: promote a lesson candidate captured by
  `/capture-lessons` instead of starting from an investigation. When present, the first
  positional investigation argument becomes optional — the candidate's `lesson_text`,
  `lesson_type`, `evidence_quote`, and `source_artifact` stand in for the investigation's
  root-cause material.
```

- [ ] **Step 2: Add a candidate pre-flight branch**

In the `## Pre-flight` section, before step 1 ("Read the investigation file"), add:

```markdown
0. **If `--from-candidate <id>` was provided**, this is the candidate-sourced path. Skip the
   investigation-status gate (steps 1-2 below) and instead read the candidate from the ledger:

   ```bash
   python3 .specship/ledger/specship_ledger.py query "
       SELECT candidate_id, lesson_text, lesson_type, evidence_quote,
              source_command, source_artifact, status
       FROM lesson_candidates WHERE candidate_id = '<id>'
   "
   ```

   - If the candidate does not exist, stop: "no such candidate <id>".
   - If its `status` is not `captured` (already promoted/dismissed/decayed), stop and tell the
     user the current status — do not re-promote.
   - Use the candidate's `lesson_text` as the Stage 1 draft lesson, its `lesson_type` for the
     Stage 2 classification, and its `source_artifact` as the linkback source. Then continue
     at Stage 1 with the human-approval gate fully intact.

   The investigation-sourced path (steps 1-2) is unchanged for invocations without
   `--from-candidate`.
```

- [ ] **Step 3: Emit `lesson_promoted` on the candidate path**

In the ledger-logging block at the end of "Stage 4: Cross-reference", add — only when the
candidate path was used — a second log call right after the existing `lesson_encoded` log:

```markdown
If this promotion came from `--from-candidate <id>`, ALSO log the candidate's terminal event
so its status folds to `promoted`:

\`\`\`bash
python3 .specship/ledger/specship_ledger.py log lesson_promoted \
    candidate_id="\"<id>\"" \
    lesson_id="\"<stable-hash>\"" \
    destination_path="\"<path>\"" \
    session_id="\"$SID\"" \
    --quiet
\`\`\`
```

- [ ] **Step 4: Note the candidate path in "When to use"**

In the `## When to use this command` section, add one bullet under the "Use `/encode-lesson` when:" list:

```markdown
- A lesson candidate from `/capture-lessons` has been reviewed via `/review-lessons` and the
  human chose to promote it (`--from-candidate <id>`) — the candidate path does not require a
  formal investigation, but every other guardrail in this command still applies.
```

- [ ] **Step 5: Verify the file still parses and is within the line budget**

Run: `python3 -c "t=open('dist/commands/encode-lesson.md').read(); assert t.startswith('---'); n=len(t.splitlines()); print('lines:', n); assert n <= 500, 'over 500-line budget'"`
Expected: prints a line count ≤ 500.

- [ ] **Step 6: Commit**

```bash
git add dist/commands/encode-lesson.md
git commit -m "feat(commands): /encode-lesson --from-candidate promotion path (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 8 — Capture triggers: SessionEnd hook, command end-steps, install wiring

**Files:**
- Create: `dist/hooks/session-end-capture.json`
- Modify: `dist/commands/work.md`, `dist/commands/ship.md`, `dist/commands/fix.md`
- Modify: `scripts/install.sh`

This task wires the two capture triggers required by the spec: (b) an end-of-command step in
`/work`, `/ship`, `/fix`, and (a) the SessionEnd hook + installer support.

- [ ] **Step 0: Append a capture step to `/work`, `/ship`, `/fix`**

Each of these commands ends with a report/close section and logs `session_end`. Immediately
**before** the `session_end` log (so capture runs while the transcript is still the active
session), insert this stage. For `dist/commands/work.md` use `--source /work`; for
`ship.md` use `--source /ship`; for `fix.md` use `--source /fix`:

```markdown
## Capture lessons (auto)

Before closing, capture any durable lessons from this session so they are not lost. Run:

> `/capture-lessons --session-id $SID --source /work`

This records at most 3 lesson candidates (corrections, confirmed approaches, preferences,
surprising decisions) to the ledger. It is idempotent — if the SessionEnd hook also fires,
it will not double-record. Candidates are NOT invariants; they are reviewed later via
`/review-lessons`. If the session taught nothing durable, `/capture-lessons` records nothing,
which is the common case. Do not block the command's completion on this step.
```

(Replace `--source /work` with `--source /ship` / `--source /fix` in the respective files.
Use each command's existing session-id variable — they already define `$SID` in their ledger
sections.)

After editing, verify each is still within budget:

```bash
for f in dist/commands/work.md dist/commands/ship.md dist/commands/fix.md; do
  python3 -c "n=len(open('$f').read().splitlines()); print('$f', n); assert n<=500, 'over budget: $f'"
done
```
Expected: all three ≤ 500 lines.

- [ ] **Step 1: Write the hook snippet**

Create `dist/hooks/session-end-capture.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "/capture-lessons --source session-end-hook",
            "statusMessage": "specship: capturing lesson candidates from this session..."
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Read install.sh to find the scaffolding + dist-copy sections**

Run: `grep -n "for dir in\|LEDGER_DEST\|CMD_DEST\|--with\|settings.json" scripts/install.sh`
Note the line where `.specship/<subdir>` directories are created and where command/ledger files are copied — you will add `.specship/lessons` and a `dist/lessons/*` copy alongside them.

- [ ] **Step 3: Add `.specship/lessons` to the scaffolded dirs**

In `scripts/install.sh`, find the `for dir in specs fixes investigations ... .specship/templates; do` loop and add `.specship/lessons` to the list (just before `.specship/templates`).

- [ ] **Step 4: Copy the lessons helpers during install**

After the ledger-copy block (where `LEDGER_DEST` is populated), add:

```bash
LESSONS_DEST="$TARGET/.specship/lessons"
run "mkdir -p '$LESSONS_DEST'"
for f in lessons_query.py curate.py curate.sh selftest.py HOW-IT-WORKS.md; do
    run "cp '$DIST/lessons/$f' '$LESSONS_DEST/$f'"
done
run "chmod +x '$LESSONS_DEST/curate.sh'"
```

- [ ] **Step 5: Add optional cron + SessionEnd hook wiring**

Near where install.sh parses flags, add handling for a new `--with-cron` flag (default off).
After the lessons copy, add:

```bash
# Auto-lessons: SessionEnd capture hook + optional hourly curator cron.
HOOK_SNIPPET="$DIST/hooks/session-end-capture.json"
SETTINGS_FILE="$TARGET/.claude/settings.json"
echo ""
echo "Auto-lessons setup:"
echo "  To capture lessons automatically at session end, merge this into $SETTINGS_FILE:"
echo "    $(cat "$HOOK_SNIPPET")"
CRON_LINE="0 * * * * cd '$TARGET' && .specship/lessons/curate.sh >> .specship/lessons/curate.log 2>&1"
if [[ "${WITH_CRON:-0}" == "1" ]]; then
    if crontab -l 2>/dev/null | grep -qF ".specship/lessons/curate.sh"; then
        echo "  cron: hourly curator already installed"
    else
        ( crontab -l 2>/dev/null; echo "$CRON_LINE" ) | crontab -
        echo "  cron: installed hourly curator"
    fi
else
    echo "  To run the curator hourly, add this crontab line (or re-run install with --with-cron):"
    echo "    $CRON_LINE"
fi
```

(Place the `WITH_CRON` flag parse alongside the other flag parsing — set `WITH_CRON=1` when
`--with-cron` is seen. If install.sh uses a `case` over `"$@"`, add a `--with-cron) WITH_CRON=1 ;;` arm.)

- [ ] **Step 6: Verify install.sh syntax**

Run: `bash -n scripts/install.sh`
Expected: no output (success).

- [ ] **Step 7: Commit**

```bash
git add dist/commands/work.md dist/commands/ship.md dist/commands/fix.md dist/hooks/session-end-capture.json scripts/install.sh
git commit -m "feat(capture): end-of-command capture steps + SessionEnd hook + curator cron (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 9 — Docs: HOW-IT-WORKS, HOW-TO-LOG, CLAUDE.md, CHANGELOG

**Files:**
- Create: `dist/lessons/HOW-IT-WORKS.md`
- Modify: `dist/ledger/HOW-TO-LOG.md`
- Modify: `CLAUDE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write `dist/lessons/HOW-IT-WORKS.md`**

Create `dist/lessons/HOW-IT-WORKS.md`:

```markdown
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
```

- [ ] **Step 2: Add ledger logging patterns to HOW-TO-LOG.md**

In `dist/ledger/HOW-TO-LOG.md`, under "## Per-command patterns", add three subsections after
the `### /encode-lesson command` section:

```markdown
### `/capture-lessons` command

Log `session_start`, then one `lesson_candidate` per captured lesson (≤3), then `session_end`.

\`\`\`bash
python3 .specship/ledger/specship_ledger.py log lesson_candidate \
    candidate_id="\"$CID\"" lesson_text="\"...\"" lesson_type="\"tooling\"" \
    evidence_quote="\"...\"" source_command="\"/work\"" source_artifact="\"\"" \
    confidence="\"high\"" session_id="\"$SID\"" --quiet
\`\`\`

### `/review-lessons` command

Log `session_start`, one `lesson_dismissed` per dismissed candidate, `session_end`.
Promotions are logged by `/encode-lesson` (as `lesson_promoted`), not here.

\`\`\`bash
python3 .specship/ledger/specship_ledger.py log lesson_dismissed \
    candidate_id="\"$CID\"" reason="\"noise\"" session_id="\"$SID\"" --quiet
\`\`\`

### Curator (`curate.py`)

Emits `lesson_decayed` per expired candidate and one `lessons_curated` digest per run. The
curator logs these itself; no command authoring is needed. Query the latest digest with:

\`\`\`bash
python3 .specship/ledger/specship_ledger.py query "
    SELECT ts, raw_json FROM events WHERE event_type='lessons_curated' ORDER BY ts DESC LIMIT 1
"
\`\`\`
```

- [ ] **Step 3: Update specship's CLAUDE.md**

In `CLAUDE.md`, under "## Where things live", add after the `dist/ledger/` line:

```markdown
- `dist/lessons/` — auto-lessons loop: `lessons_query.py` (projection helpers),
  `curate.py` + `curate.sh` (LLM-free hourly curator), `selftest.py`, `HOW-IT-WORKS.md`
```

Under "## How to verify work is done", add:

```markdown
- `python3 dist/lessons/selftest.py` — auto-lessons projection + curator self-test (ALL PASS)
- `python3 -c "import py_compile; py_compile.compile('dist/lessons/curate.py', doraise=True)"` and same for `lessons_query.py`, `selftest.py`
- `bash -n dist/lessons/curate.sh`
```

In "dist/commands/" line under "Where things live", update the count and list to include the
two new commands (`capture-lessons`, `review-lessons`) — it currently says "eleven slash
command prompts (...)"; change to "thirteen" and append `capture-lessons, review-lessons`.

- [ ] **Step 4: Add a CHANGELOG entry**

In `CHANGELOG.md`, add a new entry at the top (matching the existing entry format — check the
top of the file for the exact heading style and version scheme):

```markdown
## Auto-lessons continual-learning loop

Added the automatic-capture half of a learning loop, feeding the existing /encode-lesson
promotion path:
- `/capture-lessons` — records ≤3 lesson candidates per session (SessionEnd hook + end of
  /work,/ship,/fix); idempotent per session.
- `dist/lessons/curate.py` — LLM-free hourly curator: decay + token-overlap clustering + digest.
- `/review-lessons` — triage affordance (promote/dismiss/skip), mirrors /review-decisions.
- `/encode-lesson --from-candidate <id>` — promote a candidate without a formal investigation,
  guardrails intact.
- Five new ledger event types projected into a `lesson_candidates` table.
- Candidates never auto-write to CLAUDE.md; only the human-gated /encode-lesson does.

Spec: specs/2026-05-20-auto-lessons-continual-learning.md
```

- [ ] **Step 5: Verify markdown + line budgets**

Run:
```bash
for f in dist/lessons/HOW-IT-WORKS.md dist/ledger/HOW-TO-LOG.md; do
  python3 -c "n=len(open('$f').read().splitlines()); print('$f', n); assert n<=500, 'over budget: $f'"
done
```
Expected: both print line counts ≤ 500.

- [ ] **Step 6: Commit**

```bash
git add dist/lessons/HOW-IT-WORKS.md dist/ledger/HOW-TO-LOG.md CLAUDE.md CHANGELOG.md
git commit -m "docs: auto-lessons how-it-works, ledger patterns, constitution, changelog (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

### Task 10 — Sync `.claude/`, run verifications, final commit

**Files:**
- Modify: `.claude/**` (generated)

- [ ] **Step 1: Sync dist/ → .claude/**

Run: `./scripts/sync-local.sh`
Expected: regenerates `.claude/` from `dist/`. Note any output listing copied files.

- [ ] **Step 2: Verify sync**

Run: `./scripts/verify-sync.sh`
Expected: passes (`.claude/` matches `dist/`). If it reports a mismatch, re-run `sync-local.sh` and check that the new `dist/lessons/` files and commands are covered by the sync script's copy globs; if `sync-local.sh` only copies known subdirs, add `lessons` to its copy list (mirror how it copies `ledger`).

- [ ] **Step 3: Run the full specship verification battery**

Run each and confirm success:
```bash
python3 -c "import py_compile; py_compile.compile('dist/ledger/specship_ledger.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('dist/lessons/lessons_query.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('dist/lessons/curate.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('dist/lessons/selftest.py', doraise=True)"
bash -n dist/lessons/curate.sh
bash -n scripts/install.sh
python3 dist/lessons/selftest.py
```
Expected: no syntax errors; `selftest.py` prints `ALL PASS`.

- [ ] **Step 4: Ledger smoke test (from CLAUDE.md verify list) still passes**

Run:
```bash
cd "$(mktemp -d)" && git init -q && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py log session_start command='"smoke"' --quiet && \
  python3 /Users/superdeveloper/dev/claude-projects/specship/dist/ledger/specship_ledger.py rebuild-index && echo "ledger OK"
```
Expected: `ledger OK` (the new event types must not have broken the indexer).

- [ ] **Step 5: Commit the synced `.claude/`**

```bash
cd /Users/superdeveloper/dev/claude-projects/specship
git add .claude
git commit -m "chore(sync): regenerate .claude from dist for auto-lessons (specs/2026-05-20-auto-lessons-continual-learning.md)"
```

---

## Done

After Task 10 the auto-lessons loop is fully wired: capture (hook + command), curate (cron),
review, and promote. Existing specship behavior is unchanged for anyone who doesn't install
the SessionEnd hook or the cron — both are opt-in, and no candidate ever reaches CLAUDE.md
without the human-gated `/encode-lesson`.

**Suggested follow-up (separate spec, not this plan):** a `/show lessons` view or a dashboard
panel summarizing candidate throughput (captured → promoted/dismissed/decayed rates) from the
`lessons_curated` digests.

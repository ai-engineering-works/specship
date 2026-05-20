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

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


def main() -> int:
    test_pending_candidates_excludes_terminal()
    test_session_has_candidates()
    test_decay_expires_old_pending_only()
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

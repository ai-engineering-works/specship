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

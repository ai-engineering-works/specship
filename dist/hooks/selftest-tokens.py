#!/usr/bin/env python3
"""Selftest for dist/hooks/session-end-tokens.py.

Sets up a temporary specship-style repo (with .specship/ledger/), fabricates a
transcript file, pipes a Claude-Code-style hook payload via stdin, and asserts
the resulting session_end event landed in events.jsonl with the right tokens.

Run from the specship repo root:
  python3 dist/hooks/selftest-tokens.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # specship/
LEDGER_SRC = ROOT / "dist" / "ledger" / "specship_ledger.py"
TRANSCRIPTS_SRC = ROOT / "dist" / "transcripts" / "reader.py"
HOOK_SRC = ROOT / "dist" / "hooks" / "session-end-tokens.py"

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}" + (f"  ({detail})" if detail else ""))
        FAILURES.append(label)


def _make_repo(td: Path) -> Path:
    """Create a fake repo with .specship/ledger/specship_ledger.py installed
    and dist/transcripts/reader.py reachable on sys.path."""
    sd = td / ".specship"
    (sd / "ledger").mkdir(parents=True)
    (sd / "hooks").mkdir(parents=True)
    (sd / "transcripts").mkdir(parents=True)
    shutil.copy(LEDGER_SRC, sd / "ledger" / "specship_ledger.py")
    shutil.copy(TRANSCRIPTS_SRC, sd / "transcripts" / "reader.py")
    shutil.copy(HOOK_SRC, sd / "hooks" / "session-end-tokens.py")
    return td


def _make_transcript(td: Path, records: list[dict]) -> Path:
    p = td / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return p


def _invoke_hook(repo: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(repo / ".specship" / "hooks" / "session-end-tokens.py")],
        input=json.dumps(payload).encode(),
        cwd=str(repo),
        capture_output=True,
        timeout=15,
    )


def _read_events(repo: Path) -> list[dict]:
    p = repo / ".specship" / "ledger" / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def case_happy_path() -> None:
    print("case: hook records tokens from a normal transcript")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        repo = _make_repo(td)
        transcript = _make_transcript(td, [
            {"type": "user", "timestamp": "2026-05-22T10:00:00Z",
             "message": {"content": "/work bar"}},
            {"type": "assistant", "timestamp": "2026-05-22T10:00:15Z",
             "message": {"model": "claude-opus-4-7", "usage": {
                 "input_tokens": 4, "output_tokens": 500,
                 "cache_creation_input_tokens": 20000,
                 "cache_read_input_tokens": 0}}},
        ])
        r = _invoke_hook(repo, {
            "session_id": "sess-abc",
            "transcript_path": str(transcript),
            "cwd": str(repo),
        })
        check("hook exited 0", r.returncode == 0,
              detail=f"stderr={r.stderr.decode()!r}")
        events = _read_events(repo)
        ends = [e for e in events if e.get("event_type") == "session_end"]
        check("one session_end event written", len(ends) == 1)
        if ends:
            e = ends[0]
            check("session_id captured", e.get("session_id") == "sess-abc")
            check("command captured", e.get("command") == "work")
            check("output_tokens", e.get("output_tokens") == 500)
            check("cache_creation", e.get("cache_creation_input_tokens") == 20000)
            check("model captured", e.get("model") == "claude-opus-4-7")
            check("duration_ms = 15000", e.get("duration_ms") == 15000)
            check("tokens_source tag", e.get("tokens_source") == "session-end-hook")


def case_no_specship_dir() -> None:
    print("case: cwd has no .specship/ — hook exits 0 silently")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        transcript = _make_transcript(td, [
            {"type": "user", "timestamp": "2026-05-22T10:00:00Z",
             "message": {"content": "anything"}},
            {"type": "assistant", "timestamp": "2026-05-22T10:00:05Z",
             "message": {"usage": {"output_tokens": 10}}},
        ])
        r = subprocess.run(
            ["python3", str(HOOK_SRC)],
            input=json.dumps({
                "session_id": "orphan",
                "transcript_path": str(transcript),
                "cwd": str(td),
            }).encode(),
            cwd=str(td),
            capture_output=True,
            timeout=10,
        )
        check("exit 0 without ledger", r.returncode == 0)
        check("no events file created", not (td / ".specship").exists())


def case_missing_transcript() -> None:
    print("case: transcript_path missing — hook exits 0, writes nothing")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        repo = _make_repo(td)
        r = _invoke_hook(repo, {
            "session_id": "x",
            "transcript_path": str(td / "does-not-exist.jsonl"),
            "cwd": str(repo),
        })
        check("exit 0", r.returncode == 0)
        check("no events", _read_events(repo) == [])


def case_empty_transcript() -> None:
    print("case: transcript has no assistant turns — skip (no record)")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        repo = _make_repo(td)
        transcript = _make_transcript(td, [
            {"type": "user", "timestamp": "2026-05-22T10:00:00Z",
             "message": {"content": "/spec"}},
        ])
        r = _invoke_hook(repo, {
            "session_id": "no-asst",
            "transcript_path": str(transcript),
            "cwd": str(repo),
        })
        check("exit 0", r.returncode == 0)
        check("no events written", _read_events(repo) == [])


def case_malformed_stdin() -> None:
    print("case: malformed stdin JSON — hook exits 0 silently")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        repo = _make_repo(td)
        r = subprocess.run(
            ["python3", str(repo / ".specship" / "hooks" / "session-end-tokens.py")],
            input=b"{not-json",
            cwd=str(repo),
            capture_output=True,
            timeout=10,
        )
        check("exit 0", r.returncode == 0)


def main() -> int:
    case_happy_path()
    case_no_specship_dir()
    case_missing_transcript()
    case_empty_transcript()
    case_malformed_stdin()
    print()
    if FAILURES:
        print(f"FAIL  {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

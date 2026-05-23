#!/usr/bin/env python3
"""SessionEnd hook: record per-session token usage to the specship ledger.

Claude Code invokes this script at SessionEnd with a JSON payload on stdin
containing at minimum `transcript_path` and `cwd`. We:

  1. Parse the transcript at `transcript_path` (Claude Code's per-session
     JSONL) and sum billing-grade token usage via dist/transcripts/reader.
  2. Locate the specship ledger at `<cwd>/.specship/ledger/specship_ledger.py`.
     If that path doesn't exist (repo doesn't use specship), exit 0 silently.
  3. Shell out to `specship_ledger.py log session_end ...` carrying the token
     totals, model, duration, and `tokens_source="session-end-hook"`.

Soft-degrade on every error. SessionEnd hooks must NEVER fail loudly — Claude
Code keeps the session-close path fast. We exit 0 on any caught exception.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Add the bundled dist/ root to sys.path so we can import transcripts.reader
# whether this script runs out of the source tree or out of `.specship/hooks/`.
_THIS = Path(__file__).resolve()
for candidate in (_THIS.parent.parent, _THIS.parent.parent.parent / "dist"):
    if (candidate / "transcripts" / "reader.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from transcripts.reader import summarize_transcript  # type: ignore
except Exception:
    summarize_transcript = None  # type: ignore


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _find_ledger(cwd: str | None) -> Path | None:
    if not cwd:
        return None
    p = Path(cwd) / ".specship" / "ledger" / "specship_ledger.py"
    return p if p.exists() else None


def _fields_for_log(summary: dict, session_id: str | None) -> list[str]:
    """Build `key='"value"'` strings for specship_ledger.py log.

    The CLI parses each `key=value` arg as JSON. Strings need to be JSON-quoted
    (so the quoting nests: shell ' " ' around a JSON " " ).
    """
    fields: list[str] = []
    if session_id:
        fields.append(f'session_id={json.dumps(session_id)}')
    cmd = summary.get("command")
    if cmd:
        fields.append(f'command={json.dumps(cmd)}')
    model = summary.get("model")
    if model:
        fields.append(f'model={json.dumps(model)}')
    for k in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "duration_ms",
    ):
        v = summary.get(k)
        if isinstance(v, int):
            fields.append(f"{k}={v}")
    fields.append(f'tokens_source={json.dumps("session-end-hook")}')
    return fields


def main() -> int:
    try:
        payload = _read_payload()
        transcript_path = payload.get("transcript_path")
        session_id = payload.get("session_id")
        cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

        ledger = _find_ledger(cwd)
        if ledger is None or summarize_transcript is None or not transcript_path:
            return 0

        if not Path(transcript_path).exists():
            return 0

        summary = summarize_transcript(transcript_path)

        # If the transcript yielded no assistant turns, skip — nothing to record.
        if not summary.get("turn_count"):
            return 0

        args = ["python3", str(ledger), "log", "session_end", "--quiet"]
        args += _fields_for_log(summary, session_id)

        # Capture and discard output. Never raise.
        subprocess.run(
            args,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except Exception:
        # Soft-degrade. The hook must never block session close.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

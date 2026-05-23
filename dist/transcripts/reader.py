"""Shared reader for Claude Code session transcripts.

Transcripts live at ~/.claude/projects/<slug>/<sessionId>.jsonl. Each line is a
JSON record; assistant records carry message.usage with the four billing-grade
token fields. We expose a minimal stdlib-only API used by:

  - dist/hooks/session-end-tokens.py  (Phase A: per-session token accounting)
  - dist/retrospective/generate.py    (Phase B: LLM retrospective analyzer)

Both readers tolerate malformed JSONL lines and missing fields — the data is
external and Claude Code's emit format has changed across versions.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

SLASH_CMD_RE = re.compile(r"^/(\S+)")


def iter_session_records(path: str | Path) -> Iterator[dict]:
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def sum_usage(records: Iterable[dict]) -> dict[str, int]:
    """Sum the four billing-grade usage fields across all assistant records.

    `input_tokens` is the marginal-uncached delta and is small but real; we
    include it so the sum matches the API's true input bill. Cache fields
    dominate when caching is working.
    """
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        usage = (rec.get("message") or {}).get("usage") or {}
        for k in totals:
            v = usage.get(k)
            if isinstance(v, int):
                totals[k] += v
    return totals


def detect_command(records: Iterable[dict]) -> str | None:
    """Regex /<word> on the first user message. Returns the command name or None."""
    for rec in records:
        if rec.get("type") != "user":
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        text = _flatten_text(content)
        if not text:
            continue
        m = SLASH_CMD_RE.match(text.strip())
        return m.group(1) if m else None
    return None


def detect_model(records: Iterable[dict]) -> str | None:
    """Last assistant message's model (most representative of what was billed)."""
    last = None
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        m = (rec.get("message") or {}).get("model")
        if m:
            last = m
    return last


def first_and_last_ts(records: Iterable[dict]) -> tuple[str | None, str | None]:
    first = last = None
    for rec in records:
        ts = rec.get("timestamp")
        if not ts:
            continue
        if first is None:
            first = ts
        last = ts
    return first, last


def duration_ms(first_ts: str | None, last_ts: str | None) -> int | None:
    if not first_ts or not last_ts:
        return None
    try:
        a = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        b = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = (b - a).total_seconds() * 1000
    return int(delta) if delta >= 0 else None


def _flatten_text(content) -> str:
    """Pull text out of a user message's content. Claude Code emits either a
    plain string or a list of content blocks. Returns the first text we find."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    return block["text"]
                if isinstance(block.get("content"), str):
                    return block["content"]
    return ""


def summarize_transcript(path: str | Path) -> dict:
    """One-shot helper used by the SessionEnd hook. Reads twice (stdlib iterators
    don't tee cheaply), which is fine — transcripts are local and small."""
    records = list(iter_session_records(path))
    first, last = first_and_last_ts(records)
    return {
        "command": detect_command(records),
        "model": detect_model(records),
        "first_ts": first,
        "last_ts": last,
        "duration_ms": duration_ms(first, last),
        **sum_usage(records),
        "turn_count": sum(1 for r in records if r.get("type") == "assistant"),
    }

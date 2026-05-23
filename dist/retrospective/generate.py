#!/usr/bin/env python3
"""Generate a workflow retrospective from recent Claude Code sessions.

Reads transcripts at ~/.claude/projects/<slug>/*.jsonl plus the specship
ledger for the chosen scope, calls the Anthropic API with the prompt at
dist/retrospective/prompt.md, and logs a retrospective_generated event into
the appropriate ledger.

CLI only — the dashboard does not trigger generation. See HOW-IT-WORKS.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template

# ---------------------------------------------------------------------------
# Import path setup. This script runs both from the source tree (specship/
# repo) and from the installed location (.specship/retrospective/ in a target
# repo). Both layouts contain dist/transcripts/reader.py alongside or above us;
# we try a few candidates so the import works either way.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
for _candidate in (
    _HERE.parent.parent,                # source tree:    dist/  → has transcripts/
    _HERE.parent.parent.parent / "dist", # installed:     .specship/retrospective/ → ../dist
    _HERE.parent.parent,                 # installed alt: .specship/  → has transcripts/
):
    if (_candidate / "transcripts" / "reader.py").exists():
        sys.path.insert(0, str(_candidate))
        break

try:
    from transcripts.reader import (  # noqa: E402
        iter_session_records,
        sum_usage,
        detect_command,
        detect_model,
        first_and_last_ts,
        duration_ms,
    )
except Exception as e:  # pragma: no cover
    print(f"FATAL: cannot import transcripts.reader: {e}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Configuration and constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-6"
GLOBAL_LEDGER_DIR = Path.home() / ".specship" / "global" / "ledger"
MAX_TRANSCRIPT_EXCERPT = 400  # chars per assistant/user message included in prompt


@dataclass
class SessionSummary:
    session_id: str
    command: str | None
    started: str | None
    ended: str | None
    model: str | None
    duration_ms: int | None
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    transcript_excerpt: str  # truncated user+assistant content


# ---------------------------------------------------------------------------
# Transcript discovery + extraction
# ---------------------------------------------------------------------------

def _claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _slug_to_dirs(slug: str | None) -> list[Path]:
    """If a slug is provided, return the single matching ~/.claude/projects/<...>
    directory. The Claude Code dir name encodes the absolute path with slashes
    replaced by hyphens; we substring-match the slug against each candidate
    so the user can pass a short slug ("specship-parent") rather than the full
    encoded path. If slug is None, return all project dirs."""
    root = _claude_projects_dir()
    if not root.exists():
        return []
    if slug is None or slug == "all":
        return sorted(d for d in root.iterdir() if d.is_dir())
    needle = slug.lower()
    return sorted(d for d in root.iterdir() if d.is_dir() and needle in d.name.lower())


def _within_window(ts_str: str | None, cutoff: datetime) -> bool:
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    return ts >= cutoff


def _excerpt_from_records(records: list[dict]) -> str:
    """Concatenate user-text and assistant-text content (no tool results) up
    to MAX_TRANSCRIPT_EXCERPT chars total. Conveys what the conversation was
    about without dumping the whole transcript."""
    parts: list[str] = []
    remaining = MAX_TRANSCRIPT_EXCERPT
    for rec in records:
        t = rec.get("type")
        if t not in ("user", "assistant"):
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        text = _flatten(content)
        if not text:
            continue
        prefix = "U:" if t == "user" else "A:"
        snippet = f"{prefix} {text.strip()[:remaining]}"
        parts.append(snippet)
        remaining -= len(snippet)
        if remaining <= 0:
            break
    return "\n".join(parts)


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    out.append(block["text"])
                elif isinstance(block.get("content"), str):
                    out.append(block["content"])
        return "\n".join(out)
    return ""


def collect_sessions(slug: str | None, days: int) -> list[SessionSummary]:
    """Scan ~/.claude/projects/<slug>/*.jsonl for sessions started in the last
    `days` days. Returns one SessionSummary per file."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[SessionSummary] = []
    for project_dir in _slug_to_dirs(slug):
        for jsonl in sorted(project_dir.glob("*.jsonl")):
            try:
                records = list(iter_session_records(jsonl))
            except Exception:
                continue
            if not records:
                continue
            first_ts, last_ts = first_and_last_ts(records)
            if not _within_window(first_ts or last_ts, cutoff):
                continue
            usage = sum_usage(records)
            out.append(SessionSummary(
                session_id=jsonl.stem,
                command=detect_command(records),
                started=first_ts,
                ended=last_ts,
                model=detect_model(records),
                duration_ms=duration_ms(first_ts, last_ts),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_creation_input_tokens=usage["cache_creation_input_tokens"],
                cache_read_input_tokens=usage["cache_read_input_tokens"],
                transcript_excerpt=_excerpt_from_records(records),
            ))
    return out


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def _prompt_template() -> str:
    return (_HERE.parent / "prompt.md").read_text(encoding="utf-8")


def assemble_prompt(sessions: list[SessionSummary], days: int) -> str:
    total_input = sum(s.input_tokens for s in sessions)
    total_output = sum(s.output_tokens for s in sessions)
    total_cache_creation = sum(s.cache_creation_input_tokens for s in sessions)
    total_cache_read = sum(s.cache_read_input_tokens for s in sessions)
    total_billed = total_input + total_cache_creation + total_cache_read
    cache_hit_rate = (total_cache_read / total_billed) if total_billed else 0.0

    by_cmd: dict[str, int] = {}
    for s in sessions:
        cmd = s.command or "<no-command>"
        by_cmd[cmd] = by_cmd.get(cmd, 0) + 1
    cmd_lines = "\n".join(
        f"  - {cmd}: {count} session(s)"
        for cmd, count in sorted(by_cmd.items(), key=lambda kv: -kv[1])
    ) or "  (no sessions in window)"

    sessions_block_parts: list[str] = []
    for s in sessions[:50]:  # cap to keep prompt manageable
        billed = s.input_tokens + s.cache_creation_input_tokens + s.cache_read_input_tokens
        hit = (s.cache_read_input_tokens / billed) if billed else 0.0
        sessions_block_parts.append(
            f"--- session {s.session_id[:8]} ---\n"
            f"  command: {s.command or '<none>'}\n"
            f"  started: {s.started}\n"
            f"  duration_ms: {s.duration_ms}\n"
            f"  model: {s.model}\n"
            f"  input_billed: {billed}  (cache hit {hit:.0%})\n"
            f"  output: {s.output_tokens}\n"
            f"  excerpt:\n{s.transcript_excerpt}\n"
        )
    sessions_block = "\n".join(sessions_block_parts) or "(no sessions)"

    metrics_block = (
        f"  - sessions: {len(sessions)}\n"
        f"  - cache_hit_rate: {cache_hit_rate:.0%}\n"
        f"  - total_input_billed_tokens: {total_billed}\n"
        f"  - total_output_tokens: {total_output}\n"
        f"  - by_command:\n{cmd_lines}\n"
    )

    return Template(_prompt_template()).safe_substitute(
        days_covered=days,
        session_count=len(sessions),
        total_billed_tokens=total_billed,
        cache_hit_rate_pct=int(cache_hit_rate * 100),
        metrics_block=metrics_block,
        sessions_block=sessions_block,
    )


# ---------------------------------------------------------------------------
# Anthropic call (with graceful fallback)
# ---------------------------------------------------------------------------

def _missing_sdk_error() -> str:
    return (
        "ERROR: the `anthropic` Python SDK is not installed.\n"
        "\n"
        "Install it with:\n"
        "  pip install --user anthropic\n"
        "\n"
        "Then re-run this command. The SDK is required only for the\n"
        "retrospective feature; the rest of specship works without it.\n"
    )


def call_anthropic(prompt: str, model: str) -> tuple[dict, int]:
    """Call the Anthropic API and return (parsed_json, tokens_used).

    Raises SystemExit(2) if the SDK is missing, or RuntimeError on any other
    API failure or response-shape problem.
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        sys.stderr.write(_missing_sdk_error())
        sys.exit(2)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    # Extract text content
    text_parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    text = "\n".join(text_parts).strip()
    if not text:
        raise RuntimeError("Anthropic response had no text content")

    parsed = _parse_response_json(text)
    return parsed, _tokens_from_usage(msg)


def _tokens_from_usage(msg) -> int:
    u = getattr(msg, "usage", None)
    if u is None:
        return 0
    in_tok = getattr(u, "input_tokens", 0) or 0
    out_tok = getattr(u, "output_tokens", 0) or 0
    return int(in_tok) + int(out_tok)


def _parse_response_json(text: str) -> dict:
    """The prompt instructs the model to emit JSON only, but be defensive:
    strip leading/trailing prose and try to extract the outermost object."""
    # Try as-is first
    text = text.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Find the outermost {...}
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(f"Anthropic response not parseable as JSON: {text[:200]!r}")
        obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise RuntimeError(f"Anthropic response did not parse to an object: {obj!r}")
    if "summary" not in obj or "suggestions" not in obj:
        raise RuntimeError(f"Anthropic response missing required keys: {sorted(obj.keys())}")
    if not isinstance(obj["suggestions"], list):
        raise RuntimeError("'suggestions' must be a list")
    return obj


# ---------------------------------------------------------------------------
# Ledger I/O
# ---------------------------------------------------------------------------

def _ledger_dir_for(slug: str | None) -> Path:
    """Return the .specship/ledger/ directory the retrospective should write to."""
    if slug in (None, "all"):
        return GLOBAL_LEDGER_DIR
    # Look for a repo dir under ~/dev/claude-projects/<slug> by default.
    # If the caller has cd'd into a specific repo, the cwd's .specship/ledger/
    # takes precedence.
    cwd_ledger = Path.cwd() / ".specship" / "ledger"
    if cwd_ledger.exists() and Path.cwd().name == slug:
        return cwd_ledger
    # Fallback: search parents of cwd for a matching repo
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / slug / ".specship" / "ledger"
        if candidate.exists():
            return candidate
    # If nothing else, default to creating it under the cwd
    return Path.cwd() / ".specship" / "ledger"


def _ledger_jsonl(ledger_dir: Path) -> Path:
    return ledger_dir / "events.jsonl"


def already_generated_today(ledger_dir: Path, scope: str, days: int) -> bool:
    """Idempotency check: read events.jsonl and look for a retrospective_generated
    with the same scope+days emitted on the same UTC date."""
    p = _ledger_jsonl(ledger_dir)
    if not p.exists():
        return False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event_type") != "retrospective_generated":
            continue
        if e.get("scope") != scope or e.get("days_covered") != days:
            continue
        if (e.get("ts") or "").startswith(today):
            return True
    return False


def write_retrospective(
    ledger_dir: Path,
    *,
    scope: str,
    days: int,
    model: str,
    summary_text: str,
    suggestions: list[dict],
    tokens_used: int,
    session_count: int,
) -> dict:
    """Append a retrospective_generated event to the ledger and return the event.
    We append directly via JSONL rather than shelling out to specship_ledger.py
    because the workspace-wide ledger (~/.specship/global/) is not part of any
    repo install; the indexer rebuilds from JSONL whenever the dashboard reads it."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seed = f"{scope}|{now}|{days}".encode()
    rid = hashlib.sha256(seed).hexdigest()[:7]
    event = {
        "ts": now,
        "event_id": rid,
        "event_type": "retrospective_generated",
        "retrospective_id": rid,
        "scope": scope,
        "days_covered": days,
        "model": model,
        "summary_text": summary_text,
        "suggestions": suggestions,
        "tokens_used": tokens_used,
        "session_count": session_count,
    }
    with _ledger_jsonl(ledger_dir).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="specship-retro",
        description="Generate a workflow retrospective from recent Claude Code sessions.",
    )
    ap.add_argument("--repo", default="all",
                    help="repo slug, or 'all' for workspace-wide (default: all)")
    ap.add_argument("--days", type=int, default=7,
                    help="how many days of history to include (default: 7)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Anthropic model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble the prompt + count sessions; do NOT call the API or write a ledger event")
    ap.add_argument("--target", type=Path, default=None,
                    help="override the ledger directory (advanced; default: discovered from --repo)")
    ap.add_argument("--force", action="store_true",
                    help="re-generate even if a same-day retrospective already exists for this scope+days")
    args = ap.parse_args(argv)

    scope = args.repo
    sessions = collect_sessions(scope if scope != "all" else None, args.days)

    print(f"Scope: {scope}   Days: {args.days}   Sessions found: {len(sessions)}",
          file=sys.stderr)

    if not sessions:
        print("No sessions in the chosen window. Nothing to retrospect on.", file=sys.stderr)
        return 0

    prompt = assemble_prompt(sessions, args.days)

    if args.dry_run:
        print(prompt)
        return 0

    ledger_dir = args.target or _ledger_dir_for(scope)
    if not args.force and already_generated_today(ledger_dir, scope, args.days):
        print(f"Already generated a retrospective today for scope={scope} days={args.days}. "
              f"Use --force to overwrite.", file=sys.stderr)
        return 0

    parsed, tokens_used = call_anthropic(prompt, args.model)

    event = write_retrospective(
        ledger_dir,
        scope=scope,
        days=args.days,
        model=args.model,
        summary_text=parsed["summary"],
        suggestions=parsed["suggestions"],
        tokens_used=tokens_used,
        session_count=len(sessions),
    )

    print(f"Wrote retrospective {event['retrospective_id']} to {_ledger_jsonl(ledger_dir)}",
          file=sys.stderr)
    print(json.dumps(event, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

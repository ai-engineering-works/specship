#!/usr/bin/env python3
"""Selftest for dist/transcripts/reader.py.

Run from repo root:  python3 dist/transcripts/selftest.py
Exits non-zero on any failure, prints "ALL PASS" on success.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcripts.reader import (  # noqa: E402
    detect_command,
    detect_model,
    duration_ms,
    first_and_last_ts,
    iter_session_records,
    summarize_transcript,
    sum_usage,
)


def _write_jsonl(records: list[dict], extra_lines: list[str] | None = None) -> str:
    lines = [json.dumps(r) for r in records]
    if extra_lines:
        lines.extend(extra_lines)
    f = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".jsonl", encoding="utf-8"
    )
    f.write("\n".join(lines) + "\n")
    f.close()
    return f.name


FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        msg = f"  FAIL {label}" + (f"  ({detail})" if detail else "")
        print(msg)
        FAILURES.append(label)


def case_missing_file() -> None:
    print("case: missing file")
    records = list(iter_session_records("/nonexistent/path.jsonl"))
    check("returns no records", records == [])


def case_empty_file() -> None:
    print("case: empty file")
    path = _write_jsonl([])
    records = list(iter_session_records(path))
    check("zero records", records == [])
    totals = sum_usage(records)
    check("zero totals", all(v == 0 for v in totals.values()))


def case_single_turn() -> None:
    print("case: single user → assistant turn")
    path = _write_jsonl([
        {
            "type": "user",
            "timestamp": "2026-05-22T06:50:00Z",
            "message": {"content": "/work foo"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-05-22T06:50:30Z",
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 862,
                    "cache_creation_input_tokens": 47709,
                    "cache_read_input_tokens": 0,
                },
            },
        },
    ])
    records = list(iter_session_records(path))
    check("two records read", len(records) == 2)
    totals = sum_usage(records)
    check("input_tokens summed", totals["input_tokens"] == 5)
    check("output_tokens summed", totals["output_tokens"] == 862)
    check("cache_creation summed", totals["cache_creation_input_tokens"] == 47709)
    check("command detected", detect_command(records) == "work")
    check("model detected", detect_model(records) == "claude-opus-4-7")
    first, last = first_and_last_ts(records)
    check("first ts", first == "2026-05-22T06:50:00Z")
    check("last ts", last == "2026-05-22T06:50:30Z")
    check("duration ms = 30000", duration_ms(first, last) == 30000)


def case_multi_turn_with_cache() -> None:
    print("case: multi-turn with cache hits accumulating")
    path = _write_jsonl([
        {"type": "user", "timestamp": "2026-05-22T07:00:00Z",
         "message": {"content": "/ship"}},
        {"type": "assistant", "timestamp": "2026-05-22T07:00:05Z",
         "message": {"model": "claude-sonnet-4-6", "usage": {
             "input_tokens": 3, "output_tokens": 100,
             "cache_creation_input_tokens": 10000,
             "cache_read_input_tokens": 0}}},
        {"type": "user", "timestamp": "2026-05-22T07:00:15Z",
         "message": {"content": [{"type": "text", "text": "continue"}]}},
        {"type": "assistant", "timestamp": "2026-05-22T07:00:25Z",
         "message": {"model": "claude-sonnet-4-6", "usage": {
             "input_tokens": 2, "output_tokens": 200,
             "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 10000}}},
    ])
    records = list(iter_session_records(path))
    totals = sum_usage(records)
    check("input summed", totals["input_tokens"] == 5)
    check("output summed", totals["output_tokens"] == 300)
    check("cache_creation summed", totals["cache_creation_input_tokens"] == 10000)
    check("cache_read summed", totals["cache_read_input_tokens"] == 10000)
    check("command from first user msg", detect_command(records) == "ship")


def case_malformed_jsonl() -> None:
    print("case: malformed JSONL line is skipped")
    path = _write_jsonl(
        [{"type": "assistant", "message": {"usage": {"output_tokens": 50}}}],
        extra_lines=["{not valid json", "", "  "],
    )
    records = list(iter_session_records(path))
    check("only the one valid record", len(records) == 1)
    check("output read despite malformed siblings",
          sum_usage(records)["output_tokens"] == 50)


def case_non_slash_first_user_msg() -> None:
    print("case: first user message is not a slash command")
    path = _write_jsonl([
        {"type": "user", "timestamp": "2026-05-22T08:00:00Z",
         "message": {"content": "hey, can you look at this?"}},
        {"type": "assistant", "timestamp": "2026-05-22T08:00:05Z",
         "message": {"usage": {"output_tokens": 10}}},
    ])
    records = list(iter_session_records(path))
    check("command is None", detect_command(records) is None)


def case_summarize_helper() -> None:
    print("case: summarize_transcript composes the public fields")
    path = _write_jsonl([
        {"type": "user", "timestamp": "2026-05-22T09:00:00Z",
         "message": {"content": "/spec drift"}},
        {"type": "assistant", "timestamp": "2026-05-22T09:00:10Z",
         "message": {"model": "claude-sonnet-4-6", "usage": {
             "input_tokens": 1, "output_tokens": 500,
             "cache_creation_input_tokens": 5000,
             "cache_read_input_tokens": 0}}},
    ])
    s = summarize_transcript(path)
    expected_keys = {
        "command", "model", "first_ts", "last_ts", "duration_ms",
        "input_tokens", "output_tokens",
        "cache_read_input_tokens", "cache_creation_input_tokens",
        "turn_count",
    }
    check("has all expected keys", set(s.keys()) == expected_keys,
          detail=f"got {sorted(s.keys())}")
    check("command captured", s["command"] == "spec")
    check("turn_count = 1", s["turn_count"] == 1)
    check("model captured", s["model"] == "claude-sonnet-4-6")
    check("output_tokens", s["output_tokens"] == 500)
    check("duration_ms = 10000", s["duration_ms"] == 10000)


def case_duration_edge_cases() -> None:
    print("case: duration edge cases")
    check("None when missing first", duration_ms(None, "2026-05-22T00:00:01Z") is None)
    check("None when missing last", duration_ms("2026-05-22T00:00:00Z", None) is None)
    check("None when reversed", duration_ms(
        "2026-05-22T00:01:00Z", "2026-05-22T00:00:00Z") is None)
    check("None on malformed", duration_ms("not-a-ts", "also-bad") is None)


def main() -> int:
    case_missing_file()
    case_empty_file()
    case_single_turn()
    case_multi_turn_with_cache()
    case_malformed_jsonl()
    case_non_slash_first_user_msg()
    case_summarize_helper()
    case_duration_edge_cases()
    print()
    if FAILURES:
        print(f"FAIL  {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

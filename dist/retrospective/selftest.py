#!/usr/bin/env python3
"""Selftest for dist/retrospective/generate.py.

Exercises the full pipeline (transcript scan → prompt assembly → mocked LLM
call → ledger write → idempotency) without hitting the Anthropic API. The
Anthropic SDK is mocked via sys.modules injection so the test does not
require the package to be installed.

Run from the specship repo root:
  python3 dist/retrospective/selftest.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
import unittest.mock as mock
from pathlib import Path

# Add dist/ to sys.path so we can import transcripts and retrospective
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent.parent))

# Inject a fake anthropic module BEFORE importing generate.py so its delayed
# `import anthropic` finds our fake.
_fake_anthropic = types.ModuleType("anthropic")


class _FakeUsage:
    def __init__(self, in_tok: int, out_tok: int):
        self.input_tokens = in_tok
        self.output_tokens = out_tok


class _FakeContentBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text: str, in_tok: int = 1000, out_tok: int = 300):
        self.content = [_FakeContentBlock(text)]
        self.usage = _FakeUsage(in_tok, out_tok)


class _FakeMessagesAPI:
    def __init__(self, response_text: str = ""):
        self._response_text = response_text

    def create(self, **kwargs):
        return _FakeMessage(self._response_text)


class _FakeAnthropic:
    _next_response_text: str = ""

    def __init__(self, *args, **kwargs):
        self.messages = _FakeMessagesAPI(_FakeAnthropic._next_response_text)


_fake_anthropic.Anthropic = _FakeAnthropic
sys.modules["anthropic"] = _fake_anthropic

# Now import the module under test
from retrospective import generate  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}" + (f"  ({detail})" if detail else ""))
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TRANSCRIPT_RECORDS = [
    {"type": "user", "timestamp": "2026-05-22T10:00:00Z",
     "message": {"content": "/work fix the auth bug"}},
    {"type": "assistant", "timestamp": "2026-05-22T10:00:15Z",
     "message": {"model": "claude-opus-4-7", "usage": {
         "input_tokens": 5, "output_tokens": 400,
         "cache_creation_input_tokens": 20000,
         "cache_read_input_tokens": 30000}}},
]

_VALID_LLM_RESPONSE = json.dumps({
    "summary": "User ran one /work session this week with a 60% cache hit rate. "
               "Activity was concentrated in a single repo.",
    "suggestions": [
        {"title": "Pin CLAUDE.md mid-session", "body": "Caching benefits from a stable prefix.",
         "priority": "high"},
        {"title": "Use /spec before /work", "body": "Add a 1-paragraph spec.",
         "priority": "med"},
        {"title": "Try Sonnet for /work", "body": "Cheaper for routine edits.",
         "priority": "low"},
    ],
})

_MALFORMED_LLM_RESPONSE = "Here is the analysis: it was a productive week."


def _setup_fake_claude_projects(td: Path, slug: str = "demo-repo") -> Path:
    """Create ~/.claude/projects-style structure inside td."""
    p = td / ".claude" / "projects" / f"-Users-x-dev-{slug}"
    p.mkdir(parents=True)
    (p / "sess-1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _TRANSCRIPT_RECORDS),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def case_collect_sessions() -> None:
    print("case: collect_sessions reads transcripts from ~/.claude/projects/<slug>/")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        _setup_fake_claude_projects(td)
        with mock.patch.object(generate, "_claude_projects_dir",
                               return_value=td / ".claude" / "projects"):
            sessions = generate.collect_sessions("demo-repo", days=30)
        check("found one session", len(sessions) == 1)
        if sessions:
            s = sessions[0]
            check("session command is 'work'", s.command == "work")
            check("model captured", s.model == "claude-opus-4-7")
            check("output_tokens summed", s.output_tokens == 400)
            check("cache_read summed", s.cache_read_input_tokens == 30000)
            check("excerpt non-empty", bool(s.transcript_excerpt))


def case_assemble_prompt() -> None:
    print("case: assemble_prompt fills template via Template substitution (no KeyError on JSON braces)")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        _setup_fake_claude_projects(td)
        with mock.patch.object(generate, "_claude_projects_dir",
                               return_value=td / ".claude" / "projects"):
            sessions = generate.collect_sessions("demo-repo", days=30)
        prompt = generate.assemble_prompt(sessions, days=7)
        check("prompt contains session count", "Sessions analyzed: 1" in prompt)
        # 30000 / (5 + 20000 + 30000) = 0.5999... → int * 100 = 59
        check("prompt contains cache hit rate", "59% cache hit rate" in prompt)
        check("prompt preserves JSON example braces", '"summary":' in prompt)
        check("prompt has by_command line", "work: 1 session" in prompt)


def case_parse_response_clean_json() -> None:
    print("case: _parse_response_json accepts clean JSON")
    obj = generate._parse_response_json(_VALID_LLM_RESPONSE)
    check("summary present", "summary" in obj)
    check("3 suggestions", len(obj["suggestions"]) == 3)
    check("first suggestion is high priority",
          obj["suggestions"][0]["priority"] == "high")


def case_parse_response_with_prose() -> None:
    print("case: _parse_response_json strips leading/trailing prose")
    wrapped = "Here is the JSON:\n" + _VALID_LLM_RESPONSE + "\nThanks."
    obj = generate._parse_response_json(wrapped)
    check("summary still extracted", obj["summary"].startswith("User ran one /work"))


def case_parse_response_malformed() -> None:
    print("case: _parse_response_json raises on unparseable response")
    raised = False
    try:
        generate._parse_response_json(_MALFORMED_LLM_RESPONSE)
    except RuntimeError:
        raised = True
    check("raises RuntimeError", raised)


def case_full_pipeline_writes_ledger() -> None:
    print("case: full pipeline writes a retrospective_generated event")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        _setup_fake_claude_projects(td)
        target = td / "ledger"
        _FakeAnthropic._next_response_text = _VALID_LLM_RESPONSE
        with mock.patch.object(generate, "_claude_projects_dir",
                               return_value=td / ".claude" / "projects"):
            rc = generate.main([
                "--repo", "demo-repo",
                "--days", "30",
                "--target", str(target),
            ])
        check("exit code 0", rc == 0)
        events_path = target / "events.jsonl"
        check("events.jsonl exists", events_path.exists())
        if events_path.exists():
            lines = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
            check("one event written", len(lines) == 1)
            if lines:
                e = lines[0]
                check("event_type matches",
                      e.get("event_type") == "retrospective_generated")
                check("scope matches", e.get("scope") == "demo-repo")
                check("days_covered matches", e.get("days_covered") == 30)
                check("3 suggestions", len(e.get("suggestions") or []) == 3)
                check("session_count = 1", e.get("session_count") == 1)
                check("tokens_used reported",
                      isinstance(e.get("tokens_used"), int) and e["tokens_used"] > 0)


def case_idempotency_skip_same_day() -> None:
    print("case: same-day re-run is a no-op (idempotency)")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        _setup_fake_claude_projects(td)
        target = td / "ledger"
        _FakeAnthropic._next_response_text = _VALID_LLM_RESPONSE
        with mock.patch.object(generate, "_claude_projects_dir",
                               return_value=td / ".claude" / "projects"):
            # First run writes.
            rc1 = generate.main([
                "--repo", "demo-repo", "--days", "7", "--target", str(target),
            ])
            # Second run — same scope+days — skips.
            rc2 = generate.main([
                "--repo", "demo-repo", "--days", "7", "--target", str(target),
            ])
        events_path = target / "events.jsonl"
        lines = [l for l in events_path.read_text().splitlines() if l.strip()]
        check("first run wrote", rc1 == 0 and len(lines) == 1)
        check("second run was no-op", rc2 == 0 and len(lines) == 1)


def case_force_overrides_idempotency() -> None:
    print("case: --force generates a second retrospective even on the same day")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        _setup_fake_claude_projects(td)
        target = td / "ledger"
        _FakeAnthropic._next_response_text = _VALID_LLM_RESPONSE
        with mock.patch.object(generate, "_claude_projects_dir",
                               return_value=td / ".claude" / "projects"):
            generate.main([
                "--repo", "demo-repo", "--days", "7", "--target", str(target),
            ])
            generate.main([
                "--repo", "demo-repo", "--days", "7", "--target", str(target), "--force",
            ])
        lines = [l for l in (target / "events.jsonl").read_text().splitlines() if l.strip()]
        check("two events with --force", len(lines) == 2)


def case_no_sessions_skips_cleanly() -> None:
    print("case: empty window exits 0 without ledger writes")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        # No transcripts under ~/.claude/projects
        (td / ".claude" / "projects").mkdir(parents=True)
        target = td / "ledger"
        with mock.patch.object(generate, "_claude_projects_dir",
                               return_value=td / ".claude" / "projects"):
            rc = generate.main([
                "--repo", "demo-repo", "--days", "7", "--target", str(target),
            ])
        check("exit 0", rc == 0)
        check("no ledger file created", not (target / "events.jsonl").exists())


def case_dry_run_no_api_call_no_ledger() -> None:
    print("case: --dry-run prints prompt and does NOT write the ledger or call the API")
    with tempfile.TemporaryDirectory() as tdir:
        td = Path(tdir)
        _setup_fake_claude_projects(td)
        target = td / "ledger"
        called_marker = {"called": False}

        class _SpyAnthropic(_FakeAnthropic):
            def __init__(self, *a, **k):
                called_marker["called"] = True
                super().__init__(*a, **k)
        sys.modules["anthropic"].Anthropic = _SpyAnthropic  # type: ignore

        try:
            with mock.patch.object(generate, "_claude_projects_dir",
                                   return_value=td / ".claude" / "projects"):
                rc = generate.main([
                    "--repo", "demo-repo", "--days", "7",
                    "--target", str(target), "--dry-run",
                ])
        finally:
            sys.modules["anthropic"].Anthropic = _FakeAnthropic  # type: ignore

        check("dry-run exit 0", rc == 0)
        check("API not called", not called_marker["called"])
        check("no ledger written", not (target / "events.jsonl").exists())


def case_missing_sdk_exits_with_hint() -> None:
    print("case: missing anthropic SDK → SystemExit(2) with install hint")
    # Temporarily remove the fake to exercise the ImportError branch.
    saved = sys.modules.pop("anthropic")
    try:
        raised = False
        try:
            generate.call_anthropic("prompt", model="x")
        except SystemExit as e:
            raised = (e.code == 2)
        check("SystemExit(2) raised", raised)
    finally:
        sys.modules["anthropic"] = saved


def main() -> int:
    case_collect_sessions()
    case_assemble_prompt()
    case_parse_response_clean_json()
    case_parse_response_with_prose()
    case_parse_response_malformed()
    case_full_pipeline_writes_ledger()
    case_idempotency_skip_same_day()
    case_force_overrides_idempotency()
    case_no_sessions_skips_cleanly()
    case_dry_run_no_api_call_no_ledger()
    case_missing_sdk_exits_with_hint()
    print()
    if FAILURES:
        print(f"FAIL  {len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

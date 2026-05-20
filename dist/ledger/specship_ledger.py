#!/usr/bin/env python3
"""
specship_ledger.py — the observability ledger for specship.

Two storage layers:
  - JSONL at .specship/ledger/events.jsonl   (source of truth, append-only)
  - SQLite at .specship/ledger/index.db      (derived index for fast queries)

The JSONL is durable, append-only, human-readable, and survives concurrent
writes via O_APPEND. The SQLite is a query-side projection that can be
rebuilt from the JSONL at any time.

Design choices:
  - Events are typed (session_start, artifact_created, decision_logged,
    command_completed, ...). Each event is one JSONL line.
  - Schema is forward-compatible: unknown event types are kept in JSONL,
    skipped (with a warning) by the SQLite indexer.
  - No external dependencies beyond Python stdlib. SQLite is built into
    Python; jsonl is just text.

CLI:
  python3 specship_ledger.py log <event-type> --key value ...   # append event
  python3 specship_ledger.py rebuild-index                       # rebuild SQLite from JSONL
  python3 specship_ledger.py query <sql>                         # run SQL against index
  python3 specship_ledger.py summary [--since DATE]              # human-readable digest
  python3 specship_ledger.py export-csv <output.csv> [--table T] # CSV export
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---- Locations --------------------------------------------------------------

def repo_root() -> Path:
    """Walk up from CWD looking for .git or a marker."""
    p = Path.cwd().resolve()
    while p != p.parent:
        if (p / ".git").exists() or (p / ".specship").exists():
            return p
        p = p.parent
    return Path.cwd().resolve()


def ledger_dir() -> Path:
    d = repo_root() / ".specship" / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    return d


def jsonl_path() -> Path:
    return ledger_dir() / "events.jsonl"


def db_path() -> Path:
    return ledger_dir() / "index.db"


# ---- Event schema -----------------------------------------------------------

# Valid event types. Adding a new one: extend this set AND update the indexer.
# Unknown types are kept in JSONL but skipped in the SQLite index with a warning.
KNOWN_EVENT_TYPES = {
    "session_start",            # a slash command was invoked
    "session_end",              # the command completed (or was abandoned)
    "artifact_created",         # a spec/fix/investigation/contract file was created
    "artifact_updated",         # status change, metadata edit, etc.
    "decision_logged",          # /work made a non-obvious choice
    "decision_reviewed",        # /review-decisions recorded a verdict on a prior decision
    "drift_detected",           # /check found drift
    "gate_passed",              # a hook or pre-flight check accepted
    "gate_blocked",             # a hook or pre-flight check refused
    "gate_bypassed",            # --no-verify or similar
    "subagent_spawned",         # /ship dispatched a Task subagent
    "subagent_completed",       # subagent returned
    "verification_ran",         # a test/lint command ran with its outcome
    "lesson_encoded",           # an invariant was added to CLAUDE.md / skill / command
    "breaking_change_detected", # /contract detected a structural breaking change
    "coverage_measured",        # /work or /fix measured test coverage
    "plan_drafted",             # /work --plan-only produced a plan awaiting approval (for /ship orchestration)
    "plan_approved",            # /ship orchestrator recorded human verdict on a drafted plan
    "plan_executing",           # /work --from-plan started executing a previously approved plan
    "qa_artifact_created",      # /qa created a regression/property/scenario artifact
    "qa_artifact_updated",      # status change on a QA artifact
    "qa_tests_generated",       # /qa generated runnable test file(s) from an artifact
    "qa_waiver_granted",        # human granted a waiver to bypass /ship Stage 0 QA gate
    "lesson_candidate",         # /capture-lessons recorded a lesson candidate
    "lesson_dismissed",         # /review-lessons rejected a candidate
    "lesson_promoted",          # a candidate was promoted via /encode-lesson --from-candidate
    "lesson_decayed",           # curate.py expired an un-actioned candidate
    "lessons_curated",          # curate.py completed a curator run
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_event(event_type: str, **fields: Any) -> dict[str, Any]:
    """
    Append one event to events.jsonl. Returns the event dict written.

    Required fields always present:
      ts          ISO-8601 UTC timestamp
      event_id    UUID4
      event_type  one of KNOWN_EVENT_TYPES (or arbitrary; JSONL accepts all)

    Caller supplies the rest via **fields.
    """
    event = {
        "ts": now_iso(),
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        **fields,
    }
    # O_APPEND is atomic at OS level for write() <= PIPE_BUF. JSON lines are
    # typically under PIPE_BUF (4096 bytes on Linux), so concurrent appends
    # interleave at line granularity, not within a line.
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(jsonl_path(), "a", encoding="utf-8") as f:
        f.write(line)
    return event


# ---- SQLite indexer ---------------------------------------------------------

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    session_id  TEXT,
    command     TEXT,
    artifact    TEXT,
    raw_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_ts          ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_type        ON events(event_type);
CREATE INDEX IF NOT EXISTS ix_events_session     ON events(session_id);
CREATE INDEX IF NOT EXISTS ix_events_artifact    ON events(artifact);

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    command           TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    outcome           TEXT,
    artifact_path     TEXT,
    scope             TEXT,
    parent_session_id TEXT,
    raw_args          TEXT
);

CREATE INDEX IF NOT EXISTS ix_sessions_command   ON sessions(command);
CREATE INDEX IF NOT EXISTS ix_sessions_outcome   ON sessions(outcome);
CREATE INDEX IF NOT EXISTS ix_sessions_started   ON sessions(started_at);

CREATE TABLE IF NOT EXISTS artifacts (
    path           TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    first_seen     TEXT NOT NULL,
    last_updated   TEXT NOT NULL,
    current_status TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id      TEXT PRIMARY KEY,
    ts               TEXT NOT NULL,
    session_id       TEXT,
    artifact         TEXT,
    summary          TEXT,
    rationale        TEXT,
    accepted         INTEGER,
    review_verdict   TEXT,    -- null | accepted | rejected | needs-redo
    reviewer_note    TEXT,
    reviewed_at      TEXT,
    reviewed_session TEXT
);

CREATE INDEX IF NOT EXISTS ix_decisions_artifact ON decisions(artifact);
CREATE INDEX IF NOT EXISTS ix_decisions_verdict  ON decisions(review_verdict);

CREATE TABLE IF NOT EXISTS lessons (
    lesson_id            TEXT PRIMARY KEY,
    ts                   TEXT NOT NULL,
    session_id           TEXT,
    destination_path     TEXT NOT NULL,
    source_investigation TEXT,
    source_fix           TEXT,
    lesson_text          TEXT
);

CREATE INDEX IF NOT EXISTS ix_lessons_dest        ON lessons(destination_path);
CREATE INDEX IF NOT EXISTS ix_lessons_investigation ON lessons(source_investigation);

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

CREATE TABLE IF NOT EXISTS breaking_changes (
    event_id        TEXT PRIMARY KEY,
    ts              TEXT NOT NULL,
    session_id      TEXT,
    artifact        TEXT,
    tool            TEXT,
    breaking        INTEGER,
    findings_count  INTEGER
);

CREATE INDEX IF NOT EXISTS ix_breaking_ts ON breaking_changes(ts);

CREATE TABLE IF NOT EXISTS coverage (
    event_id          TEXT PRIMARY KEY,
    ts                TEXT NOT NULL,
    session_id        TEXT,
    artifact          TEXT,
    tool              TEXT,
    metric            TEXT,             -- 'line' | 'branch' | 'both'
    line_pct          REAL,
    branch_pct        REAL,
    delta_pct         REAL,             -- coverage of code changed in this session
    project_pct       REAL,             -- overall project coverage after this session
    files_measured    INTEGER,
    threshold_delta   REAL,             -- the configured gating threshold
    threshold_project REAL,             -- the configured project floor (informational)
    passed            INTEGER,          -- 1 if delta_pct >= threshold_delta, else 0
    excluded_paths    TEXT              -- JSON array of exclusion globs used
);

CREATE INDEX IF NOT EXISTS ix_coverage_ts ON coverage(ts);
CREATE INDEX IF NOT EXISTS ix_coverage_artifact ON coverage(artifact);
CREATE INDEX IF NOT EXISTS ix_coverage_passed ON coverage(passed);

CREATE TABLE IF NOT EXISTS plans (
    plan_id           TEXT PRIMARY KEY,
    drafted_at        TEXT NOT NULL,
    drafted_session   TEXT,
    parent_session    TEXT,
    scope             TEXT,
    source_artifact   TEXT,
    plan_path         TEXT,
    files_to_modify   TEXT,                 -- JSON array
    estimated_decisions INTEGER,
    verdict           TEXT,                 -- 'approved' | 'rejected' | 'changes-requested' | NULL
    reviewer_note     TEXT,
    reviewed_at       TEXT,
    executed_at       TEXT,                 -- set when plan_executing fires
    executing_session TEXT
);

CREATE INDEX IF NOT EXISTS ix_plans_verdict ON plans(verdict);
CREATE INDEX IF NOT EXISTS ix_plans_source ON plans(source_artifact);
CREATE INDEX IF NOT EXISTS ix_plans_parent ON plans(parent_session);

CREATE TABLE IF NOT EXISTS qa_artifacts (
    path             TEXT PRIMARY KEY,
    kind             TEXT,    -- 'regression' | 'property' | 'scenario'
    parent_intent    TEXT,    -- spec/fix/investigation that motivated this
    current_status   TEXT,    -- 'draft' | 'approved' | 'generated' | 'retired'
    test_file_path   TEXT,    -- the generated test file, if any
    generator_used   TEXT,    -- 'pytest' | 'jest' | 'hypothesis' | 'fast-check'
    language         TEXT,    -- 'python' | 'typescript'
    first_seen       TEXT,
    last_updated     TEXT
);
CREATE INDEX IF NOT EXISTS ix_qa_kind ON qa_artifacts(kind);
CREATE INDEX IF NOT EXISTS ix_qa_parent ON qa_artifacts(parent_intent);

CREATE TABLE IF NOT EXISTS qa_waivers (
    event_id                 TEXT PRIMARY KEY,
    session_id               TEXT,
    target_intent            TEXT NOT NULL,
    waiver_granted_by        TEXT,
    reason                   TEXT,
    target_resolution_date   TEXT,
    ts                       TEXT
);
CREATE INDEX IF NOT EXISTS ix_waivers_target ON qa_waivers(target_intent);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def index_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    """Project one event into the appropriate SQLite tables."""
    et = event.get("event_type")
    ts = event.get("ts")
    eid = event.get("event_id")
    session_id = event.get("session_id")
    command = event.get("command")
    artifact = event.get("artifact") or event.get("artifact_path")

    # Always insert into events table
    conn.execute(
        "INSERT OR REPLACE INTO events "
        "(event_id, ts, event_type, session_id, command, artifact, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eid, ts, et, session_id, command, artifact, json.dumps(event)),
    )

    if et == "session_start":
        conn.execute(
            "INSERT OR REPLACE INTO sessions "
            "(session_id, command, started_at, artifact_path, scope, "
            " parent_session_id, raw_args) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, command, ts,
                event.get("artifact_path"),
                event.get("scope"),
                event.get("parent_session_id"),
                json.dumps(event.get("args", [])),
            ),
        )
    elif et == "session_end":
        conn.execute(
            "UPDATE sessions SET ended_at = ?, outcome = ? "
            "WHERE session_id = ?",
            (ts, event.get("outcome"), session_id),
        )
    elif et in ("artifact_created", "artifact_updated"):
        path = event.get("path") or artifact
        if path:
            conn.execute(
                "INSERT INTO artifacts (path, kind, first_seen, last_updated, current_status) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "  last_updated = excluded.last_updated, "
                "  current_status = COALESCE(excluded.current_status, artifacts.current_status)",
                (
                    path,
                    event.get("kind") or _infer_kind(path),
                    ts, ts,
                    event.get("status"),
                ),
            )
    elif et == "decision_logged":
        conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(decision_id, ts, session_id, artifact, summary, rationale, accepted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eid, ts, session_id, artifact,
                event.get("summary"),
                event.get("rationale"),
                1 if event.get("accepted") else 0 if event.get("accepted") is False else None,
            ),
        )
    elif et == "decision_reviewed":
        # Layer the review verdict on top of the (previously-logged) decision.
        # If the original decision_logged event hasn't been indexed yet (e.g.
        # this is a partial rebuild), we still want the verdict to land — so
        # we insert a stub row that future indexing will fill in.
        target_id = event.get("decision_id")
        if target_id:
            conn.execute(
                "INSERT INTO decisions "
                "(decision_id, ts, review_verdict, reviewer_note, reviewed_at, reviewed_session) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(decision_id) DO UPDATE SET "
                "  review_verdict = excluded.review_verdict, "
                "  reviewer_note = excluded.reviewer_note, "
                "  reviewed_at = excluded.reviewed_at, "
                "  reviewed_session = excluded.reviewed_session",
                (
                    target_id, ts,
                    event.get("verdict"),
                    event.get("reviewer_note"),
                    ts,
                    session_id,
                ),
            )
    elif et == "lesson_encoded":
        lesson_id = event.get("lesson_id") or eid
        conn.execute(
            "INSERT OR REPLACE INTO lessons "
            "(lesson_id, ts, session_id, destination_path, "
            " source_investigation, source_fix, lesson_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                lesson_id, ts, session_id,
                event.get("destination_path"),
                event.get("source_investigation"),
                event.get("source_fix"),
                event.get("lesson_text"),
            ),
        )
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
    elif et == "breaking_change_detected":
        conn.execute(
            "INSERT OR REPLACE INTO breaking_changes "
            "(event_id, ts, session_id, artifact, tool, breaking, findings_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eid, ts, session_id, artifact,
                event.get("tool"),
                1 if event.get("breaking") else 0,
                event.get("findings_count") or 0,
            ),
        )
    elif et == "coverage_measured":
        conn.execute(
            "INSERT OR REPLACE INTO coverage "
            "(event_id, ts, session_id, artifact, tool, metric, "
            " line_pct, branch_pct, delta_pct, project_pct, "
            " files_measured, threshold_delta, threshold_project, "
            " passed, excluded_paths) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eid, ts, session_id, artifact,
                event.get("tool"),
                event.get("metric"),
                event.get("line_pct"),
                event.get("branch_pct"),
                event.get("delta_pct"),
                event.get("project_pct"),
                event.get("files_measured") or 0,
                event.get("threshold_delta"),
                event.get("threshold_project"),
                1 if event.get("passed") else 0,
                json.dumps(event.get("excluded_paths") or []),
            ),
        )
    elif et == "plan_drafted":
        conn.execute(
            "INSERT OR REPLACE INTO plans "
            "(plan_id, drafted_at, drafted_session, parent_session, "
            " scope, source_artifact, plan_path, files_to_modify, "
            " estimated_decisions, verdict, reviewer_note, reviewed_at, "
            " executed_at, executing_session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)",
            (
                event.get("plan_id"),
                ts,
                session_id,
                event.get("parent_session_id"),
                event.get("scope"),
                event.get("source_artifact"),
                event.get("plan_path"),
                json.dumps(event.get("files_to_modify") or []),
                event.get("estimated_decisions") or 0,
            ),
        )
    elif et == "plan_approved":
        # Layer the verdict onto an existing plans row (created by plan_drafted)
        conn.execute(
            "UPDATE plans SET verdict = ?, reviewer_note = ?, reviewed_at = ? "
            "WHERE plan_id = ?",
            (
                event.get("verdict"),
                event.get("reviewer_note"),
                ts,
                event.get("plan_id"),
            ),
        )
    elif et == "plan_executing":
        # Layer execution onto an existing plans row
        conn.execute(
            "UPDATE plans SET executed_at = ?, executing_session = ? "
            "WHERE plan_id = ?",
            (
                ts,
                session_id,
                event.get("plan_id"),
            ),
        )

    elif et == "qa_artifact_created":
        path = event.get("path") or event.get("artifact")
        if not path:
            return
        conn.execute(
            "INSERT OR IGNORE INTO qa_artifacts "
            "(path, kind, parent_intent, current_status, first_seen, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                path,
                event.get("kind"),
                event.get("parent_intent"),
                event.get("status") or "draft",
                ts,
                ts,
            ),
        )

    elif et == "qa_artifact_updated":
        path = event.get("path") or event.get("artifact")
        if not path:
            return
        new_status = event.get("status")
        if new_status:
            conn.execute(
                "UPDATE qa_artifacts SET current_status = ?, last_updated = ? WHERE path = ?",
                (new_status, ts, path),
            )
        else:
            conn.execute(
                "UPDATE qa_artifacts SET last_updated = ? WHERE path = ?",
                (ts, path),
            )

    elif et == "qa_tests_generated":
        qa_path = event.get("qa_artifact_path") or event.get("path")
        if not qa_path:
            return
        conn.execute(
            "UPDATE qa_artifacts SET test_file_path = ?, generator_used = ?, "
            "language = ?, current_status = ?, last_updated = ? WHERE path = ?",
            (
                event.get("test_file_path"),
                event.get("generator_used"),
                event.get("language"),
                "generated",
                ts,
                qa_path,
            ),
        )

    elif et == "qa_waiver_granted":
        target = event.get("target_intent")
        if not target:
            return
        conn.execute(
            "INSERT OR REPLACE INTO qa_waivers "
            "(event_id, session_id, target_intent, waiver_granted_by, reason, "
            "target_resolution_date, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eid,
                session_id,
                target,
                event.get("waiver_granted_by"),
                event.get("reason"),
                event.get("target_resolution_date"),
                ts,
            ),
        )


def _infer_kind(path: str) -> str:
    if path.startswith("specs/"):
        return "spec"
    if path.startswith("fixes/"):
        return "fix"
    if path.startswith("investigations/"):
        return "investigation"
    if path.startswith("post-mortems/"):
        return "post-mortem"
    if path.startswith("_generated/"):
        return "contract-artifact"
    return "other"


def rebuild_index() -> tuple[int, int, list[str]]:
    """Drop and recreate the SQLite index from the JSONL log.

    Returns (events_indexed, events_skipped, warnings).
    """
    if db_path().exists():
        db_path().unlink()
    conn = open_db()
    conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                 ("rebuilt_at", now_iso()))

    indexed = 0
    skipped = 0
    warnings: list[str] = []

    if not jsonl_path().exists():
        conn.commit()
        return 0, 0, ["no events.jsonl found; index is empty"]

    with open(jsonl_path(), "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                warnings.append(f"line {lineno}: malformed JSON ({e})")
                skipped += 1
                continue
            if event.get("event_type") not in KNOWN_EVENT_TYPES:
                # Keep in events table but don't project to specialised tables
                warnings.append(
                    f"line {lineno}: unknown event_type "
                    f"{event.get('event_type')!r} — stored raw"
                )
            try:
                index_event(conn, event)
                indexed += 1
            except sqlite3.Error as e:
                warnings.append(f"line {lineno}: index failure ({e})")
                skipped += 1

    conn.commit()
    conn.close()
    return indexed, skipped, warnings


# ---- Summary / report -------------------------------------------------------

def summary(since: str | None = None) -> str:
    """Human-readable summary of recent ledger activity."""
    if not db_path().exists():
        rebuild_index()
    conn = open_db()
    where = ""
    params: tuple = ()
    if since:
        where = "WHERE started_at >= ?"
        params = (since,)

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("specship ledger summary")
    if since:
        lines.append(f"(events since {since})")
    lines.append("=" * 60)

    # Sessions by command
    rows = conn.execute(
        f"SELECT command, COUNT(*) AS n, "
        f"  SUM(CASE WHEN outcome = 'completed' THEN 1 ELSE 0 END) AS completed, "
        f"  SUM(CASE WHEN outcome = 'blocked' THEN 1 ELSE 0 END) AS blocked, "
        f"  SUM(CASE WHEN outcome = 'abandoned' THEN 1 ELSE 0 END) AS abandoned "
        f"FROM sessions {where} GROUP BY command ORDER BY n DESC",
        params,
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Sessions by command:")
        lines.append(f"  {'command':<14}{'total':>8}{'completed':>12}{'blocked':>10}{'abandoned':>12}")
        for r in rows:
            lines.append(
                f"  {(r['command'] or '?'):<14}{r['n']:>8}"
                f"{r['completed'] or 0:>12}{r['blocked'] or 0:>10}{r['abandoned'] or 0:>12}"
            )

    # Artifacts by kind
    rows = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM artifacts GROUP BY kind ORDER BY n DESC"
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Artifacts tracked:")
        for r in rows:
            lines.append(f"  {r['kind']:<20} {r['n']}")

    # Gate activity
    rows = conn.execute(
        f"SELECT event_type, COUNT(*) AS n FROM events "
        f"WHERE event_type IN ('gate_blocked', 'gate_bypassed', 'drift_detected') "
        f"{'AND ts >= ?' if since else ''} "
        f"GROUP BY event_type",
        params if since else (),
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Gate activity:")
        for r in rows:
            lines.append(f"  {r['event_type']:<20} {r['n']}")

    # Recent decisions
    rows = conn.execute(
        f"SELECT ts, summary, accepted, review_verdict FROM decisions "
        f"{where if 'started_at' not in where else where.replace('started_at', 'ts')} "
        f"ORDER BY ts DESC LIMIT 5",
        params,
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Recent decisions:")
        for r in rows:
            mark = {1: "✓", 0: "✗", None: "?"}[r["accepted"]]
            verdict_mark = {
                "accepted": "→ ✓",
                "rejected": "→ ✗",
                "needs-redo": "→ ↻",
                None: "→ ?",
            }.get(r["review_verdict"], "→ ?")
            lines.append(
                f"  {r['ts']}  {mark} {verdict_mark}  "
                f"{(r['summary'] or '')[:55]}"
            )

    # Decision reviews
    rows = conn.execute(
        "SELECT review_verdict, COUNT(*) AS n FROM decisions "
        "WHERE review_verdict IS NOT NULL GROUP BY review_verdict"
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Decision reviews:")
        for r in rows:
            lines.append(f"  {r['review_verdict']:<14} {r['n']}")

    # Lessons encoded
    rows = conn.execute(
        "SELECT lesson_id, destination_path, source_investigation, ts "
        "FROM lessons ORDER BY ts DESC LIMIT 10"
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Lessons encoded:")
        for r in rows:
            lines.append(
                f"  {r['lesson_id'][:12]}  → {r['destination_path']}"
                f"  (from {r['source_investigation']})"
            )

    # Breaking-change checks
    rows = conn.execute(
        "SELECT tool, "
        "  SUM(CASE WHEN breaking = 1 THEN 1 ELSE 0 END) AS breaking_n, "
        "  SUM(CASE WHEN breaking = 0 THEN 1 ELSE 0 END) AS clean_n "
        "FROM breaking_changes GROUP BY tool"
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Breaking-change checks (/contract):")
        for r in rows:
            lines.append(
                f"  tool={r['tool']:<10} clean={r['clean_n'] or 0}  "
                f"breaking={r['breaking_n'] or 0}"
            )

    # Coverage measurements
    rows = conn.execute(
        "SELECT COUNT(*) AS n, "
        "  SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed_n, "
        "  SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS failed_n, "
        "  AVG(delta_pct) AS avg_delta, "
        "  AVG(project_pct) AS avg_project "
        "FROM coverage"
    ).fetchall()
    if rows and rows[0]['n']:
        r = rows[0]
        lines.append("")
        lines.append("Coverage measurements:")
        lines.append(
            f"  total: {r['n']}  passed: {r['passed_n'] or 0}  "
            f"failed: {r['failed_n'] or 0}"
        )
        if r['avg_delta'] is not None:
            lines.append(
                f"  avg delta coverage:   {r['avg_delta']:.1f}%"
            )
        if r['avg_project'] is not None:
            lines.append(
                f"  avg project coverage: {r['avg_project']:.1f}%"
            )

    # Recent coverage failures (most useful for fixing)
    rows = conn.execute(
        "SELECT ts, artifact, delta_pct, threshold_delta, tool "
        "FROM coverage WHERE passed = 0 "
        "ORDER BY ts DESC LIMIT 5"
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("Recent coverage failures:")
        for r in rows:
            lines.append(
                f"  {r['ts']}  {r['artifact'] or '?'}  "
                f"{r['delta_pct']:.1f}% < {r['threshold_delta']:.1f}%  ({r['tool']})"
            )

    # /ship plan approval activity
    rows = conn.execute(
        "SELECT COUNT(*) AS total, "
        "  SUM(CASE WHEN verdict = 'approved' THEN 1 ELSE 0 END) AS approved, "
        "  SUM(CASE WHEN verdict = 'rejected' THEN 1 ELSE 0 END) AS rejected, "
        "  SUM(CASE WHEN verdict = 'changes-requested' THEN 1 ELSE 0 END) AS changes, "
        "  SUM(CASE WHEN verdict IS NULL THEN 1 ELSE 0 END) AS pending, "
        "  SUM(CASE WHEN executed_at IS NOT NULL THEN 1 ELSE 0 END) AS executed "
        "FROM plans"
    ).fetchall()
    if rows and rows[0]['total']:
        r = rows[0]
        lines.append("")
        lines.append("/ship plan approvals:")
        lines.append(
            f"  total drafted: {r['total']}  "
            f"approved: {r['approved'] or 0}  "
            f"rejected: {r['rejected'] or 0}  "
            f"changes-requested: {r['changes'] or 0}  "
            f"pending: {r['pending'] or 0}"
        )
        lines.append(f"  executed: {r['executed'] or 0} of {r['approved'] or 0} approved")

    # QA artifacts
    rows = conn.execute(
        "SELECT kind, COUNT(*) AS n, "
        "SUM(CASE WHEN current_status = 'generated' THEN 1 ELSE 0 END) AS generated "
        "FROM qa_artifacts GROUP BY kind ORDER BY n DESC"
    ).fetchall()
    if rows:
        lines.append("")
        lines.append("QA artifacts:")
        for r in rows:
            kind = r['kind'] or 'unknown'
            lines.append(f"  {kind:<14} {r['n']:>3}  (generated tests: {r['generated'] or 0})")

    # QA waivers
    waivers = conn.execute(
        "SELECT COUNT(*) AS total FROM qa_waivers"
    ).fetchone()
    if waivers and waivers['total']:
        lines.append("")
        lines.append(f"QA waivers granted: {waivers['total']}")

    conn.close()
    return "\n".join(lines)


# ---- CLI --------------------------------------------------------------------

def cmd_log(args: argparse.Namespace) -> int:
    fields: dict[str, Any] = {}
    for kv in args.fields:
        if "=" not in kv:
            print(f"bad field {kv!r} — use key=value", file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        # Try to parse as JSON; fall back to string
        try:
            fields[k] = json.loads(v)
        except json.JSONDecodeError:
            fields[k] = v
    event = append_event(args.event_type, **fields)
    if args.quiet:
        print(event["event_id"])
    else:
        print(json.dumps(event, indent=2))
    return 0


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    indexed, skipped, warnings = rebuild_index()
    print(f"Indexed: {indexed}")
    print(f"Skipped: {skipped}")
    for w in warnings[:20]:
        print(f"  ! {w}", file=sys.stderr)
    if len(warnings) > 20:
        print(f"  ... and {len(warnings) - 20} more warnings", file=sys.stderr)
    return 0 if skipped == 0 else 1


def cmd_query(args: argparse.Namespace) -> int:
    if not db_path().exists():
        rebuild_index()
    conn = open_db()
    try:
        rows = conn.execute(args.sql).fetchall()
    except sqlite3.Error as e:
        print(f"SQL error: {e}", file=sys.stderr)
        return 2
    if not rows:
        print("(no rows)")
        return 0
    cols = rows[0].keys()
    widths = [max(len(c), max(len(str(r[c])) for r in rows)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    print(summary(since=args.since))
    return 0


def cmd_export_csv(args: argparse.Namespace) -> int:
    import csv
    if not db_path().exists():
        rebuild_index()
    conn = open_db()
    rows = conn.execute(f"SELECT * FROM {args.table}").fetchall()
    if not rows:
        print(f"(no rows in {args.table})")
        return 0
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys())
        for r in rows:
            w.writerow([r[c] for c in rows[0].keys()])
    print(f"Wrote {len(rows)} rows to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="specship observability ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("log", help="append an event")
    lp.add_argument("event_type", help="event type (see KNOWN_EVENT_TYPES)")
    lp.add_argument("fields", nargs="*", help="key=value pairs; value parsed as JSON if possible")
    lp.add_argument("--quiet", action="store_true", help="print only the event_id")
    lp.set_defaults(func=cmd_log)

    rp = sub.add_parser("rebuild-index", help="rebuild SQLite from JSONL")
    rp.set_defaults(func=cmd_rebuild_index)

    qp = sub.add_parser("query", help="run SQL against the index")
    qp.add_argument("sql", help="SQL query")
    qp.set_defaults(func=cmd_query)

    sp = sub.add_parser("summary", help="human-readable digest")
    sp.add_argument("--since", help="ISO date/datetime; show only events at or after")
    sp.set_defaults(func=cmd_summary)

    ep = sub.add_parser("export-csv", help="export a table to CSV")
    ep.add_argument("output", help="output file path")
    ep.add_argument("--table", default="sessions",
                    choices=["sessions", "events", "artifacts", "decisions",
                             "lessons", "breaking_changes", "coverage", "plans"])
    ep.set_defaults(func=cmd_export_csv)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

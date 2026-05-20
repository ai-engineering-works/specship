#!/usr/bin/env python3
"""assert.py — verification helpers for the e2e harness.

Subcommands operate on a TARGET repo's ledger. `count` rebuilds the SQLite
index first, then runs a COUNT(*) and compares with an operator. Exit 0 on
pass, 1 on fail (with a diff message on stderr).

    assert.py count <target> <table> --where "<sql>" --op ge --n 1
    assert.py event <target> <event_type> --op ge --n 1
    assert.py rebuild <target>
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from pathlib import Path

OPS = {
    "eq": lambda a, b: a == b,
    "ge": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "le": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
}


def ledger(target: str) -> Path:
    return Path(target) / ".specship" / "ledger" / "specship_ledger.py"


def rebuild(target: str) -> None:
    subprocess.run(
        ["python3", str(ledger(target)), "rebuild-index"],
        check=True, capture_output=True, text=True,
        cwd=target,
    )


def db(target: str) -> sqlite3.Connection:
    return sqlite3.connect(Path(target) / ".specship" / "ledger" / "index.db")


def do_count(target: str, table: str, where: str, op: str, n: int) -> int:
    rebuild(target)
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    with db(target) as conn:
        actual = conn.execute(sql).fetchone()[0]
    if OPS[op](actual, n):
        print(f"PASS {table}: {actual} {op} {n}  ({where or 'all'})")
        return 0
    print(f"FAIL {table}: got {actual}, expected {op} {n}  ({where or 'all'})", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("count")
    c.add_argument("target"); c.add_argument("table")
    c.add_argument("--where", default=""); c.add_argument("--op", default="ge", choices=OPS)
    c.add_argument("--n", type=int, default=1)
    e = sub.add_parser("event")
    e.add_argument("target"); e.add_argument("event_type")
    e.add_argument("--op", default="ge", choices=OPS); e.add_argument("--n", type=int, default=1)
    r = sub.add_parser("rebuild"); r.add_argument("target")
    a = p.parse_args()

    if a.cmd == "rebuild":
        rebuild(a.target); return 0
    if a.cmd == "count":
        return do_count(a.target, a.table, a.where, a.op, a.n)
    if a.cmd == "event":
        where = f"event_type = '{a.event_type}'"
        return do_count(a.target, "events", where, a.op, a.n)
    return 2


if __name__ == "__main__":
    sys.exit(main())

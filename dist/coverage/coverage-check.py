#!/usr/bin/env python3
"""
coverage-check.py — measure test coverage and produce a structured result

This script is invoked by /work and /fix in their post-flight verification step.
It is a thin wrapper around the project's actual coverage tool — specship does
not implement coverage measurement itself. The wrapper:

  1. Reads coverage policy from CLAUDE.md
  2. Locates the coverage report (or runs the tool to produce one)
  3. Parses the report (supports JSON from coverage.py and lcov from JS)
  4. Computes delta coverage by intersecting changed lines (git diff) with
     covered/uncovered lines from the report
  5. Returns a structured JSON result for the caller to use

The result conforms to a shape the ledger's `coverage_measured` event expects.

Usage:
    python3 coverage-check.py [--report PATH] [--format json|lcov|auto]
                              [--base BASE_REF] [--threshold N] [--project-floor N]
                              [--excluded PATTERN]... [--quiet]

Output: JSON to stdout. Exit code:
    0 = measurement succeeded (passed or not — content of output indicates)
    1 = tool error (couldn't run, couldn't parse, no report found)
    2 = bad arguments

Output JSON schema:
    {
        "tool": "coverage.py" | "lcov" | ...,
        "metric": "line" | "branch" | "both",
        "line_pct": float,
        "branch_pct": float | null,
        "delta_pct": float,
        "project_pct": float,
        "files_measured": int,
        "threshold_delta": float,
        "threshold_project": float,
        "passed": bool,
        "uncovered_lines": [{"file": str, "lines": [int, ...]}, ...],
        "excluded_paths": [str, ...],
        "summary": str
    }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---- CLAUDE.md policy reader ------------------------------------------------

DEFAULT_THRESHOLD_DELTA = 90.0
DEFAULT_THRESHOLD_PROJECT = 80.0
DEFAULT_EXCLUDED = ["_generated/**", "tests/**", "test/**", "migrations/**"]


def read_policy_from_claude_md() -> dict[str, Any]:
    """
    Look for a Coverage policy section in CLAUDE.md and extract values.
    Returns defaults for anything not declared. Tolerant of missing CLAUDE.md.

    Expected format:
        ## Coverage policy
        - **Metric**: line
        - **Threshold**: 90
        - **Project floor**: 80
        - **Tool**: pytest --cov=src --cov-report=json
        - **Excluded paths**: _generated/**, tests/**
    """
    policy = {
        "metric": "line",
        "threshold_delta": DEFAULT_THRESHOLD_DELTA,
        "threshold_project": DEFAULT_THRESHOLD_PROJECT,
        "tool_command": None,
        "report_path": None,
        "excluded_paths": list(DEFAULT_EXCLUDED),
    }

    claude_md = Path("CLAUDE.md")
    if not claude_md.exists():
        return policy

    try:
        text = claude_md.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return policy

    # Find the Coverage policy section
    m = re.search(r"^##\s+Coverage policy\s*$(.*?)(?=^##\s|\Z)",
                  text, re.MULTILINE | re.DOTALL)
    if not m:
        return policy

    section = m.group(1)

    def grab(label: str) -> str | None:
        match = re.search(rf"\*\*{re.escape(label)}\*\*:?\s*([^\n]+)", section)
        if not match:
            return None
        val = match.group(1).strip()
        # Strip placeholder-y values
        if val.startswith("<") or val.startswith("[e.g.") or not val:
            return None
        return val

    metric = grab("Metric")
    if metric and metric.lower() in ("line", "branch", "both"):
        policy["metric"] = metric.lower()

    threshold = grab("Threshold")
    if threshold:
        try:
            policy["threshold_delta"] = float(threshold.rstrip("%").strip())
        except ValueError:
            pass

    floor = grab("Project floor")
    if floor:
        try:
            policy["threshold_project"] = float(floor.rstrip("%").strip())
        except ValueError:
            pass

    tool = grab("Tool")
    if tool:
        policy["tool_command"] = tool

    report = grab("Report path") or grab("Report")
    if report:
        policy["report_path"] = report

    excluded = grab("Excluded paths") or grab("Exclude")
    if excluded:
        policy["excluded_paths"] = [p.strip() for p in excluded.split(",") if p.strip()]

    return policy


# ---- Report parsers ---------------------------------------------------------

def parse_coverage_py_json(path: Path) -> dict[str, Any]:
    """
    Parse a coverage.py JSON report (`pytest --cov-report=json` or
    `coverage json`). Returns a normalised dict.

    The shape we produce:
      {
          "tool": "coverage.py",
          "line_pct": float,
          "branch_pct": float | None,
          "files": {path: {"covered_lines": [int], "uncovered_lines": [int]}},
      }
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    totals = data.get("totals", {})
    line_pct = float(totals.get("percent_covered", 0.0))
    branch_pct = None
    if "covered_branches" in totals and "num_branches" in totals:
        if totals["num_branches"]:
            branch_pct = (
                100.0 * totals["covered_branches"] / totals["num_branches"]
            )

    files_data = {}
    for fpath, info in (data.get("files") or {}).items():
        files_data[fpath] = {
            "covered_lines": info.get("executed_lines", []),
            "uncovered_lines": info.get("missing_lines", []),
        }

    return {
        "tool": "coverage.py",
        "line_pct": line_pct,
        "branch_pct": branch_pct,
        "files": files_data,
    }


def parse_lcov(path: Path) -> dict[str, Any]:
    """
    Parse an lcov.info file (common output from JS coverage tools).
    Returns the same normalised dict shape.

    lcov format is line-oriented:
        SF:<file path>
        DA:<line number>,<execution count>
        BRDA:<line>,<block>,<branch>,<taken>
        end_of_record
    """
    files_data: dict[str, dict[str, list[int]]] = {}
    total_lines_found = 0
    total_lines_hit = 0
    total_branches_found = 0
    total_branches_hit = 0

    current_file: str | None = None
    current_covered: list[int] = []
    current_uncovered: list[int] = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                current_file = line[3:]
                current_covered = []
                current_uncovered = []
            elif line.startswith("DA:") and current_file:
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    try:
                        lineno = int(parts[0])
                        count = int(parts[1])
                        total_lines_found += 1
                        if count > 0:
                            total_lines_hit += 1
                            current_covered.append(lineno)
                        else:
                            current_uncovered.append(lineno)
                    except ValueError:
                        pass
            elif line.startswith("BRDA:"):
                parts = line[5:].split(",")
                if len(parts) >= 4:
                    total_branches_found += 1
                    if parts[3] != "-" and parts[3] != "0":
                        total_branches_hit += 1
            elif line == "end_of_record" and current_file:
                files_data[current_file] = {
                    "covered_lines": current_covered,
                    "uncovered_lines": current_uncovered,
                }
                current_file = None

    line_pct = (
        100.0 * total_lines_hit / total_lines_found
        if total_lines_found else 0.0
    )
    branch_pct = None
    if total_branches_found:
        branch_pct = 100.0 * total_branches_hit / total_branches_found

    return {
        "tool": "lcov",
        "line_pct": line_pct,
        "branch_pct": branch_pct,
        "files": files_data,
    }


# ---- Delta coverage computation ---------------------------------------------

def changed_lines_per_file(base_ref: str) -> dict[str, set[int]]:
    """
    Use `git diff` to determine which lines changed in each file since base_ref.
    Returns {file_path: {line_numbers_changed_in_new_version}}.

    If git is unavailable or there are no changes, returns {} — caller will
    fall back to project coverage as the gating metric.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=0", f"{base_ref}...HEAD"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        diff_text = result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    changed: dict[str, set[int]] = {}
    current_file: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            changed[current_file] = set()
        elif line.startswith("@@") and current_file:
            # @@ -X,Y +A,B @@  — we want the +A,B part (new file lines)
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                # Only non-zero counts mean lines were added/changed
                if count > 0:
                    for ln in range(start, start + count):
                        changed[current_file].add(ln)

    # Drop empty entries
    return {f: lines for f, lines in changed.items() if lines}


def compute_delta_coverage(
    report: dict[str, Any],
    changed: dict[str, set[int]],
    excluded_globs: list[str],
) -> tuple[float, int]:
    """
    Intersect covered/uncovered lines from the report with changed lines
    from git diff. Returns (delta_pct, files_measured_count).

    If no files in `changed` match the report, delta_pct falls back to
    project line_pct as a conservative default.
    """
    from fnmatch import fnmatch

    files_in_report = report.get("files") or {}
    if not changed:
        # No diff info; can't compute delta — return project pct as proxy
        return (report.get("line_pct", 0.0), len(files_in_report))

    total_changed = 0
    covered_changed = 0
    files_touched = 0

    for fpath, changed_lines in changed.items():
        # Skip excluded paths
        if any(fnmatch(fpath, pattern) for pattern in excluded_globs):
            continue

        # Try to find the file in the report. Coverage tools may use
        # different path styles (relative, absolute, with/without leading
        # slash). Match by suffix as fallback.
        file_data = files_in_report.get(fpath)
        if file_data is None:
            # Try suffix match
            for k in files_in_report:
                if k.endswith(fpath) or fpath.endswith(k):
                    file_data = files_in_report[k]
                    break

        if file_data is None:
            # File changed but no coverage data — it might be a non-code file
            # (markdown, yaml, config). Skip silently.
            continue

        covered = set(file_data.get("covered_lines", []))
        uncovered = set(file_data.get("uncovered_lines", []))
        executable = covered | uncovered

        # Only count executable lines (skip comments, blank lines)
        changed_executable = changed_lines & executable
        if not changed_executable:
            continue

        files_touched += 1
        total_changed += len(changed_executable)
        covered_changed += len(changed_executable & covered)

    if total_changed == 0:
        # No changed executable lines — by convention, delta is "passing"
        return (100.0, files_touched)

    return (100.0 * covered_changed / total_changed, files_touched)


# ---- Main -------------------------------------------------------------------

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--report", help="Path to coverage report (JSON or lcov)")
    p.add_argument("--format", default="auto",
                   choices=["auto", "json", "lcov"],
                   help="Report format. 'auto' detects from filename.")
    p.add_argument("--base", default="origin/main",
                   help="Git ref to diff against for delta coverage")
    p.add_argument("--threshold", type=float,
                   help="Override threshold_delta from CLAUDE.md")
    p.add_argument("--project-floor", type=float,
                   help="Override threshold_project from CLAUDE.md")
    p.add_argument("--excluded", action="append", default=[],
                   help="Additional excluded path glob (repeatable)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv[1:])

    policy = read_policy_from_claude_md()
    if args.threshold is not None:
        policy["threshold_delta"] = args.threshold
    if args.project_floor is not None:
        policy["threshold_project"] = args.project_floor
    policy["excluded_paths"] = policy["excluded_paths"] + list(args.excluded)

    # Locate the report
    report_path = args.report or policy.get("report_path")
    if not report_path:
        # Try a couple of common defaults
        for candidate in ["coverage.json", "coverage/coverage.json",
                          "coverage/lcov.info", "lcov.info",
                          ".coverage.json"]:
            if Path(candidate).exists():
                report_path = candidate
                break

    if not report_path or not Path(report_path).exists():
        print(json.dumps({
            "tool": "none",
            "summary": "No coverage report found. Run the project's coverage "
                       "command first, or pass --report PATH.",
            "passed": False,
        }))
        return 1

    # Detect format
    fmt = args.format
    if fmt == "auto":
        if report_path.endswith(".json"):
            fmt = "json"
        elif report_path.endswith((".info", ".lcov")):
            fmt = "lcov"
        else:
            # Try JSON first, fall back to lcov
            try:
                with open(report_path, "r") as f:
                    f.read(1)
                fmt = "json"
            except Exception:
                fmt = "lcov"

    # Parse
    try:
        if fmt == "json":
            report = parse_coverage_py_json(Path(report_path))
        else:
            report = parse_lcov(Path(report_path))
    except Exception as e:
        print(json.dumps({
            "tool": "unknown",
            "summary": f"Failed to parse coverage report: {e}",
            "passed": False,
        }))
        return 1

    # Compute delta
    changed = changed_lines_per_file(args.base)
    delta_pct, files_touched = compute_delta_coverage(
        report, changed, policy["excluded_paths"]
    )

    project_pct = report.get("line_pct", 0.0)
    threshold_delta = policy["threshold_delta"]
    threshold_project = policy["threshold_project"]

    # Decision: delta is the gate; project is informational
    passed = delta_pct >= threshold_delta

    # Build uncovered-lines payload for the failure case
    uncovered = []
    if not passed:
        for fpath, changed_lines in changed.items():
            file_data = report.get("files", {}).get(fpath)
            if not file_data:
                # try suffix match
                for k in report.get("files", {}):
                    if k.endswith(fpath) or fpath.endswith(k):
                        file_data = report["files"][k]
                        break
            if file_data:
                uncov = sorted(
                    set(file_data.get("uncovered_lines", [])) & changed_lines
                )
                if uncov:
                    uncovered.append({"file": fpath, "lines": uncov})

    summary_parts = [
        f"delta: {delta_pct:.1f}% (threshold {threshold_delta:.1f}%)",
        f"project: {project_pct:.1f}% (floor {threshold_project:.1f}%)",
        f"files: {files_touched}",
    ]
    if not passed:
        summary_parts.append("FAIL")

    result = {
        "tool": report["tool"],
        "metric": policy["metric"],
        "line_pct": project_pct,
        "branch_pct": report.get("branch_pct"),
        "delta_pct": delta_pct,
        "project_pct": project_pct,
        "files_measured": files_touched,
        "threshold_delta": threshold_delta,
        "threshold_project": threshold_project,
        "passed": passed,
        "uncovered_lines": uncovered,
        "excluded_paths": policy["excluded_paths"],
        "summary": " | ".join(summary_parts),
    }

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

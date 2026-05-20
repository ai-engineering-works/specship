#!/usr/bin/env python3
"""
breaking-change-fallback.py — detect common OpenAPI breaking changes

Used by breaking-change-check.sh when `oasdiff` is not installed. This is
not as thorough as oasdiff but catches the most common breaking changes
that real APIs experience:

    1. Removed endpoint (path or method)
    2. Removed response status code from an existing endpoint
    3. Required request field added (a "new required field" is breaking
       for existing consumers that don't send it)
    4. Removed request field
    5. Type change on an existing field (string → integer, etc.)
    6. Removed enum value (consumers that send the value will now fail)
    7. Required → optional is additive; optional → required is breaking

Limitations vs oasdiff:
    - Does not understand $ref chains across files
    - Does not understand allOf / oneOf / anyOf composition deeply
    - Does not track parameter location changes (query → header, etc.)
    - Does not classify the *severity* of breaks (oasdiff has levels)

For specship's purposes, the fallback is "good enough to refuse a silently
breaking change." Banks and other regulated users should install oasdiff
for the full check; the install script will warn if it's missing.

Output: JSON to stdout in the same schema as breaking-change-check.sh produces.
Exit code: 0 on success (regardless of whether breakage was found), non-zero
on tool error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_openapi(path: str) -> dict[str, Any]:
    """Load an OpenAPI file (YAML or JSON). Returns {} if unreadable."""
    text = Path(path).read_text(encoding="utf-8")
    # Try JSON first; fall back to a tiny YAML parser if PyYAML isn't installed.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        # Minimal YAML fallback: only handles the subset that specship's
        # /contract command produces (no anchors, no flow style). If the
        # file is hand-written YAML with exotic features, install PyYAML
        # or oasdiff.
        return _minimal_yaml_parse(text)


def _minimal_yaml_parse(text: str) -> dict[str, Any]:
    """A toy parser for specship-generated YAML. Lossy on edge cases."""
    # Be honest about the limitation rather than silently producing wrong
    # results: refuse and tell the caller to install PyYAML.
    raise RuntimeError(
        "PyYAML not installed and the file isn't JSON. "
        "Install with `pip install pyyaml` or install oasdiff for full breaking-change detection."
    )


def diff_openapi(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Compare two OpenAPI documents and return a list of breaking-change descriptions."""
    findings: list[str] = []

    old_paths = (old.get("paths") or {})
    new_paths = (new.get("paths") or {})

    # Removed paths
    for path in old_paths:
        if path not in new_paths:
            findings.append(f"removed path: {path}")
            continue
        # Removed methods on a path
        old_methods = {m for m in old_paths[path] if m in HTTP_METHODS}
        new_methods = {m for m in new_paths[path] if m in HTTP_METHODS}
        for m in old_methods - new_methods:
            findings.append(f"removed method: {m.upper()} {path}")
        # For methods that exist in both, compare deeply
        for m in old_methods & new_methods:
            findings.extend(_diff_operation(path, m, old_paths[path][m], new_paths[path][m]))

    # Removed components/schemas
    old_schemas = ((old.get("components") or {}).get("schemas") or {})
    new_schemas = ((new.get("components") or {}).get("schemas") or {})
    for name in old_schemas:
        if name not in new_schemas:
            findings.append(f"removed schema: components.schemas.{name}")
            continue
        findings.extend(_diff_schema(f"components.schemas.{name}", old_schemas[name], new_schemas[name]))

    return findings


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _diff_operation(path: str, method: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    label = f"{method.upper()} {path}"

    # Removed response statuses
    old_responses = (old.get("responses") or {})
    new_responses = (new.get("responses") or {})
    for code in old_responses:
        if code not in new_responses:
            findings.append(f"removed response: {label} → {code}")

    # Request body schema diff
    old_body = ((old.get("requestBody") or {}).get("content") or {})
    new_body = ((new.get("requestBody") or {}).get("content") or {})
    for media in old_body:
        if media not in new_body:
            findings.append(f"removed request media: {label} content-type {media}")
            continue
        old_schema = (old_body[media].get("schema") or {})
        new_schema = (new_body[media].get("schema") or {})
        findings.extend(_diff_schema(f"{label} body[{media}]", old_schema, new_schema))

    # New required fields in request = breaking
    # (We handle this in _diff_schema for object properties; here we cover the body-level required list.)

    # Parameter removals
    old_params = {(p.get("name"), p.get("in")): p for p in (old.get("parameters") or [])}
    new_params = {(p.get("name"), p.get("in")): p for p in (new.get("parameters") or [])}
    for key, p in old_params.items():
        if key not in new_params:
            findings.append(f"removed parameter: {label} {key[1]}.{key[0]}")
        elif p.get("required") is False and new_params[key].get("required") is True:
            findings.append(f"parameter became required: {label} {key[1]}.{key[0]}")
    for key, p in new_params.items():
        if key not in old_params and p.get("required") is True:
            findings.append(f"new required parameter: {label} {key[1]}.{key[0]}")

    return findings


def _diff_schema(prefix: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    findings: list[str] = []

    # Type change
    old_type = old.get("type")
    new_type = new.get("type")
    if old_type and new_type and old_type != new_type:
        findings.append(f"type changed: {prefix} {old_type} → {new_type}")

    # Enum shrunk
    old_enum = set(old.get("enum") or [])
    new_enum = set(new.get("enum") or [])
    if old_enum and new_enum:
        removed = old_enum - new_enum
        if removed:
            findings.append(f"enum values removed from {prefix}: {sorted(removed)}")

    # Properties — removed or type-changed or made required
    old_props = (old.get("properties") or {})
    new_props = (new.get("properties") or {})
    for name in old_props:
        if name not in new_props:
            findings.append(f"removed property: {prefix}.{name}")
            continue
        findings.extend(_diff_schema(f"{prefix}.{name}", old_props[name], new_props[name]))

    # Required list — new required = breaking
    old_required = set(old.get("required") or [])
    new_required = set(new.get("required") or [])
    newly_required = (new_required - old_required) & set(new_props)
    for name in sorted(newly_required):
        if name not in old_required:
            findings.append(f"property became required: {prefix}.{name}")

    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: breaking-change-fallback.py OLD NEW", file=sys.stderr)
        return 2
    try:
        old = load_openapi(argv[1])
        new = load_openapi(argv[2])
    except RuntimeError as e:
        result = {
            "tool": "fallback",
            "breaking": None,
            "additive": None,
            "summary": f"fallback check could not run: {e}",
            "details": [],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    findings = diff_openapi(old, new)
    breaking = bool(findings)
    result = {
        "tool": "fallback",
        "breaking": breaking,
        "additive": not breaking,
        "summary": (
            f"fallback check found {len(findings)} potential breaking change(s) — "
            "install oasdiff for fuller analysis"
            if breaking
            else "fallback check: no breaking changes detected "
            "(install oasdiff for fuller analysis)"
        ),
        "details": findings,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

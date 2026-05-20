#!/usr/bin/env python3
"""property-pytest.py — generate a hypothesis property test from a property artifact.

Usage:
    python3 property-pytest.py <artifact-path> [--out tests/property/]

A property artifact declares:
  - An action (HTTP endpoint, function, or event)
  - Generators for each input field (DSL form, see below)
  - An invariant expression that must hold for ALL generated inputs
  - max_examples — how many cases hypothesis should generate

This generator parses the artifact's structured frontmatter, translates the
generator DSL to hypothesis strategies, and emits a runnable @given test.

DSL forms (v1):
  int(min: M, max: N)            -> st.integers(min_value=M, max_value=N)
  float(min: M, max: N)          -> st.floats(min_value=M, max_value=N)
  string(min_len: M, max_len: N) -> st.text(min_size=M, max_size=N)
  enum[a, b, c]                  -> st.sampled_from(['a','b','c'])
  bool                           -> st.booleans()
  date(min: D1, max: D2)         -> st.dates(min_value=..., max_value=...)
  list(of: <sub>, min_len: M, max_len: N) -> st.lists(<sub>, ...)
  optional(<sub>)                -> st.one_of(st.none(), <sub>)
  dict(k: <sub>, ...)            -> st.fixed_dictionaries({...})

Logging: invoked by /qa, which logs qa_tests_generated.
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# YAML-ish frontmatter parser — copied from scenario-pytest.py
# ============================================================================

def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 5:]
    fm = _parse_simple_yaml(fm_text)
    return fm, body


def _parse_simple_yaml(text: str) -> dict:
    """Recursive descent YAML-ish parser. See scenario-pytest.py for the canonical."""
    lines = []
    for raw in text.split("\n"):
        stripped_right = raw.rstrip()
        if not stripped_right.lstrip():
            continue
        if stripped_right.lstrip().startswith("#"):
            continue
        lines.append(stripped_right)

    def parse_block(start, base_indent):
        if start >= len(lines):
            return {}, start
        first = lines[start]
        first_stripped = first.lstrip()
        if first_stripped.startswith("- "):
            return parse_list(start, len(first) - len(first_stripped))
        return parse_dict(start, len(first) - len(first_stripped))

    def parse_dict(start, base_indent):
        result = {}
        i = start
        while i < len(lines):
            line = lines[i]
            indent = len(line) - len(line.lstrip())
            stripped = line.lstrip()
            if indent != base_indent:
                break
            if ":" not in stripped:
                i += 1
                continue
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip()
            if v:
                result[k] = _parse_scalar(v)
                i += 1
            else:
                j = i + 1
                if j >= len(lines):
                    result[k] = None
                    i += 1
                    continue
                ni = len(lines[j]) - len(lines[j].lstrip())
                if ni <= base_indent:
                    result[k] = None
                    i += 1
                    continue
                nested, new_i = parse_block(j, ni)
                result[k] = nested
                i = new_i
        return result, i

    def parse_list(start, base_indent):
        result = []
        i = start
        while i < len(lines):
            line = lines[i]
            indent = len(line) - len(line.lstrip())
            stripped = line.lstrip()
            if indent != base_indent or not stripped.startswith("- "):
                break
            item_text = stripped[2:].strip()
            if ":" in item_text and not item_text.startswith('"') and not item_text.startswith("'"):
                k, _, v = item_text.partition(":")
                k = k.strip()
                v = v.strip()
                item = {}
                if v:
                    item[k] = _parse_scalar(v)
                j = i + 1
                while j < len(lines):
                    ll = lines[j]
                    ii = len(ll) - len(ll.lstrip())
                    ss = ll.lstrip()
                    if ii == base_indent + 2 and not ss.startswith("- ") and ":" in ss:
                        kk, _, vv = ss.partition(":")
                        item[kk.strip()] = _parse_scalar(vv.strip())
                        j += 1
                    else:
                        break
                result.append(item)
                i = j
            else:
                result.append(_parse_scalar(item_text))
                i += 1
        return result, i

    parsed, _ = parse_dict(0, 0)
    return parsed


def _parse_scalar(s: str) -> object:
    if s == "":
        return None
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() == "true": return True
    if s.lower() == "false": return False
    if s.lower() == "null": return None
    try:
        if "." in s: return float(s)
        return int(s)
    except ValueError:
        return s


# ============================================================================
# DSL parser for generator forms
# ============================================================================

class DSLParseError(Exception):
    pass


def parse_dsl(text: str) -> dict:
    """Parse a generator DSL expression into a structured form.

    Returns a dict with at least 'type' and form-specific keys.

    Grammar (informal):
        expr        := simple | compound
        simple      := 'bool'
        compound    := name '(' args ')' | 'enum[' items ']'
        args        := arg (',' arg)*
        arg         := key ':' value
        value       := expr | scalar
        scalar      := int | string | identifier
        items       := identifier (',' identifier)*
    """
    text = text.strip()
    if not text:
        raise DSLParseError("empty DSL expression")

    # bool — atomic
    if text == "bool":
        return {"type": "bool"}

    # enum[a, b, c]
    m = re.match(r"^enum\s*\[(.+)\]$", text, re.DOTALL)
    if m:
        items = [it.strip() for it in m.group(1).split(",")]
        return {"type": "enum", "values": items}

    # name(args) — find the matching paren
    m = re.match(r"^([a-z_]+)\s*\(", text)
    if not m:
        raise DSLParseError(f"unrecognized DSL form: {text!r}")
    name = m.group(1)
    if not text.endswith(")"):
        raise DSLParseError(f"unbalanced parens in: {text!r}")
    args_text = text[m.end():-1]

    # Split args at TOP-LEVEL commas (not inside nested parens/brackets)
    args = _split_top_level(args_text, ",")
    parsed_args = {}
    for arg in args:
        arg = arg.strip()
        if not arg:
            continue
        # arg = key: value  OR  just a value (for optional(<sub>))
        if ":" in arg:
            # Find the FIRST colon at top level
            colon_pos = _find_top_level_colon(arg)
            if colon_pos < 0:
                # No top-level colon — the whole thing is a value
                parsed_args["__value"] = parse_dsl(arg)
            else:
                key = arg[:colon_pos].strip()
                value = arg[colon_pos + 1:].strip()
                parsed_args[key] = _parse_dsl_value(value)
        else:
            # Positional: only used by optional(<sub>)
            parsed_args["__value"] = parse_dsl(arg)

    return {"type": name, **parsed_args}


def _parse_dsl_value(text: str) -> object:
    """Parse a value that's either a nested DSL expression or a scalar."""
    text = text.strip()
    # Try nested DSL first if it looks like one
    if re.match(r"^[a-z_]+\s*\(", text) or text == "bool" or text.startswith("enum["):
        return parse_dsl(text)
    # Otherwise it's a scalar — try int, then date, then string
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    # Strip quotes if present
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _split_top_level(text: str, delim: str) -> list[str]:
    """Split on delim, but only at top-level (paren/bracket depth 0)."""
    parts = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == delim and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _find_top_level_colon(text: str) -> int:
    """Find the first colon at paren/bracket depth 0. Returns -1 if none."""
    depth = 0
    for i, ch in enumerate(text):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == ":" and depth == 0:
            return i
    return -1


# ============================================================================
# DSL → hypothesis strategy code
# ============================================================================

def dsl_to_hypothesis(parsed: dict) -> str:
    """Translate a parsed DSL form to a hypothesis strategy expression."""
    t = parsed.get("type")
    if t == "bool":
        return "st.booleans()"
    if t == "int":
        lo = parsed.get("min", "")
        hi = parsed.get("max", "")
        parts = []
        if lo != "": parts.append(f"min_value={lo}")
        if hi != "": parts.append(f"max_value={hi}")
        return f"st.integers({', '.join(parts)})"
    if t == "float":
        lo = parsed.get("min", "")
        hi = parsed.get("max", "")
        parts = ["allow_nan=False", "allow_infinity=False"]
        if lo != "": parts.append(f"min_value={lo}")
        if hi != "": parts.append(f"max_value={hi}")
        return f"st.floats({', '.join(parts)})"
    if t == "string":
        lo = parsed.get("min_len", "")
        hi = parsed.get("max_len", "")
        parts = []
        if lo != "": parts.append(f"min_size={lo}")
        if hi != "": parts.append(f"max_size={hi}")
        return f"st.text({', '.join(parts)})"
    if t == "enum":
        items = parsed.get("values", [])
        return "st.sampled_from([" + ", ".join(repr(v) for v in items) + "])"
    if t == "date":
        lo = parsed.get("min", "")
        hi = parsed.get("max", "")
        parts = []
        if lo: parts.append(f"min_value=date.fromisoformat({lo!r})")
        if hi: parts.append(f"max_value=date.fromisoformat({hi!r})")
        return f"st.dates({', '.join(parts)})"
    if t == "list":
        of = parsed.get("of")
        if not of:
            raise DSLParseError("list(...) requires 'of:' argument")
        sub = dsl_to_hypothesis(of)
        lo = parsed.get("min_len", "")
        hi = parsed.get("max_len", "")
        parts = [sub]
        if lo != "": parts.append(f"min_size={lo}")
        if hi != "": parts.append(f"max_size={hi}")
        return f"st.lists({', '.join(parts)})"
    if t == "optional":
        sub = parsed.get("__value")
        if not sub:
            raise DSLParseError("optional(...) requires a sub-generator")
        return f"st.one_of(st.none(), {dsl_to_hypothesis(sub)})"
    if t == "dict":
        # All non-meta keys are field generators
        fields = {k: v for k, v in parsed.items() if k != "type"}
        if not fields:
            return "st.fixed_dictionaries({})"
        entries = []
        for k, v in fields.items():
            if not isinstance(v, dict):
                raise DSLParseError(f"dict field {k!r} value is not a sub-generator")
            entries.append(f"    {k!r}: {dsl_to_hypothesis(v)}")
        return "st.fixed_dictionaries({\n" + ",\n".join(entries) + "\n})"
    raise DSLParseError(f"unknown DSL type: {t}")


# ============================================================================
# Main generator
# ============================================================================

def extract_section(body: str, heading: str) -> str:
    pattern = re.compile(
        r"^##\s+" + re.escape(heading) + r"\s*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    return m.group(1).strip() if m else ""


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s or "property"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_action_call(action: dict, has_dict_generator: bool) -> str:
    """Same shape as scenario generator's action rendering."""
    if not isinstance(action, dict):
        return "    # No action declared. Wire up the call site.\n    actual = None  # <-- REPLACE\n"
    atype = action.get("type", "")
    payload_var = "request_payload" if has_dict_generator else "input_value"
    if atype == "http":
        method = action.get("method", "GET")
        endpoint = action.get("endpoint", "/")
        return (
            f"    # Example HTTP {method} {endpoint}:\n"
            f"    #   from myapp.test_client import client\n"
            f"    #   response = client.{method.lower()}('{endpoint}', json={payload_var})\n"
            f"    #   actual_status = response.status_code\n"
            f"    #   actual_body = response.json()\n"
            f"    actual_status = None  # <-- REPLACE\n"
            f"    actual_body = None    # <-- REPLACE\n"
            f"    actual = actual_body  # convenience alias\n"
        )
    if atype == "function":
        module = action.get("module", "myapp.module")
        function = action.get("function", "the_function")
        return (
            f"    # Example function call:\n"
            f"    #   from {module} import {function}\n"
            f"    #   actual = {function}(**{payload_var}) if isinstance({payload_var}, dict) else {function}({payload_var})\n"
            f"    actual = None  # <-- REPLACE\n"
            f"    actual_status = None\n"
            f"    actual_body = actual\n"
        )
    return f"    # Action type '{atype}' — wire up manually.\n    actual = None  # <-- REPLACE\n    actual_status = None\n    actual_body = None\n"


def generate(artifact_path: Path, out_dir: Path) -> Path:
    text = artifact_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("language") not in ("python", None, ""):
        raise SystemExit(
            f"property-pytest.py only handles python artifacts; "
            f"this artifact's language is '{fm.get('language')}'"
        )

    action = fm.get("action") or {}
    generators_raw = fm.get("generators") or {}
    invariant = fm.get("invariant") or {}
    max_examples = fm.get("max_examples", 100)
    input_filter = fm.get("input_filter", "") or ""

    if not generators_raw:
        raise SystemExit(f"Artifact {artifact_path} has no 'generators:' block")
    if not invariant.get("expression"):
        raise SystemExit(f"Artifact {artifact_path} has no 'invariant.expression' field")

    # Translate each generator entry from DSL form
    field_strategies = {}
    for field_name, dsl_text in generators_raw.items():
        if not isinstance(dsl_text, str):
            raise SystemExit(
                f"generator for {field_name!r} must be a DSL string, got: {dsl_text!r}"
            )
        try:
            parsed = parse_dsl(dsl_text)
        except DSLParseError as e:
            raise SystemExit(f"DSL parse error in generator {field_name!r}: {e}")
        try:
            strategy_code = dsl_to_hypothesis(parsed)
        except DSLParseError as e:
            raise SystemExit(f"DSL translation error in generator {field_name!r}: {e}")
        field_strategies[field_name] = strategy_code

    why = extract_section(body, "Why this property exists")
    stem = artifact_path.stem
    test_func_name = "test_property_" + slugify(stem)
    chash = content_hash(text)

    expr = invariant.get("expression", "True")

    # Build the @given block
    if len(field_strategies) == 1:
        # Single field — use a positional strategy
        only_field = list(field_strategies.keys())[0]
        given_block = f"@given({only_field}={field_strategies[only_field]})"
        params_block = only_field
        has_dict_generator = False
    else:
        # Multiple fields — combine into a fixed_dictionaries-style request_payload
        entries = []
        for k, s in field_strategies.items():
            entries.append(f"    {k!r}: {s}")
        given_block = "@given(request_payload=st.fixed_dictionaries({\n" + ",\n".join(entries) + "\n}))"
        params_block = "request_payload"
        has_dict_generator = True

    parts = []
    parts.append(f"""# AUTO-GENERATED by specship /qa. Do not edit by hand.
# §qa:{artifact_path.as_posix()}
# To change this test, edit the source artifact and re-run /qa.
# Content hash: {chash}
# Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}

\"\"\"Property test for: {fm.get('property_id', '<unknown>')}

Parent spec: {fm.get('parent_spec', '<unknown>')}
Authored by: {fm.get('authored_by', '<unknown>')}
Last synced to spec at: {fm.get('last_synced_to_spec_at', '<unknown>')}

Invariant: {invariant.get('prose', '(see source artifact)')}

Why this property exists:
{_indent(why or '(see source artifact)', '  ')}
\"\"\"

from datetime import date
import pytest
from hypothesis import given, settings, strategies as st


""")

    parts.append(given_block)
    parts.append(f"@settings(max_examples={max_examples})")
    parts.append(f"def {test_func_name}({params_block}):")
    parts.append(f'    """Verify invariant against {fm.get("parent_spec", "<spec>")}.')
    parts.append("")
    parts.append("    This test is auto-generated from a property artifact. The action call site")
    parts.append("    is STUBBED — wire it up to your codebase and remove the pytest.skip() below.")
    parts.append('    """')

    # Input filter (if any)
    if input_filter:
        parts.append("")
        parts.append("    # ---- Input filter (skip cases that don't satisfy precondition) ----")
        parts.append(f"    from hypothesis import assume")
        parts.append(f"    assume({input_filter})")

    # Action
    parts.append("")
    parts.append(f"    # ---- Action under test ({action.get('type', 'unknown') if isinstance(action, dict) else 'unknown'}) ----")
    parts.append(render_action_call(action, has_dict_generator))

    # Skip stub
    parts.append("    # ---- Remove this skip once the call site is wired up ----")
    parts.append("    pytest.skip(\n        'Property test stub — wire up the call site, then remove this skip().'\n    )")

    # Invariant assertion
    parts.append("")
    parts.append("    # ---- Invariant assertion ----")
    parts.append(f'    # Prose: {invariant.get("prose", "")}')
    parts.append(f"    assert {expr}, (")
    parts.append(f'        f"Invariant violated: {invariant.get("prose", "")}"')
    parts.append("    )")
    parts.append("")

    content = "\n".join(parts)

    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / f"test_{slugify(stem)}.py"
    test_file.write_text(content, encoding="utf-8")
    return test_file


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.split("\n"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("artifact", help="path to the property artifact")
    p.add_argument("--out", default="tests/property", help="output directory")
    args = p.parse_args()

    artifact_path = Path(args.artifact)
    if not artifact_path.is_file():
        print(f"artifact not found: {artifact_path}", file=sys.stderr)
        return 1

    try:
        test_file = generate(artifact_path, Path(args.out))
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    print(str(test_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())

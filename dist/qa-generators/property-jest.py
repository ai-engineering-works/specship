#!/usr/bin/env python3
"""property-jest.py — generate a fast-check property test from a property artifact.

Usage:
    python3 property-jest.py <artifact-path> [--out tests/property/]

TypeScript/fast-check counterpart of property-pytest.py. Same DSL forms,
same artifact format, same content-hash mechanism. Translates to fc.* arbitraries
inside fc.assert(fc.property(...)).

DSL → fast-check mappings:
  bool                           -> fc.boolean()
  int(min, max)                  -> fc.integer({min, max})
  float(min, max)                -> fc.float({min, max, noNaN: true, noDefaultInfinity: true})
  string(min_len, max_len)       -> fc.string({minLength, maxLength})
  enum[a, b, c]                  -> fc.constantFrom('a','b','c')
  date(min, max)                 -> fc.date({min: new Date(...), max: new Date(...)})
  list(of, min_len, max_len)     -> fc.array(<sub>, {minLength, maxLength})
  optional(<sub>)                -> fc.option(<sub>)
  dict(k: <sub>, ...)            -> fc.record({...})

Logging: invoked by /qa, which logs qa_tests_generated.
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# YAML-ish frontmatter parser (same as property-pytest)
# ============================================================================

def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 5:]
    return _parse_simple_yaml(fm_text), body


def _parse_simple_yaml(text: str) -> dict:
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
# DSL parser — same logic as property-pytest
# ============================================================================

class DSLParseError(Exception):
    pass


def parse_dsl(text: str) -> dict:
    text = text.strip()
    if not text:
        raise DSLParseError("empty DSL expression")
    if text == "bool":
        return {"type": "bool"}
    m = re.match(r"^enum\s*\[(.+)\]$", text, re.DOTALL)
    if m:
        items = [it.strip() for it in m.group(1).split(",")]
        return {"type": "enum", "values": items}
    m = re.match(r"^([a-z_]+)\s*\(", text)
    if not m:
        raise DSLParseError(f"unrecognized DSL form: {text!r}")
    name = m.group(1)
    if not text.endswith(")"):
        raise DSLParseError(f"unbalanced parens in: {text!r}")
    args_text = text[m.end():-1]
    args = _split_top_level(args_text, ",")
    parsed_args = {}
    for arg in args:
        arg = arg.strip()
        if not arg:
            continue
        if ":" in arg:
            colon_pos = _find_top_level_colon(arg)
            if colon_pos < 0:
                parsed_args["__value"] = parse_dsl(arg)
            else:
                key = arg[:colon_pos].strip()
                value = arg[colon_pos + 1:].strip()
                parsed_args[key] = _parse_dsl_value(value)
        else:
            parsed_args["__value"] = parse_dsl(arg)
    return {"type": name, **parsed_args}


def _parse_dsl_value(text: str) -> object:
    text = text.strip()
    if re.match(r"^[a-z_]+\s*\(", text) or text == "bool" or text.startswith("enum["):
        return parse_dsl(text)
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _split_top_level(text: str, delim: str) -> list[str]:
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
# DSL → fast-check arbitrary
# ============================================================================

def dsl_to_fast_check(parsed: dict) -> str:
    t = parsed.get("type")
    if t == "bool":
        return "fc.boolean()"
    if t == "int":
        lo = parsed.get("min", "")
        hi = parsed.get("max", "")
        opts = []
        if lo != "": opts.append(f"min: {lo}")
        if hi != "": opts.append(f"max: {hi}")
        return f"fc.integer({{{', '.join(opts)}}})" if opts else "fc.integer()"
    if t == "float":
        lo = parsed.get("min", "")
        hi = parsed.get("max", "")
        opts = ["noNaN: true", "noDefaultInfinity: true"]
        if lo != "": opts.append(f"min: {lo}")
        if hi != "": opts.append(f"max: {hi}")
        return f"fc.float({{{', '.join(opts)}}})"
    if t == "string":
        lo = parsed.get("min_len", "")
        hi = parsed.get("max_len", "")
        opts = []
        if lo != "": opts.append(f"minLength: {lo}")
        if hi != "": opts.append(f"maxLength: {hi}")
        return f"fc.string({{{', '.join(opts)}}})" if opts else "fc.string()"
    if t == "enum":
        items = parsed.get("values", [])
        return "fc.constantFrom(" + ", ".join(repr(v) for v in items) + ")"
    if t == "date":
        lo = parsed.get("min", "")
        hi = parsed.get("max", "")
        opts = []
        if lo: opts.append(f"min: new Date({lo!r})")
        if hi: opts.append(f"max: new Date({hi!r})")
        return f"fc.date({{{', '.join(opts)}}})" if opts else "fc.date()"
    if t == "list":
        of = parsed.get("of")
        if not of:
            raise DSLParseError("list(...) requires 'of:'")
        sub = dsl_to_fast_check(of)
        lo = parsed.get("min_len", "")
        hi = parsed.get("max_len", "")
        opts = []
        if lo != "": opts.append(f"minLength: {lo}")
        if hi != "": opts.append(f"maxLength: {hi}")
        return f"fc.array({sub}, {{{', '.join(opts)}}})" if opts else f"fc.array({sub})"
    if t == "optional":
        sub = parsed.get("__value")
        if not sub:
            raise DSLParseError("optional(...) requires a sub-generator")
        return f"fc.option({dsl_to_fast_check(sub)})"
    if t == "dict":
        fields = {k: v for k, v in parsed.items() if k != "type"}
        if not fields:
            return "fc.record({})"
        entries = []
        for k, v in fields.items():
            if not isinstance(v, dict):
                raise DSLParseError(f"dict field {k!r} value is not a sub-generator")
            entries.append(f"      {k}: {dsl_to_fast_check(v)}")
        return "fc.record({\n" + ",\n".join(entries) + "\n    })"
    raise DSLParseError(f"unknown DSL type: {t}")


# ============================================================================
# Python expression → TypeScript expression translation
# ============================================================================

def py_expr_to_ts(expr: str) -> str:
    """Translate a small subset of Python expression syntax to TypeScript.

    Handles:
      actual_status   -> actualStatus
      actual_body     -> actualBody
      request_payload -> requestPayload
      x['y']           -> x['y'] (works in both)
      x == y           -> x === y
      x != y           -> x !== y
      'and' / 'or'     -> && / ||
      'not '           -> !
      'in (a, b, c)'   -> [a, b, c].includes(x)
      None             -> null
      True / False     -> true / false

    Anything more complex is left as-is and may need manual editing.
    """
    out = expr

    # First: variable name conversions (snake_case -> camelCase for the known
    # convenience variables that the generated test scaffold declares)
    var_renames = {
        r"\bactual_status\b": "actualStatus",
        r"\bactual_body\b": "actualBody",
        r"\brequest_payload\b": "requestPayload",
        r"\binput_value\b": "inputValue",
    }
    for pattern, replacement in var_renames.items():
        out = re.sub(pattern, replacement, out)

    # `x in (a, b, c)` → `[a, b, c].includes(x)`
    def replace_in(m):
        left = m.group(1).strip()
        items = m.group(2)
        return f"[{items}].includes({left})"
    out = re.sub(r"([\w.\[\]'\"]+)\s+in\s+\(([^)]+)\)", replace_in, out)

    # `x == y` → `x === y`
    out = re.sub(r"(?<![=!])==(?!=)", "===", out)
    out = re.sub(r"(?<![=!])!=(?!=)", "!==", out)

    out = re.sub(r"\band\b", "&&", out)
    out = re.sub(r"\bor\b", "||", out)
    out = re.sub(r"\bnot\s+", "!", out)
    out = re.sub(r"\bNone\b", "null", out)
    out = re.sub(r"\bTrue\b", "true", out)
    out = re.sub(r"\bFalse\b", "false", out)

    return out


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


def js_string_literal(s: str) -> str:
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def render_action_call(action: dict, has_dict_generator: bool) -> str:
    if not isinstance(action, dict):
        return "        // No action declared.\n        const actual: unknown = null;\n"
    atype = action.get("type", "")
    payload_var = "requestPayload" if has_dict_generator else "inputValue"
    if atype == "http":
        method = action.get("method", "GET")
        endpoint = action.get("endpoint", "/")
        return (
            f"        // Example HTTP {method} {endpoint}:\n"
            f"        //   const response = await request(app).{method.lower()}('{endpoint}').send({payload_var});\n"
            f"        //   const actualStatus = response.status;\n"
            f"        //   const actualBody = response.body;\n"
            f"        const actualStatus: number = 0;       // <-- REPLACE\n"
            f"        const actualBody: any = null;         // <-- REPLACE\n"
            f"        const actual: any = actualBody;\n"
        )
    if atype == "function":
        module = action.get("module", "myapp/module")
        function = action.get("function", "theFunction")
        return (
            f"        // Example function call:\n"
            f"        //   import {{ {function} }} from '../../src/{module}';\n"
            f"        //   const actual = await {function}({payload_var});\n"
            f"        const actual: any = null;  // <-- REPLACE\n"
            f"        const actualStatus: number = 0;\n"
            f"        const actualBody: any = actual;\n"
        )
    return f"        // Action type '{atype}' — wire up manually.\n        const actual: any = null;\n        const actualStatus: number = 0;\n        const actualBody: any = null;\n"


def generate(artifact_path: Path, out_dir: Path) -> Path:
    text = artifact_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("language") not in ("typescript", "javascript", None, ""):
        raise SystemExit(
            f"property-jest.py only handles typescript/javascript artifacts; "
            f"this artifact's language is '{fm.get('language')}'"
        )

    action = fm.get("action") or {}
    generators_raw = fm.get("generators") or {}
    invariant = fm.get("invariant") or {}
    max_examples = fm.get("max_examples", 100)
    input_filter_py = fm.get("input_filter", "") or ""

    if not generators_raw:
        raise SystemExit(f"Artifact {artifact_path} has no 'generators:' block")
    if not invariant.get("expression"):
        raise SystemExit(f"Artifact {artifact_path} has no 'invariant.expression' field")

    # Translate generators
    field_arbitraries = {}
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
            arb_code = dsl_to_fast_check(parsed)
        except DSLParseError as e:
            raise SystemExit(f"DSL translation error in generator {field_name!r}: {e}")
        field_arbitraries[field_name] = arb_code

    why = extract_section(body, "Why this property exists")
    stem = artifact_path.stem
    chash = content_hash(text)
    desc = slugify(stem)

    expr_py = invariant.get("expression", "true")
    expr_ts = py_expr_to_ts(expr_py)
    input_filter_ts = py_expr_to_ts(input_filter_py) if input_filter_py else ""

    # Build the arbitrary
    if len(field_arbitraries) == 1:
        only_field = list(field_arbitraries.keys())[0]
        arb_expr = field_arbitraries[only_field]
        callback_param = only_field
        has_dict_generator = False
    else:
        entries = []
        for k, a in field_arbitraries.items():
            entries.append(f"      {k}: {a}")
        arb_expr = "fc.record({\n" + ",\n".join(entries) + "\n    })"
        callback_param = "requestPayload"
        has_dict_generator = True

    parts = []
    parts.append(f"""// AUTO-GENERATED by specship /qa. Do not edit by hand.
// §qa:{artifact_path.as_posix()}
// To change this test, edit the source artifact and re-run /qa.
// Content hash: {chash}
// Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}

/**
 * Property test for: {fm.get('property_id', '<unknown>')}
 *
 * Parent spec: {fm.get('parent_spec', '<unknown>')}
 * Authored by: {fm.get('authored_by', '<unknown>')}
 * Last synced to spec at: {fm.get('last_synced_to_spec_at', '<unknown>')}
 *
 * Invariant: {invariant.get('prose', '(see source artifact)')}
 */

import fc from 'fast-check';

describe('property: {desc}', () => {{
  test.skip('verifies invariant against {fm.get('parent_spec', '<spec>')}', () => {{
    fc.assert(
      fc.property({arb_expr}, ({callback_param}) => {{""")

    # Input filter
    if input_filter_ts:
        parts.append(f"""
        // Input precondition (skip cases that don't satisfy)
        fc.pre({input_filter_ts});""")

    # Action
    parts.append("")
    parts.append(f"        // ---- Action under test ({action.get('type', 'unknown') if isinstance(action, dict) else 'unknown'}) ----")
    parts.append(render_action_call(action, has_dict_generator))

    # Assertion
    parts.append("        // ---- Invariant assertion ----")
    parts.append(f"        // Prose: {invariant.get('prose', '')}")
    parts.append(f"        expect({expr_ts}).toBe(true);")

    parts.append("      }),")
    parts.append(f"      {{ numRuns: {max_examples} }}")
    parts.append("    );")
    parts.append("  });")
    parts.append("});")
    parts.append("")

    content = "\n".join(parts)

    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / f"{slugify(stem)}.test.ts"
    test_file.write_text(content, encoding="utf-8")
    return test_file


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

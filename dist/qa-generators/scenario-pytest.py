#!/usr/bin/env python3
"""scenario-pytest.py — generate a pytest scenario test from a scenario artifact.

Usage:
    python3 scenario-pytest.py <artifact-path> [--out tests/scenario/]

Scenario artifacts have richer frontmatter than regressions: action, setup,
and expectations are structured. This generator parses them and emits a
test file with three labeled sections — setup, action, assertions — that
the team wires up to their real codebase.

Like the regression generator, the emitted test is INTENTIONALLY MINIMAL.
It carries the structure but leaves the call site as a fixture placeholder.

Logging: invoked by /qa, which logs qa_tests_generated.
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text).

    Frontmatter is parsed as a simple YAML-ish structure: top-level scalars
    are k: v pairs, nested blocks become dicts/lists. This is NOT a full
    YAML parser — it handles the subset scenario artifacts actually use.
    """
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
    """Parse a YAML-ish subset of frontmatter.

    Supports:
      - top-level scalars:        key: value
      - nested dicts:             key:\\n  subkey: value
      - lists of scalars:         key:\\n  - item\\n  - item
      - lists of single-key dicts: key:\\n  - subkey: value\\n  - subkey: value
      - lists of multi-key dicts: key:\\n  - subkey: value\\n    other: value

    Does NOT support: anchors, references, multi-line scalars, flow style.
    """
    # First pass: split into logical lines, dropping blanks and comments
    lines = []
    for raw in text.split("\n"):
        # Preserve indent; drop trailing whitespace
        stripped_right = raw.rstrip()
        if not stripped_right.lstrip():
            continue
        if stripped_right.lstrip().startswith("#"):
            continue
        lines.append(stripped_right)

    # Recursive parser using a line index
    def parse_block(start: int, base_indent: int) -> tuple[object, int]:
        """Parse a block starting at lines[start] with the given base indent.

        Returns (parsed_value, next_line_index).
        The parsed_value is a dict, a list, or — at the leaf — a scalar.
        """
        if start >= len(lines):
            return {}, start

        first_line = lines[start]
        first_indent = len(first_line) - len(first_line.lstrip())
        first_stripped = first_line.lstrip()

        # List detection: the first line at this indent starts with "- "
        if first_stripped.startswith("- "):
            return parse_list(start, first_indent)

        # Otherwise it's a dict
        return parse_dict(start, first_indent)

    def parse_dict(start: int, base_indent: int) -> tuple[dict, int]:
        """Parse a sequence of key: value lines at base_indent."""
        result = {}
        i = start
        while i < len(lines):
            line = lines[i]
            indent = len(line) - len(line.lstrip())
            stripped = line.lstrip()
            if indent < base_indent:
                break
            if indent > base_indent:
                # Should have been consumed by a previous nested parse; stop here
                break
            if ":" not in stripped:
                # Malformed line; skip
                i += 1
                continue
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip()
            if v:
                # Inline scalar
                result[k] = _parse_scalar(v)
                i += 1
            else:
                # Nested block
                # Peek next line to decide if dict, list, or null
                j = i + 1
                if j >= len(lines):
                    result[k] = None
                    i += 1
                    continue
                next_indent = len(lines[j]) - len(lines[j].lstrip())
                if next_indent <= base_indent:
                    result[k] = None
                    i += 1
                    continue
                nested, new_i = parse_block(j, next_indent)
                result[k] = nested
                i = new_i
        return result, i

    def parse_list(start: int, base_indent: int) -> tuple[list, int]:
        """Parse list items starting with '- ' at base_indent."""
        result = []
        i = start
        while i < len(lines):
            line = lines[i]
            indent = len(line) - len(line.lstrip())
            stripped = line.lstrip()
            if indent < base_indent:
                break
            if indent > base_indent:
                break
            if not stripped.startswith("- "):
                break

            item_text = stripped[2:].strip()
            # Three sub-cases:
            # (a) item_text is "key: value" -> start of a dict item
            # (b) item_text is empty -> dict item with content on following lines
            # (c) item_text is a scalar
            if ":" in item_text and not item_text.startswith('"') and not item_text.startswith("'"):
                # Dict item with one key inline
                k, _, v = item_text.partition(":")
                k = k.strip()
                v = v.strip()
                item = {}
                if v:
                    item[k] = _parse_scalar(v)
                else:
                    # Value is on next lines, nested
                    j = i + 1
                    if j < len(lines):
                        next_indent = len(lines[j]) - len(lines[j].lstrip())
                        if next_indent > base_indent + 2:
                            nested, new_i = parse_block(j, next_indent)
                            item[k] = nested
                            result.append(item)
                            i = new_i
                            # Then check for sibling keys at indent = base_indent + 2
                            while i < len(lines):
                                ll = lines[i]
                                ii = len(ll) - len(ll.lstrip())
                                ss = ll.lstrip()
                                if ii == base_indent + 2 and not ss.startswith("- ") and ":" in ss:
                                    kk, _, vv = ss.partition(":")
                                    item[kk.strip()] = _parse_scalar(vv.strip())
                                    i += 1
                                else:
                                    break
                            continue
                        else:
                            item[k] = None
                # Look ahead for sibling keys at indent = base_indent + 2 (multi-key dict items)
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
                continue
            else:
                # Scalar list item
                result.append(_parse_scalar(item_text))
                i += 1
                continue
        return result, i

    parsed, _ = parse_dict(0, 0)
    return parsed


def _parse_scalar(s: str) -> object:
    """Parse a scalar string. Returns int/float/bool when obvious, else string."""
    if s == "":
        return None
    # Strip surrounding quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() == "null":
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


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
    return s or "scenario"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_action_call(action: dict) -> str:
    """Render Python code that performs the action. Returns commented-out code
    the human wires up — we don't know the team's import paths or client setup."""
    if not isinstance(action, dict):
        return "    # No action declared in frontmatter. Wire up the call site.\n    actual = None  # <-- REPLACE\n"
    atype = action.get("type", "")
    if atype == "http":
        method = action.get("method", "GET")
        endpoint = action.get("endpoint", "/")
        return (
            f"    # Example HTTP {method} {endpoint}:\n"
            f"    #   from myapp.test_client import client\n"
            f"    #   response = client.{method.lower()}('{endpoint}', json=request_payload)\n"
            f"    #   actual_status = response.status_code\n"
            f"    #   actual_body = response.json()\n"
            f"    actual_status = None  # <-- REPLACE\n"
            f"    actual_body = None    # <-- REPLACE\n"
        )
    if atype == "function":
        module = action.get("module", "myapp.module")
        function = action.get("function", "the_function")
        return (
            f"    # Example function call:\n"
            f"    #   from {module} import {function}\n"
            f"    #   actual = {function}(**request_payload)\n"
            f"    actual = None  # <-- REPLACE\n"
        )
    if atype == "event":
        topic = action.get("topic", "unknown.topic")
        return (
            f"    # Example event publish:\n"
            f"    #   from myapp.events import publish\n"
            f"    #   publish('{topic}', payload=request_payload)\n"
            f"    # Then capture the resulting state/side effects below.\n"
        )
    if atype == "command":
        command = action.get("command", "./command.sh")
        return (
            f"    # Example command execution:\n"
            f"    #   import subprocess\n"
            f"    #   result = subprocess.run({command!r}.split(), capture_output=True)\n"
            f"    #   actual_stdout = result.stdout.decode()\n"
            f"    actual = None  # <-- REPLACE\n"
        )
    return f"    # Unknown action type: {atype}. Wire up manually.\n    actual = None  # <-- REPLACE\n"


def render_assertions(expectations: list, action_type: str) -> str:
    """Turn the expectations list into a sequence of assert statements."""
    if not expectations:
        return "    # No expectations declared in frontmatter. Add assertions here.\n    pass\n"

    lines = []
    for i, exp in enumerate(expectations, 1):
        if isinstance(exp, dict):
            # Structured expectation
            for key, value in exp.items():
                if key == "http_status":
                    lines.append(f"    # Assertion {i}: HTTP status")
                    lines.append(f'    assert actual_status == {value!r}, f"expected status {value}, got {{actual_status}}"')
                elif key == "response_body_contains":
                    lines.append(f"    # Assertion {i}: response body contains expected fields")
                    if isinstance(value, dict):
                        for k, v in value.items():
                            # Use double-quoted f-string in the generated code to avoid
                            # quote-collision when the value contains single quotes
                            lines.append(f'    assert actual_body.get({k!r}) == {v!r}, f"expected {k}={v!r}, got {{actual_body.get({k!r})!r}}"')
                    else:
                        lines.append(f"    # value: {value!r}")
                        lines.append(f"    # add assertions for this expectation manually")
                elif key == "error_code":
                    lines.append(f"    # Assertion {i}: error code")
                    lines.append(f'    assert actual_body.get("error", {{}}).get("code") == {value!r}, f"expected error code {value}"')
                elif key == "side_effect":
                    lines.append(f"    # Assertion {i}: side effect — {value}")
                    lines.append(f"    #   This requires hooking into your event/message bus to verify.")
                    lines.append(f"    #   Wire up the assertion to your test infrastructure.")
                elif key == "db_row_exists":
                    lines.append(f"    # Assertion {i}: db state — {value}")
                    lines.append(f"    #   Requires a db connection in the test setup.")
                    lines.append(f"    #   Wire up the assertion to your test infrastructure.")
                elif key == "response_time_ms_under":
                    lines.append(f"    # Assertion {i}: response time")
                    lines.append(f"    #   Requires timing the call site above.")
                else:
                    lines.append(f"    # Assertion {i}: {key} = {value!r}")
                    lines.append(f"    #   Custom expectation — wire up manually.")
        else:
            # Free-form string expectation
            lines.append(f"    # Assertion {i}: {exp}")
            lines.append(f"    #   Wire up assertion for this expectation manually.")
        lines.append("")  # blank line between assertions
    return "\n".join(lines)


def render_setup(setup_list: list) -> str:
    """Render setup steps as comments + a fixture stub."""
    if not setup_list:
        return ""
    parts = ["    # ---- Setup preconditions ----"]
    for i, s in enumerate(setup_list, 1):
        parts.append(f"    #   {i}. {s}")
    parts.append("    #")
    parts.append("    # The above are preconditions to satisfy before the action.")
    parts.append("    # Implement them in a fixture or directly in the test body.")
    return "\n".join(parts) + "\n"


def generate(artifact_path: Path, out_dir: Path) -> Path:
    text = artifact_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("language") not in ("python", None, ""):
        raise SystemExit(
            f"scenario-pytest.py only handles python artifacts; "
            f"this artifact's language is '{fm.get('language')}'"
        )

    action = fm.get("action", {}) or {}
    setup = fm.get("setup", []) or []
    expectations = fm.get("expectations", []) or []

    why = extract_section(body, "Why this scenario exists")
    given_section = extract_section(body, "Given")
    when_section = extract_section(body, "When")
    then_section = extract_section(body, "Then")

    stem = artifact_path.stem
    test_func_name = "test_scenario_" + slugify(stem)
    chash = content_hash(text)

    action_type = action.get("type", "") if isinstance(action, dict) else ""

    parts = []
    parts.append(f"""# AUTO-GENERATED by specship /qa. Do not edit by hand.
# §qa:{artifact_path.as_posix()}
# To change this test, edit the source artifact and re-run /qa.
# Content hash: {chash}
# Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}

\"\"\"Scenario test for: {fm.get('scenario_id', '<unknown>')}

Parent spec: {fm.get('parent_spec', '<unknown>')}
Authored by: {fm.get('authored_by', '<unknown>')}
Authored at: {fm.get('authored_at', '<unknown>')}
Last synced to spec at: {fm.get('last_synced_to_spec_at', '<unknown>')}

Why this scenario exists:
{_indent(why or '(see source artifact)', '  ')}
\"\"\"

import pytest

""")

    parts.append(f"""def {test_func_name}():
    \"\"\"Verify scenario {fm.get('scenario_id', '<id>')} against {fm.get('parent_spec', '<spec>')}.

    This test is auto-generated from a scenario artifact. The setup, call site,
    and assertions are STUBBED — wire them up to your codebase, then remove the
    pytest.skip() call below.
    \"\"\"
""")

    # Setup
    parts.append(render_setup(setup))
    parts.append("")
    parts.append("    # ---- Request payload (extract from artifact's When section) ----")
    parts.append("    # If your scenario carries a payload, paste it here as a Python dict")
    parts.append("    # or load it from the artifact's body.")
    parts.append("    request_payload = {}  # <-- REPLACE with payload from artifact's When section\n")

    parts.append("")
    parts.append(f"    # ---- Action under test ({action_type or 'unknown'}) ----")
    parts.append(render_action_call(action))

    parts.append("    # ---- Remove this skip once the call site is wired up ----")
    parts.append("    pytest.skip(\n        'Scenario test stub — wire up setup + call site + assertions, then remove this skip().'\n    )")
    parts.append("")

    parts.append("    # ---- Assertions ----")
    parts.append(render_assertions(expectations, action_type))

    content = "\n".join(parts)

    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / f"test_{slugify(stem)}.py"
    test_file.write_text(content, encoding="utf-8")
    return test_file


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.split("\n"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("artifact", help="path to the scenario artifact")
    p.add_argument("--out", default="tests/scenario", help="output directory")
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

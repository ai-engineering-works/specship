#!/usr/bin/env python3
"""scenario-jest.py — generate a Jest scenario test from a scenario artifact.

Usage:
    python3 scenario-jest.py <artifact-path> [--out tests/scenario/]

TypeScript/Jest counterpart of scenario-pytest.py. Same artifact format,
same setup/action/expectations structure. Emits a .test.ts file under
tests/scenario/.

Logging: invoked by /qa, which logs qa_tests_generated.
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the YAML-ish parser from the pytest scenario generator by importing it.
# Both generators live in the same directory; this avoids duplicating ~80 lines.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from scenario_pytest_parser import parse_frontmatter, extract_section, slugify, content_hash  # type: ignore
except ImportError:
    # Fallback: duplicate the parser inline so this works even if the helper
    # module isn't installed. (Path of least resistance for single-file
    # generators; mirrors the pattern in regression-jest.py.)
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
        """Parse YAML-ish frontmatter (subset). Mirrors scenario-pytest.py."""
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
            first_line = lines[start]
            first_stripped = first_line.lstrip()
            if first_stripped.startswith("- "):
                return parse_list(start, len(first_line) - len(first_stripped))
            return parse_dict(start, len(first_line) - len(first_stripped))

        def parse_dict(start, base_indent):
            result = {}
            i = start
            while i < len(lines):
                line = lines[i]
                indent = len(line) - len(line.lstrip())
                stripped = line.lstrip()
                if indent < base_indent or indent > base_indent:
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
                    next_indent = len(lines[j]) - len(lines[j].lstrip())
                    if next_indent <= base_indent:
                        result[k] = None
                        i += 1
                        continue
                    nested, new_i = parse_block(j, next_indent)
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
                    else:
                        j = i + 1
                        if j < len(lines):
                            next_indent = len(lines[j]) - len(lines[j].lstrip())
                            if next_indent > base_indent + 2:
                                nested, new_i = parse_block(j, next_indent)
                                item[k] = nested
                                result.append(item)
                                i = new_i
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
                    result.append(_parse_scalar(item_text))
                    i += 1
                    continue
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
    """Render TS code that performs the action."""
    if not isinstance(action, dict):
        return "    // No action declared. Wire up the call site.\n    const actual: unknown = null;  // <-- REPLACE\n"
    atype = action.get("type", "")
    if atype == "http":
        method = action.get("method", "GET")
        endpoint = action.get("endpoint", "/")
        return (
            f"    // Example HTTP {method} {endpoint}:\n"
            f"    //   import {{ request }} from 'supertest';\n"
            f"    //   import app from '../../src/app';\n"
            f"    //   const response = await request(app).{method.lower()}('{endpoint}').send(requestPayload);\n"
            f"    //   const actualStatus = response.status;\n"
            f"    //   const actualBody = response.body;\n"
            f"    const actualStatus: number = 0;          // <-- REPLACE\n"
            f"    const actualBody: any = null;            // <-- REPLACE\n"
        )
    if atype == "function":
        module = action.get("module", "myapp/module")
        function = action.get("function", "theFunction")
        return (
            f"    // Example function call:\n"
            f"    //   import {{ {function} }} from '../../src/{module}';\n"
            f"    //   const actual = await {function}(requestPayload);\n"
            f"    const actual: unknown = null;  // <-- REPLACE\n"
        )
    if atype == "event":
        topic = action.get("topic", "unknown.topic")
        return (
            f"    // Example event publish:\n"
            f"    //   import {{ publish }} from '../../src/events';\n"
            f"    //   await publish('{topic}', requestPayload);\n"
            f"    // Then capture the resulting state/side effects below.\n"
        )
    if atype == "command":
        command = action.get("command", "./command.sh")
        return (
            f"    // Example command execution:\n"
            f"    //   import {{ execSync }} from 'child_process';\n"
            f"    //   const actualStdout = execSync({command!r}).toString();\n"
            f"    const actual: unknown = null;  // <-- REPLACE\n"
        )
    return f"    // Unknown action type: {atype}. Wire up manually.\n    const actual: unknown = null;  // <-- REPLACE\n"


def render_assertions(expectations: list) -> str:
    if not expectations:
        return "    // No expectations declared. Add assertions here.\n"
    lines = []
    for i, exp in enumerate(expectations, 1):
        if isinstance(exp, dict):
            for key, value in exp.items():
                if key == "http_status":
                    lines.append(f"    // Assertion {i}: HTTP status")
                    lines.append(f"    expect(actualStatus).toBe({value!r});")
                elif key == "response_body_contains":
                    lines.append(f"    // Assertion {i}: response body contains expected fields")
                    if isinstance(value, dict):
                        for k, v in value.items():
                            lines.append(f"    expect(actualBody.{k}).toEqual({json_repr(v)});")
                    else:
                        lines.append(f"    // value: {value!r} — add assertions manually")
                elif key == "error_code":
                    lines.append(f"    // Assertion {i}: error code")
                    lines.append(f"    expect(actualBody?.error?.code).toBe({value!r});")
                elif key == "side_effect":
                    lines.append(f"    // Assertion {i}: side effect — {value}")
                    lines.append(f"    //   Hook into your event bus to verify.")
                elif key == "db_row_exists":
                    lines.append(f"    // Assertion {i}: db state — {value}")
                    lines.append(f"    //   Wire up db check.")
                elif key == "response_time_ms_under":
                    lines.append(f"    // Assertion {i}: response time under {value}ms")
                    lines.append(f"    //   Requires timing the call.")
                else:
                    lines.append(f"    // Assertion {i}: {key} = {value!r}")
        else:
            lines.append(f"    // Assertion {i}: {exp}")
            lines.append(f"    //   Wire up assertion manually.")
        lines.append("")
    return "\n".join(lines)


def json_repr(v) -> str:
    """Render a Python value as a JS literal (simplified)."""
    if isinstance(v, str):
        return f"'{v}'"
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    return str(v)


def render_setup(setup_list: list) -> str:
    if not setup_list:
        return ""
    parts = ["    // ---- Setup preconditions ----"]
    for i, s in enumerate(setup_list, 1):
        parts.append(f"    //   {i}. {s}")
    parts.append("    //")
    parts.append("    // Implement in beforeEach or directly in the test body.")
    return "\n".join(parts) + "\n"


def generate(artifact_path: Path, out_dir: Path) -> Path:
    text = artifact_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    if fm.get("language") not in ("typescript", "javascript", None, ""):
        raise SystemExit(
            f"scenario-jest.py only handles typescript/javascript artifacts; "
            f"this artifact's language is '{fm.get('language')}'"
        )

    action = fm.get("action", {}) or {}
    setup = fm.get("setup", []) or []
    expectations = fm.get("expectations", []) or []

    why = extract_section(body, "Why this scenario exists")
    stem = artifact_path.stem
    chash = content_hash(text)
    test_desc = slugify(stem)
    action_type = action.get("type", "") if isinstance(action, dict) else ""

    parts = []
    parts.append(f"""// AUTO-GENERATED by specship /qa. Do not edit by hand.
// §qa:{artifact_path.as_posix()}
// To change this test, edit the source artifact and re-run /qa.
// Content hash: {chash}
// Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}

/**
 * Scenario test for: {fm.get('scenario_id', '<unknown>')}
 *
 * Parent spec: {fm.get('parent_spec', '<unknown>')}
 * Authored by: {fm.get('authored_by', '<unknown>')}
 * Last synced to spec at: {fm.get('last_synced_to_spec_at', '<unknown>')}
 *
 * Why this scenario exists:
{_doc_indent(why or '(see source artifact)')}
 */

""")

    parts.append(f"""describe('scenario: {test_desc}', () => {{
  test.skip('verifies {fm.get('scenario_id', '<id>')} against {fm.get('parent_spec', '<spec>')}', async () => {{
""")

    parts.append(render_setup(setup))
    parts.append("")
    parts.append("    // ---- Request payload (extract from artifact's When section) ----")
    parts.append("    const requestPayload: any = {};  // <-- REPLACE with payload from artifact's When section\n")

    parts.append(f"    // ---- Action under test ({action_type or 'unknown'}) ----")
    parts.append(render_action_call(action))

    parts.append("    // ---- Remove the test.skip() above once the call site is wired up ----")
    parts.append("")
    parts.append("    // ---- Assertions ----")
    parts.append(render_assertions(expectations))

    parts.append("  });\n})\n;\n")

    content = "\n".join(parts)

    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / f"{slugify(stem)}.test.ts"
    test_file.write_text(content, encoding="utf-8")
    return test_file


def _doc_indent(text: str) -> str:
    return "\n".join(" * " + line for line in text.split("\n"))


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

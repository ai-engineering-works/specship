#!/usr/bin/env python3
"""regression-playwright.py — generate a Playwright e2e test from a regression artifact.

Usage:
    python3 regression-playwright.py <artifact-path> [--out tests/e2e/]

Only generates a test if the regression artifact has a `ui_action:` block.
Backend-only regressions (no ui_action) are silently skipped.

Same selector/step/expectation vocabulary as scenario-playwright.py. Differs
in that the test describes "guards against this past UI bug" rather than
"verifies this user flow."

Logging: invoked by /qa, which logs qa_tests_generated.
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# Reuse scenario-playwright helpers — share the same module if available,
# else inline the minimum needed (same pattern as the other generators).
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


def _js_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def translate_selector(sel: str) -> str:
    """Same as scenario-playwright.translate_selector — see that file for docs."""
    if not isinstance(sel, str):
        return f"page.locator({_js_str(str(sel))})"
    sel = sel.strip()
    if not sel:
        return "page.locator('body')"
    prefixes = {
        "text": "getByText",
        "button": ("getByRole", "button"),
        "link": ("getByRole", "link"),
        "heading": ("getByRole", "heading"),
        "label": "getByLabel",
        "testid": "getByTestId",
        "placeholder": "getByPlaceholder",
        "title": "getByTitle",
        "alt": "getByAltText",
    }
    if ":" in sel:
        prefix, _, rest = sel.partition(":")
        prefix = prefix.strip().lower()
        rest = rest.strip()
        if prefix in prefixes:
            mapped = prefixes[prefix]
            if isinstance(mapped, tuple):
                method, role = mapped
                return f"page.{method}('{role}', {{ name: {_js_str(rest)} }})"
            else:
                return f"page.{mapped}({_js_str(rest)})"
    return f"page.locator({_js_str(sel)})"


def translate_step(step: dict, indent: str) -> str:
    if not isinstance(step, dict):
        return f"{indent}// Malformed step: {step!r}"
    action_keys = [k for k in step.keys() if k != "value"]
    if not action_keys:
        return f"{indent}// Step missing action key: {step!r}"
    action = action_keys[0]
    target = step.get(action)
    value = step.get("value")
    if action == "navigate":
        return f"{indent}await page.goto({_js_str(str(target))});"
    if action == "click":
        loc = translate_selector(str(target))
        return f"{indent}await {loc}.click();"
    if action == "fill":
        if value is None:
            return f"{indent}// fill step missing 'value' field: {step!r}"
        loc = translate_selector(str(target))
        return f"{indent}await {loc}.fill({_js_str(str(value))});"
    if action == "select":
        if value is None:
            return f"{indent}// select step missing 'value' field: {step!r}"
        loc = translate_selector(str(target))
        return f"{indent}await {loc}.selectOption({_js_str(str(value))});"
    if action == "wait_for":
        loc = translate_selector(str(target))
        return f"{indent}await {loc}.waitFor();"
    if action == "check":
        loc = translate_selector(str(target))
        return f"{indent}await {loc}.check();"
    if action == "uncheck":
        loc = translate_selector(str(target))
        return f"{indent}await {loc}.uncheck();"
    if action == "press":
        return f"{indent}await page.keyboard.press({_js_str(str(target))});"
    return f"{indent}// Unknown step action '{action}': {step!r} — wire up manually"


def translate_expectation(exp: dict, indent: str) -> str:
    if not isinstance(exp, dict):
        return f"{indent}// Malformed expectation: {exp!r}"
    keys = list(exp.keys())
    if not keys:
        return f"{indent}// Empty expectation"
    key = keys[0]
    val = exp[key]
    if key == "url_matches":
        v = str(val)
        if v.startswith("/") and v.endswith("/"):
            return f"{indent}await expect(page).toHaveURL(new RegExp({_js_str(v[1:-1])}));"
        return f"{indent}await expect(page).toHaveURL({_js_str(v)});"
    if key == "visible":
        loc = translate_selector(str(val))
        return f"{indent}await expect({loc}).toBeVisible();"
    if key == "not_visible":
        loc = translate_selector(str(val))
        return f"{indent}await expect({loc}).not.toBeVisible();"
    if key == "text_contains":
        return f"{indent}await expect(page.locator('body')).toContainText({_js_str(str(val))});"
    if key == "title_contains":
        return f"{indent}await expect(page).toHaveTitle(new RegExp({_js_str(str(val))}));"
    if key == "value_equals":
        if isinstance(val, dict) and "selector" in val and "value" in val:
            loc = translate_selector(str(val["selector"]))
            return f"{indent}await expect({loc}).toHaveValue({_js_str(str(val['value']))});"
        return f"{indent}// value_equals needs {{selector, value}} dict: {val!r}"
    if key == "count":
        if isinstance(val, dict) and "selector" in val and "n" in val:
            loc = translate_selector(str(val["selector"]))
            return f"{indent}await expect({loc}).toHaveCount({val['n']});"
        return f"{indent}// count needs {{selector, n}} dict: {val!r}"
    return f"{indent}// Unknown expectation '{key}': {val!r} — wire up manually"


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
    return s or "regression"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _doc_indent(text: str) -> str:
    return "\n".join(" * " + line for line in text.split("\n"))


def generate(artifact_path: Path, out_dir: Path):
    text = artifact_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    ui_action = fm.get("ui_action")
    if not ui_action:
        return None  # Silent skip for backend-only regressions

    if not isinstance(ui_action, dict):
        raise SystemExit(
            f"ui_action in {artifact_path} must be a block, got: {type(ui_action).__name__}"
        )

    start_url = ui_action.get("start_url", "/")
    steps = ui_action.get("steps") or []
    expectations = ui_action.get("expect") or []

    if not steps and not expectations:
        raise SystemExit(
            f"ui_action in {artifact_path} has neither steps nor expectations"
        )

    why = extract_section(body, "Why this regression exists")
    stem = artifact_path.stem
    test_desc = slugify(stem)
    chash = content_hash(text)

    parts = []
    parts.append(f"""// AUTO-GENERATED by specship /qa. Do not edit by hand.
// §qa:{artifact_path.as_posix()}
// To change this test, edit the source artifact and re-run /qa.
// Content hash: {chash}
// Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}

/**
 * Playwright e2e regression test for: {fm.get('regression_id', '<unknown>')}
 *
 * Parent fix: {fm.get('parent_fix', '<unknown>')}
 * Authored by: {fm.get('authored_by', '<unknown>')}
 *
 * Why this regression exists:
{_doc_indent(why or '(see source artifact)')}
 *
 * NOTE: regression e2e tests are append-only along with their source artifact.
 * If this test fails, fix the code — do not weaken the assertions to match
 * broken behavior. If the bug it guards against is genuinely no longer
 * relevant, retire the source artifact (status: retired) and regenerate.
 */

import {{ test, expect }} from '@playwright/test';

// Record video for every run.
test.use({{ video: 'on' }});

test.describe('e2e regression: {test_desc}', () => {{
  test.skip('guards against the UI bug fixed by {fm.get('parent_fix', '<unknown>')}', async ({{ page }}) => {{
    // ─── Navigate to start_url ────────────────────────────────────────────
    await page.goto({_js_str(start_url)});
""")

    if steps:
        parts.append("    // ─── Reproduce the user flow that originally exposed the bug ────────")
        for step in steps:
            parts.append(translate_step(step, "    "))
        parts.append("")

    if expectations:
        parts.append("    // ─── Assertions that fail if the bug returns ──────────────────────────")
        for exp in expectations:
            parts.append(translate_expectation(exp, "    "))
        parts.append("")

    parts.append("    // Remove test.skip() once selectors are wired up to the real UI.")
    parts.append("  });")
    parts.append("});")
    parts.append("")

    content = "\n".join(parts)

    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / f"{slugify(stem)}.spec.ts"
    test_file.write_text(content, encoding="utf-8")
    return test_file


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("artifact", help="path to the regression artifact")
    p.add_argument("--out", default="tests/e2e", help="output directory")
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

    if test_file is None:
        return 0

    print(str(test_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())

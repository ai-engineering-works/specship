#!/usr/bin/env python3
"""scenario-playwright.py — generate a Playwright e2e test from a scenario artifact.

Usage:
    python3 scenario-playwright.py <artifact-path> [--out tests/e2e/]

Only generates a test if the scenario artifact has a `ui_action:` block in its
frontmatter. Backend-only scenarios (no ui_action) are silently skipped — the
exit code is 0 and no file is written.

The generated test uses @playwright/test (the modern Playwright Test runner)
with video recording enabled via `test.use({ video: 'on' })`. The test starts
with `test.skip()` — same pattern as the other QA generators. The QA author
wires up selectors that need refining and removes the skip.

Logging: invoked by /qa, which logs qa_tests_generated.
"""

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# YAML-ish frontmatter parser — shared subset (same as scenario-pytest.py)
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
# Selector translation
# ============================================================================

def translate_selector(sel: str) -> str:
    """Translate a selector prefix string into a Playwright locator expression.

    Examples:
        'text:Welcome'         -> "page.getByText('Welcome')"
        'button:Subscribe'     -> "page.getByRole('button', { name: 'Subscribe' })"
        'label:Email'          -> "page.getByLabel('Email')"
        'testid:submit-btn'    -> "page.getByTestId('submit-btn')"
        '.btn-primary'         -> "page.locator('.btn-primary')"
    """
    if not isinstance(sel, str):
        return f"page.locator({_js_str(str(sel))})"
    sel = sel.strip()
    if not sel:
        return "page.locator('body')"

    # Recognized prefixes
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
                # Role-based: getByRole('button', { name: '...' })
                method, role = mapped
                return f"page.{method}('{role}', {{ name: {_js_str(rest)} }})"
            else:
                # Direct: getByText('...'), getByLabel('...')
                return f"page.{mapped}({_js_str(rest)})"

    # Fallback: raw CSS / XPath
    return f"page.locator({_js_str(sel)})"


def _js_str(s: str) -> str:
    """Encode a string for inclusion in a TypeScript single-quoted literal."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ============================================================================
# Step translation
# ============================================================================

def translate_step(step: dict, indent: str) -> str:
    """Translate one ui_action step to a Playwright statement.

    Steps are dicts with at most two keys: the action (navigate/click/fill/etc.)
    and supporting fields (value, for fill/select).
    """
    if not isinstance(step, dict):
        return f"{indent}// Malformed step: {step!r}"

    # Find the action key (first non-'value' key)
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
        # Special: press a keyboard key, no selector needed
        return f"{indent}await page.keyboard.press({_js_str(str(target))});"

    # Unknown action — emit a comment that the human can replace
    return f"{indent}// Unknown step action '{action}': {step!r} — wire up manually"


# ============================================================================
# Expectation translation
# ============================================================================

def translate_expectation(exp: dict, indent: str) -> str:
    """Translate one expect entry to a Playwright assertion."""
    if not isinstance(exp, dict):
        return f"{indent}// Malformed expectation: {exp!r}"

    keys = list(exp.keys())
    if not keys:
        return f"{indent}// Empty expectation"
    key = keys[0]
    val = exp[key]

    if key == "url_matches":
        # url_matches can be a literal string or a regex-ish pattern
        v = str(val)
        if v.startswith("/") and v.endswith("/"):
            # Treat as regex: /pattern/
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
        # Specifically for input/select: { value_equals: {selector: ..., value: ...} }
        # Expressed as a dict; needs both
        if isinstance(val, dict) and "selector" in val and "value" in val:
            loc = translate_selector(str(val["selector"]))
            return f"{indent}await expect({loc}).toHaveValue({_js_str(str(val['value']))});"
        return f"{indent}// value_equals needs {{selector, value}} dict: {val!r}"

    if key == "count":
        # count: { selector: ..., n: ... }
        if isinstance(val, dict) and "selector" in val and "n" in val:
            loc = translate_selector(str(val["selector"]))
            return f"{indent}await expect({loc}).toHaveCount({val['n']});"
        return f"{indent}// count needs {{selector, n}} dict: {val!r}"

    # Free-form / unknown
    return f"{indent}// Unknown expectation '{key}': {val!r} — wire up manually"


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
    return s or "scenario"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def generate(artifact_path: Path, out_dir: Path) -> Path | None:
    """Generate a Playwright test from the artifact.

    Returns the path of the written test file, or None if the artifact has no
    ui_action block (in which case nothing is written — backend-only scenarios
    don't need Playwright tests).
    """
    text = artifact_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    ui_action = fm.get("ui_action")
    if not ui_action:
        # No ui_action block — silently skip; this is the expected path for
        # backend-only scenarios.
        return None

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

    why = extract_section(body, "Why this scenario exists")
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
 * Playwright e2e test for scenario: {fm.get('scenario_id', '<unknown>')}
 *
 * Parent spec: {fm.get('parent_spec', '<unknown>')}
 * Authored by: {fm.get('authored_by', '<unknown>')}
 *
 * Why this scenario exists:
{_doc_indent(why or '(see source artifact)')}
 */

import {{ test, expect }} from '@playwright/test';

// Record video for every run of this test. Videos save to test-results/
// alongside any other test artifacts. CI can upload them.
test.use({{ video: 'on' }});

test.describe('e2e: {test_desc}', () => {{
  test.skip('verifies user flow for {test_desc}', async ({{ page }}) => {{
    // ─── Setup ────────────────────────────────────────────────────────────
    // The source artifact declares these scenario preconditions; the e2e test
    // needs them satisfied via UI setup, fixtures, or seeded test data:""")

    # Preserve scenario setup as comments for context (the test author has to
    # implement them since they're free-form prose, not structured steps)
    setup = fm.get("setup") or []
    if setup:
        for i, s in enumerate(setup, 1):
            parts.append(f"    //   {i}. {s}")
    else:
        parts.append(f"    //   (no preconditions declared)")

    parts.append("")
    parts.append(f"    // ─── Navigate to start_url ────────────────────────────────────────────")
    parts.append(f"    await page.goto({_js_str(start_url)});")
    parts.append("")

    if steps:
        parts.append("    // ─── User flow steps ──────────────────────────────────────────────────")
        for step in steps:
            parts.append(translate_step(step, "    "))
        parts.append("")

    if expectations:
        parts.append("    // ─── Expectations ─────────────────────────────────────────────────────")
        for exp in expectations:
            parts.append(translate_expectation(exp, "    "))
        parts.append("")

    parts.append(f"    // ─── Remove the test.skip() above once selectors are wired up ────────")
    parts.append(f"    //")
    parts.append(f"    // The generated selectors above use semantic locators (getByRole, getByLabel,")
    parts.append(f"    // getByText) based on the ui_action block. If they don't match your real UI,")
    parts.append(f"    // either:")
    parts.append(f"    //   (a) Edit the ui_action block in the source artifact and re-run /qa,")
    parts.append(f"    //   (b) Replace selectors directly here (the pre-commit hook will warn).")
    parts.append("  });")
    parts.append("});")
    parts.append("")

    content = "\n".join(parts)

    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / f"{slugify(stem)}.spec.ts"
    test_file.write_text(content, encoding="utf-8")
    return test_file


def _doc_indent(text: str) -> str:
    return "\n".join(" * " + line for line in text.split("\n"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("artifact", help="path to the scenario artifact")
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
        # No ui_action — silent skip is the expected path for backend-only artifacts
        return 0

    print(str(test_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())

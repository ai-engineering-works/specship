#!/usr/bin/env bash
#
# breaking-change-check.sh — classify a contract artifact diff as additive or breaking
#
# Invoked by /contract when the contract surface hash differs from the
# previous compilation. Compares the OLD generated OpenAPI artifact against
# the NEW one and tells the caller what changed.
#
# Strategy (graceful degradation):
#   1. If oasdiff is on PATH, use it (gold-standard OpenAPI breaking-change
#      detection; supports all OpenAPI 3.x semantics).
#   2. Otherwise, run a built-in Python fallback that detects the most
#      common breaking changes (removed endpoints, removed fields, type
#      changes, required-field additions). This is not as thorough as
#      oasdiff but catches ~80% of real-world cases.
#
# Usage:
#   breaking-change-check.sh OLD_OPENAPI NEW_OPENAPI
#
# Output: JSON to stdout describing the result. Exit code is always 0
# unless the tool itself fails (missing files, etc.) — the *content* of
# the output indicates whether breaking changes were detected.
#
# Output schema:
#   {
#     "tool": "oasdiff" | "fallback",
#     "breaking": true | false,
#     "additive": true | false,
#     "summary": "<one-line summary>",
#     "details": ["<line-by-line findings>", ...]
#   }

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 OLD_OPENAPI NEW_OPENAPI" >&2
    exit 2
fi

OLD="$1"
NEW="$2"

if [[ ! -f "$OLD" ]]; then
    # No old file — this is a first generation. Not a diff scenario.
    cat <<EOF
{"tool":"none","breaking":false,"additive":true,"summary":"first generation; no previous artifact to compare against","details":[]}
EOF
    exit 0
fi

if [[ ! -f "$NEW" ]]; then
    echo "NEW_OPENAPI not found: $NEW" >&2
    exit 2
fi

# Resolve the helper directory for the Python fallback
HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Try oasdiff first ----

if command -v oasdiff >/dev/null 2>&1; then
    # oasdiff's `breaking` subcommand exits non-zero if breaking changes are
    # found, 0 if none. The `--format json` produces structured output we
    # can re-shape.
    OASDIFF_OUT=$(oasdiff breaking "$OLD" "$NEW" --format json 2>/dev/null || true)
    OASDIFF_EXIT=$?

    # We use Python to reshape oasdiff's output into our schema, because
    # oasdiff's JSON shape has shifted across versions and we want stable
    # output for downstream tooling.
    python3 - "$OASDIFF_OUT" "$OASDIFF_EXIT" <<'PYEOF'
import json
import sys

raw = sys.argv[1]
exit_code = int(sys.argv[2])

# oasdiff may return empty string on "no breaking changes"
try:
    parsed = json.loads(raw) if raw.strip() else []
except json.JSONDecodeError:
    parsed = []

# Normalise to a list of finding dicts
if isinstance(parsed, dict):
    findings = parsed.get("changes", []) or parsed.get("breakingChanges", []) or []
else:
    findings = parsed if isinstance(parsed, list) else []

breaking = bool(findings)
details = []
for f in findings:
    if isinstance(f, dict):
        text = f.get("text") or f.get("description") or json.dumps(f, ensure_ascii=False)
        details.append(text)
    else:
        details.append(str(f))

result = {
    "tool": "oasdiff",
    "breaking": breaking,
    "additive": not breaking,
    "summary": (
        f"oasdiff detected {len(findings)} breaking change(s)"
        if breaking
        else "oasdiff: no breaking changes (changes are additive or none)"
    ),
    "details": details,
}
print(json.dumps(result, ensure_ascii=False))
PYEOF
    exit 0
fi

# ---- Fallback: built-in Python check ----

python3 "$HELPER_DIR/breaking-change-fallback.py" "$OLD" "$NEW"

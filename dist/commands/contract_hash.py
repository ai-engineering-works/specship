#!/usr/bin/env python3
"""
Reference implementation of the Contract surface section hash.

This is NOT meant to be invoked by /contract or /work — those commands
implement the same algorithm inline. This script exists as:
  1. Executable documentation of the algorithm
  2. A sanity-test fixture proving the algorithm is stable across
     spec metadata edits (the core correctness property)
"""
import hashlib
import re
import sys


def extract_normalised_contract_surface(spec_text: str) -> str:
    """
    Extract and normalise the Contract surface section.

    Steps:
      1. Find `## Contract surface` heading
      2. Take everything until the next `##` heading (or EOF)
      3. Strip HTML comments
      4. Trim trailing whitespace from each line
      5. Collapse 2+ blank lines to one
      6. Strip leading/trailing blank lines
      7. Ensure exactly one trailing '\n'

    Returns the normalised section as a string, ready to hash.
    Raises ValueError if no Contract surface section exists.
    """
    # 1 + 2: Find the section
    pattern = re.compile(
        r"^## Contract surface\s*$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(spec_text)
    if not match:
        raise ValueError("No Contract surface section found in spec")
    section = match.group(1)

    # 3: Strip HTML comments (multi-line aware)
    section = re.sub(r"<!--.*?-->", "", section, flags=re.DOTALL)

    # 4: Trim trailing whitespace from each line
    lines = [line.rstrip() for line in section.split("\n")]

    # 5: Collapse 2+ blank lines to one
    collapsed = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    # 6: Strip leading/trailing blank lines
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()

    # 7: Exactly one trailing newline
    return "\n".join(collapsed) + "\n"


def contract_hash(spec_text: str) -> str:
    """Compute the full 64-char sha256 of the normalised contract surface."""
    normalised = extract_normalised_contract_surface(spec_text)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: contract_hash.py <spec-file>", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        spec_text = f.read()
    print(contract_hash(spec_text))

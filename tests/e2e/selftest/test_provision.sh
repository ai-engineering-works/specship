#!/usr/bin/env bash
. "$(dirname "$0")/../lib/provision.sh"
fails=0
T="$(provision_repo)"
trap 'rm -rf "$T"' EXIT

check() { if eval "$2"; then ok "$1"; else fail "$1"; fails=$((fails+1)); fi; }
check ".specship/ledger exists"     "[[ -f '$T/.specship/ledger/specship_ledger.py' ]]"
check "pre-commit hook installed"   "[[ -x '$T/.git/hooks/pre-commit' ]]"
check "qa-check helper installed"   "[[ -f '$T/.specship/hooks/qa-check.py' ]]"
check "CLAUDE.md full-stack"        "grep -q 'Project type:.*full-stack' '$T/CLAUDE.md'"
check "commands installed"          "[[ -f '$T/.claude/commands/spec.md' ]]"
[[ $fails -eq 0 ]]

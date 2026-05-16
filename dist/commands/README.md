# Commands

Slash commands for the specship workflow.

## Main commands (these are what Claude Code invokes)

- `spec.md` — `/spec`, drafts a spec
- `contract.md` — `/contract`, compiles contract surface
- `work.md` — `/work`, executes against a spec
- `check.md` — `/check`, drift detection

## Auxiliary files

- `contract_hash.py` — reference implementation of the Contract surface hash algorithm.
  Not invoked by `/contract` directly; `/contract` re-implements the same algorithm
  inline. This script exists as executable documentation and a sanity-test fixture.

  Usage:
  ```
  python3 contract_hash.py path/to/spec.md
  ```

- `test-fixtures/spec-before.md` and `test-fixtures/spec-after.md` — fixture pair
  proving the hash is stable across the spec mutations `/contract` performs.

  Verify:
  ```
  python3 contract_hash.py test-fixtures/spec-before.md
  python3 contract_hash.py test-fixtures/spec-after.md
  # Both should print the same hash.
  ```

Neither auxiliary file is needed at runtime. They can be omitted from a production
install. They exist because the hash mechanism is the most subtle part of the
workflow and is worth having a verifiable spec for.

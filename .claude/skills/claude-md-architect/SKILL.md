---
name: claude-md-architect
description: Write a new CLAUDE.md from scratch, convert an existing CLAUDE.md (or AGENTS.md / rules file) into the specship template, audit a CLAUDE.md against the template, OR design and refactor nested CLAUDE.md hierarchies for monorepos and multi-module projects. Use whenever the user mentions writing, refactoring, restructuring, migrating, or splitting a CLAUDE.md, AGENTS.md, project constitution, repo-level AI instructions, or any "rules file" that guides AI-assisted coding. Also trigger when the user wants to bootstrap AI-assisted development in a new repo, audit an existing CLAUDE.md for gaps, extract invariants from incidents or runbooks into a constitution, design module-level CLAUDE.md files for a monorepo, split a bloated root CLAUDE.md into root + nested files, or check whether nested CLAUDE.md files are coherent with the root.
---

# claude-md-architect

A skill for producing high-quality `CLAUDE.md` files — the files Claude Code reads to anchor its behaviour in a repo.

The target shape is the **specship template**: a small (≤200 line) file with six fixed sections that capture what the codebase is, the non-negotiable invariants, the soft conventions, the verification steps, the repo layout, and the domain glossary.

Claude Code supports **nested CLAUDE.md files** in subdirectories. The root file loads at session start; nested files load on demand when Claude reads files in those subtrees. This skill handles both root and nested files, and helps users design the hierarchy.

This skill handles four modes:

1. **Greenfield** — write a CLAUDE.md from nothing, by interviewing the user
2. **Conversion** — take an existing CLAUDE.md (or similar file) and restructure it into the template
3. **Audit** — review an existing CLAUDE.md (and any nested ones) against the template and report gaps
4. **Hierarchy** — design or refactor nested CLAUDE.md files across modules, or split a bloated root file into root + nested

Pick the mode based on what the user actually has and asks for.

## When to use each mode

- User says *"create a CLAUDE.md"* with no existing file → **Greenfield**
- User says *"convert this"*, *"reformat"*, *"migrate"*, or points at an existing file → **Conversion**
- User says *"review"*, *"audit"*, *"check"*, *"what's missing"* → **Audit**
- User mentions *"nested"*, *"monorepo"*, *"per-module"*, *"split"*, *"modules/packages"*, or asks how to organise CLAUDE.md across a multi-module project → **Hierarchy**

If unclear, ask once.

## Core principles (apply to all modes)

1. **One file, ≤200 lines.** If a section bloats, move detail to a referenced file (`architecture.md`, `runbooks/`, etc.) and link from CLAUDE.md.
2. **Invariants are append-only and traceable.** Every invariant should trace to a real incident, regulation, design decision, or domain rule — not aspirational hygiene. Aspirational stuff belongs in "Conventions worth following".
3. **Verification steps are mechanical.** "Code is clean" is not a verification step. "`ruff check src/` clean" is.
4. **No fluff.** If a section is empty, write "none" — don't pad.
5. **Respect the user's voice.** When converting an existing file, preserve the user's terminology, project names, and judgement calls. The skill restructures; it does not invent technical opinions.

## The template

The canonical template lives in `references/template.md`. Read it before drafting any CLAUDE.md so the structure is exactly right. Section order and headings matter — they're the schema other tools (slash commands, hooks) will look for.

Section structure (must appear in this order, with these exact `##` headings):

1. `## What this codebase is`
2. `## Non-negotiable invariants`
3. `## Conventions worth following`
4. `## How to verify work is done`
5. `## Where things live`
6. `## Domain glossary`

## Mode 1: Greenfield

The user has no existing CLAUDE.md and wants one.

**Step 1 — Discover.** Before interviewing, look at the repo for free signals:
- `README.md` — usually has the "what this codebase is" content
- `package.json` / `pyproject.toml` / `pom.xml` / `build.gradle` — gives stack, scripts, deps
- `.github/workflows/` or `.gitlab-ci.yml` — gives verification commands
- Top-level directory structure — gives "where things live"
- Any `ARCHITECTURE.md`, `CONTRIBUTING.md`, runbooks, ADRs — mine for invariants

Pull everything you can passively. Only ask the user about things you genuinely cannot infer.

**Step 2 — Interview, but only for gaps.** Ask focused questions, batched. Examples of high-value questions:

- "Is there a class of bug you've shipped more than once? Those are candidate invariants."
- "Are there regulatory or compliance rules that constrain how this code behaves at runtime?"
- "What's the single command (or commands) that proves a change is ready to merge?"
- "What acronyms would a new engineer get stuck on?"

Use the `ask_user_input_v0` tool if you have multiple choice questions; use prose questions for open-ended ones. Limit to one round of questions unless the user wants more depth.

**Step 3 — Draft.** Fill the template. Where the user gave you content, use their wording. Where you inferred from the repo, attribute (e.g. "Inferred from pyproject.toml — confirm?"). Where you have nothing, leave a `[fill in — <hint>]` placeholder rather than inventing.

**Step 4 — Review with the user.** Show the draft. Specifically call out:
- Any `[fill in]` placeholders that still need attention
- Any inferred items that need confirmation
- Anything you flagged as a candidate invariant that the user should accept or reject

## Mode 2: Conversion

The user has an existing CLAUDE.md (or AGENTS.md, or a project rules file by any name) and wants it restructured into the template.

**Step 1 — Read the source file.** Read it in full. Note its current structure, voice, and any conventions it uses.

**Step 2 — Classify every piece of content.** Walk through the source file paragraph by paragraph. For each piece of content, decide which target section it belongs to:

| Source content looks like | Target section |
|---|---|
| Project description, what the system does | `## What this codebase is` |
| "Never do X", "always Y", hard rules, regulatory constraints | `## Non-negotiable invariants` |
| "We prefer", "usually", "style guide" type guidance | `## Conventions worth following` |
| Commands that prove done-ness, CI checks, test commands | `## How to verify work is done` |
| Directory descriptions, file location guidance | `## Where things live` |
| Acronyms, domain terms, project-specific jargon | `## Domain glossary` |
| Tone/personality instructions ("be concise", "don't apologise") | DROP (these belong in user preferences, not CLAUDE.md) |
| Tool-specific instructions ("when using bash, do X") | DROP or move to conventions, depending on importance |
| Long explanatory prose about architecture | EXTRACT to `architecture.md`, link from CLAUDE.md |

Use `references/conversion-rules.md` for the full rules, including edge cases.

**Step 3 — Strengthen invariants.** This is the highest-value part of conversion. Most existing CLAUDE.md files mix invariants with conventions and vague guidance. Pull out the genuine invariants and:
- Restate each as a short imperative
- Add a §ref or incident ID if the user can supply one (ask if not provided)
- Mark anything that's actually a convention (not an invariant) and move it down

**Step 4 — Strip and tighten.** Cut:
- Redundancy across sections
- Filler ("please remember to", "it's important that")
- Anything that's documentation, not instruction
- Tone/personality content (move to user preferences if the user wants)

**Step 5 — Write the new file.** Use the template structure. Preserve the user's terminology and project-specific judgement. Keep the result under 200 lines — if it's longer, identify what to extract.

**Step 6 — Show a diff-style summary.** Tell the user:
- What was preserved (and from where)
- What was promoted to invariant
- What was demoted to convention
- What was dropped (and why)
- What was extracted to a separate file (if anything)

## Mode 3: Audit

The user has an existing CLAUDE.md and wants to know how it stacks up against the template, without an immediate rewrite.

**Step 1 — Discover all CLAUDE.md files in the repo.** Don't assume there's only one. Run a scan:

```bash
find . -name "CLAUDE.md" -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/_generated/*'
find . -name "CLAUDE.local.md" -not -path '*/node_modules/*' -not -path '*/.git/*'
```

Note all discovered files. The root file is loaded at every session; nested ones load on demand when Claude reads files in those subtrees. Each file's quality matters independently AND in relation to the root.

**Step 2 — Read the root file.**

**Step 3 — Score the root against the template.** For each of the six required sections, note:
- Present and adequate
- Present but weak (and why)
- Missing

**Step 4 — Read each nested file (if any).** For each, note:
- Path
- Approximate scope (which module/package it covers)
- Whether it follows the template shape (nested files MAY use a lighter shape — see Mode 4 for guidance)
- Whether it conflicts with or duplicates the root

**Step 5 — Identify the top issues.** Don't list everything. Surface the 3–5 highest-impact gaps. Examples:
- "Invariants section is missing in root — the file is documentation, not instruction."
- "Nested `frontend/CLAUDE.md` duplicates 12 lines from root verbatim — should reference root, not repeat."
- "Verification steps in `backend/CLAUDE.md` contradict root (root says `pytest`, nested says `unittest`)."
- "No nested files exist despite repo having 6 distinct services — likely missed opportunity for module-specific context."

**Step 6 — Offer next steps.** End with options:
- "Want me to convert the root file?" → Mode 2
- "Want me to design a nested hierarchy?" → Mode 4
- "Want me to fix the conflicts between root and nested?" → Mode 4 (refactor variant)

## Mode 4: Hierarchy

The user has (or wants) a monorepo / multi-module project with module-specific CLAUDE.md files. This mode designs the hierarchy, splits a bloated root, or refactors existing nested files for coherence.

### When nested CLAUDE.md files earn their place

Nested files are valuable when AND ONLY when one of these is true:

1. **Module has distinct invariants** the root can't articulate (e.g. frontend has accessibility rules backend doesn't care about)
2. **Module has distinct verification commands** (e.g. backend runs `pytest`, frontend runs `vitest`, infra runs `terraform validate`)
3. **Module has distinct domain glossary** (e.g. `frontend/CLAUDE.md` explains UI-specific terms like "panel", "drawer")
4. **Module's `Where things live` differs** materially from siblings
5. **Module is owned by a different team** with different conventions inside this repo

If none of those apply, **do not create a nested file.** A README.md works fine. Nested CLAUDE.md adds maintenance burden — each one is another file that can drift, contradict the root, or go stale.

### What goes WHERE

| Content | Lives in |
|---|---|
| Project-wide invariants (regulatory, cross-cutting data integrity) | **Root only** |
| Project-wide verification commands (CI gate, top-level test command) | **Root only** |
| `Project type`, `Backend language`, `Frontend language`, `Contract pair name` | **Root only** (consumed by /spec and /contract) |
| Module-specific invariants | **Module CLAUDE.md** |
| Module-specific verification (per-package test command) | **Module CLAUDE.md** |
| Module-specific glossary terms | **Module CLAUDE.md** |
| The same content in both root and module | **Pick one; never duplicate** |

The discipline that protects this: **a nested file inherits everything from root; it adds, refines, or scopes — it does not duplicate.** Always start with "this module's CLAUDE.md adds these constraints on top of root" and only write what's genuinely additive.

### Nested file template (lighter than root)

Nested files use a *reduced* template. Most sections are optional. Only sections that genuinely add value over the root should be present.

```markdown
# <Module name> Constitution

<!-- Inherits all rules from the root CLAUDE.md. This file adds
     module-specific guidance. Sections present here OVERRIDE or
     EXTEND the root; sections absent here defer to root. -->

## What this module is

<1-2 sentences. Just enough that Claude knows the module's role
within the larger project.>

## Non-negotiable invariants
<!-- Only invariants specific to THIS module. Omit if none. -->

- <invariant>

## Conventions worth following
<!-- Only conventions specific to THIS module. Omit if none. -->

- <convention>

## How to verify work is done
<!-- Module-specific verification commands. Omit if same as root. -->

- <command>

## Domain glossary
<!-- Only terms specific to THIS module. Omit if none. -->

- <term> — <definition>
```

Strict size cap: **nested files ≤100 lines.** If approaching, extract to a referenced file or push content back to root.

### Step 1 — Discover

Same scan as Audit Step 1. Map the repo structure:

```bash
find . -name "CLAUDE.md" -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/_generated/*'
# Also look at the directory structure to find candidate module boundaries
ls -d */ */*/  2>/dev/null  # top-level and one-deep directories
```

### Step 2 — Identify module boundaries

Ask the user (or infer from the layout):
- Is this a monorepo with workspaces (e.g. `services/`, `apps/`, `packages/`)?
- Is this a single project with logical modules (e.g. `src/api/`, `src/web/`)?
- Are there team boundaries (a `frontend/` team and `backend/` team)?

Each genuine boundary is a *candidate* for a nested CLAUDE.md. Most projects need at most 3-5 nested files. If you're considering more, you're likely fragmenting needlessly.

### Step 3 — For each candidate module, decide

Run through the "When nested CLAUDE.md files earn their place" checklist. Either:
- **Skip** — root coverage is sufficient; explain to user why
- **Create new** — module has distinct content worth its own file; draft it
- **Refactor existing** — module already has a file; assess whether it duplicates root and tighten

### Step 4 — Split a bloated root (if applicable)

If the root CLAUDE.md is over 200 lines because it documents per-module specifics, the right move is to split:

1. Identify content in root that is module-specific (e.g. "backend invariants:", "frontend invariants:")
2. For each module-specific block, create or update a nested file containing only that content
3. Remove the module-specific blocks from root, leaving only cross-cutting content
4. Root should shrink. If it doesn't, the content wasn't module-specific — investigate.

### Step 5 — Verify coherence

After all files are written:
- No fact appears in both root and a nested file (no duplication)
- No nested file contradicts root (no conflict)
- Each nested file is ≤100 lines
- Root is still ≤200 lines
- Sum of all CLAUDE.md content in the repo is genuinely smaller than the original bloated root (otherwise the split was theatre)

### Step 6 — Report

Tell the user:
- Files created or modified
- Lines of content in each
- Total CLAUDE.md content in the repo, before and after
- Any module that was deliberately left without a nested file, and why

### Pitfalls to call out

- **Duplication.** The single biggest failure mode of nested files. If you find yourself copying the root's "Multi-character delimiters use `~|~`" into a nested file, stop — that rule already applies via the root.
- **Contradiction.** Worse than duplication. If root says `pytest` and `backend/CLAUDE.md` says `unittest`, Claude will be confused. Pick one and have the other defer.
- **Premature fragmentation.** Two specs that *might* diverge are not a reason to split. Wait until they actually diverge.
- **Personal preference creep.** Nested files are NOT for "I prefer to format my Python this way". That's user preferences, not project constitution.

## After producing a CLAUDE.md (any mode)

1. **Save it.** If the user is in their repo, the file goes at the repo root as `CLAUDE.md`. If you're producing it as a deliverable to share, save it somewhere the user can copy from and tell them clearly where it is.

2. **Suggest the next step.** If they don't already have the rest of the specship setup:
   - Set up `specs/` directory
   - Install the `/spec` and `/work` slash commands
   - Install the pre-commit hook

3. **Don't lecture.** A short next-step nudge is enough. The user can take it or leave it.

## What not to do

- Do not invent invariants the user didn't supply or imply. Invariants must be real.
- Do not pad sections to look complete. "none" is a valid section content.
- Do not preserve fluff from the source file out of politeness. The whole point of conversion is to tighten.
- Do not include personality/tone instructions ("be concise", "be helpful"). CLAUDE.md is for project constraints, not assistant behaviour.
- Do not exceed 200 lines. If you're heading there, extract to a referenced file.
- Do not invent ticket IDs, §ref codes, or incident numbers. Leave a placeholder and ask the user to fill them.

## Reference files

- `references/template.md` — the canonical empty template for root CLAUDE.md
- `references/nested-template.md` — the lighter template for module-level CLAUDE.md files
- `references/conversion-rules.md` — detailed classification rules for Mode 2
- `references/examples.md` — example before/after conversions for common cases
- `references/hierarchy-examples.md` — worked examples for Mode 4 (monorepo splits)

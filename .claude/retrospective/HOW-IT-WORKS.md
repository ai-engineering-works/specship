# Retrospective — meta-reflection on your Claude Code workflow

`dist/retrospective/generate.py` reads recent Claude Code transcripts plus the
specship ledger, calls the Anthropic API with a structured prompt, and writes a
`retrospective_generated` event into the ledger. The dashboard's
`/#/retrospectives` tab renders the result.

The output is **about HOW you used the tools**, not about your code:
a 3-5 sentence summary plus exactly 3 ranked, actionable workflow suggestions.

## When it runs

CLI only on day 1. The dashboard never triggers generation — it stays
read-only.

```bash
# Workspace-wide, last 7 days (default)
python3 .specship/retrospective/generate.py

# A specific repo (slug as discovered by the dashboard)
python3 .specship/retrospective/generate.py --repo specship-parent

# Different window
python3 .specship/retrospective/generate.py --days 30

# Dry run: assemble prompt + count sessions, no API call
python3 .specship/retrospective/generate.py --dry-run

# Override model
python3 .specship/retrospective/generate.py --model claude-opus-4-7
```

Re-running on the same day with the same `--scope` and `--days` is a no-op —
the generator detects an existing same-day `retrospective_generated` event and
exits 0 without calling the API.

If you want it to run on a schedule, add a cron entry yourself:

```cron
0 9 * * 1  cd $HOME && python3 ~/.specship/retrospective/generate.py >/dev/null 2>&1
```

## Where retrospectives land

| Scope                | Ledger location                                         |
|----------------------|---------------------------------------------------------|
| `--repo <slug>`      | `<repo>/.specship/ledger/events.jsonl`                  |
| `--repo all` (default) | `~/.specship/global/ledger/events.jsonl`              |

The dashboard discovers the global ledger as a pseudo-repo with slug `global`,
so workspace-wide retrospectives appear under that filter.

## Privacy posture

Day 1: raw transcript text (user messages + assistant text) is sent to the
Anthropic API. Tool result blocks beyond a short metadata summary are dropped,
but anything you typed or anything Claude wrote IS sent. That includes pasted
code, file contents Claude read in context, and any secrets you may have
shared.

If that's not acceptable in your environment, do not install this hook. A
future phase can add aggressive scrubbing (paths/secrets redaction) before
sending — file an issue if you want it.

The API call uses your `ANTHROPIC_API_KEY` environment variable. We send no
telemetry beyond that.

## Anthropic SDK dependency

The generator imports the `anthropic` Python SDK. If it's not installed, the
script prints an actionable install hint and exits non-zero:

```
pip install --user anthropic
```

This is the first runtime dependency specship introduces. It is required only
for the retrospective feature — all other specship commands continue to work
with stdlib alone.

## Output shape

The `retrospective_generated` event carries:

| Field             | Type      | Notes                                                |
|-------------------|-----------|------------------------------------------------------|
| `retrospective_id`| str       | sha256[:7] of `(scope, ts, days)`                    |
| `ts`              | ISO-8601  | Generation time                                      |
| `scope`           | str       | Repo slug, or the literal string `all`               |
| `days_covered`    | int       | How many days back the analysis read                 |
| `model`           | str       | Anthropic model used                                 |
| `summary_text`    | str       | 3-5 sentence workflow summary                        |
| `suggestions`     | JSON list | Exactly 3 entries, each `{title, body, priority}`    |
| `tokens_used`     | int       | Anthropic API tokens for this generation             |
| `session_count`   | int       | How many Claude Code sessions fed into the analysis  |

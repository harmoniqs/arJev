# Agent setup runbook — installing arJev for a researcher

You are an AI agent setting up **arJev** — a daily arXiv digest engine that ranks
against a researcher's Obsidian vault — on this person's machine, on their behalf.
Follow this runbook top to bottom. Every step has an acceptance check; do not claim
a step done without its check passing. Ask the human only where a browser or a
taste decision is genuinely theirs (marked **HUMAN STEP**).

## 0. What you are building

```
their Obsidian vault (taste, records, ground truth)
        → daily digest (ranked against the vault) → stdout / vault / Slack
        → keeps scaffold back into the vault → taste grows
        → weekly calibration report (labels vs predictions)
```

The vault is the core. Slack is optional. Keys are optional (the engine runs
lexical-only without them and says so). **Invariants you must respect:**

- Never edit an existing note (arJev writes new files only; the single exception is
  `arjev rate accept`, which the human explicitly invokes).
- Keys/tokens live in env vars or mode-600 files, never in configs or the repo.
- Runtime artifacts go under the XDG state dir (`~/.local/state/arjev/`), never
  inside a repo or the vault.

## 1. Install

```bash
uv tool install git+https://github.com/harmoniqs/arJev@v0.1.9
```

(`pipx install` works too. Python 3.11+ required.)

**Check:** `arjev --version` prints a version.

## 2. Find (or plan) the vault

Ask the human where their literature notes live. A vault works if it has markdown
notes with frontmatter `type: paper` and an `arxiv:` (or `doi:`) field — but **every
field is remappable**, so Zotero-style exports and custom schemas are fine. No
vault yet? Create an empty directory and seed it in step 5.

**Check:** `arjev init --vault <path>` succeeds and runs a smoke digest (it prints
the config path; zero notes is fine — the digest will say `profile-degraded`).

## 3. Configure

The scaffolded config is at `~/.config/arjev/arjev.toml`. Adjust with the human:

- `feeds` — arXiv categories (e.g. `["quant-ph", "cond-mat.mes-hall", "cs.AI"]`)
- `top` — picks per digest (default 5)
- `ranking` — `jev-first` (default; requires a Jev key) or `lexical-first`
- Ask them for a taste-directives note (`arjev-directives.md` at the vault root):
  labs, companies, topics as frontmatter lists plus a prose body saying what they
  want. **HUMAN STEP** — taste is theirs; offer the template and let them edit.

**Check:** `arjev digest --post stdout` prints a digest with a `mode:` line.

## 4. Keys (optional, both fail open)

- **Jev** (semantic ranking of the full feed): get a key from
  <https://console.typesafe.ai>, drop it in a mode-600 file, and set
  `ARJEV_JEV_KEY_FILE=<path>` in the timer environment. Cost is ~pennies/day/feed.
  Without it: lexical-only, clearly flagged.
- **Slack** (optional attention layer): see [slack-setup.md](slack-setup.md).
  **HUMAN STEP** — creating the Slack app requires their browser. Scopes:
  `chat:write`, `reactions:read`, `conversations:replies`. Token in a mode-600
  file; `ARJEV_SLACK_TOKEN` env. Set `channel` (the channel ID), `keepers`
  (user IDs whose reactions count as labels), `why_style` in the config.

**Check:** with a Jev key, the digest's `mode:` line says `jev`.

## 5. Seed the vault from what they already have

Any combination, all idempotent, all provenance-stamped:

```bash
arjev ingest --bibtex ~/Downloads/library.bib
arjev ingest --pdf-dir ~/Papers
arjev ingest --slack-channel-id C01234567 --limit 200
```

**Check:** the printed counts match reality; seeded notes appear in the vault's
`papers/` dir with `why:` provenance lines. Re-running changes nothing.

## 6. The daily run + timers

One manual run first: `arjev digest --post slack` (or `vault`/`stdout`). Then a
timer. Linux systemd user unit (daily 13:00 UTC):

```ini
# ~/.config/systemd/user/arjev-digest.timer
[Timer]
OnCalendar=*-*-* 13:00:00 UTC
Persistent=true
```

with a `.service` running a wrapper that exports the key env vars from their
mode-600 files, then `arjev digest --feed <feeds> --top 5 --post slack` and
`arjev slack sync` (idempotent; harvests reactions → labels → staged stubs).
macOS: a launchd plist with the same shape. **Check:** `systemctl --user
list-timers` shows it armed (or `launchctl list` on macOS), and the first manual
run posted.

## 7. Tell the human what they own

- React 👍/👀/❌ on picks (if keepers-listed) — each becomes a label + a vault stub.
- Fill `rating:` and `why:` on stubs — that's what makes notes taste.
- `arjev calibrate` (weekly; add it to the timer on Sundays) — read the report;
  thresholds are human-applied, by design.
- Rate-proposals: `arjev rate propose` asks the model for advisory first-pass
  ratings (side table only, vault untouched); `arjev rate accept <arxiv> <rating>`
  is the human gate that writes the rating.

## Failure modes you will hit

- **"feed parsed to zero items"** — arXiv RSS occasionally returns junk mid-day;
  the digest refuses to post empty and the next run recovers.
- **Slack `missing_scope`** — the app lacks a scope; the setup doc lists all three.
- **`profile-degraded` in the mode line** — fewer than 5 notes or no `why` lines
  yet; seed more or write a few notes.

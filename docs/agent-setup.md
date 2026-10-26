# Agent setup runbook — installing arJev for a researcher

You are an AI agent setting up **arJev** — a daily arXiv digest engine that ranks
against a researcher's Obsidian vault — on this person's machine, on their behalf.

This runbook is **field-agnostic**. arJev serves any field that posts to arXiv and
sources nothing beyond arXiv — the same engine, the same steps, whether this person
works on moiré materials, market design, or neural coding. Nothing below assumes
which field; the interview (step 2) asks.

Follow it top to bottom. Every step has an acceptance check you run verbatim —
do not claim a step done without its check passing. Ask the human only where a
browser or a taste decision is genuinely theirs (marked **HUMAN STEP**).
The human-facing version of these steps is [setup.md](setup.md); link the human
there for anything they do by hand.

## 0. What you are building — and what you write

```
their Obsidian vault (taste, records, ground truth)
        → daily digest (ranked against the vault) → stdout / vault / Slack
        → keeps scaffold back into the vault (status: staged)
        → YOU write the staged notes' prose (status: written) → taste grows
        → weekly calibration report (labels vs predictions)
```

The division of labor: **the decision model judges, you write, the vault stays
theirs.** Jev — the ranking model — is text-free by design and cannot generate a
sentence. Every piece of prose in this system (note bodies, why-lines, takes) is
yours to write, or the human's. arJev itself never writes prose. **Invariants you
must respect:**

- Never edit an existing note through the tool (arJev writes new files only; the
  single exception is `arjev rate accept`, which the human explicitly invokes).
  Your own prose edits to staged notes are ordinary vault edits the human reviews.
- Keys/tokens live in env vars or mode-600 files, never in configs or the repo.
- Runtime artifacts go under the XDG state dir (`~/.local/state/arjev/`), never
  inside a repo or the vault.

## 1. Install

```bash
uv tool install git+https://github.com/harmoniqs/arJev
```

(`pipx install` works too. Python 3.11+ required. To pin, append `@vX.Y.Z`
from the [changelog](../CHANGELOG.md).)

**Check:** `arjev --version` prints a version.

## 2. The interview (five questions, in order)

Interview the researcher before touching the config. One question at a time; the
answers decide everything downstream:

1. **Field** — what field do they work in? → their arXiv categories, taken from
   the taxonomy at <https://arxiv.org/category_taxonomy>. Examples: a
   condensed-matter researcher might pick `cond-mat.mes-hall` and
   `cond-mat.str-el`; an econometrician `econ.TH` and `econ.GN`; a computational
   neuroscientist `q-bio.NC`. **Never guess a default** — arJev never defaults
   to a category, and an empty `feeds` blocks the digest by design.
2. **Vault state** — do they already keep literature notes in Obsidian? →
   **extant vault** (step 3A: map their schema) or **fresh vault** (step 3B: the
   checklist-file). No agent-free human is different: the same file, hand-edited.
3. **Schema** — (extant only) look at two or three of their real notes'
   frontmatter and fill the remapping table in step 3A. Every field is
   remappable; there is no schema they must adopt.
4. **Taste** — what do they want to see more of, and less of? → the taste
   directives note (step 4). **HUMAN STEP** — taste is theirs; draft, let them edit.
5. **Seeds** — what do they already have? → a BibTeX export (Zotero, Scholar), a
   PDF folder, a Slack channel where their group shares papers (step 5).

## 3A. Extant vault — adoption (map it, then prove it)

Ask where their literature notes live. Map what you see into
`~/.config/arjev/arjev.toml` — do **not** reorganize their vault; the config
adapts to them.

The remapping table (their frontmatter field → the config slot it fills):

| their note has…                        | config slot                      | default            |
| -------------------------------------- | -------------------------------- | ------------------ |
| a `type:` value marking a paper note    | `[vault] type`                   | `"paper"`          |
| the field(s) holding the paper id       | `[vault.fields] identity`        | `["arxiv", "doi"]` |
| the field for when they read it         | `[vault.fields] read_date`       | `"date_read"`      |
| the field for their verdict             | `[vault.fields] rating`          | `"rating"`         |
| the field for their one-line reason     | `[vault.fields] why`             | `"why"`            |
| the field listing tags                  | `[vault.fields] tags`            | `"tags"`           |
| the field for staged-vs-written status  | `[vault.fields] status`          | `"status"`         |

Three common schemas, worked (any other is the same idea):

- **arXiv-native** — notes with `arxiv:` ids and default-looking fields. The
  defaults already fit; a condensed-matter researcher hand-writing
  `type: paper` / `arxiv: "2610.01234"` notes needs no remap at all.
- **Zotero-style export** — notes typed `journalArticle`, ids in `doi:`, dates in
  `dateAdded:`, tags in `keywords:`:

  ```toml
  [vault]
  type = "journalArticle"
  [vault.fields]
  identity = ["doi", "arxiv"]
  read_date = "dateAdded"
  tags = "keywords"
  ```

- **Bare-DOI** — notes carrying only `doi:` (common in bio- and med-adjacent
  fields): `identity = ["doi"]`, everything else default.

Worked example — a condensed-matter researcher keeps notes like:

```yaml
type: paper
arxiv: "2609.16123"
date_read: 2026-09-20
why: "flat-band mechanism, relevant to the twist-angle project"
tags: [moiré, superconductivity]
```

The defaults match field-for-field; you set `roots` and `feeds` only.
For an econometrician whose notes carry `takeaway:` instead of `why:`, you would
set `why = "takeaway"` under `[vault.fields]` — same table, different row.

**Check:** `arjev inspect` — read-only, exits 1 when blocked. The line shapes are
stable; grep them:

```
slot roots: set (/home/they/ObsidianVault)
slot feeds: set (cond-mat.mes-hall, cond-mat.str-el)
slot identity: set (arxiv, doi)
fold scanned: 214
fold type-matched: 41
fold identity-bearing: 41
fold warnings: none
```

- every slot line reads `slot <name>: set (<value>)` or `slot <name>: empty` —
  the slot names are the checklist-file's, verbatim (roots, include, type,
  half_life_days, feeds, top, screen, probe_k, directives_path, identity,
  read_date, rating, why, tags, status, digest_dir, library_dir);
- `fold identity-bearing` above zero proves the mapping landed — it is the count
  of notes whose identity field the config now sees;
- `fold type-matched` well below `fold identity-bearing` is advisory (the type
  slot missed; identity is the discriminator that matters);
- fold warnings surface verbatim, one per line as `warning: <text>` (e.g. a
  duplicate identity) — fix what they name, or accept them;
- blocked runs print `blocked: no feeds configured`, `blocked: no roots
  configured`, or `blocked: zero identity-bearing notes` on stderr and exit 1 —
  adoption is not done until `arjev inspect` exits 0.

## 3B. Fresh vault — the checklist-file (init, fill, prove)

No literature notes yet? Create an empty directory for the vault, then:

```bash
arjev init --vault /home/they/ObsidianVault
```

`arjev init` writes `~/.config/arjev/arjev.toml` as a **checklist-file**: every
decision slot carries its own one-line explanation, and `feeds` starts empty
(the tool never defaults to a category). Fill it **with the human**, one
interview answer at a time. The slots, in the file's order, each with its
explanation:

- `roots` — vault folders scanned recursively for paper notes (init sets the one
  you passed);
- `include` — glob selecting which files are scanned (default `**/*.md`);
- `type` — the frontmatter value that marks a paper note (default `"paper"` —
  for a Zotero-style vault, `"journalArticle"`);
- `half_life_days` — taste decay: a read counts half as much after this many days
  (default 180);
- `feeds` — **the arXiv categories they follow**, from the taxonomy; starts
  empty, and the digest refuses to run until it is filled;
- `top` — picks shown per digest (default 5);
- `screen` — candidates screened per run before ranking down to top (default 40);
- `probe_k` — synonym-probe pool size, the recall pass that feeds the ranking
  (default 20);
- `directives_path` — their taste-directives note (optional; defaults to
  `arjev-directives.md` at the first root);
- `[vault.fields] identity` — frontmatter field(s) holding the paper id; the
  first present one wins (default `["arxiv", "doi"]` — bare-DOI vaults set
  `["doi"]`);
- `read_date` — the when-they-read-it field (fallback: `date`, then file mtime);
- `rating` — their verdict field (core / useful / marginal);
- `why` — their one-line reason field — the taste signal;
- `tags` — the tags field;
- `status` — the staged-vs-written field (a written note's body feeds taste);
- `digest_dir` — where digest notes land (optional; default: `digests` under the
  first root);
- `library_dir` — where `arjev fetch` saves PDFs (optional).

Worked example — an econometrician starting fresh: `roots` set by init, you fill
`feeds = ["econ.TH", "econ.GN"]` from the interview, and the `[vault.fields]`
defaults stand until their notes say otherwise.

**Check:** right after init the vault is empty, so `arjev inspect` blocks with
`blocked: zero identity-bearing notes` on stderr, exit 1 — expected; what must
already be true: `slot feeds: set (econ.TH, econ.GN)` and `slot roots: set (…)`,
no `blocked: no feeds configured`, no `blocked: no roots configured`. After the
seeds land (step 5), `arjev inspect` exits 0 with `fold identity-bearing` above
zero. The self-server hand path is the same loop: `arjev init`, edit the file
(every slot explains itself inline), `arjev inspect`, `arjev digest`.

## 4. Taste directives (HUMAN STEP)

Draft an `arjev-directives.md` at the vault root — labs, companies, topics as
frontmatter lists, plus a prose body saying what they want and what to
de-prioritize — and let them edit it. Taste is theirs; the ranking follows what
they write, in plain English.

**Check:** `arjev inspect` shows `fold directives: loaded (<n> terms)`.

## 5. Seed the vault from what they already have

Any combination, all idempotent, all provenance-stamped:

```bash
arjev ingest --bibtex ~/Downloads/library.bib
arjev ingest --pdf-dir ~/Papers
arjev ingest --slack-channel-id C0123456ABC --limit 200
```

**Check:** the printed counts match reality; seeded notes appear in the vault's
`papers/` dir with `why:` provenance lines. Re-running changes nothing. Then
`arjev inspect` exits 0 — `fold identity-bearing` now counts their library.

## 6. Keys (optional, both fail open)

Both credentials live in mode-600 files under `~/.config/arjev/`; a missing
file disables that feature and nothing else.

- **Jev** (semantic ranking of the full feed). **HUMAN STEP** — the human signs
  up at <https://console.typesafe.ai> for their own key, then saves it:
  `install -m 600 /dev/stdin ~/.config/arjev/jev.key`. arJev reads it through
  `ARJEV_JEV_KEY_FILE`. Without it: lexical-only ranking, flagged in the `mode:` line.
- **Slack** (optional attention layer). **HUMAN STEP** — creating the app needs
  their browser. Walk them through [slack-setup.md](slack-setup.md): create the
  app from `docs/slack-app-manifest.yaml` (four scopes: `chat:write`,
  `reactions:read`, `channels:history`, `channels:join`), save the token to
  `~/.config/arjev/slack-token` (read through `ARJEV_SLACK_TOKEN_FILE`), and set
  `[slack] channel` (the channel **ID**), `keepers`, `who_style`, `why_style`.
  Never put a token in the config or a repo.

**Check:** `ARJEV_JEV_KEY_FILE=~/.config/arjev/jev.key arjev digest` shows
`mode: jev`. With Slack: `ARJEV_SLACK_TOKEN_FILE=~/.config/arjev/slack-token arjev slack sync`
exits 0.

## 7. The daily run + timers

`arjev daily` is the whole day in one command: the digest (retried with backoff
when arXiv's RSS is flaky; a quiet day on weekends, when arXiv publishes
nothing), then — when a Slack token and channel are configured — ingest of
shared papers and `slack sync`; on Sundays, the calibration report and the
week-in-review. Without Slack, the digest goes to the vault note only. Run it
once by hand first:

```bash
arjev daily
```

Then schedule it with the shipped units, which set both credential file paths:
on Linux the systemd service + timer in `contrib/systemd/`, on macOS the
launchd plist in `contrib/launchd/`. The exact install commands are in
[setup.md](setup.md#9-run-it-every-day); on Linux also run
`loginctl enable-linger "$USER"` so the timer fires while they're logged out.

**Check:** `systemctl --user list-timers` lists `arjev-daily.timer` (or
`launchctl list | grep arjev` on macOS), and the manual `arjev daily` ended
with `done`.

## 8. The staged loop — your prose obligation

Keeping a paper (Slack reaction, `arjev keep`, or a checkbox) scaffolds a note
with `status: staged` — metadata only, zero taste contribution until prose
exists. Writing that prose is **your** obligation (the model can't; the tool
won't). Schedule this pass right after the daily run:

1. Pull the worklist: `arjev staged` — one stable line per staged note,
   `id | title | kept-when | kept-by`, and nothing else.
2. Fetch the PDF: `arjev fetch <id>` (lands in the configured `library_dir`).
3. Read it, then write the note: a summary body in your own words, and a
   one-line `why:` in the frontmatter — the taste signal.
4. Flip `status: staged` → `status: written` — an ordinary frontmatter edit;
   there is no verb for it, by design.

**Check:** the note's line disappears from `arjev staged`; `arjev inspect`
shows `fold staged:` counting down; the written body feeds taste exactly like a
hand-authored note's. A digested keep left staged is a loop left open — schedule
this pass with the daily run.

## 9. Tell the human what they own

- React 👍/👀/❌ on picks (if keepers-listed) — each becomes a label + a vault stub.
- Fill `rating:` and `why:` on notes — that's what makes notes taste.
- `arjev calibrate` — the weekly report (`arjev daily` writes it to the state
  dir on Sundays); thresholds are human-applied, by design.
- `arjev review --days 7` — the week-in-review: relevant papers that missed a
  daily top 5, tracked-author matches, and the week's labels. `arjev daily`
  posts it to Slack on Sundays.
- Rate-proposals: `arjev rate propose` asks the model for advisory first-pass
  ratings (side table only, vault untouched); `arjev rate accept <arxiv>
  <core|useful|marginal>` is the human gate that writes the rating.

## Failure modes you will hit

- **`feeds not configured`** at digest, or `blocked: no feeds configured` at
  `arjev inspect` — the `feeds` slot is empty; fill it from the taxonomy, never
  with a guessed default.
- **`feed failure — every configured feed returned 0 items`** — on a weekday,
  arXiv RSS is briefly empty and `arjev daily` retries; on Saturday or Sunday it
  is expected (no new listings) and logged as a quiet weekend.
- **Slack `missing_scope`** — the app lacks a scope; recreate it from the manifest.
- **Slack `not_in_channel`** — the bot isn't in the digest channel; `/invite @arJev`.
- **`profile-degraded` in the mode line** — fewer than 5 notes or no `why` lines
  yet; seed more, or write a few (that's your job anyway — step 8).
- **A type mismatch** (`fold type-matched: 0` but `fold identity-bearing` healthy)
  — the `[vault] type` slot doesn't match their schema; fix the slot, not the vault.

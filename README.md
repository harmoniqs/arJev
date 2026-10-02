# arJev

A daily arXiv digest engine that ranks against your **living Obsidian vault** — so the picks get better every week you use it, because *you* are the training data.

arJev serves **any field that posts to arXiv** — condensed matter, economics, quantitative biology, mathematics, any discipline with an arXiv category — and it sources nothing beyond arXiv: no PubMed, no RePEc, no journal feeds. If your field doesn't post to arXiv, arJev is not for you yet, and it will never silently rank a category you didn't choose.

## The division of labor

Three sentences are the product:

- **The decision model judges.** [Jev](https://typesafe.ai), the ranking model, is text-free by design: it scores, rescues, and rates with calibrated confidence, and it can never write a sentence. Every call is a typed decision, logged as a receipt.
- **Your agent writes — or your own hand does.** All the prose in the loop (note bodies, why-lines, takes on the picks) comes from an LLM agent or from you. The tool itself never writes prose and never edits an existing note.
- **The vault stays yours.** Your Obsidian vault is the source of truth: the taste profile is folded from your paper notes (tags, `why` lines, note bodies, wikilink signals), your authored **taste directives** state in plain English what you want, and papers you keep become ground truth. Slack is an optional attention layer on top — the vault is the product.

## Two ways to start

**You already have a vault.** Your agent maps it: every note field is remappable (Zotero-style exports, bare-DOI notes, any custom schema), and `arjev inspect` proves the mapping landed by printing exactly what the config sees — checklist state, notes scanned, identity-bearing count — and exiting nonzero when something blocks.

**You're starting fresh.** `arjev init` writes the config as a **checklist-file**: every decision slot (feeds, note-type, identity fields, taste knobs) carries its own one-line explanation, `feeds` starts empty, and your agent fills the file in with you — one interview question at a time. `arjev inspect` proves it green before the first digest.

**No agent?** The same loop, your hand: `arjev init` → edit the file (every slot explains itself inline) → `arjev inspect` → `arjev digest`. The hand path is the same contract traversed slower — nothing here requires an agent.

## Install

Python 3.11+:

```bash
uv tool install git+https://github.com/harmoniqs/arJev@v0.3.0
arjev init --vault /path/to/your/vault  # writes the checklist-file config
# fill feeds = [...] with your arXiv categories — yours or your agent's hand
arjev inspect                           # proves the config green (exit 0)
arjev digest                            # today's picks, explainable, to stdout
```

Point it at any Obsidian vault with literature notes (a frontmatter `type` value and an `arxiv:` or `doi:` identity field — both remappable for any schema). No vault yet? `arjev ingest` seeds one from what you already have.

## The loop, and the staged worklist

1. **Digest** — every day, the full multi-feed union is screened and ranked against the vault's taste profile; each pick carries its why-line.
2. **Keep** — a Slack reaction, `arjev keep`, or a checkbox scaffolds the paper into your vault as a note with `status: staged` — metadata only, zero taste contribution until prose exists.
3. **Write** — `arjev staged` lists the staged notes awaiting prose; your agent (or your hand) writes each note's body and `why` line, then flips `status: staged` → `status: written` in the frontmatter.
4. **Learn** — a written body feeds taste exactly like a hand-authored note's; `arjev calibrate` replays past digests against your labels and reports Brier scores, reliability, precision@5 — with honest n, never fake confidence.

## Why

Keyword-based paper alerts miss everything that isn't spelled the same way ("jitter robustness" never matches "amplitude noise"), never learn from what you actually read, and can't be installed by anyone outside the lab that built them. arJev fixes all three:

- **A decision model at the front line.** With a [Jev](https://typesafe.ai) key (the default), a cheap, calibrated model screens the **full feed** — every item, every day — so papers with zero keyword overlap still surface when they're relevant. Every call is a logged receipt.
- **The vault still explains every pick.** Your taste profile supplies the matched terms on each why-line and the tiebreak — and it carries the whole digest without a key: no Jev, no outage, no problem; the ranking falls back to the deterministic lexical order and the `mode:` line says exactly which engine ran.
- **A learning loop.** Keeps scaffold, writes feed taste, calibration reports the truth — the loop above, closing every day.

## Seeding and taste

- `arjev ingest --bibtex library.bib` — from a Google Scholar or Zotero export
- `arjev ingest --pdf-dir ~/papers` — from a PDF collection (ids from filenames or the arXiv stamp)
- `arjev ingest --slack-channel-id C0123456ABC` — from the papers **people** share in your Slack (bot posts are filtered; each seeded note carries who/where/when provenance)
- **Taste directives** — drop an `arjev-directives.md` in your vault: labs, companies, topics as lists, plus a prose body that rides first-class into the model's state. You write taste in English; the ranking follows.

## Multi-feed

```toml
feeds = ["cond-mat.mes-hall", "econ.TH", "q-bio.NC"]
```

The union is deduped across feeds (cross-listings score once), and ranked as one list. No category is ever defaulted: an empty `feeds` blocks the digest with a plain-language error naming the slot.

## Slack, on top of the vault (optional)

Each pick posts as its own message, so a 👍 maps 1:1 to a paper: reaction → label → **staged stub in your vault, automatically** — decision in Slack, memory in Obsidian. Thread replies count as `discussed`. A keepers allowlist decides whose reactions become labels. Full setup in **[docs/slack-setup.md](docs/slack-setup.md)** — five minutes, one Slack app.

## Have your agent set it up

arJev is designed to be installed *by an AI agent on your behalf* — the interview, the schema mapping, Slack, seeding, timers, the staged prose loop, with acceptance checks at every step. Hand **[docs/agent-setup.md](docs/agent-setup.md)** to your agent and say "set this up for me." The runbook is field-agnostic: it works the same for a condensed-matter lab, an econ group, or a q-bio team.

## Prose: the two seams

arJev's core is deliberately **text-free** — deterministic rendering, and the decision model can't generate strings by design. Prose rides two seams, both filled by your agent (or your hand):

- **Enrich (digest out)** — configure `enrich_command` and arJev pipes the canonical picks JSON to it, appending whatever comes back to the digest. Any LLM CLI works; **[docs/amicode-integration.md](docs/amicode-integration.md)** has the contract.
- **Write (vault in)** — the staged worklist above: `arjev staged` is the pull, and the prose lands in your notes where you review it like any other vault edit.

## Calibration, honestly

`arjev calibrate` joins the label ledger, the digest journal, and the decision receipts: Brier per primitive, reliability bins, precision@5. The report states its n, names its censoring (labels only exist for papers you were shown), and recommends thresholds — **you** apply them; the tool never tunes itself.

## Status

v0.3.0. v1 in daily use at [Harmoniqs](https://harmoniqs.ai). [Issue #1](https://github.com/harmoniqs/arJev/issues/1) is the plan of record (spec, compiled plan, obligation register).

Apache-2.0.

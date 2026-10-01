# arJev

A daily arXiv digest engine that ranks against your **living Obsidian vault** — so the picks get better every week you use it, because *you* are the training data.

Your vault is the source of truth: the taste profile is folded from your paper notes (tags, `why` lines, note bodies, wikilink signals), your authored **taste directives** state in plain English what you want, and papers you keep become ground truth. Slack is an optional attention layer on top — the vault is the product.

## Why

Keyword-based paper alerts miss everything that isn't spelled the same way ("jitter robustness" never matches "amplitude noise"), never learn from what you actually read, and can't be installed by anyone outside the lab that built them. arJev fixes all three:

- **A deterministic lexical front-line** ranks the day's arXiv feed against your taste profile. Free, instant, auditable — every pick says why it matched.
- **[Jev](https://typesafe.ai) — a cheap, calibrated decision model — re-scores the full feed.** Every item is screened, so a paper with zero keyword overlap still surfaces if it's relevant. Every call is a logged receipt; every seam fails open to the lexical ranking. **No key required** — without one, arJev runs lexical-only and says so.
- **A learning loop.** A paper you keep (Slack reaction, `arjev keep`, or a checkbox) is scaffolded into your vault as a staged note; a paper that lands there feeds taste back; `arjev calibrate` replays past digests against your labels and reports Brier scores, reliability, precision@5 — with honest n, never fake confidence.

## Install

Python 3.11+:

```bash
uv tool install git+https://github.com/harmoniqs/arJev@v0.1.9
arjev init --vault /path/to/your/vault    # scaffolds the config, runs a smoke digest
arjev digest --feed quant-ph              # today's picks, explainable, to stdout
```

Point it at any Obsidian vault with paper notes (frontmatter `type: paper`, an `arxiv:` or `doi:` identity field — remappable for any schema). No vault yet? `arjev ingest` builds one from what you already have.

## Seeding and taste

- `arjev ingest --bibtex library.bib` — from a Google Scholar or Zotero export
- `arjev ingest --pdf-dir ~/papers` — from a PDF collection (ids from filenames or the arXiv stamp)
- `arjev ingest --slack-channel-id C…` — from the papers **people** share in your Slack (bot posts are filtered; each seeded note carries who/where/when provenance)
- **Taste directives** — drop an `arjev-directives.md` in your vault: labs, companies, topics as lists, plus a prose body that rides first-class into the model's state. You write taste in English; the ranking follows.

## Multi-feed

```toml
feeds = ["quant-ph", "cond-mat.mes-hall", "cs.AI"]
```

The union is deduped across feeds (cross-listings score once), and ranked as one list.

## Slack, on top of the vault (optional)

Each pick posts as its own message, so a 👍 maps 1:1 to a paper: reaction → label → **staged stub in your vault, automatically** — decision in Slack, memory in Obsidian. Thread replies count as `discussed`. A keepers allowlist decides whose reactions become labels. Full setup in **[docs/slack-setup.md](docs/slack-setup.md)** — five minutes, one Slack app.

## Have your agent set it up

arJev is designed to be installed *by an AI agent on your behalf* — vault discovery, config, Slack, seeding, timers, with acceptance checks at every step. Hand **[docs/agent-setup.md](docs/agent-setup.md)** to your agent and say "set this up for me."

## Summaries and prose: the enrichment seam

arJev's core is deliberately **text-free** — deterministic rendering, and the decision model can't generate strings by design. Prose (takes, summaries) is a separable seam: configure `enrich_command` and arJev pipes the canonical picks JSON to it, appending whatever comes back. Amicode's agent fills that seam first-party; any LLM CLI works. **[docs/amicode-integration.md](docs/amicode-integration.md)** has the contract and the thinking.

## Calibration, honestly

`arjev calibrate` joins the label ledger, the digest journal, and the decision receipts: Brier per primitive, reliability bins, precision@5. The report states its n, names its censoring (labels only exist for papers you were shown), and recommends thresholds — **you** apply them; the tool never tunes itself.

## Status

v1 in daily use at [Harmoniqs](https://harmoniqs.ai). [Issue #1](https://github.com/harmoniqs/arJev/issues/1) is the plan of record (spec, compiled plan, obligation register).

Apache-2.0.

# arjev

A daily arXiv digest engine that ranks against your **living Obsidian vault**.

- **Deterministic front-line** — a lexical scorer ranks each day's arXiv RSS feed against your vault's taste profile (tags, why-lines, note bodies, wikilink signals, recency-decayed). Free, instant, auditable.
- **Jev middle layer** — [TypeSafe System One](https://typesafe.ai) re-ranks lexical survivors, rescues near-misses the lexical scorer can't see (synonyms), and probes a sample of zero-match items so recall failures are *visible*, not silent. Every call is a logged receipt; every seam fails open to the lexical ranking. No key required.
- **Learning loop** — your vault is the ground truth. A paper you keep (Slack reaction or `arjev keep`) is scaffolded into your vault; a paper that lands there feeds taste back; `arjev calibrate` replays past digests against your labels and reports Brier, reliability, precision@5, and probe lift — with honest n, never fake confidence.

Slack is attention; Obsidian is memory. arjev translates between them.

## Install

Python 3.11+. [Bun not required. Nothing watches you.]

```bash
pipx install git+https://github.com/harmoniqs/arjev@v0.1.0
arjev init          # scaffolds ~/.config/arjev/arjev.toml
arjev digest --feed quant-ph --top 5 --post stdout
```

## The loop

```
vault fold → lexical score → Jev rerank + probe → digest (Slack / vault / stdout)
     ↑                                                        │
     └── keep reaction / arjev keep → staged stub ─────────────┘
          labels ledger + digest journal + receipts
                → arjev calibrate → human-applied thresholds
```

## Status

v1 in active development — see [issue #1](https://github.com/harmoniqs/arjev/issues/1) for the plan of record.

Apache-2.0.

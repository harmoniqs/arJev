# How arJev works

The design in one paragraph: arJev folds your vault into a taste profile, judges
every new paper in your feeds against a fixed-size summary of that profile, and
posts a few picks with their reasons. Your reactions become labels; the papers
you keep become notes; written notes feed the profile. The ranking model only
ever makes typed decisions — every sentence in the system comes from you or
your agent.

## The division of labor

- **The decision model judges.** [Jev](https://typesafe.ai), the ranking model,
  is text-free by design: it scores, rescues, and rates with calibrated
  confidence, and it cannot write a sentence. Every call is logged as a receipt.
- **Your agent writes, or you do.** All prose — note bodies, why-lines, takes on
  the picks — comes from an LLM agent or a person. arJev itself never writes
  prose and never edits an existing note ([ADR 0001](adr/0001-vault-generation-is-the-agents-contract.md)).
- **The vault stays yours.** Your Obsidian vault is the source of truth: the
  profile is folded from your paper notes, your taste directives say in plain
  English what you want, and papers you keep become ground truth. Slack is an
  optional attention layer on top.

## The context engine: how a corpus becomes a ranking

The invariant: **your corpus can grow without bound; the model's window never
does — and that is the mechanism, not a limitation.** Every digest runs the
same fold:

1. **Fold** — every note under your roots is scanned once; kept papers become
   records (title, your `why`, your rating, tags, the vault's link graph).
2. **Taste cards** — each kept paper becomes a card: your why, the paper's own
   abstract, and its conclusions (extracted from your local PDF library), with a
   180-day half-life and your rating as weights. Your directives ride first.
3. **The budgeted window** — each candidate is judged against a fixed,
   byte-budgeted context assembled for it: directives, then cards, terms, and
   why-lines filled greedily by recency-weighted priority.

Two phases fall out of that one mechanism:

- **Small corpus → maximal fill.** With a handful of kept papers, everything
  rides the window.
- **Growing corpus → recency-proportional width.** Past the window's size, decay
  gives recent work proportionally more of it — a paper read 300 days ago holds
  a quarter the width of one read 90 days ago. The window tracks your drift with
  no reconfiguration.

The corpus never rides into the model wholesale: the fold is a local linear
scan, and the model's context is a fixed-budget summary, so a 10,000-note vault
costs the same per digest as a 10-note one.

| Taste budget (`taste_budget_bytes`) | What rides |
|---|---|
| 2.5 KB (default) | full directives + ~15 weighted terms + recent why-lines |
| 8 KB | full directives + ~4–6 recent taste cards + terms |
| 12 KB | full directives + ~8–10 cards + terms — about 12% of the model's window |

Measured in daily use at [Harmoniqs](https://harmoniqs.ai) (three feeds): about
650–980 papers screened per day (every paper in the union, never truncated),
about 470 model calls per digest at a median 171 ms, and about $0.02/day at the
default budget ($0.08/day at 12 KB).

The vendor documents *context rot* — accuracy falls as irrelevant state grows —
so every enlargement is an opt-in arm gated on measurement:
`arjev calibrate --replay-arms` re-scores your labeled candidates under each arm
(the fixed budget, `budget-greedy` at 4/8/12 KB, each with and without candidate
conclusions) and reports Brier, precision@5, and realized state size, with n.
Defaults change only on a measured win, and the tool never edits its own config.

## Ranking without a key

With a Jev key (the default ranking, `jev-first`), the model screens the full
feed, so papers with no words in common with your notes still surface. Without
one, the ranking falls back to the deterministic lexical order from your taste
profile, and the digest's `mode:` line says which engine ran. Either way, every
pick's why-line shows the matched terms from your vault.

## The who-line

Each Slack pick shows who wrote the paper: the first three authors (`+N` for
the rest), tracked people as `⭐ Name (Group)` from your directives, and — with
`who_style = "full"` — the institutions printed on the paper's own first page.
At digest time no external index carries affiliations yet, so the paper's PDF
is the only same-day source; the parse is deliberately conservative, never
binds an institution to a person, and shows authors only when the page is
ambiguous ([ADR 0002](adr/0002-at-digest-time-affiliations-ride-from-the-papers-own-pdf.md)).

## The loop

1. **Digest** — the multi-feed union is screened and ranked; each pick carries
   its why-line (and in Slack, its who-line).
2. **Keep** — a 👍 (harvested by `arjev slack sync`) or `arjev keep <arxiv-id>`
   creates a note with `status: staged`: metadata only, no taste yet. Checking a
   pick's box in the vault digest note records a keep label (`arjev labels sync`).
   An untouched stub provably changes nothing; the fold audits this every digest.
3. **Write** — `arjev staged` lists notes awaiting prose; your agent or you
   write the body and a `why:`, then set `status: written`.
4. **Enrich the library** — `arjev fetch <arxiv-id>` downloads a paper's PDF and
   extracted text; `arjev backfill` does the whole corpus (paced, idempotent).
   Library text gives taste cards their abstract and conclusions.
5. **Learn** — written notes feed taste; `arjev calibrate` replays past digests
   against your labels and reports Brier scores, reliability, and precision@5
   with honest n. It recommends thresholds; you apply them.

## Calibration, honestly

`arjev calibrate` joins three records — the label ledger, the digest journal,
and the decision receipts — and reports Brier per decision type, reliability
bins, and precision@5. It states its n and its censoring: labels exist only for
papers you were shown, so it grades selection, not recall in general.

## The week-in-review

The daily digest shows the top 5 of one day. `arjev review --days 7` is the
across-days view, a deterministic re-read of the journal with no fetches and no
model calls: relevant papers that missed a daily top 5, tracked-author matches,
where Jev and the keyword ranking disagreed (file report only), and the week's
labels. `arjev review --post slack` sends a channel-friendly version.

## What touches the network

- arXiv RSS, once per feed per digest.
- Jev, once per screened candidate (with a key).
- Slack, when configured: posting picks, reading reactions and replies.
- arXiv PDFs: `arjev fetch`/`backfill`, `who_style = "full"` (one per pick,
  library-cached), and the opt-in candidate-content arm (finalists only, paced
  at 3 s, cached). Every PDF fetch is fail-open: a dead network degrades the
  feature and the digest still ships.

Your vault and library are only ever read locally.

## Records

Everything arJev records lives under `~/.local/state/arjev/` (XDG state),
never in your vault or a repo: the digest journal, Jev receipts, the label
ledger, posted ids, and the calibration and review reports.

Further reading: [CONTEXT.md](../CONTEXT.md) (the glossary) and the
[ADRs](adr/) (decisions with their alternatives).

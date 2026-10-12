# arJev v0.4.1

**The one-line version:** the digest grew its across-days view — `arjev review`
re-reads the week's own records (no fetches, no model calls) and shows the
patterns a top-5-per-day cap structurally cannot.

## What's new

**The week-in-review (issue #83).** The journal already records every candidate from
every run — scores, pools, posted flags, author-lane matches. `arjev review --days 7`
is a pure, deterministic re-read of that record in four sections:

- **The Buried** — the cap's casualties: never-posted candidates re-ranked by Jev
  confidence, deduped across runs at their best judgment, top 10 of the window's
  total (both numbers stated).
- **Your People** — the author-signal-lane matches this window, posted or not.
- **The Divergences** — the two rank-gap tails where Jev and the words disagreed,
  biggest divergence first: jev-hot/lexical-buried and lexical-hot/jev-cold.
- **The Week's Receipts** — kept vs. skipped with the calibration headline
  (precision@5, Brier n); an unlabeled week says so plainly instead of reading hollow.

Read-only throughout — the review proposes, never stages; the staged worklist stays
human-gated. An empty window renders an honest report, a missing journal fails loud.
`--post slack` rides the digest's client seam to the configured channel, and the
Sunday timer wiring posts it after the digest (`review --days 7 --post slack`, report
filed in the state dir alongside the calibration report).

Fail-open Jev rows (a lone `fail_reason` carries no judgment) never rank — no mass,
no line. On the live Harmoniqs journal the first run did its job immediately: the
jev-hot tail surfaced old cs.AI survey spam carrying suspicious `confidence: 1.0`
values while the lexical-hot tail was real physics (trapped-ion gates, bosonic-code
protection, Kitaev-chain readout) that Jev scored cold — exactly the pattern the
calibration needs labels to grade.

## Repairs

- The `v0.4.0` tag was never pushed at its release — the README install pin
  `@v0.4.0` pointed at nothing. Both tags ship with this train: `v0.4.0` (retroactive,
  at its bump commit) and `v0.4.1`.

Upgrading: `uv tool install git+https://github.com/harmoniqs/arJev@v0.4.1 --force`.

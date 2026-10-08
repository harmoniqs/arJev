# arJev v0.4.0

**The one-line version:** the Jev state grew up — the taste context is now a budgeted,
recency-weighted window that can carry the papers' own words (abstracts, conclusions),
and every enlargement of that window is an opt-in arm gated on measured calibration.

## What's new

**The context engine (issue #75).** The corpus had outgrown the fixed-15 state (the
median production call ran at 4055 of 4096 bytes) while note bodies were compressed to
token frequencies — the papers' own prose never reached the model. One mechanism
replaces the fixed counts:

- **Budget-greedy assembly** (`state_policy = "budget-greedy"`): directives ride whole
  — the 800-char truncation of authored taste is gone — then per-paper **taste cards**
  (your why + the paper's abstract + its conclusions/outlook excerpt) and terms fill
  the configured `taste_budget_bytes` by recency-weighted priority. A small corpus fits
  everything; a growing one gives recent work proportionally more of the window. The
  180-day half-life rides the weights, so the window tracks your drift with no
  reconfiguration.
- **Paper content, both halves**: kept papers get their abstract and conclusions
  extracted from your local PDF library (`arjev fetch` and `arjev backfill` emit the
  extracted text at fetch time, paced and idempotent — backfill converges on libraries
  that predate this release), and digest finalists can be re-scored with their fetched
  conclusions in the candidate state (`candidate_content = true`; cached in the state
  dir, never the PDF library; fail-open to abstract-only on any fetch failure).
- **The A/B that gates every default**: `arjev calibrate --replay-arms` re-scores your
  labeled candidates under each arm — fixed-15, budget-greedy at 4/8/12 KB, each with
  and without candidate conclusions — and reports Brier, n, and the realized state
  size per arm. Arm receipts are quarantined from the production calibration join.

## Behavior changes — read before upgrading

There are none: **defaults are byte-identical to v0.3.x.** The incumbent fixed-15
policy ships as the default; `budget-greedy` and `candidate_content` are opt-in arms
until `calibrate --replay-arms` shows a measured win (the vendor documents context
rot — accuracy falls as irrelevant state grows — so evidence decides, not economics).
One disclosure: under `budget-greedy`, a digest pays a missing PDF's text extraction
once and writes the `.txt` back into your library (idempotent, same content
`arjev fetch` would write).

## New knobs

- `state_policy` — `"fixed-15"` (default) | `"budget-greedy"`
- `taste_budget_bytes` — the taste half of the Jev state (default 2500)
- `candidate_content` — finalist conclusions enrichment (default false)
- `candidate_pace_s` — politeness gap between candidate PDF fetches (default 3.0)

All three decision slots carry their one-line explanations in the init checklist-file
and appear in `arjev inspect` output. New dependency: `pypdf` (pure-Python, PDF text
extraction at the fetch/backfill seams).

---
type: plan
schema_version: "1"
plan_id: plan-20261001-arjev-v1
spec: config/specs/spec-20261001-113338-arjev-v1.md
spec_review: degraded   # 3 manual rounds; round-3 blockers fixed per critic prescription, not re-adjudicated
compile: manual        # no `amico plan compile` on this host — hand-compiled per the deliberate contract
budget: none            # task_type implement-slice — no solve-bearing steps, no device access
steps: 6
---

# arjev v1 — compiled plan (manual)

Every step: task_type `implement-slice`, model n/a (agent-executed code work), no
solve-bearing work, no device access. Gates are named tests derived from the spec's
acceptance block; step state derives from gate verdicts, never self-reported.

## Steps

### Step 1 — Bootstrap (spec slice 0)
Repo skeleton, pyproject (3.11+, PyYAML + httpx, tomllib reads, static template config
writer), GitHub Actions (pytest + ruff), packaging (git-tag pipx installs), ruff config,
`scripts/capture_fixtures.py` (records + sanitizes RSS/Jev/Slack payloads), synthetic
fixture vault (≥ 5 notes, ≥ 1 `why`-bearing) + synthetic posted-state fixture, README,
Apache-2.0.
- **Gates**: CI green on the empty-test skeleton; capture script's sanitizer unit-tested
  (fixture payloads contain zero channel/user ids, zero keys).
- **Needs**: `gh repo create harmoniqs/arjev --public`; issue #0 (plan of record).

### Step 2 — Engine, lexical-only (spec slice 1)
Vault fold (+ field mapping, `relevance` back-compat with precedence, date fallback
ladder, wikilink inlink rule, id normalization), taste profile, RSS parse, lexical score,
render (mrkdwn / vault note / stdout with composite mode string), `arjev init` (enumerated
keys + fixture-digest smoke), CLI.
- **Gates**: `init.bootstrap_failures == 0`; `digest.fingerprint_mismatches == 0`;
  fold tests (back-compat, ladder, wikilink, normalization, staged-gate zero-weight);
  `mode: lexical-only, ok` on the no-key fixture; vault-note sink checkbox format test.
- **Obligations exercised**: #4 ladder, #6 normalization, #15 back-compat precedence,
  #16 wikilink rule, #17 init enumeration, #22 fingerprint definition, #23 vocabularies.

### Step 3 — Jev middle layer (spec slice 2)
Thin client; disjoint pools (survivors top-screen / near-miss below-cutoff one-term /
probe seeded K of zero-score, membership + seed journaled); canonical run-bound
receipts; budgeted state assembly (2.5 KB + 0.75 KB, overflow fail-open); low-confidence
fail-open (`jev.min_confidence`, default 0.6).
- **Gates**: `jev.calls_without_receipt == 0`; `jev.receipts_without_candidate_id == 0`;
  `jev.state_bytes_max <= 4096`; `failopen.no_key_exit == 0` (no key AND low-confidence
  paths); pool partition + journal probe-membership tests; overflow ladder test.
- **Obligations exercised**: #2 receipts, #3 pools/seed, #5 state arithmetic, #8 low-conf,
  #9 mode, #26 probe why-line.

### Step 4 — Labels + Obsidian writes (spec slice 3)
Label ledger (closed vocabularies); digest journal; three-branch arrival join (non-staged
→ positive; any staged presence → no row + clock suspension, touched or not; otherwise
30-day → weak negative); byte-compat posted-state + in-memory legacy ts; `arjev keep`
scaffold (rating/why absent); staged gate; `arjev fetch`.
- **Gates**: `scaffold.roundtrip_failures == 0` (incl. `rating` absent, idempotent
  re-run); `state.posted_ids_lost == 0`; touched-stub clock-suspension test (kept papers
  never flip negative); time-free 30-day test via injectable clock; new-file-only/
  atomic/idempotent write tests.
- **Obligations exercised**: #1 three sources, #4 clock, #7 legacy ts, #23 vocabularies,
  #24 unsaved≠irrelevant separation.

### Step 5 — Slack surface (spec slice 4)
Bot-app client (recorded-response seam), digest post, reaction sync with keepers
allowlist, `discussed` reply harvest, checkbox parse of arjev's own digest notes,
LaTeX→Unicode cleanup, rate discipline (≤ 1 req/s, 429 backoff), `docs/slack-setup.md`.
- **Gates**: keepers enforcement test (unauthorized reaction labels nothing); reaction
  → keep → auto-scaffold roundtrip on recorded payloads; discussed-harvest test; content
  boundary test (no paths/titles/why in posts; why_style gating); rate-limit seam test.
- **Obligations exercised**: #10 keepers, #11 artifacts-outside-repo, #12 content
  boundary, #18 rate discipline, #13 sanitized payloads.

### Step 6 — Calibrate + ops swap (spec slice 5)
Join ledger + journal + receipts over last N runs → Brier per primitive (positive class
keep ∪ read-later), 10-bin reliability, precision@5, probe lift (rescue keep-rate vs.
top-5 keep-rate) — each n-stated, unsaved-weak-negatives reported separately; staged-gate
fold self-audit (current fold only); recommendation-only thresholds; ops swap dry-run +
one-line daily.sh change.
- **Gates**: `calibrate.metrics_emitted >= 4` on fixture labels; audit-violation test
  (planted staged-untouched term must fail the audit); no-config-write assertion
  (calibrate never edits arjev.toml); ops-swap dry-run against the real state file copy.
- **Obligations exercised**: #1, #14 tuning human-only, #19 reliability bins, #20 censoring
  named in report, #21 probe lift.

## Obligation register (review advisories → binding implementation constraints)

| # | Obligation (source round) | Step |
|---|---|---|
| 1 | Calibration joins ledger + journal + receipts, nothing else; staged-gate audit is a fold self-audit (R1-B) | 4, 6 |
| 2 | Receipts: canonical schema, run-bound + candidate-bound, metadata only (R2) | 3 |
| 3 | Disjoint pools; journal carries membership + seed (R2) | 3 |
| 4 | date_read fallback ladder (R1) | 2 |
| 5 | State assembly 2.5 KB/0.75 KB + overflow fail-open, journaled (R1+R2) | 3 |
| 6 | Normalized ids in every persisted record (R3) | 2 |
| 7 | Byte-compat state; legacy ts in-memory only, 30-day rule only (R2) | 4 |
| 8 | Low-confidence fail-open, `jev.min_confidence` config (R3) | 3 |
| 9 | Composite mode flags rendered everywhere (R3) | 2 |
| 10 | Keepers allowlist enforced for keep gestures (R1) | 5 |
| 11 | Runtime artifacts in XDG state dir, .gitignore ships regardless (R1) | 1 |
| 12 | Slack content boundary + why_style gating (R1) | 5 |
| 13 | Recorded fixtures sanitized before commit (R2) | 1 |
| 14 | Threshold tuning recommendation-only (R2) | 6 |
| 15 | Back-compat relevance precedence (why wins; fold warning) (R2) | 2 |
| 16 | Wikilink inlink rule exact: weight × (1 + 0.5 × min(3, inlinks)) (R2) | 2 |
| 17 | init enumerates all config keys + fixture-digest smoke (R2) | 2 |
| 18 | Slack harvest ≤ 1 req/s + 429 backoff (R1) | 5 |
| 19 | Reliability bins: 10 equal-width over [0,1], per primitive (R1) | 6 |
| 20 | Label censoring at posting boundary named in the report (R1) | 6 |
| 21 | Probe lift numeric definition (R2) | 6 |
| 22 | Fingerprint = sha256 of canonical picks JSON, date-excluded (R1) | 2 |
| 23 | Closed label_type + source vocabularies (R1) | 4 |
| 24 | Unsaved-weak-negative separate, never alone drives a recommendation (R1) | 6 |
| 25 | Profile-degraded flag on thin folds (R1) | 2 |
| 26 | Probe why-line: feed-derived + one confidence number (R3) | 3 |
| 27 | Brier positive class keep ∪ read-later; Score top-two-levels mapping (R2) | 6 |

A step may not be marked passed while any obligation it exercises is violated; the plan
may not complete while any obligation row is open.

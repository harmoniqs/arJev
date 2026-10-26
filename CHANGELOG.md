# Changelog

All notable changes, newest first. Dates are release tags (UTC). Install a
specific release with `uv tool install git+https://github.com/harmoniqs/arJev@vX.Y.Z`.

## v0.6.1 — 2026-10-26

- **Fixed: relevant papers lost to a confidence gate, junk posted instead.**
  A Jev answer whose single top label fell below `min_confidence` (0.6) was
  scored as zero relevance. A paper Jev judged 92% relevant but split between
  *must-read* and *worth-reading* failed the gate, while papers it called
  *irrelevant* with 61% confidence passed and kept a small nonzero score — so
  from Oct 22, with the wider feed union, they filled the top 5. Low-confidence
  answers now rank on their must-read + worth-reading probability, which
  already encodes the uncertainty; they are still recorded as `low-confidence`
  in the journal. Replaying the Oct 22–26 receipts, every day posts five
  relevant papers.

## v0.6.0 — 2026-10-26

**One command for the whole day, and a setup kit in the repo.**

- **`arjev daily`** runs the full day for a timer: the digest (retried with
  backoff when arXiv's RSS is flaky), Slack ingest and reaction sync, and on
  Sundays the calibration report and week-in-review. On Saturdays and Sundays
  arXiv publishes no new listings, so an empty feed is logged as a quiet day
  instead of an outage. One failing step never stops the others.
- **`ARJEV_SLACK_TOKEN_FILE`** reads the Slack token from a mode-600 file, the
  same way `ARJEV_JEV_KEY_FILE` already worked for the Jev key.
- **`contrib/`** ships a systemd service + timer and a macOS launchd plist that
  call `arjev daily`.
- The version is single-sourced from `pyproject.toml`.
- Digest headers say "ranked against your vault" instead of "the lab corpus",
  since arJev serves individual researchers as well as labs.
- Docs reorganized: a human-first README, a step-by-step `docs/setup.md`,
  `AGENTS.md` for agents working on the repo, and this changelog in place of
  per-release notes files.

## v0.5.6 — 2026-10-26

- `arjev digest --post slack,vault` ranks once and writes to every listed sink:
  the dated vault note first, then Slack. If one sink fails the others still
  run, the failed sink is named on stderr, and the exit code is 1. Config
  errors are caught before ranking, so a misconfigured run spends no Jev calls.

## v0.5.5 — 2026-10-25

- **Fixed:** Slack Web API calls are form-encoded. `reactions.get` and
  `conversations.replies` ignore JSON bodies, so `arjev slack sync` never
  worked against real Slack before this release.
- The Slack app manifest adds `channels:join`, so the bot can join its channel.

## v0.5.4 — 2026-10-25

- `arjev review --post slack` posts a Slack-native week-in-review: bold section
  titles, titles linked to arXiv, readable dates, plain labels. The full report
  (stdout, `review-YYYYMMDD.md`) is unchanged.
- `\( … \)` inline math in titles is cleaned like `$ … $`.

## v0.5.3 — 2026-10-25

- **Fixed:** the week-in-review ranked by Jev's confidence in *any* label, so
  papers Jev was surest were *irrelevant* led "The Buried". It now orders by
  label, then confidence, and only relevant papers are listed. The digest was
  never affected.

## v0.5.2 — 2026-10-21

- Affiliation parsing strips email parentheticals and handles an abstract
  heading run into its first word (`ABSTRACTCloud…`).

## v0.5.1 — 2026-10-21

- **Fixed:** arXiv RSS puts every author in one comma-joined field, and names
  were never split. Splitting them fixes the who-line's author list and lets
  the tracked-author lane match anyone on the paper, not just the last name.

## v0.5.0 — 2026-10-21

- **The who-line:** every Slack pick shows its authors (first three + `+N`),
  tracked people as `⭐ Name (Group)`, and the institutions printed on the
  paper's own PDF. Affiliations are never inferred or bound to individual
  authors; an ambiguous parse shows authors only (ADR 0002).
- Roster entries may carry a display-only group: `"M. Lukin — Harvard-Lukin"`.
- New config slot `[slack] who_style = "full" | "authors" | "none"`
  (default `authors`; `full` fetches each pick's PDF).

## v0.4.1 — 2026-10-12

- `arjev review --days 7`: the week-in-review, a read-only re-read of the
  journal (papers that missed the daily cap, tracked-author matches,
  Jev-vs-keyword divergences, the week's labels).

## v0.4.0 — 2026-10-08

- The context engine: an opt-in `budget-greedy` state policy that fills a byte
  budget with directives and per-paper taste cards (your why, the abstract, the
  conclusions), weighted by recency. `arjev calibrate --replay-arms` measures
  each arm on your labels; defaults change only on a measured win.
- `arjev fetch` and `arjev backfill` extract PDF text into the library.

## v0.3.0 — 2026-10-02

- Field-neutral: `feeds` defaults to empty and the digest refuses to run until
  you choose categories. `arjev init` writes a self-explaining config and never
  overwrites an existing one.
- New verbs: `arjev inspect` (verify the config) and `arjev staged` (the notes
  awaiting prose).

## Earlier

v0.1–v0.2 (2026-10-01): the first digest, Slack picks and reaction labels,
taste directives, multi-feed digests, `arjev ingest`, and Jev-first ranking.
The original spec and plan are in [`docs/history/`](docs/history/).

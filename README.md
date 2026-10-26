<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/banner-dark.svg">
    <img alt="arJev" src="docs/brand/banner-light.svg" width="520">
  </picture>
</p>

<p align="center"><em>Your daily arXiv, ranked against your vault.</em></p>

**arJev** reads the new papers in the arXiv categories you follow every day,
ranks them against your Obsidian vault — the papers you've read, kept, and
written about — and sends you the few worth your time, each with a reason. Your
reactions teach it, so the picks improve the longer you use it.

It works for any field that posts to arXiv, from condensed matter to economics,
and it reads nothing but arXiv. It never picks categories for you.

## What a pick looks like

Each pick arrives in the terminal, a dated note in your vault, or a Slack channel:

```text
arJev pick 2/5 for 2026-10-21 — mode: jev, ok
Parallel Omnidirectional Atom Rearrangement with Dynamic Holograms
   who: Samuel A. Engel, Dewei Gong, Ziguang Lin +3 · Harvard University, Cambridge, Harvard-MIT Center for Ultracold Atoms, Cambridge
   why: control, quantum, transport, array, atoms (score 5496.1)
```

The *why* line shows which of your interests it matched. The *who* line shows
the authors, a ⭐ when someone you track wrote it, and the institutions printed
on the paper itself.

## How it works

- **Your vault is the taste profile.** arJev reads your paper notes — what you
  kept, how you rated it, the one line on why it mattered — plus an optional
  note where you say in plain English what you want more and less of.
- **Every new paper gets judged.** With a [Jev](https://typesafe.ai) key, a
  small calibrated model screens every paper in your feeds, so relevant work
  surfaces even when it shares no keywords with your notes. Without a key,
  arJev ranks by your vault's vocabulary.
- **Your reactions are the training data.** 👍 keeps a paper (it becomes a
  vault note), 👀 saves it for later, ❌ skips it. Kept papers shape tomorrow's
  ranking once they're written up.
- **It never writes your notes.** The ranking model only makes decisions; every
  sentence in your vault comes from you or an AI agent you choose.

## Quick start

```bash
uv tool install git+https://github.com/harmoniqs/arJev
arjev init --vault ~/path/to/your/vault      # writes ~/.config/arjev/arjev.toml
# edit the config: set feeds = ["your", "arxiv", "categories"]
arjev inspect                                # checks the setup (exit 0 = ready)
arjev digest                                 # today's picks, printed
```

No paper notes yet? Seed the vault from a Zotero or Google Scholar export with
`arjev ingest --bibtex library.bib`, or from a folder of PDFs.

**Full setup** — your existing notes, a Jev key, Slack, and a daily
schedule — is in **[docs/setup.md](docs/setup.md)**, about fifteen minutes.
**Using an AI agent?** Hand it **[docs/agent-setup.md](docs/agent-setup.md)**
and say "set this up for me".

## Every day

Schedule `arjev daily` once (the [setup guide](docs/setup.md#9-run-it-every-day)
ships systemd and launchd files) and it runs the whole day: the digest, retried
if arXiv's feed is flaky; Slack ingest and reaction sync; and on Sundays, a
week-in-review of good papers that missed a daily top 5.

| You | arJev |
|---|---|
| 👍 a pick in Slack | creates a vault note for it, waiting for a summary |
| 👀 / ❌ a pick | saves it to read later / marks it not for you |
| reply in a pick's thread | marks it discussed |
| write a kept note's summary and `why:` | uses it to rank tomorrow's papers |

## Commands

| Command | What it does |
|---|---|
| `arjev init --vault PATH` | writes a commented starter config |
| `arjev inspect` | shows what the config sees; exits 1 if setup is incomplete |
| `arjev digest` | ranks today's papers; `--post vault`, `--post slack`, or `--post slack,vault` to deliver |
| `arjev daily` | the whole day, for a timer |
| `arjev ingest --bibtex FILE` | seeds the vault (also `--pdf-dir`, `--slack-channel-id`) |
| `arjev keep ARXIV_ID` | keeps a paper from a digest as a vault note |
| `arjev staged` | lists kept notes still waiting for a write-up |
| `arjev fetch ARXIV_ID` | downloads a paper's PDF into your library |
| `arjev backfill` | fetches PDFs for every paper in the vault |
| `arjev slack sync` | turns Slack reactions and replies into labels |
| `arjev labels sync` | records keeps from checked boxes in vault digest notes |
| `arjev review --days 7` | the week-in-review (`--post slack` to share it) |
| `arjev calibrate` | how well the ranking matches your reactions |
| `arjev rate propose` | suggests ratings for your notes; `arjev rate accept` applies one |

Every command takes `--config PATH`, and `--help` on any command lists its options.

## Documentation

| | |
|---|---|
| [docs/setup.md](docs/setup.md) | step-by-step setup and troubleshooting |
| [docs/slack-setup.md](docs/slack-setup.md) | the Slack app, in five minutes |
| [docs/agent-setup.md](docs/agent-setup.md) | the runbook for an AI agent installing arJev |
| [docs/architecture.md](docs/architecture.md) | how ranking, the context window, and calibration work |
| [docs/amicode-integration.md](docs/amicode-integration.md) | connecting an agent to write notes and enrich digests |
| [CONTEXT.md](CONTEXT.md) · [docs/adr/](docs/adr/) | the glossary and design decisions |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each release |
| [AGENTS.md](AGENTS.md) | working on arJev itself — layout, tests, releases |

## Status

In daily use at [Harmoniqs](https://harmoniqs.ai) since October 2026. The plan
of record is [issue #1](https://github.com/harmoniqs/arJev/issues/1).

Apache-2.0.

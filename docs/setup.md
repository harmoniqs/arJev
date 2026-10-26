# Setting up arJev

From nothing to a daily digest in about fifteen minutes. Each step ends with a
check you can run; if a check fails, see [Troubleshooting](#troubleshooting).

Prefer to have an AI agent do this for you? Give it
[agent-setup.md](agent-setup.md) — the same steps, written as a runbook.

**You need:** Python 3.11+, [uv](https://docs.astral.sh/uv/), and an Obsidian
vault (or an empty folder that will become one). Optional: a Jev key for
semantic ranking, and a Slack workspace for the shared channel.

## 1. Install

```bash
uv tool install git+https://github.com/harmoniqs/arJev
```

To pin a release instead, append `@vX.Y.Z` (see the [changelog](../CHANGELOG.md)).
`pipx install git+https://github.com/harmoniqs/arJev` works too.

**Check:** `arjev --version` prints a version.

## 2. Point it at your vault

```bash
arjev init --vault ~/path/to/your/vault
```

This writes `~/.config/arjev/arjev.toml`. Every setting in it has a one-line
comment explaining it, and `arjev init` never overwrites an existing config.

**If your vault already has paper notes**, tell arJev how they're written. A
paper note needs a `type` value marking it as a paper, and an identity field
holding its arXiv id or DOI. The defaults expect:

```yaml
type: paper
arxiv: "2610.01234"
date_read: 2026-10-20
rating: core          # core | useful | marginal
why: "one line on why this paper matters to you"
tags: [topic, another]
```

If your notes use different field names, remap them under `[vault.fields]`
rather than changing your notes:

| Your notes use… | Set this in `arjev.toml` |
|---|---|
| a different type value, e.g. Zotero's `journalArticle` | `[vault]` `type = "journalArticle"` |
| only DOIs | `[vault.fields]` `identity = ["doi"]` |
| `dateAdded` instead of `date_read` | `[vault.fields]` `read_date = "dateAdded"` |
| `takeaway` instead of `why` | `[vault.fields]` `why = "takeaway"` |
| `keywords` instead of `tags` | `[vault.fields]` `tags = "keywords"` |

**If you're starting fresh**, leave the defaults; step 4 fills the vault.

## 3. Choose your feeds

arJev never picks categories for you. In `arjev.toml`, set the arXiv
categories you follow ([the full list](https://arxiv.org/category_taxonomy)):

```toml
[vault]
feeds = ["quant-ph", "cond-mat.mes-hall"]
```

Cross-listed papers are counted once, and every new paper in every feed is
screened each day.

## 4. Seed the vault

Start the vault from what you already have. Every option is safe to re-run:
existing papers are skipped, and existing notes are never edited.

```bash
arjev ingest --bibtex ~/Downloads/library.bib     # a Google Scholar or Zotero export
arjev ingest --pdf-dir ~/Papers                   # a folder of PDFs
arjev ingest --slack-channel-id C0123456ABC       # links people shared in Slack (needs step 8)
```

**Check:** `arjev inspect` exits 0, and its `fold identity-bearing:` line counts
your papers. It prints `blocked: …` and exits 1 if something is missing.

## 5. Say what you want (optional, recommended)

Create `arjev-directives.md` at the root of your vault. The lists become
high-weight terms; the prose is read by the ranking model as written.

```markdown
---
type: directives
labs: [Some Lab, Another Group]
companies: [A Company]
topics: [optimal control, error correction]
authors: ["A. Researcher — Their Lab", "Another Person"]
---

I want experimental results on superconducting and neutral-atom hardware, and
control methods with real benchmarks. De-prioritize pure complexity theory.
```

Authors are matched by surname and first initial. The `— Group` suffix is
display-only: it's shown next to the name when that person is on a pick.

**Check:** `arjev inspect` shows `fold directives: loaded (<n> terms)`.

## 6. Run your first digest

```bash
arjev digest
```

This prints today's picks, each with its reason. Nothing is posted or saved;
`stdout` is a preview, so run it as often as you like.

## 7. Add a Jev key (optional, recommended)

Without a key, arJev ranks by matching your vault's vocabulary. With one, the
[Jev](https://typesafe.ai) model screens every paper in your feeds, so relevant
papers surface even when they share no words with your notes. It costs a few
cents a day.

Get a key at <https://console.typesafe.ai>, then save it to a file only you can
read (paste the key, press Enter, then Ctrl-D):

```bash
install -m 600 /dev/stdin ~/.config/arjev/jev.key
```

**Check:** `ARJEV_JEV_KEY_FILE=~/.config/arjev/jev.key arjev digest` shows
`mode: jev` in its header.

## 8. Connect Slack (optional)

Slack turns the digest into a shared channel: each pick is its own message, and
reactions teach the ranking. Follow **[slack-setup.md](slack-setup.md)** (about
five minutes), which ends with the token saved at
`~/.config/arjev/slack-token` and this in `arjev.toml`:

```toml
[slack]
channel = "C0123456ABC"      # the channel ID, not its name
keepers = ["U0YOURID"]       # Slack user IDs whose reactions count
```

## 9. Run it every day

`arjev daily` runs the whole day: the digest (retried if arXiv's feed is
flaky), Slack ingest and reaction sync, and on Sundays the week-in-review. It
reads the key and token files from steps 7 and 8; either can be missing.

**Linux (systemd):**

```bash
mkdir -p ~/.config/systemd/user
for f in arjev-daily.service arjev-daily.timer; do
  curl -fsSL -o ~/.config/systemd/user/$f https://raw.githubusercontent.com/harmoniqs/arJev/main/contrib/systemd/$f
done
systemctl --user daemon-reload
systemctl --user enable --now arjev-daily.timer
loginctl enable-linger "$USER"     # so the timer also runs when you're logged out
```

**macOS (launchd):**

```bash
P=~/Library/LaunchAgents/io.github.harmoniqs.arjev.daily.plist
curl -fsSL https://raw.githubusercontent.com/harmoniqs/arJev/main/contrib/launchd/io.github.harmoniqs.arjev.daily.plist \
  | sed "s|__HOME__|$HOME|g" > "$P"
launchctl bootstrap gui/$(id -u) "$P"
```

The macOS job runs at 9:00 local time; edit `Hour` in the plist if you're not
on US Eastern time (13:00 UTC is when arXiv's new listings are out).

**Check:** run it once now with `arjev daily`. Then `systemctl --user
list-timers` (Linux) or `launchctl list | grep arjev` (macOS) shows it armed.
Logs: `journalctl --user -u arjev-daily` on Linux, `~/Library/Logs/arjev-daily.log`
on macOS.

## 10. Day to day

| You do | What happens |
|---|---|
| 👍 a pick in Slack | It becomes a note in your vault, waiting for a summary |
| 👀 a pick | It's saved to read later |
| ❌ a pick | It's marked as not for you |
| Reply in a pick's thread | It's marked as discussed |
| Fill `rating:` and `why:` on a note | That note starts shaping the ranking |

Without Slack, keep a paper from a digest with `arjev keep <arxiv-id>`.

Kept papers start as **staged** notes (metadata only). They begin to count once
someone writes them up: `arjev staged` lists them; write the summary and a
`why:` line, then change `status: staged` to `status: written`. An agent can do
this for you; see [agent-setup.md](agent-setup.md#8-the-staged-loop--your-prose-obligation).

Weekly, `arjev review --days 7` shows relevant papers that missed a daily top 5,
and `arjev calibrate` reports how well the ranking matches your reactions.
`arjev daily` runs both on Sundays.

## Troubleshooting

| You see | What it means | Fix |
|---|---|---|
| `feeds not configured` | No categories chosen | Set `feeds` (step 3) |
| `blocked: zero identity-bearing notes` | arJev can't find paper notes | Seed the vault (step 4), or remap fields (step 2) |
| `fold type-matched: 0` with papers present | The `type` value doesn't match your notes | Set `[vault] type` to your notes' value |
| `profile-degraded` in the digest header | Fewer than 5 notes, or none with a `why:` | Seed more papers, write a few `why:` lines |
| `feed failure — every configured feed returned 0 items` on a weekday | arXiv's feed is temporarily empty | `arjev daily` retries automatically |
| The same message on a Saturday or Sunday | arXiv doesn't publish on weekends | Nothing; `arjev daily` logs a quiet weekend |
| `no Slack token` | The token file is missing or empty | Redo the token step in [slack-setup.md](slack-setup.md) |
| Slack `missing_scope` | The Slack app lacks a permission | Recreate it from the manifest in [slack-setup.md](slack-setup.md) |
| Slack `not_in_channel` | The bot isn't in the channel | `/invite @arJev` in the channel |

## Upgrading

```bash
uv tool upgrade arjev
```

Or reinstall a pinned release: `uv tool install --force git+https://github.com/harmoniqs/arJev@vX.Y.Z`.
The [changelog](../CHANGELOG.md) lists what changed.

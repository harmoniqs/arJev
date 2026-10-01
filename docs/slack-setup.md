# Slack setup — the dedicated arJev bot app

arJev posts each digest pick as its own message, so Slack reactions map 1:1 to papers:
a `👍` on a pick message is a *keep* for that paper. Five minutes of setup, once.

## 1. Create the app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → *From scratch*.
2. Name it (e.g. `arJev`), pick your workspace.
3. **OAuth & Permissions** → add the three Bot Token Scopes:
   - `chat:write` — post digest picks
   - `reactions:read` — harvest 👍 / 👀 / ❌ on pick messages
   - `conversations.replies` — harvest thread replies as `discussed` labels
4. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-…`).
5. Invite the bot to your digest channel: `/invite @arJev`.

## 2. Configure arJev

```toml
[slack]
channel = "#papers"                  # the digest channel
keepers = ["U0YOURID", "U0TEAMMATE"] # Slack user ids whose reactions count as labels
why_style = "terms"                  # terms | opaque | none — what the why-line reveals
emoji_map = { thumbsup = "keep", eyes = "read-later", x = "skip" }

[slack.emoji_map]  # long form, equivalent
thumbsup = "keep"
```

- **keepers** is the allowlist: a reaction from anyone *not* on the list labels nothing.
  Find user ids with `arjev slack sync --config …` run once with everyone reacting, or
  via the Slack API `users.list`.
- **why_style** controls what the why-line shows: `terms` (matched taste terms — your
  own channel, fine), `opaque` (just "profile match"), or `none` (just the score).

## 3. Environment

```bash
export ARJEV_SLACK_TOKEN="xoxb-…"   # never in the repo, never in config
export ARJEV_JEV_KEY="…"            # optional — without it the digest runs lexical-only
```

## 4. Run

```bash
arjev digest --feed quant-ph --post slack     # the daily digest (cron/launchd)
arjev slack sync                             # after: harvest reactions → labels + stubs
```

`slack sync` reads the digest journal for posted messages, harvests reactions
(keepers-gated) and thread replies, writes label rows, and **auto-scaffolds a staged
vault stub** for every new keep — decision in Slack, record in Obsidian, zero steps
between. Re-run it as often as you like; it's idempotent. Rate discipline is built in
(≤ 1 request/s, 429 backoff).

## Security notes

- The token lives in the environment, never in the repo or config (the repo's
  `.gitignore` blocks `*token*` defensively anyway).
- Digest messages carry only feed-derived content (title, abstract excerpt, link,
  score) plus matched taste terms per `why_style` — never vault paths, note filenames,
  or your `why` text.
- A thread reply marks a paper `discussed` — a flavor label; it never auto-keeps.

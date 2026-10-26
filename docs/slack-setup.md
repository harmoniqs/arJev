# Slack setup

arJev posts each digest pick as its own Slack message, so a reaction maps to
exactly one paper: 👍 keeps it, 👀 saves it for later, ❌ skips it. This takes
about five minutes, once.

## 1. Create the app from the manifest

1. Open <https://api.slack.com/apps?new_app=1> → **From an app manifest** → pick
   your workspace → **Next**.
2. Choose the **YAML** tab, replace its contents with
   [`slack-app-manifest.yaml`](slack-app-manifest.yaml), then **Next** → **Create**.
3. Click **Install to Workspace** → **Allow**.
4. On **OAuth & Permissions**, copy the **Bot User OAuth Token** (`xoxb-…`).

The manifest asks for four permissions, one per feature:

| Scope | Used for |
|---|---|
| `chat:write` | posting picks and the weekly review |
| `reactions:read` | turning 👍 / 👀 / ❌ into labels |
| `channels:history` | reading thread replies and papers people share (add `groups:history` for a private channel) |
| `channels:join` | letting the bot join the channel itself |

Optional: on **Basic Information**, set the app icon to
[`brand/icon-light-1024.png`](brand/icon-light-1024.png).

## 2. Save the token

Paste the token, press Enter, then Ctrl-D:

```bash
install -m 600 /dev/stdin ~/.config/arjev/slack-token
```

The file is readable only by you. arJev finds it through
`ARJEV_SLACK_TOKEN_FILE`, which the daily service in [setup.md](setup.md#9-run-it-every-day)
sets for you. Never put the token in `arjev.toml` or a repo.

## 3. Configure the channel

arJev needs the channel's **ID**, not its name. In Slack, open the channel, click
its name at the top, and copy the ID at the bottom of the panel (it starts with
`C`). Add to `~/.config/arjev/arjev.toml`:

```toml
[slack]
channel = "C0123456ABC"        # the digest channel's ID
keepers = ["U0123ABCD"]        # Slack user IDs whose reactions count as labels
who_style = "full"             # full | authors | none — see below
why_style = "terms"            # terms | opaque | none — see below
```

- **keepers** — only reactions from these people become labels; anyone else's
  reaction is ignored. Find your user ID in Slack under your profile → ⋮ →
  **Copy member ID**. Every keeper's 👍 shapes the shared ranking, so list the
  people whose taste the channel should follow.
- **who_style** — the line of authors under each pick. `full` also shows the
  institutions printed on the paper (arJev fetches each pick's PDF to read them),
  `authors` shows authors and tracked people only, `none` hides the line.
- **why_style** — the reason line. `terms` shows the matched taste terms,
  `opaque` just says "profile match", `none` shows only the score.

Then add the bot to the channel: type `/invite @arJev` there.

## 4. Check it

```bash
export ARJEV_SLACK_TOKEN_FILE=~/.config/arjev/slack-token
arjev digest --post slack,vault
arjev slack sync
```

The first command posts today's picks to the channel and writes the same
digest as a dated note in your vault. Put a 👍 on one pick, then run
`arjev slack sync` again: it should report a label, and a new note for that
paper appears in your vault with `status: staged`.

From here, `arjev daily` (the scheduled service) does both every day.

## What arJev posts, and what it reads

- **Posts:** each pick's title and arXiv link, its authors and printed
  affiliations (per `who_style`), and the reason line (per `why_style`). Never
  vault paths, note filenames, or your notes' text.
- **Reads:** reactions and thread replies on its own pick messages, and arXiv
  links that people (not bots) share in the channel.
- A thread reply marks a paper as discussed; it never keeps it on its own.
- arJev stays under Slack's rate limits (at most one request per second, with
  backoff on `ratelimited`).

# arJev v0.5.6

**The one-line version:** one digest run can post to Slack and write the vault note.

## What's new

- **`--post` takes a comma list of sinks** (`arjev digest --post slack,vault`). The run
  ranks once, writes the dated vault digest note, then posts to Slack. Posted ids are
  consumed once and the journal is written once.
- **Partial failure is honest.** If one sink fails, the others still run. The CLI prints
  the digest, names the failed sink on stderr, and exits 1. The vault note is written
  first, so a Slack outage never loses the day's record.
- **Config errors fail early.** The Slack channel and token checks run before ranking,
  so a misconfigured run spends no Jev calls.
- `stdout` (the preview) cannot be combined with a durable sink.

Part of amicode rd-system v2.1, decision A8(a) (harmoniqs/arJev#106).

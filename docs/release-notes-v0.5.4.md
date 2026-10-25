# arJev v0.5.4

**The one-line version:** the week-in-review reads like a Slack message now.

## What's fixed

- **A Slack-native review.** `arjev review --post slack` posts Slack mrkdwn: bold
  section titles instead of raw `#` headings, every title linked to arXiv,
  readable dates, plain labels ("must-read", "worth reading"), and a one-line
  nudge to react. The debugging-only divergence section and internal notes stay
  in the file report (`render()`, stdout and `review-YYYYMMDD.md`), unchanged.
- **`\\( … \\)` inline math** in titles is cleaned like `$ … $` — in the review
  and in daily picks.

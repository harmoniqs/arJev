# arJev v0.5.5

**The one-line version:** the reaction harvest works against real Slack.

## What's fixed

- **Form-encoded Slack calls.** The client sent every Web API call as a JSON
  body. `chat.postMessage` accepts that, but `reactions.get` and
  `conversations.replies` ignore JSON, so the first live `arjev slack sync`
  failed with `no_item_specified`. Every call is now form-encoded, which all
  methods accept. A wire-format test drives the real HTTP path.
- **Manifest:** adds `channels:join`, so the bot can join the digest channel
  itself.

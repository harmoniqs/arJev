"""The Slack surface: a dedicated bot app (scopes chat:write, reactions:read,
conversations.replies — docs/slack-setup.md). Rate discipline: ≤ 1 request/s with 429
backoff (obligation #18). Content boundary: feed-derived + matched terms (why_style-
gated) + one probe confidence — never vault paths, note filenames, or why text
(obligation #12). Keepers allowlist: unauthorized reactions label nothing (#10).

Each pick posts as its own message — reactions map 1:1 to papers. The journal
records every posted (arxiv, slack_ts) pair; the sync harvests reactions + thread
replies from those exact messages."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .latex import latex_to_unicode

Transport = Callable[[str, str, dict], dict]  # (method, payload, token) -> response json
MIN_INTERVAL_S = 1.0
MAX_BACKOFF_RETRIES = 2


class SlackClient:
    def __init__(self, token: str, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.token = token
        self._transport = transport or self._http_transport
        self._sleep = sleep
        self._last_call = 0.0

    def _http_transport(self, method: str, payload: dict, token: str) -> dict:
        import httpx

        with httpx.Client(timeout=30, headers={"authorization": f"Bearer {token}"}) as client:
            r = client.post(f"https://slack.com/api/{method}", json=payload)
            r.raise_for_status()
            return r.json()

    def _call(self, method: str, payload: dict) -> dict:
        wait = self._last_call + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            self._sleep(wait)  # the rate discipline: never faster than 1/s
        self._last_call = time.monotonic()
        response = self._transport(method, payload, self.token)
        retries = 0
        while response.get("ok") is True and response.get("error") == "ratelimited" and retries < MAX_BACKOFF_RETRIES:
            self._sleep(2**retries)
            retries += 1
            response = self._transport(method, payload, self.token)
        if not response.get("ok"):
            raise RuntimeError(f"slack {method} failed: {response.get('error')}")
        return response

    def post_message(self, channel: str, text: str) -> str:
        return str(self._call("chat.postMessage", {"channel": channel, "text": text})["ts"])

    def get_reactions(self, channel: str, ts: str) -> list[dict]:
        msg = self._call("reactions.get", {"channel": channel, "timestamp": ts, "full": True})
        return list(msg.get("message", {}).get("reactions", []))

    def channel_history(self, channel: str, limit: int = 200) -> list[dict]:
        msgs = self._call("conversations.history", {"channel": channel, "limit": limit})
        return list(msgs.get("messages", []))

    def get_replies(self, channel: str, ts: str) -> list[dict]:
        msgs = self._call("conversations.replies", {"channel": channel, "ts": ts, "limit": 100})
        return [m for m in msgs.get("messages", []) if m.get("ts") != ts]  # drop the parent


# ── rendering: the content boundary lives here ───────────────────────────────────

DEFAULT_EMOJI_MAP = {"thumbsup": "keep", "eyes": "read-later", "x": "skip"}


@dataclass
class SlackPost:
    text: str
    arxiv: str


def render_pick_message(pick, index: int, total: int, today, mode: str, why_style: str) -> SlackPost:
    title = latex_to_unicode(pick.title)
    # the digest header names the feeds; pick headers stay link-free (Slack
    # linkifies raw "quant-ph+cond-mat..." strings into fake URLs)
    lines = [f"*arJev pick {index}/{total} for {today.isoformat()}* — {mode}",
             f"<http://arxiv.org/abs/{pick.arxiv}|{title}>"]
    if why_style == "terms":
        shown = ", ".join(f"`{t}`" for t in pick.terms[:5])
        why = f"{shown} (score {pick.lexical_score})" if shown else "(no terms)"
    elif why_style == "opaque":
        why = f"profile match (score {pick.lexical_score})"
    else:
        why = f"score {pick.lexical_score}"
    if pick.rescued == "probe":
        why = f"rescued by probe — no lexical match, Jev relevance p={pick.jev_primary:.2f}"
    lines.append(f"   _why:_ {why}")
    return SlackPost(text="\n".join(lines), arxiv=pick.arxiv)


# ── the harvest: reactions (keepers-gated) + replies (discussed) ─────────────────

def harvest_labels(client: SlackClient, channel: str, posted: list[dict],
                   keepers: set[str], emoji_map: dict[str, str],
                   now_ts: str) -> tuple[list, list[str], list[str]]:
    """posted = journal rows {arxiv, slack_ts}. Returns (labels, new_keeps, discussed)
    as (arxiv, label_type) tuples for the caller to ledger; the caller scaffolds the
    new keeps. Unauthorized reactors label nothing — the boundary is here."""
    from .ledger import Label

    labels: list[Label] = []
    new_keeps: list[str] = []
    discussed: list[str] = []
    for row in posted:
        arxiv, ts = row["arxiv"], row["slack_ts"]
        for reaction in client.get_reactions(channel, ts):
            label_type = emoji_map.get(reaction["name"])
            if not label_type:
                continue  # unmapped emoji is someone's opinion, not a label
            for user in reaction.get("users", []):
                if user not in keepers:
                    continue  # keepers allowlist — obligation #10
                labels.append(Label(arxiv, label_type, "slack-reaction", now_ts))
                if label_type == "keep":
                    new_keeps.append(arxiv)
        if client.get_replies(channel, ts):
            discussed.append(arxiv)  # flavor: never an auto-keep
            labels.append(Label(arxiv, "discussed", "slack-reply", now_ts))
    return labels, new_keeps, discussed


def resolve_channel(cfg, name: str) -> str:
    """Channel ids only — a bare name is an error to make loudly, never a guess
    (the config's slack.channel carries the id for the digest channel)."""
    import re

    if re.fullmatch(r"[CGD][0-9A-Z]{6,}", name):
        return name
    raise SystemExit(f"channel {name!r} is a name, not an id — pass --slack-channel-id")

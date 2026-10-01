"""The arXiv RSS feed: zero-dep parse (stdlib ET), malformed input degrades to [].
The fetch seam is injectable — CI reads the recorded fixture; live runs GET politely."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path

import httpx

from .fold import normalize_arxiv

UA = "arjev/0.1 (harmoniqs/arjev; daily digest; https://github.com/harmoniqs/arjev)"
_ABSPATH = re.compile(r"abs/([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(v\d+)?")


@dataclass
class FeedItem:
    arxiv: str  # normalized (vN stripped)
    title: str
    abstract: str  # tag-stripped, entity-unescaped, capped


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]*>", " ", unescape(s)).strip()


def _text_of(el) -> str:
    return el.text or ""


def parse_arxiv_rss(xml: str) -> list[FeedItem]:
    """Parse arXiv's RSS <item><title/><link>…abs/<id></link><description/></item>.
    Malformed input degrades to [] — a bad feed never crashes the digest."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    items: list[FeedItem] = []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        if title_el is None or link_el is None or _text_of(title_el) is None:
            continue
        m = _ABSPATH.search(_text_of(link_el).strip())
        if not m:
            continue
        desc = _strip_tags(_text_of(desc_el)) if desc_el is not None else ""
        items.append(
            FeedItem(
                arxiv=normalize_arxiv(m.group(1)),
                title=_strip_tags(_text_of(title_el)),
                abstract=desc[:2000],
            )
        )
    return items


def feed_url(name: str) -> str:
    return f"https://export.arxiv.org/rss/{name}"


def fetch_feed(url: str, timeout: float = 30.0) -> str:
    with httpx.Client(timeout=timeout, headers={"user-agent": UA}) as client:
        return client.get(url).text


def load_feed(feed: str | None = None, feed_file: str | None = None) -> list[FeedItem]:
    """From a recorded fixture file (deterministic, CI) or the live RSS (deployment)."""
    if feed_file:
        return parse_arxiv_rss(Path(feed_file).read_text())
    return parse_arxiv_rss(fetch_feed(feed_url(feed or "quant-ph")))

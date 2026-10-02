"""The arXiv RSS feed: zero-dep parse (stdlib ET), malformed input degrades to [].
The fetch seam is injectable — CI reads the recorded fixture; live runs GET politely."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    authors: list[str] = field(default_factory=list)


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
        authors = [
            _strip_tags(t.text)
            for t in item.iter()
            if t.tag.endswith("creator") or t.tag.endswith("author")
        ]
        m = _ABSPATH.search(_text_of(link_el).strip())
        if not m:
            continue
        desc = _strip_tags(_text_of(desc_el)) if desc_el is not None else ""
        items.append(
            FeedItem(
                arxiv=normalize_arxiv(m.group(1)),
                title=_strip_tags(_text_of(title_el)),
                abstract=desc[:2000],
                authors=[a for a in authors if a],
            )
        )
    return items


def feed_url(name: str) -> str:
    return f"https://export.arxiv.org/rss/{name}"


def fetch_feed(url: str, timeout: float = 30.0) -> str:
    with httpx.Client(timeout=timeout, headers={"user-agent": UA}) as client:
        return client.get(url).text


def load_feed(feed: str | None = None, feed_file: str | None = None) -> list[FeedItem]:
    """From a recorded fixture file (deterministic, CI) or the live RSS (deployment).
    No default category — a caller that passes neither a feed nor a file is an error,
    not a silent fetch of someone else's field (issue #53)."""
    if feed_file:
        return parse_arxiv_rss(Path(feed_file).read_text())
    if feed is None:
        raise ValueError("load_feed needs an arXiv feed name or a feed_file — no category is ever defaulted")
    return parse_arxiv_rss(fetch_feed(feed_url(feed)))


def load_feeds(feeds: list[str], feed_files: list[str] | None = None) -> list[FeedItem]:
    """The multi-feed union: fetch every configured feed, union the items, dedupe by
    normalized arXiv id (cross-listed papers appear in several category feeds — one
    candidate, scored once). Feed order preserved for the winner."""
    items: list[FeedItem] = []
    seen: set[str] = set()
    for path in feed_files or []:
        for item in parse_arxiv_rss(Path(path).read_text()):
            if item.arxiv not in seen:
                seen.add(item.arxiv)
                items.append(item)
    if not feeds:
        return items
    for name in feeds:
        for item in parse_arxiv_rss(fetch_feed(feed_url(name))):
            if item.arxiv not in seen:
                seen.add(item.arxiv)
                items.append(item)
    return items

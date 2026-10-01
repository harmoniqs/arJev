"""Render: the digest as Slack mrkdwn, an Obsidian digests/ note (checkboxes are the
`checkbox` label source in slice 3), or stdout markdown. Every render carries the
composite mode line `mode: <primary>, <profile>` (obligation #9)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .rank import RankResult


def mode_line(primary: str, profile_flag: str) -> str:
    return f"mode: {primary}, {profile_flag}"


def canonical_picks(rank: RankResult) -> list[dict]:
    """The fingerprint basis: scores + terms, date-free, sort-stable (obligation #22)."""
    return [
        {"arxiv": s.item.arxiv, "score": s.score, "terms": s.terms, "rescued": False}
        for s in sorted(rank.picks, key=lambda s: (-s.score, s.item.arxiv))
    ]


def _why_terms(s, limit: int = 5) -> str:
    shown = ", ".join(f"`{t}`" for t in s.terms[:limit])
    return f"{shown} (score {s.score})" if shown else "(no terms)"


def render_mrkdwn(rank: RankResult, feed_name: str, total: int, today: date, mode: str) -> str:
    header = f"*arXiv {feed_name} picks for {today.isoformat()}* ({len(rank.picks)} of {total} new"
    lines = [f"{header}, ranked against the lab corpus)", f"_{mode}_"]
    for i, s in enumerate(rank.picks):
        lines.append(f"{i + 1}. <http://arxiv.org/abs/{s.item.arxiv}|{s.item.title}>")
        lines.append(f"   _why:_ {_why_terms(s)}")
    if not rank.picks:
        lines.append("_nothing matched the lab profile today_")
    if rank.skipped_corpus:
        lines.append(f"_{len(rank.skipped_corpus)} already in the lab corpus — skipped_")
    return "\n".join(lines)


def render_vault_note(rank: RankResult, feed_name: str, total: int, today: date, mode: str) -> str:
    """The digests/ note: checkboxes are decision records — slice 3's labels sync parses
    exactly this format (source: `checkbox`)."""
    fm = (
        "---\n"
        f"type: digest\n"
        f"date: {today.isoformat()}\n"
        f"feed: {feed_name}\n"
        f"mode: {mode}\n"
        "---\n"
    )
    lines = [f"# arXiv {feed_name} picks — {today.isoformat()}", "", f"`{mode}`", ""]
    for s in rank.picks:
        target = f"[arXiv:{s.item.arxiv}](https://arxiv.org/abs/{s.item.arxiv})"
        lines.append(f"- [ ] {s.item.title} — {target} · {_why_terms(s)}")
    if not rank.picks:
        lines.append("- nothing matched the lab profile today")
    lines.append("")
    lines.append(f"_{len(rank.skipped_corpus)} in corpus · {total} new items_")
    return fm + "\n".join(lines) + "\n"


def write_vault_note(content: str, digest_dir: Path, today: date) -> Path:
    """New-file-only, atomic, idempotent (obligation: write safety)."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    target = digest_dir / f"{today.isoformat()}.md"
    tmp = digest_dir / f".{today.isoformat()}.md.tmp"
    tmp.write_text(content)
    tmp.replace(target)
    return target

"""Render: the digest as Slack mrkdwn, an Obsidian digests/ note (checkboxes are the
`checkbox` label source in slice 3), or stdout markdown. Every render carries the
composite mode line `mode: <primary>, <profile>` (obligation #9)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .rerank import Pick


def mode_line(primary: str, profile_flag: str) -> str:
    return f"mode: {primary}, {profile_flag}"


def canonical_picks(picks: list[Pick]) -> list[dict]:
    """The fingerprint basis: scores + terms + rescue flags, date-free, sort-stable
    (obligation #22)."""
    return [
        {
            "arxiv": p.arxiv,
            "score": p.lexical_score,
            "terms": p.terms,
            "rescued": p.rescued,
        }
        for p in sorted(picks, key=lambda p: (-p.jev_primary, -p.lexical_score, p.arxiv))
    ]


def _why_terms(p: Pick, limit: int = 5) -> str:
    if p.rescued == "probe":
        return f"rescued by probe — no lexical match, Jev relevance p={p.jev_primary:.2f}"
    if p.jev_primary > 0 and not p.terms:
        return f"picked by Jev — no lexical match, relevance p={p.jev_primary:.2f}"
    shown = ", ".join(f"`{t}`" for t in p.terms[:limit])
    base = f"{shown} (score {p.lexical_score})" if shown else "(no terms)"
    if p.rescued == "near-miss":
        return f"rescued by near-miss match · {base}"
    return base


def render_mrkdwn(picks: list[Pick], feed_name: str, total: int, today: date, mode: str, skipped_corpus: int) -> str:
    header = f"*arXiv {feed_name} picks for {today.isoformat()}* ({len(picks)} of {total} new"
    lines = [f"{header}, ranked against the lab corpus)", f"_{mode}_"]
    for i, p in enumerate(picks):
        lines.append(f"{i + 1}. <http://arxiv.org/abs/{p.arxiv}|{p.title}>")
        lines.append(f"   _why:_ {_why_terms(p)}")
    if not picks:
        lines.append("_nothing matched the lab profile today_")
    if skipped_corpus:
        lines.append(f"_{skipped_corpus} already in the lab corpus — skipped_")
    return "\n".join(lines)


def render_vault_note(picks: list[Pick], feed_name: str, total: int, today: date, mode: str,
                      skipped_corpus: int) -> str:
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
    for p in picks:
        target = f"[arXiv:{p.arxiv}](https://arxiv.org/abs/{p.arxiv})"
        lines.append(f"- [ ] {p.title} — {target} · {_why_terms(p)}")
    if not picks:
        lines.append("- nothing matched the lab profile today")
    lines.append("")
    lines.append(f"_{skipped_corpus} in corpus · {total} new items_")
    return fm + "\n".join(lines) + "\n"


def write_vault_note(content: str, digest_dir: Path, today: date) -> Path:
    """New-file-only, atomic, idempotent (obligation: write safety)."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    target = digest_dir / f"{today.isoformat()}.md"
    tmp = digest_dir / f".{today.isoformat()}.md.tmp"
    tmp.write_text(content)
    tmp.replace(target)
    return target

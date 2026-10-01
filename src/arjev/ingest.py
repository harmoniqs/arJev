"""arjev ingest — seed the taste profile from existing human signal (spec's Feed +
seeding amendment). Three seeds, one contract: every seed creates a staged paper
note whose `why` carries machine-written provenance, is DELIBERATELY touched (the
staged-gate invariant stops the recommender training on its OWN scaffolds — human-
curated papers are the opposite case), and is new-file-only, atomic, idempotent
(a note that already owns the id is skipped, never edited).

Seeds:
- BibTeX: a user-initiated Google Scholar/Zotero .bib export (parsing a file the
  user provides is not scraping).
- PDF folder: arXiv ids from filenames (the arjev fetch convention + bare ids),
  falling back to a raw-text stamp scan over the PDF bytes.
- Slack channel: arXiv links from human messages in history (channels:history).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .keep import KeepCandidate, scaffold_note

_ARXIV_IN_TEXT = re.compile(
    r"arxiv\.org/abs/([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(v\d+)?"
    r"|arXiv:([0-9]{4}\.[0-9]{4,5})(v\d+)?",
    re.IGNORECASE,
)
_ARXIV_IN_FILENAME = re.compile(r"([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(v\d+)?", re.IGNORECASE)
_ARXIV_IN_PDF = re.compile(rb"arXiv:([0-9]{4}\.[0-9]{4,5})(v\d+)?", re.IGNORECASE)


@dataclass
class SeedHit:
    arxiv: str
    title: str
    authors: list[str]
    why: str  # machine-written provenance — auditable and prunable


def ingest_bibtex(path: Path, cfg, today: date, papers_dir: Path | None = None) -> list[SeedHit]:
    """Parse a .bib export (Scholar/Zotero style): @article entries with title,
    author, eprint/archivePrefix or doi. Malformed entries are skipped, not fatal."""
    text = Path(path).read_text(errors="replace")
    hits: list[SeedHit] = []
    for match in re.finditer(r"@article\s*\{([^,]*,.*?)\n\}", text, re.DOTALL | re.IGNORECASE):
        body = match.group(1)
        title = _bib_field(body, "title")
        if not title:
            continue
        arxiv = _bib_field(body, "eprint") or ""
        if not arxiv:
            continue
        authors = _split_authors(_bib_field(body, "author") or "")
        hits.append(SeedHit(
            arxiv=arxiv.strip(),
            title=title,
            authors=authors,
            why=f"Seeded from bibliography export ({Path(path).name}), {today.isoformat()}",
        ))
    _write_all(hits, cfg, today, papers_dir)
    return hits


def _bib_field(body: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*=\s*[\{{\"](.+?)[\}}\"]\s*,?\s*\n", body, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    value = re.sub(r"\s+", " ", m.group(1)).strip()
    return value or None


def _split_authors(raw: str) -> list[str]:
    parts = re.split(r"\s+and\s+|;", raw)
    cleaned = [re.sub(r"[{}]", "", p).strip() for p in parts]
    return [p for p in cleaned if p]


def ingest_pdf_dir(directory: Path, cfg, today: date, papers_dir: Path | None = None) -> list[SeedHit]:
    """A paper collection: ids from filenames first, then the arXiv stamp inside the
    PDF bytes. Unidentifiable PDFs are reported, never guessed."""
    hits: list[SeedHit] = []
    failures: list[str] = []
    for pdf in sorted(Path(directory).glob("*.pdf")):
        arxiv = _ARXIV_IN_FILENAME.search(pdf.stem)
        if arxiv:
            arxiv = arxiv.group(1).lower()
        else:
            head = pdf.read_bytes()[:60000]
            m = _ARXIV_IN_PDF.search(head)
            arxiv = m.group(1).decode().lower() if m else None
        if not arxiv:
            failures.append(pdf.name)
            continue
        hits.append(SeedHit(
            arxiv=arxiv,
            title=pdf.stem.replace("-", " ").replace("_", " ").strip(),
            authors=[],
            why=f"Seeded from the PDF collection ({pdf.name}), {today.isoformat()}",
        ))
    _write_all(hits, cfg, today, papers_dir)
    if failures:
        shown = ", ".join(failures[:5])
        print(f"no arXiv id found in {len(failures)} PDF(s): {shown}")
    return hits


def ingest_slack_channel(client, channel: str, channel_name: str, users: dict[str, str],
                         cfg, today: date, papers_dir: Path | None = None, limit: int = 200) -> list[SeedHit]:
    """Human-shared papers are the strongest seed: every arXiv link a person chose
    to post becomes a staged note carrying who/where/when provenance."""
    messages = client.channel_history(channel, limit=limit)
    hits: list[SeedHit] = []
    seen: set[str] = set()
    for message in messages:
        # the anti-self-reinforcement filter: bot messages (the digest's own posts
        # above all) are machines, not taste — never seed from them
        if message.get("bot_id") or message.get("subtype"):
            continue
        user = users.get(message.get("user", "?"), message.get("user", "?"))
        if user.startswith("U") and user not in users:
            user = f"@{user}"
        text = message.get("text", "")
        ts = message.get("ts", "")
        when = date.fromtimestamp(float(ts.split(".")[0])) if ts else today
        for m in _ARXIV_IN_TEXT.finditer(text):
            arxiv = (m.group(1) or m.group(3) or "").lower()
            if not arxiv or arxiv in seen:
                continue
            seen.add(arxiv)
            hits.append(SeedHit(
                arxiv=arxiv,
                title=f"arXiv:{arxiv}",
                authors=[],
                why=f"Shared by {user} in #{channel_name} ({when.isoformat()}) — seeded {today.isoformat()}",
            ))
    _write_all(hits, cfg, today, papers_dir)
    return hits


def _papers_dir(cfg) -> Path:
    root = cfg.expanded_roots[0] if cfg.expanded_roots else Path.cwd()
    return Path(cfg.papers_dir).expanduser() if cfg.papers_dir else root / "papers"


def _write_all(hits: list[SeedHit], cfg, today: date, papers_dir: Path | None) -> list[Path]:
    """Idempotent and never-editing: a note that already owns the id is SKIPPED
    entirely (a later seed never stamps provenance into a human's keep-stub); a
    new note is scaffolded and immediately stamped with its provenance."""
    from .keep import find_note_for_id

    papers = papers_dir or _papers_dir(cfg)
    written = []
    for hit in hits:
        if find_note_for_id(papers, hit.arxiv) is not None:
            continue
        candidate = KeepCandidate(arxiv=hit.arxiv, title=hit.title or f"arXiv:{hit.arxiv}", authors=hit.authors)
        path = scaffold_note(candidate, cfg, today, papers_dir=papers)
        _stamp_why(path, hit.why)
        written.append(path)
    return written


def _stamp_why(path: Path, why: str) -> None:
    """Fill the why of a note THIS seed just created (the keep template leaves it
    absent; the provenance is the deliberate touch that makes the seed taste)."""
    text = path.read_text()
    text = text.replace("status: staged\n", f'status: staged\nwhy: "{why}"\n', 1)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)

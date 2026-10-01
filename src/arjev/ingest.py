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

_API_URL = "https://export.arxiv.org/api/query?id_list={ids}&max_results=100"
_PLACEHOLDER_TITLE = "arXiv:{arxiv}"


def fetch_titles(arxiv_ids: list[str]) -> dict[str, str]:
    """Resolve real titles from the arXiv API (batch id_list query — one call for
    the whole seed). Fail-open: unresolved ids map to nothing, the placeholder
    stands, and the backfill command can retry later."""
    import xml.etree.ElementTree as ET

    import httpx

    titles: dict[str, str] = {}
    for chunk in [arxiv_ids[i : i + 50] for i in range(0, len(arxiv_ids), 50)]:
        try:
            with httpx.Client(timeout=30, headers={"user-agent": "arjev/0.2 (harmoniqs/arJev)"}) as client:
                xml = client.get(_API_URL.format(ids=",".join(chunk))).text
            root = ET.fromstring(xml)
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.findall(f"{ns}entry"):
                arxiv = (entry.findtext(f"{ns}id") or "").rsplit("abs/", 1)[-1].split("v")[0]
                title = " ".join((entry.findtext(f"{ns}title") or "").split())
                if arxiv and title:
                    titles[arxiv] = title
        except (httpx.HTTPError, ET.ParseError):
            continue
    return titles


_PLACEHOLDER_LINE = re.compile(r'^title: "arXiv:([0-9]{4}\.[0-9]{4,5})"$', re.MULTILINE)


def backfill_titles(papers_dir: Path, limit: int = 100) -> int:
    """The human-invoked repair for placeholder-titled seeds: fetch real titles
    from the arXiv API and write them into notes whose title line is EXACTLY the
    placeholder. Never touches a human-written title."""
    candidates: list[tuple[Path, str]] = []
    for note in sorted(papers_dir.glob("*.md")):
        m = _PLACEHOLDER_LINE.search(note.read_text(errors="replace"))
        if m:
            candidates.append((note, m.group(1)))
    if not candidates:
        return 0
    titles = fetch_titles([arxiv for _, arxiv in candidates][:limit])
    fixed = 0
    for note, arxiv in candidates:
        title = titles.get(arxiv)
        if not title:
            continue
        text = note.read_text()
        updated = _PLACEHOLDER_LINE.sub(f'title: "{title.replace(chr(34), chr(39))}"', text, count=1)
        if updated != text:
            tmp = note.with_suffix(".tmp")
            tmp.write_text(updated)
            tmp.replace(note)
            fixed += 1
    return fixed


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
    raw_ids: set[str] = set()
    pre_hits: list[SeedHit] = []
    for message in messages:
        if message.get("bot_id") or message.get("subtype"):
            continue
        user = users.get(message.get("user", "?"), message.get("user", "?"))
        text = message.get("text", "")
        ts = message.get("ts", "")
        when = date.fromtimestamp(float(ts.split(".")[0])) if ts else today
        for m in _ARXIV_IN_TEXT.finditer(text):
            arxiv = (m.group(1) or m.group(3) or "").lower()
            if arxiv and arxiv not in raw_ids:
                raw_ids.add(arxiv)
                pre_hits.append(SeedHit(
                    arxiv=arxiv, title="", authors=[],
                    why=f"Shared by {user} in #{channel_name} ({when.isoformat()}) — seeded {today.isoformat()}"))
    titles = fetch_titles(sorted(raw_ids)) if raw_ids else {}
    hits: list[SeedHit] = []
    for hit in pre_hits:
        hit.title = titles.get(hit.arxiv, f"arXiv:{hit.arxiv}")
        hits.append(hit)
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

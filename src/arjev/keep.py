"""`arjev keep`: one human action — a keep label row AND a staged vault stub.
The scaffold is new-file-only, atomic, idempotent; `rating` and `why` are ABSENT
(blank means absent — the roundtrip metric rejects empty-string stand-ins).
`arjev fetch` completes the library join (PDF acquisition)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .feed import ARXIV, Identity
from .ledger import Label, LabelLedger, now_ts

DEFAULT_TEMPLATE = """---
type: paper
arxiv: "{arxiv}"
title: "{title}"
authors: [{authors_yaml}]
date: {today}
date_read: {today}
status: staged
tags: [paper]
---

# {title}

Scaffolded by arjev on {today} from the daily digest — fill `rating` and `why`
to promote this note from staged (it contributes zero taste until then).
"""

# the fetch path is arXiv-only: both id forms the RSS grammar produces, vN allowed
_ARXIV_FETCH_FORM = re.compile(r"^([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(v\d+)?$", re.IGNORECASE)


@dataclass
class KeepCandidate:
    arxiv: str
    title: str
    authors: list[str]
    source: str = ARXIV  # identity.source — the half a future source adapter fills

    def __post_init__(self) -> None:
        # normalize-at-parse: the pair is normalized where the candidate is born
        self.source = self.source.strip().lower()

    @property
    def identity(self) -> Identity:
        return Identity(self.source, self.arxiv)


def _slugify(title: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:limit].strip("-") or "untitled"


def load_template(cfg) -> str:
    if cfg.note_template and Path(cfg.note_template).expanduser().is_file():
        return Path(cfg.note_template).expanduser().read_text()
    return DEFAULT_TEMPLATE


def find_note_for_id(papers_dir: Path, arxiv: str) -> Path | None:
    """The note that already owns this id, if any (the seed's never-edit guard).
    `arxiv` is a vault-side bare id — both sides of this compare live in the
    arxiv namespace of the identity pair."""
    for existing in papers_dir.glob("*.md"):
        if _identity_of(existing.read_text(errors="replace")) == arxiv:
            return existing
    return None


def scaffold_note(candidate: KeepCandidate, cfg, today: date, papers_dir: Path | None = None) -> Path:
    """Write the staged stub. Idempotent: an existing note for the identity is
    returned as-is (never edit an existing note — obligation: write safety)."""
    papers_dir = papers_dir or _papers_dir(cfg)
    target = papers_dir / f"paper-{today:%Y%m%d}-{_slugify(candidate.title)}.md"
    if target.exists():
        return target
    for existing in papers_dir.glob("*.md"):
        # the vault note's `arxiv:` field is the arxiv namespace — join on the pair:
        # a same-id candidate from a different source is a different paper
        note_id = _identity_of(existing.read_text(errors="replace"))
        if note_id and Identity(ARXIV, note_id) == candidate.identity:
            return existing  # a note already owns this identity — never a second one
    authors_yaml = ", ".join(f'"{a}"' for a in candidate.authors)
    content = load_template(cfg).format(
        arxiv=candidate.identity.id,  # the stub's `arxiv:` field persists the identity's id half
        title=candidate.title.replace('"', "'"),
        authors_yaml=authors_yaml,
        today=today.isoformat(),
    )
    assert "rating:" not in content and "why:" not in content, "the stub must leave rating/why absent"
    papers_dir.mkdir(parents=True, exist_ok=True)
    tmp = papers_dir / f".{target.name}.tmp"
    tmp.write_text(content)
    tmp.replace(target)
    return target


def _papers_dir(cfg) -> Path:
    root = cfg.expanded_roots[0] if cfg.expanded_roots else Path.cwd()
    return Path(cfg.papers_dir).expanduser() if cfg.papers_dir else root / "papers"


def _identity_of(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    m = re.search(r'^arxiv:\s*"?(2601\.\d{4,5}|[0-9]{4}\.[0-9]{4,5})"?\s*$', text[4:end], re.MULTILINE)
    return m.group(1) if m else None


def keep(candidate: KeepCandidate, ledger: LabelLedger, cfg, today: date) -> Path:
    """The keep gesture: one label row, one stub. Idempotent on both."""
    scaffold_note(candidate, cfg, today)
    # the ledger row persists the identity's id half (frozen schema)
    ledger.append(Label(arxiv_id=candidate.identity.id, label_type="keep", source="cli-keep", ts=now_ts()))
    return _papers_dir(cfg) / f"paper-{today:%Y%m%d}-{_slugify(candidate.title)}.md"


def fetch_pdf(arxiv: str, library_dir: Path, fetcher: Callable[[str], bytes] | None = None) -> Path:
    """Download the arXiv PDF into the content-addressed library (the acquisition
    half of the record↔PDF join). The fetch path is arXiv-only and errors loudly on
    anything else — a future source adapter owns its own fetcher and never rides
    this one silently. The extracted .txt is emitted alongside (best-effort, the
    paper_content ladder consumes it); extraction failure never fails the fetch."""
    if not _ARXIV_FETCH_FORM.match(arxiv.strip()):
        raise ValueError(f"fetch is arXiv-only — {arxiv!r} is not an arXiv id (source adapters own their fetchers)")
    library_dir.mkdir(parents=True, exist_ok=True)
    target = library_dir / f"arxiv-{arxiv}.pdf"
    if target.exists():
        return target
    fetcher = fetcher or _http_fetch
    target.write_bytes(fetcher(f"https://export.arxiv.org/pdf/{arxiv}"))
    from .paper_content import pdf_text, write_library_text

    text = pdf_text(target)
    if text:
        write_library_text(library_dir, arxiv, text)
    return target


def _http_fetch(url: str) -> bytes:
    import httpx

    with httpx.Client(timeout=60, follow_redirects=True, headers={"user-agent": "arjev/0.1"}) as client:
        return client.get(url).content

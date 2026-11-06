"""The cited-by-me seed (issue #122): what a researcher's own papers cite is the
strongest record of their taste. Input is a BibTeX export of THEIR OWN papers (the
Google Scholar "My profile → select → Export → BibTeX" human step — a file the user
provides, never a scrape). Each paper's reference list comes from the Semantic
Scholar Graph API — documented, free without a key, paced, fail-open.

Every cited work with an arXiv id or DOI becomes one staged note whose why-line is
the printed fact of the citation ("Cited in your paper “…”"), never an inferred
reason (ADR 0002); the researcher's own papers are staged too, marked authored. The
contract is the other seeds' (ingest.py): new files only, idempotent (a work any
root already holds — by arXiv id OR DOI — is skipped, never edited), and anything
unresolved is counted and reported, never silently dropped."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

API = "https://api.semanticscholar.org/graph/v1"
REF_FIELDS = "title,externalIds,authors"
PACE_S = 1.1  # the unauthenticated limit is ~1 request/s, shared
MAX_RETRIES = 3

_ARXIV_ID = re.compile(r"(?:arxiv[:\s/]*|abs/)([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(?:v\d+)?", re.IGNORECASE)
_BARE_ARXIV = re.compile(r"^([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(?:v\d+)?$", re.IGNORECASE)
_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]*)\s*,(.*?)\n\}", re.DOTALL)
_FIELD = re.compile(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)\s*,?", re.DOTALL)


# ── the researcher's own export ──────────────────────────────────────────────────

@dataclass
class OwnPaper:
    title: str
    kind: str = "article"
    arxiv: str | None = None
    doi: str | None = None


def parse_own_papers(text: str) -> list[OwnPaper]:
    """Every titled entry of any type (articles, theses, proceedings). Scholar's
    export rarely carries a DOI and puts an arXiv id in `journal`, so ids are read
    from eprint, doi, url, and any field printing `arXiv:<id>`."""
    papers: list[OwnPaper] = []
    for kind, _key, body in _ENTRY.findall(text):
        fields = {name.lower(): _clean(value) for name, value in _FIELD.findall(body)}
        title = fields.get("title")
        if not title:
            continue
        arxiv = None
        eprint = fields.get("eprint", "")
        if (m := _BARE_ARXIV.match(eprint)) is not None:
            arxiv = m.group(1).lower()
        else:
            for value in fields.values():
                if (m := _ARXIV_ID.search(value)) is not None:
                    arxiv = m.group(1).lower()
                    break
        doi = _normalize_doi(fields.get("doi"))
        if doi and doi.lower().startswith("10.48550/arxiv."):  # arXiv's own DOI is the arXiv id
            arxiv = arxiv or doi.split(".", 2)[-1].lower()
            doi = None
        papers.append(OwnPaper(title=title, kind=kind.lower(), arxiv=arxiv, doi=doi))
    return papers


def _clean(value: str) -> str:
    value = value.strip()
    if value[:1] in "{\"" and value[-1:] in "}\"":
        value = value[1:-1]
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.IGNORECASE)
    return doi or None


# ── the Semantic Scholar Graph API ───────────────────────────────────────────────

def s2_key() -> str | None:
    """Optional: ARJEV_S2_KEY_FILE (a mode-600 file) for a higher rate limit."""
    path = os.environ.get("ARJEV_S2_KEY_FILE")
    if not path:
        return None
    try:
        return Path(path).expanduser().read_text().strip() or None
    except OSError:
        return None


class S2Client:
    """References and exact-title resolution. Paced (≤ 1 request per pace_s),
    429/5xx retried with backoff; a lookup that still fails returns None — the
    caller reports it, the run continues."""

    def __init__(self, http_transport=None, sleep: Callable[[float], None] = time.sleep,
                 key: str | None = None, pace_s: float = PACE_S, page: int = 1000) -> None:
        self._transport = http_transport
        self._sleep = sleep
        self._key = key
        self._pace = pace_s
        self._page = page
        self._last = 0.0

    def _get(self, path: str, params: dict) -> dict | None:
        import httpx

        headers = {"user-agent": "arjev (harmoniqs/arJev)"}
        if self._key:
            headers["x-api-key"] = self._key
        for attempt in range(MAX_RETRIES + 1):
            wait = self._last + self._pace - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                with httpx.Client(timeout=30, headers=headers, transport=self._transport) as client:
                    r = client.get(f"{API}{path}", params=params)
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code == 200:
                return r.json()
            if r is not None and r.status_code == 404:
                return None
            if attempt < MAX_RETRIES:
                self._sleep(2.0 ** attempt)
        return None

    def references(self, ref: str) -> list[dict] | None:
        """Every reference of one paper (`ARXIV:<id>`, `DOI:<doi>`, or a paperId),
        paginated. None when the paper cannot be resolved."""
        out: list[dict] = []
        offset = 0
        while True:
            body = self._get(f"/paper/{ref}/references",
                             {"fields": REF_FIELDS, "offset": offset, "limit": self._page})
            if body is None:
                return None if offset == 0 else out
            out += [row.get("citedPaper") or {} for row in body.get("data") or []]
            if body.get("next") is None:
                return out
            offset = int(body["next"])

    def match_title(self, title: str) -> dict | None:
        """The API's best title match — accepted only when the titles are equal
        after normalization; a near miss is somebody else's paper."""
        body = self._get("/paper/search/match", {"query": title, "fields": "title,externalIds"})
        hits = (body or {}).get("data") or []
        if hits and _norm_title(hits[0].get("title") or "") == _norm_title(title):
            return hits[0]
        return None


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


# ── the seed ────────────────────────────────────────────────────────────────────

@dataclass
class _Work:
    arxiv: str | None
    doi: str | None
    title: str
    authors: list[str]
    citers: list[str] = field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        return {k for k in (self.arxiv and f"arxiv:{self.arxiv}", self.doi and f"doi:{self.doi.lower()}") if k}


@dataclass
class CitedReport:
    cited_seeded: int = 0
    authored_seeded: int = 0
    already_present: int = 0
    no_identifier: int = 0
    unresolved: list[str] = field(default_factory=list)  # own-paper titles
    written: list[Path] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [f"cited-by-me: {self.cited_seeded} cited works and {self.authored_seeded} of your papers seeded "
                 f"({self.already_present} already in the vault, never edited)"]
        if self.unresolved:
            noun = "paper" if len(self.unresolved) == 1 else "papers"
            lines.append(f"cited-by-me: {len(self.unresolved)} own {noun} unresolved: "
                         + "; ".join(self.unresolved))
        if self.no_identifier:
            noun = "work" if self.no_identifier == 1 else "works"
            lines.append(f"cited-by-me: {self.no_identifier} cited {noun} without an arXiv id or DOI (not seeded)")
        return lines


def ingest_cited_by_me(path: Path, cfg, today: date, papers_dir: Path | None = None,
                       client: S2Client | None = None) -> CitedReport:
    from .fold import fold_roots
    from .ingest import _papers_dir

    papers = Path(papers_dir) if papers_dir else _papers_dir(cfg)
    client = client or S2Client(key=s2_key())
    report = CitedReport()
    authored: dict[str, _Work] = {}
    cited: dict[str, _Work] = {}
    alias: dict[str, str] = {}  # every key of a work → its canonical key

    def add(bucket: dict[str, _Work], work: _Work, citer: str | None) -> None:
        canonical = next((alias[k] for k in work.keys if k in alias), None)
        if canonical is None or canonical not in bucket:
            canonical = sorted(work.keys)[0]
            bucket[canonical] = work
        target = bucket[canonical]
        target.arxiv = target.arxiv or work.arxiv
        target.doi = target.doi or work.doi
        for k in target.keys:
            alias[k] = canonical
        if citer and citer not in target.citers:
            target.citers.append(citer)

    for own in parse_own_papers(Path(path).read_text(errors="replace")):
        arxiv, doi, ref = own.arxiv, own.doi, None
        if arxiv:
            ref = f"ARXIV:{arxiv}"
        elif doi:
            ref = f"DOI:{doi}"
        else:
            hit = client.match_title(own.title)
            if hit is not None:
                ext = hit.get("externalIds") or {}
                arxiv, doi = _ids(ext)
                ref = hit.get("paperId")
        refs = client.references(ref) if ref else None
        if refs is None:
            report.unresolved.append(own.title)
            continue
        if arxiv or doi:
            add(authored, _Work(arxiv, doi, own.title, []), None)
        for paper in refs:
            r_arxiv, r_doi = _ids(paper.get("externalIds") or {})
            if not (r_arxiv or r_doi):
                report.no_identifier += 1
                continue
            authors = [a.get("name") for a in paper.get("authors") or [] if a.get("name")]
            add(cited, _Work(r_arxiv, r_doi, paper.get("title") or "", authors), own.title)

    roots = list(cfg.expanded_roots)
    if papers.is_dir() and not any(papers.resolve().is_relative_to(r.resolve()) for r in roots):
        roots.append(papers)  # a papers dir outside every root still owns its ids
    existing = {p.identity.lower() for p in fold_roots(roots, cfg).papers}
    source = Path(path).name
    for kind, bucket in (("authored", authored), ("cited", cited)):
        for work in bucket.values():
            if work.keys & existing:
                report.already_present += 1
                continue
            if kind == "authored":
                why = f"Your paper (seeded from {source}, {today.isoformat()})"
            else:
                noun = "paper" if len(work.citers) == 1 else "papers"
                why = (f"Cited in your {noun} " + "; ".join(f"“{_safe(t)}”" for t in work.citers)
                       + f" — seeded {today.isoformat()}")
            report.written.append(_write_note(work, kind, why, cfg, today, papers))
            existing |= work.keys
            if kind == "authored":
                report.authored_seeded += 1
            else:
                report.cited_seeded += 1
    return report


def _ids(ext: dict) -> tuple[str | None, str | None]:
    arxiv = ext.get("ArXiv")
    doi = _normalize_doi(ext.get("DOI"))
    if doi and doi.lower().startswith("10.48550/arxiv."):
        arxiv = arxiv or doi.split(".", 2)[-1]
        doi = None
    return (arxiv.lower() if arxiv else None), doi


def _safe(text: str) -> str:
    """A double-quoted YAML scalar carries the why: no quotes or backslashes inside."""
    return " ".join(text.replace('"', "'").replace("\\", "/").split())


def _write_note(work: _Work, kind: str, why: str, cfg, today: date, papers: Path) -> Path:
    """A new note only — the filename never collides with an existing file (a
    clash gets a numeric suffix), and nothing that exists is ever opened for write."""
    from .keep import DEFAULT_TEMPLATE, _slugify, load_template

    title = _safe(work.title) or (f"arXiv:{work.arxiv}" if work.arxiv else f"doi:{work.doi}")
    template = load_template(cfg) if work.arxiv else DEFAULT_TEMPLATE.replace('arxiv: "{arxiv}"', 'doi: "{arxiv}"')
    content = template.format(
        arxiv=work.arxiv or work.doi,
        title=title,
        authors_yaml=", ".join(f'"{_safe(a)}"' for a in work.authors),
        today=today.isoformat(),
    )
    if work.arxiv and work.doi and "\ndoi:" not in content:
        content = content.replace(f'arxiv: "{work.arxiv}"\n', f'arxiv: "{work.arxiv}"\ndoi: "{work.doi}"\n', 1)
    content = content.replace("status: staged\n", f'status: staged\nseed: {kind}\nwhy: "{_safe(why)}"\n', 1)
    papers.mkdir(parents=True, exist_ok=True)
    stem = f"paper-{today:%Y%m%d}-{_slugify(title)}"
    target, n = papers / f"{stem}.md", 2
    while target.exists():
        target, n = papers / f"{stem}-{n}.md", n + 1
    tmp = papers / f".{target.name}.tmp"
    tmp.write_text(content)
    tmp.replace(target)
    return target

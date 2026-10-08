"""The paper's own words — abstract and conclusions/outlook excerpts — for the taste
cards (the corpus half of the Jev state) and finalist enrichment (the candidate half).

Digest-time reads are LOCAL-ONLY (the fold/profile never touch the network — the
digest stays deterministic and hermetic); the network lives behind the explicit
human/agent paths (`arjev fetch`, `arjev backfill`, the finalist enrichment cache):

- corpus: library text (arxiv-<id>.txt beside the PDF) → PDF extraction (the .txt is
  written back so the cost is paid once) → the sections cache (backfill's arXiv API
  abstract floor) → nothing (the card rides with why/title only).
- candidates: the state-dir sections cache → a polite PDF fetch → nothing.

Conclusions extraction is tolerant of heading conventions: Conclusion(s), Summary,
Outlook, Discussion, Perspectives, compound forms ("6 Summary and outlook"), with
References/Acknowledgments as the section terminator. Every path fails open —
missing content never blocks a digest."""

from __future__ import annotations

import json
import re
from pathlib import Path

ABSTRACT_CHARS = 400
CONCLUSIONS_CHARS = 450
CANDIDATE_CONCLUSIONS_CHARS = 600
_MIN_SECTION_CHARS = 40  # a shorter "conclusions" body is a heading misfire, not a section

_CONCLUSIONS_HEADING = re.compile(
    r"^\s*(?:\(?\d+[.)]?\s*|[IVX]+\.?\s*|•\s*)?"
    r"(conclusions?|concluding remarks|summary\s+and\s+outlook|summary|outlook|"
    r"discussion|perspectives?)\s*[:.\-—]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SECTION_END = re.compile(
    r"^\s*(?:\(?\d+[.)]?\s*|[IVX]+\.?\s*)?(references|acknowledgments?|acknowledgements?|appendix|bibliography|supplementary)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ABSTRACT_HEADING = re.compile(r"(?im)^\s*abstract\s*[:.\-—]?\s*$|^\s*abstract\s*[:.\-—]\s*")
_INTRODUCTION = re.compile(r"(?im)^\s*(?:\(?\d+[.)]\s*)?introduction\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_abstract(text: str, cap: int = ABSTRACT_CHARS) -> str | None:
    m = _ABSTRACT_HEADING.search(text)
    if not m:
        return None
    rest = text[m.end():]
    end = _INTRODUCTION.search(rest)
    body = _norm(rest[: end.start()] if end else rest)
    return body[:cap] or None


def extract_conclusions(text: str, cap: int = CONCLUSIONS_CHARS) -> str | None:
    """First matching heading wins (papers occasionally summarize per-section); the
    body runs until the next section-ending heading. Short bodies are heading
    misfires (a lone 'Summary' in a table of contents) and are rejected."""
    for m in _CONCLUSIONS_HEADING.finditer(text):
        rest = text[m.end():]
        stop = _SECTION_END.search(rest)
        body = _norm(rest[: stop.start()] if stop else rest)
        if len(body) >= _MIN_SECTION_CHARS:
            return body[:cap]
    return None


# ── PDF text (fail-open: pypdf is a best-effort seam, never a requirement) ─────────


def pdf_text(data: bytes | Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(data if isinstance(data, Path) else __import__("io").BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


_ID_IN_STEM = re.compile(r"arxiv-([0-9]{4}\.[0-9]{4,5}|[a-z-]+-\d{7}|[a-z-]+/\d{7})$", re.IGNORECASE)
_ID_DASHED = re.compile(r"arxiv-([0-9]{4})-([0-9]{4,5})$", re.IGNORECASE)  # the dot-flattened .txt form


def id_from_library_stem(stem: str) -> str | None:
    m = _ID_IN_STEM.match(stem)
    if m:
        return m.group(1).lower()
    m = _ID_DASHED.match(stem)
    return f"{m.group(1)}.{m.group(2)}".lower() if m else None


def write_library_text(library_dir: Path, arxiv: str, text: str) -> Path:
    """The library .txt convention: arxiv-<id>.txt beside the PDF, atomic."""
    target = library_dir / f"arxiv-{arxiv}.txt"
    tmp = library_dir / f".{target.name}.tmp"
    tmp.write_text(text)
    tmp.replace(target)
    return target


# ── sections cache (the API abstract floor + the candidate cache) ─────────────────


def sections_cache_dir() -> Path:
    import os

    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))
    return Path(base) / "arjev" / "paper-content"


def read_sections_cache(arxiv: str, cache_dir: Path | None = None) -> dict:
    path = (cache_dir or sections_cache_dir()) / f"{_cache_stem(arxiv)}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_sections_cache(arxiv: str, sections: dict, cache_dir: Path | None = None) -> Path:
    # slash-form ids (math/9701001) must stay flat filenames — the real id rides
    # inside the JSON so the corpus resolution can key by it, never by the slug
    path = (cache_dir or sections_cache_dir()) / f"{_cache_stem(arxiv)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**sections, "arxiv": arxiv}, sort_keys=True))
    tmp.replace(path)
    return path


def _cache_stem(arxiv: str) -> str:
    return arxiv.replace("/", "-")


# ── the corpus half: local-only resolution at digest time ─────────────────────────


def corpus_content(cfg) -> dict[str, dict]:
    """{arxiv: {abstract, conclusions}} for every locally-known paper — no network.
    The two sources MERGE per id (issue #79: a library hit with conclusions but no
    abstract must never discard the cache's canonical API abstract): the cache
    supplies the abstract of record, the library text supplies the conclusions.
    A PDF without its .txt pays extraction once and writes it back."""
    out: dict[str, dict] = {}
    cache_dir = sections_cache_dir()
    for cached in cache_dir.glob("*.json"):
        data = read_sections_cache(cached.stem, cache_dir)
        if not (data.get("abstract") or data.get("conclusions")):
            continue
        # the id of record rides inside the JSON — a slug never becomes the join key
        out[data.get("arxiv", cached.stem)] = {k: data.get(k) for k in ("abstract", "conclusions")}
    library = Path(cfg.library_dir).expanduser() if cfg.library_dir else None
    if library is None:
        return out
    seen: set[str] = set()
    for entry in sorted(list(library.glob("arxiv-*.txt")) + list(library.glob("arxiv-*.pdf"))):
        arxiv = id_from_library_stem(entry.stem)
        if arxiv is None or arxiv in seen:
            continue
        seen.add(arxiv)
        text = ensure_library_text(library, arxiv)
        if text is None:
            continue
        # per-field precedence: the cache's abstract is canonical (the API's); the
        # library's conclusions are fresher than a stale cache entry's
        cached_entry = out.get(arxiv, {})
        merged = {
            "abstract": cached_entry.get("abstract") or extract_abstract(text),
            "conclusions": extract_conclusions(text) or cached_entry.get("conclusions"),
        }
        merged = {k: v for k, v in merged.items() if v}
        if merged:
            out[arxiv] = merged
    return out


def ensure_library_text(library: Path, arxiv: str) -> str | None:
    """The library text for a paper, paying extraction exactly once: read the .txt
    (both on-disk conventions) if present, else extract from the PDF and write it
    back. Digest and fetch/backfill share this seam, so a pre-feature PDF gains its
    .txt on first touch from either side."""
    for txt in (library / f"arxiv-{arxiv}.txt", library / f"arxiv-{arxiv.replace('.', '-')}.txt"):
        if txt.is_file():
            return txt.read_text(errors="replace")
    text = pdf_text(library / f"arxiv-{arxiv}.pdf")
    if text:
        write_library_text(library, arxiv, text)
    return text


# ── the candidate half: cache-first, polite fetch, state-dir only ─────────────────


def candidate_conclusions(
    arxiv: str, cache_dir: Path | None = None, fetcher=None, cap: int = CANDIDATE_CONCLUSIONS_CHARS
) -> str | None:
    """Conclusions excerpt for a feed candidate. Cached excerpts are reused; a miss
    fetches the PDF, extracts, and caches — successes only, so a transient failure
    retries tomorrow. Transport and parse failures are caught HERE (the fetch is the
    one network surface on the digest path — a dead proxy must never kill a digest;
    it fails open to None like every other content miss). The PDF itself is never
    stored: the library stays keep-only."""
    cache_dir = cache_dir or sections_cache_dir()
    cached = read_sections_cache(arxiv, cache_dir)
    if cached.get("conclusions"):
        return cached["conclusions"]
    if fetcher is None:
        from .keep import _http_fetch

        fetcher = _http_fetch
    try:
        text = pdf_text(fetcher(f"https://export.arxiv.org/pdf/{arxiv}"))
    except Exception:
        return None  # transport/parse fail-open: cache nothing, retry tomorrow
    conclusions = extract_conclusions(text, cap) if text else None
    if conclusions:
        write_sections_cache(arxiv, {**cached, "conclusions": conclusions}, cache_dir)
    return conclusions


def paced_conclusions(ids, cache_dir: Path | None = None, pace_s: float = 3.0, sleep=None,
                      fetcher=None) -> dict[str, str]:
    """The single politeness seam both call sites route through (digest enrichment,
    replay-arms warming): cache hits are free, sleeps come ONLY after real fetch
    attempts — success or failure, the arXiv hit happened. Fail-open per id."""
    import time

    sleep = sleep or time.sleep
    out: dict[str, str] = {}
    for i, arxiv in enumerate(ids):
        cached = read_sections_cache(arxiv, cache_dir).get("conclusions")
        if cached is not None:
            out[arxiv] = cached
            continue
        conclusions = candidate_conclusions(arxiv, cache_dir, fetcher=fetcher)
        if conclusions:
            out[arxiv] = conclusions
        if i < len(ids) - 1:
            sleep(pace_s)
    return out


# ── the backfill: the explicit network path for corpus papers ─────────────────────


def backfill_corpus(cfg, pace_s: float = 3.0, fetcher=None, sleep=None, fetch_meta=None) -> dict:
    """The explicit network path for corpus content. Two jobs, in order:

    1. Canonical abstracts: the abstract of record is the arXiv API's, not a PDF
       extraction's (pypdf usually drops the standalone "Abstract" heading — the
       live backfill resolved 1 abstract per 12 texts). One batched call stamps the
       API abstract into the sections cache for every corpus id lacking one.
    2. Library text: fetch every paper missing its .txt (PDF + extraction), the
       conclusions source. Paced, idempotent, fail-open per paper.

    Returns {"abstracts_stamped", "fetched", "failed", "n_corpus"}. The digest never
    calls this — backfill is an explicit human/agent command."""
    import time

    from .fold import fold_roots
    from .ingest import fetch_metadata

    fetch_meta = fetch_meta or fetch_metadata
    sleep = sleep or time.sleep
    fold = fold_roots(cfg.expanded_roots, cfg)
    library = Path(cfg.library_dir).expanduser() if cfg.library_dir else None
    if library is None:
        raise SystemExit("library_dir not configured — backfill needs a library to fetch into")
    all_ids = sorted(fold.arxiv_ids())
    # 1 — canonical abstracts: only the ids still missing one ride the batched call
    # (a fully-stamped corpus makes an idempotent backfill do zero network)
    need = [a for a in all_ids if not read_sections_cache(a).get("abstract")]
    meta = fetch_meta(need) if need else {}
    abstracts_stamped = 0
    for arxiv in need:
        abstract = (meta.get(arxiv) or {}).get("abstract")
        if abstract:
            write_sections_cache(arxiv, {"abstract": abstract[:ABSTRACT_CHARS]})
            abstracts_stamped += 1
    # 2 — library text for the papers missing it
    from .keep import fetch_pdf

    missing = sorted(
        arxiv for arxiv in all_ids
        if not (library / f"arxiv-{arxiv}.txt").is_file()
        and not (library / f"arxiv-{arxiv.replace('.', '-')}.txt").is_file()
    )
    fetched, failed = [], []
    for i, arxiv in enumerate(missing):
        if i:
            sleep(pace_s)
        try:
            fetch_pdf(arxiv, library, fetcher=fetcher)
            fetched.append(arxiv)
        except Exception:
            failed.append(arxiv)
    return {"abstracts_stamped": abstracts_stamped, "fetched": fetched, "failed": failed,
            "n_corpus": len(fold.papers)}

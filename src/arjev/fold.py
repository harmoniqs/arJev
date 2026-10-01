"""The vault fold: read every candidate note under the configured roots, split paper
notes from non-paper notes, apply the schema-v2 contract, and expose the wikilink graph.

Spec contracts honored here:
- identity: first present of the mapped identity fields (default arxiv, then doi);
  arXiv ids are normalized (vN stripped) once, here — every persisted record stores
  normalized ids (obligation #6).
- back-compat: a literal `relevance` field reads as `rating` when enum-valued, else as
  `why`; an explicit mapped `why` wins over prose `relevance`, and the ignored prose is
  reported as a fold warning (obligation #15).
- date ladder: mapped read_date → mapped `date` → file mtime → None (weight 1) (#4).
- staged gate: an untouched staged note (mapped why AND rating absent) carries zero
  taste — flagged here, enforced by the profile.
- wikilink signal: a paper note's term weights scale by (1 + 0.5 × min(3, inlinks))
  where an inlink is a wikilink from a NON-PAPER note (no mapped identity) (#16).
- "blank" means ABSENT: a rating outside the closed enum is dropped with a warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

RATING_ENUM = {"core", "useful", "marginal"}
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_ARXIV_FORM = re.compile(r"^(?:arxiv:)?([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})(v\d+)?$", re.IGNORECASE)


@dataclass
class PaperNote:
    file: Path
    title: str
    identity: str  # "arxiv:2601.01001" or "doi:10.…" — normalized
    arxiv: str | None
    read_date: date | None
    rating: str | None
    why: str | None
    tags: list[str]
    status: str  # "staged" | "distilled" (absent = distilled)
    body: str
    basename: str  # filename without .md — the wikilink target
    touched: bool  # human filled why or set rating (the staged gate's trigger)
    inlinks: int = 0

    @property
    def contributes_taste(self) -> bool:
        return not (self.status == "staged" and not self.touched)


@dataclass
class FoldResult:
    papers: list[PaperNote] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def arxiv_ids(self) -> set[str]:
        return {p.arxiv for p in self.papers if p.arxiv}


def normalize_arxiv(raw: str) -> str:
    m = _ARXIV_FORM.match(raw.strip())
    return m.group(1).lower() if m else raw.strip()


def wikilink_targets(body: str) -> set[str]:
    return {m.strip() for m in _WIKILINK.findall(body) if m.strip()}


def _parse_frontmatter(text: str) -> tuple[dict, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4 : end]) or {}
    except yaml.YAMLError:
        return None
    return (fm if isinstance(fm, dict) else {}), text[end + 5 :]


def _identity(fm: dict, fields: dict) -> tuple[str | None, str | None]:
    """(identity, arxiv) — first present mapped identity field wins."""
    for f in fields["identity"]:
        v = fm.get(f)
        if isinstance(v, str) and v.strip():
            value = v.strip()
            if f.lower() == "arxiv":
                normalized = normalize_arxiv(value)
                return f"arxiv:{normalized}", normalized
            return f"{f.lower()}:{value}", None
    return None, None


def _as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip()[:10])
        except ValueError:
            return None
    return None


def _date_from_mtime(path: Path) -> date | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return None


def _build_paper(
    fm: dict, body: str, path: Path, identity: str, arxiv: str | None, cfg, warnings: list[str]
) -> PaperNote:
    fields = cfg.fields
    rating = fm.get(fields["rating"])
    rating = rating.strip() if isinstance(rating, str) else None
    why = fm.get(fields["why"])
    why = why.strip() if isinstance(why, str) and why.strip() else None
    # back-compat: the literal legacy `relevance` field (only when not itself remapped)
    if fields["rating"] != "relevance" and fields["why"] != "relevance":
        legacy = fm.get("relevance")
        if isinstance(legacy, str) and legacy.strip():
            legacy = legacy.strip()
            if rating is None and legacy in RATING_ENUM:
                rating = legacy
            elif why is None:
                why = legacy
            else:
                warnings.append(f"{path.name}: prose `relevance` ignored — explicit `{fields['why']}` wins")
    if rating is not None and rating not in RATING_ENUM:
        warnings.append(f"{path.name}: rating {rating!r} outside enum — dropped")
        rating = None
    read_date = _as_date(fm.get(fields["read_date"])) or _as_date(fm.get("date")) or _date_from_mtime(path)
    status = fm.get(fields["status"])
    status = status.strip().lower() if isinstance(status, str) else "distilled"
    tags = fm.get(fields["tags"]) or []
    if isinstance(tags, str):
        tags = [tags]
    return PaperNote(
        file=path,
        title=str(fm.get("title") or path.stem),
        identity=identity,
        arxiv=arxiv,
        read_date=read_date,
        rating=rating,
        why=why,
        tags=[str(t).strip() for t in tags if str(t).strip()],
        status="staged" if status == "staged" else "distilled",
        body=body,
        basename=path.stem,
        touched=why is not None or rating is not None,
    )


def fold_roots(roots: list[Path], cfg) -> FoldResult:
    """Fold every configured root into one result. Read-only; missing roots warn."""
    result = FoldResult()
    nonpaper_bodies: list[str] = []
    for root in roots:
        if not root.is_dir():
            result.warnings.append(f"vault root missing: {root}")
            continue
        for path in sorted(root.glob(cfg.include)):
            if not path.is_file() or path.suffix != ".md":
                continue
            text = path.read_text(errors="replace")
            fm_body = _parse_frontmatter(text)
            if fm_body is None:
                nonpaper_bodies.append(text)
                continue
            fm, body = fm_body
            identity, arxiv = _identity(fm, cfg.fields)
            if identity is None:
                nonpaper_bodies.append(body)
                continue
            result.papers.append(_build_paper(fm, body, path, identity, arxiv, cfg, result.warnings))
    _apply_wikilink_graph(result, nonpaper_bodies)
    seen: set[str] = set()
    deduped: list[PaperNote] = []
    for p in result.papers:
        if p.identity in seen:
            result.warnings.append(f"duplicate identity {p.identity}: {p.file.name} (kept first)")
            continue
        seen.add(p.identity)
        deduped.append(p)
    result.papers = deduped
    return result


def _apply_wikilink_graph(result: FoldResult, nonpaper_bodies: list[str]) -> None:
    by_basename = {p.basename: p for p in result.papers}
    for body in nonpaper_bodies:
        for target in wikilink_targets(body):
            if target in by_basename:
                by_basename[target].inlinks += 1

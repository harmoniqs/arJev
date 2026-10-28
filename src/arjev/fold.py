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
- per-root field mapping (issue #97): each root may carry its own field slots via
  cfg.root_configs; a root without an entry inherits the global cfg.fields mapping.
  A rating_values map in the RootConfig remaps source enum values to canonical ones.
  A sentence-valued rating/why field (when rating and why map to the same frontmatter
  key) is consumed as the why-line instead of triggering an 'outside enum' warning.
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
    scanned: int = 0  # every .md file examined under the roots (inspect's fold view)
    type_matched: int = 0  # frontmatter type == the configured discriminator (advisory signal)

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


def _effective_fields(cfg, root: Path) -> dict:
    """Resolve the effective field mapping for a root (issue #97).
    The root's own field overrides take precedence over the global mapping;
    a root with no RootConfig entry inherits the global mapping unchanged."""
    root_configs = getattr(cfg, "root_configs", {}) or {}
    rc = root_configs.get(str(root))
    if rc is None or not rc.fields:
        return cfg.fields
    # Merge: start from global, override with per-root entries.
    merged = dict(cfg.fields)
    merged.update(rc.fields)
    if isinstance(merged.get("identity"), str):
        merged["identity"] = [merged["identity"]]
    return merged


def _rating_values(cfg, root: Path) -> dict[str, str]:
    """Rating value map for this root (issue #97), or empty dict for no remapping."""
    root_configs = getattr(cfg, "root_configs", {}) or {}
    rc = root_configs.get(str(root))
    if rc is None:
        return {}
    return rc.rating_values or {}


def _build_paper(
    fm: dict,
    body: str,
    path: Path,
    identity: str,
    arxiv: str | None,
    cfg,
    warnings: list[str],
    *,
    fields: dict | None = None,
    rating_values: dict[str, str] | None = None,
) -> PaperNote:
    """Build a PaperNote from parsed frontmatter.

    `fields` and `rating_values` are the effective per-root overrides (issue #97);
    when absent they fall back to cfg.fields with no value remapping (back-compat).
    """
    if fields is None:
        fields = cfg.fields
    if rating_values is None:
        rating_values = {}

    rating_field = fields["rating"]
    why_field = fields["why"]
    same_field = (rating_field == why_field)  # e.g. both map to "relevance"

    raw_rating_val = fm.get(rating_field)
    raw_rating = raw_rating_val.strip() if isinstance(raw_rating_val, str) else None

    raw_why_val = fm.get(why_field)
    raw_why = raw_why_val.strip() if isinstance(raw_why_val, str) and raw_why_val.strip() else None

    rating: str | None = None
    why: str | None = None

    if same_field:
        # Rating and why come from the same frontmatter key.
        # Precedence: canonical enum > rating_values remap > sentence → why.
        # An empty string is invalid (blank = absent), not a sentence.
        val = raw_rating  # they point to the same key
        if val is not None:
            if not val:
                # empty string: outside enum, warn and drop
                warnings.append(f"{path.name}: rating '' outside enum — dropped")
            elif val in RATING_ENUM:
                rating = val
            elif val in rating_values:
                remapped = rating_values[val]
                if remapped in RATING_ENUM:
                    rating = remapped
                else:
                    # misconfigured value map — warn and drop
                    warnings.append(
                        f"{path.name}: rating_values maps {val!r} → {remapped!r} which is outside enum — dropped"
                    )
            else:
                # sentence-valued: treat as why-line (no 'outside enum' warning)
                why = val
    else:
        # Separate rating and why fields.
        if raw_rating is not None:
            if not raw_rating:
                # empty string: outside enum, warn and drop
                warnings.append(f"{path.name}: rating '' outside enum — dropped")
            elif raw_rating in RATING_ENUM:
                rating = raw_rating
            elif raw_rating in rating_values:
                remapped = rating_values[raw_rating]
                if remapped in RATING_ENUM:
                    rating = remapped
                else:
                    warnings.append(
                        f"{path.name}: rating_values maps {raw_rating!r} → {remapped!r} which is outside enum — dropped"
                    )
            else:
                # sentence-valued rating field with separate why field: treat as why if why is absent
                if raw_why is None:
                    why = raw_rating
                else:
                    # Both are present and rating isn't an enum value — drop rating with warning
                    warnings.append(f"{path.name}: rating {raw_rating!r} outside enum — dropped")

        if raw_why is not None and why is None:
            why = raw_why

    # back-compat: the literal legacy `relevance` field (only when not itself remapped by the
    # active fields — if rating or why already point to "relevance", the per-root mapping handles it)
    if rating_field != "relevance" and why_field != "relevance":
        legacy = fm.get("relevance")
        if isinstance(legacy, str) and legacy.strip():
            legacy = legacy.strip()
            if rating is None and legacy in RATING_ENUM:
                rating = legacy
            elif why is None:
                why = legacy
            else:
                warnings.append(f"{path.name}: prose `relevance` ignored — explicit `{why_field}` wins")

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
    """Fold every configured root into one result. Read-only; missing roots warn.
    Each root uses its own effective field mapping (issue #97): a root without a
    per-root entry in cfg.root_configs inherits the global cfg.fields unchanged."""
    result = FoldResult()
    nonpaper_bodies: list[str] = []
    for root in roots:
        if not root.is_dir():
            result.warnings.append(f"vault root missing: {root}")
            continue
        root_fields = _effective_fields(cfg, root)
        root_rating_values = _rating_values(cfg, root)
        for path in sorted(root.glob(cfg.include)):
            if not path.is_file() or path.suffix != ".md":
                continue
            result.scanned += 1
            text = path.read_text(errors="replace")
            fm_body = _parse_frontmatter(text)
            if fm_body is None:
                nonpaper_bodies.append(text)
                continue
            fm, body = fm_body
            if isinstance(fm.get("type"), str) and fm["type"].strip() == cfg.discriminator_type:
                result.type_matched += 1
            identity, arxiv = _identity(fm, root_fields)
            if identity is None:
                nonpaper_bodies.append(body)
                continue
            result.papers.append(_build_paper(
                fm, body, path, identity, arxiv, cfg, result.warnings,
                fields=root_fields, rating_values=root_rating_values,
            ))
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


def staged_worklist(fold: FoldResult, kept_by: dict[str, str] | None = None) -> list[str]:
    """The prose worklist (issue #56): one stable, greppable line per staged note —
    id, title, kept-when, kept-by — and nothing else. Read-only by construction.
    kept-when is the scaffold's own date (the ladder: read_date → date → mtime);
    kept_by maps arxiv id → the keep row's source (the label ledger's provenance) —
    an id without a keep row shows `-`. An empty worklist is an empty list, never
    an error; the staged → written flip is an ordinary frontmatter edit, so a
    written note simply stops matching here."""
    kept_by = kept_by or {}
    lines = []
    for note in fold.papers:
        if note.status != "staged":
            continue
        note_id = note.arxiv or note.identity
        kept_when = note.read_date.isoformat() if note.read_date else "-"
        lines.append(f"{note_id} | {note.title} | {kept_when} | {kept_by.get(note_id, '-')}")
    return lines


def _apply_wikilink_graph(result: FoldResult, nonpaper_bodies: list[str]) -> None:
    by_basename = {p.basename: p for p in result.papers}
    for body in nonpaper_bodies:
        for target in wikilink_targets(body):
            if target in by_basename:
                by_basename[target].inlinks += 1

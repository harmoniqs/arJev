"""Taste directives: authored preference, in English, living in the vault.
The fold's derived terms are generic bag-of-words — they cannot express
"Manchester-style control papers, hardware-tied QEC, papers from companies we
track." Jev reads prose semantically, so the directives body rides FIRST-CLASS
into the Jev state; the structured lists (labs, companies, topics) become
high-weight lexical terms. Absent file = today's behavior, unchanged."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Directives:
    body: str = ""
    labs: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)  # tracked people — issue #66

    @property
    def present(self) -> bool:
        return bool(self.body or self.labs or self.companies or self.topics or self.authors)

    def all_terms(self) -> list[str]:
        return self.labs + self.companies + self.topics

    def author_groups(self) -> dict[str, str]:
        """name → group for entries carrying the ' — Group' suffix (issue #87);
        bare entries and groups ride only where curation wrote them."""
        return {name: group for name, group in (split_group(e) for e in self.authors) if group}


def split_group(entry: str) -> tuple[str, str | None]:
    """Roster entries may carry a 'Name — Group' suffix. The group is
    display-only — matching and scoring always see the bare name."""
    if " — " in entry:
        name, group = entry.split(" — ", 1)
        return name.strip(), group.strip() or None
    return entry.strip(), None


def load_people_cards(cards_dir: Path) -> list[str]:
    """Read every .md file in cards_dir and return roster entries.

    Each card's 'name' and 'organization' frontmatter fields are read:
    - card with a real organization → 'Name — Org' (grouped entry)
    - card with organization TBD, empty, or absent → bare 'Name' entry
    - card without a 'name' field → skipped

    Returns an empty list when the directory is missing or unreadable
    (fail-open: ADR invariant #5 — external seams fail open)."""
    if not cards_dir.is_dir():
        return []
    entries: list[str] = []
    for card_path in sorted(cards_dir.glob("*.md")):
        if not card_path.is_file():
            continue
        try:
            text = card_path.read_text(errors="replace")
        except OSError:
            continue
        fm: dict = {}
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end != -1:
                try:
                    fm = yaml.safe_load(text[4:end]) or {}
                except yaml.YAMLError:
                    fm = {}
        if not isinstance(fm, dict):
            continue
        name = fm.get("name")
        if not isinstance(name, str) or not name.strip():
            continue  # no name — skip
        name = name.strip()
        org = fm.get("organization")
        org_str = org.strip() if isinstance(org, str) else ""
        if org_str and org_str.upper() != "TBD":
            entries.append(f"{name} — {org_str}")
        else:
            entries.append(name)
    return entries


def _merge_authors(list_entries: list[str], card_entries: list[str]) -> list[str]:
    """Merge two roster entry lists; an entry whose bare name already appears
    in the merged result is dropped (deduplication by bare name, issue #98)."""
    merged: list[str] = []
    seen_names: set[str] = set()
    for entry in list_entries + card_entries:
        bare = split_group(entry)[0].lower()
        if bare in seen_names:
            continue
        seen_names.add(bare)
        merged.append(entry)
    return merged


def load_directives(cfg) -> Directives:
    """The directives note: explicit path, else arjev-directives.md at the first
    root that has one. Read-only; absent degrades to empty."""
    import os

    override = os.environ.get("ARJEV_DIRECTIVES_FILE")
    candidates = [Path(override).expanduser()] if override else \
        [root / "arjev-directives.md" for root in cfg.expanded_roots]
    for path in candidates:
        if path.is_file():
            return parse_directives(path.read_text(errors="replace"), base_path=path.parent)
    return Directives()


def parse_directives(text: str, base_path: Path | None = None) -> Directives:
    body = text
    fm: dict = {}
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                fm = {}
            body = text[end + 5:]
    if not isinstance(fm, dict):
        fm = {}
    if fm.get("type") not in (None, "directives"):
        return Directives()  # an unrelated note at the path — not ours, ignore it
    list_authors = [str(x) for x in (fm.get("authors") or [])]
    # issue #98: people-card directory merges into the roster
    card_authors: list[str] = []
    raw_cards_dir = fm.get("people_cards_dir")
    if raw_cards_dir and isinstance(raw_cards_dir, str):
        cards_path = Path(raw_cards_dir.strip())
        if not cards_path.is_absolute() and base_path is not None:
            cards_path = base_path / cards_path
        card_authors = load_people_cards(cards_path)
    merged_authors = _merge_authors(list_authors, card_authors)
    directives = Directives(
        body=body.strip(),
        labs=[str(x) for x in (fm.get("labs") or [])],
        authors=merged_authors,
        companies=[str(x) for x in (fm.get("companies") or [])],
        topics=[str(x) for x in (fm.get("topics") or [])],
    )
    return directives

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


def load_directives(cfg) -> Directives:
    """The directives note: explicit path, else arjev-directives.md at the first
    root that has one. Read-only; absent degrades to empty."""
    import os

    override = os.environ.get("ARJEV_DIRECTIVES_FILE")
    candidates = [Path(override).expanduser()] if override else \
        [root / "arjev-directives.md" for root in cfg.expanded_roots]
    for path in candidates:
        if path.is_file():
            return parse_directives(path.read_text(errors="replace"))
    return Directives()


def parse_directives(text: str) -> Directives:
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
    directives = Directives(
        body=body.strip(),
        labs=[str(x) for x in (fm.get("labs") or [])],
        authors=[str(x) for x in (fm.get("authors") or [])],
        companies=[str(x) for x in (fm.get("companies") or [])],
        topics=[str(x) for x in (fm.get("topics") or [])],
    )
    if fm.get("type") not in (None, "directives"):
        return Directives()  # an unrelated note at the path — not ours, ignore it
    return directives

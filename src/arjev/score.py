"""The lexical front-line: explainable, deterministic, free. Ported from the incumbent's
proven scorer — word-boundary safe, title-weighted ×3, specificity-scaled."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .feed import FeedItem
from .profile import Profile


@dataclass
class ScoredItem:
    item: FeedItem
    score: float
    terms: list[str]

    @property
    def distinct_terms(self) -> int:
        return len(self.terms)


def _count_matches(text_lower: str, term: str) -> int:
    escaped = re.escape(term)
    matches = re.findall(rf"(^|[^a-z0-9-]){escaped}([^a-z0-9-]|$)", text_lower)
    return len(matches)


def _name_match(roster_entry: str, authors: list[str]) -> bool:
    """Surname token + first-initial agreement. A surname-only roster entry
    matches any first name (a deliberate whole-family follow); a mismatched
    initial never matches. Case-insensitive throughout (issue #66)."""
    entry = roster_entry.lower().replace(".", " ").split()
    surname = entry[-1] if entry else ""
    if not surname:
        return False
    initial = entry[0][0] if len(entry) > 1 else ""
    for author in authors:
        parts = author.lower().replace(".", " ").split()
        if not parts or parts[-1] != surname:
            continue
        if initial and len(parts[0]) >= 1 and parts[0][0] != initial:
            continue
        return True
    return False


def score_item(item: FeedItem, profile: Profile) -> ScoredItem:
    title = item.title.lower()
    abstract = item.abstract.lower()
    score = 0.0
    terms: list[str] = []
    # the author lane: tracked-people provenance is as loud as a title hit.
    # A separate namespace — roster names match only the authors field, never
    # an abstract's mere mention of the same surname.
    for roster, weight in sorted(profile.author_terms.items(), key=lambda kv: -kv[1]):
        if _name_match(roster, item.authors):
            score += weight * 3
            terms.append(roster)
    for term, weight in sorted(profile.terms.items(), key=lambda kv: -kv[1]):
        in_title = _count_matches(title, term)
        in_abstract = _count_matches(abstract, term)
        if in_title + in_abstract == 0 or weight <= 0:
            continue  # a capped-to-zero term matches nothing and explains nothing
        specificity = 1 + min(1, len(term) / 16)
        score += weight * specificity * (in_title * 3 + in_abstract)
        terms.append(term)
    return ScoredItem(item=item, score=round(score * 100) / 100, terms=terms)

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


def score_item(item: FeedItem, profile: Profile) -> ScoredItem:
    title = item.title.lower()
    abstract = item.abstract.lower()
    score = 0.0
    terms: list[str] = []
    for term, weight in profile.terms.items():
        in_title = _count_matches(title, term)
        in_abstract = _count_matches(abstract, term)
        if in_title + in_abstract == 0:
            continue
        specificity = 1 + min(1, len(term) / 16)
        score += weight * specificity * (in_title * 3 + in_abstract)
        terms.append(term)
    return ScoredItem(item=item, score=round(score * 100) / 100, terms=terms)

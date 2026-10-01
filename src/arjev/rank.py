"""Ranking and the disjoint Jev pools (spec slice 2 definitions — the classification
is deterministic and computed here, so slice 2 only wires the client onto it):

- survivors: score > 0, ranked, top `screen` by score.
- near-miss pool: score > 0, ranked BELOW the screen cutoff, matching exactly one
  distinct profile term.
- recall probe: a seeded uniform sample of `probe_k` items with score == 0.
Items in none of the pools are not Jev-scored at all. The pools are disjoint.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .feed import FeedItem
from .profile import Profile
from .score import ScoredItem, score_item


@dataclass
class Pools:
    survivors: list[ScoredItem] = field(default_factory=list)
    near_miss: list[ScoredItem] = field(default_factory=list)
    probe: list[ScoredItem] = field(default_factory=list)  # zero-score; terms always []


@dataclass
class RankResult:
    picks: list[ScoredItem]
    pools: Pools
    skipped_corpus: list[str]
    skipped_posted: list[str]
    dropped_zero: list[str]


def classify_pools(scored: list[ScoredItem], screen: int, probe_k: int, seed: str) -> Pools:
    ranked = sorted([s for s in scored if s.score > 0], key=lambda s: (-s.score, s.item.arxiv))
    survivors = ranked[:screen]
    below = ranked[screen:]
    near_miss = [s for s in below if s.distinct_terms == 1]
    zero_ids = sorted(s.item.arxiv for s in scored if s.score <= 0)
    sampled = set(random.Random(seed).sample(zero_ids, min(probe_k, len(zero_ids)))) if probe_k > 0 else set()
    by_id = {s.item.arxiv: s for s in scored}
    probe = [by_id[i] for i in sorted(sampled)]
    return Pools(survivors=survivors, near_miss=near_miss, probe=probe)


def rank(
    items: list[FeedItem],
    profile: Profile,
    corpus_ids: set[str],
    posted_ids: set[str],
    top: int,
    screen: int,
    probe_k: int,
    seed: str,
) -> RankResult:
    scored = [score_item(i, profile) for i in items]
    pools = classify_pools(scored, screen, probe_k, seed)
    picks: list[ScoredItem] = []
    skipped_corpus: list[str] = []
    skipped_posted: list[str] = []
    dropped_zero: list[str] = []
    for s in pools.survivors:
        arxiv = s.item.arxiv
        if arxiv in corpus_ids:
            skipped_corpus.append(arxiv)
        elif arxiv in posted_ids:
            skipped_posted.append(arxiv)
        else:
            picks.append(s)
    dropped_zero = [s.item.arxiv for s in scored if s.score <= 0]
    return RankResult(
        picks=picks[:top],
        pools=pools,
        skipped_corpus=skipped_corpus,
        skipped_posted=skipped_posted,
        dropped_zero=dropped_zero,
    )

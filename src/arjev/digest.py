"""Digest orchestration: fold → profile → feed → score → rank → render.
Deterministic on identical inputs (acceptance: digest.fingerprint_mismatches == 0).
In v1 the Jev layer is absent, so the primary mode is always lexical-only; slice 2
swaps the primary flag when Jev runs. State lives nowhere in slice 1 — the posted-state
and journal arrive in slice 3."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import Config
from .feed import load_feed
from .fold import fold_roots
from .profile import build_profile, profile_flag
from .rank import rank
from .render import canonical_picks, mode_line, render_mrkdwn, render_vault_note, write_vault_note


@dataclass
class DigestResult:
    markdown: str
    fingerprint: str
    mode: str
    picks: int


def fingerprint_picks(rank) -> str:
    return hashlib.sha256(json.dumps(canonical_picks(rank), sort_keys=True).encode()).hexdigest()[:16]


def run_digest(
    cfg: Config,
    feed: str | None = None,
    feed_file: str | None = None,
    post: str = "stdout",
    today: date | None = None,
    seed: str | None = None,
) -> DigestResult:
    today = today or date.today()
    seed = seed or f"{feed or feed_file or 'quant-ph'}:{today.isoformat()}"
    fold = fold_roots(cfg.expanded_roots, cfg)
    profile = build_profile(fold, cfg, today)
    items = load_feed(feed, feed_file)
    ranked = rank(
        items,
        profile,
        corpus_ids={p.arxiv for p in fold.papers if p.arxiv},
        posted_ids=set(),  # slice 3 wires the posted-state join
        top=cfg.top,
        screen=cfg.screen,
        probe_k=cfg.probe_k,
        seed=seed,
    )
    mode = mode_line("lexical-only", profile_flag(profile))
    feed_name = feed or (Path(feed_file).stem if feed_file else cfg.feeds[0])
    markdown = render_mrkdwn(ranked, feed_name, total=len(items), today=today, mode=mode)
    if post == "vault":
        digest_dir = Path(cfg.digest_dir).expanduser() if cfg.digest_dir else cfg.expanded_roots[0] / "digests"
        note = render_vault_note(ranked, feed_name, total=len(items), today=today, mode=mode)
        write_vault_note(note, digest_dir, today)
    return DigestResult(
        markdown=markdown,
        fingerprint=fingerprint_picks(ranked),
        mode=mode,
        picks=len(ranked.picks),
    )

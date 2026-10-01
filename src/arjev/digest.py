"""Digest orchestration: fold → profile → feed → score → rank → Jev middle layer →
post (stdout | vault | slack) + journal. Deterministic on identical inputs (acceptance:
fingerprint mismatches == 0). Fail-open: no key / outage / low confidence → the lexical
ranking, with the mode flag and per-candidate journal saying exactly what ran."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from .config import Config
from .feed import load_feed
from .fold import fold_roots
from .jev import JevClient, JevReceipt
from .profile import build_profile, profile_flag
from .rank import rank
from .render import canonical_picks, mode_line, render_mrkdwn, render_vault_note, write_vault_note
from .rerank import Pick, RunRecord, apply_jev, run_id_for, state_dir, write_journal, write_run_receipts
from .state import PostedState


@dataclass
class DigestResult:
    markdown: str
    fingerprint: str
    mode: str
    picks: list[Pick] = field(default_factory=list)
    run_id: str = ""
    journal_rows: int = 0


def fingerprint_picks(picks: list[Pick]) -> str:
    return hashlib.sha256(json.dumps(canonical_picks(picks), sort_keys=True).encode()).hexdigest()[:16]


def slack_token() -> str:
    token = os.environ.get("ARJEV_SLACK_TOKEN")
    if not token:
        raise SystemExit("ARJEV_SLACK_TOKEN not set (docs/slack-setup.md)")
    return token


def run_digest(
    cfg: Config,
    feed: str | None = None,
    feed_file: str | None = None,
    post: str = "stdout",
    today: date | None = None,
    seed: str | None = None,
    jev_client: JevClient | None = None,
    slack_client=None,
) -> DigestResult:
    today = today or date.today()
    seed = seed or f"{feed or feed_file or 'quant-ph'}:{today.isoformat()}"
    fold = fold_roots(cfg.expanded_roots, cfg)
    profile = build_profile(fold, cfg, today)
    items = load_feed(feed, feed_file)
    ranked = rank(
        items,
        profile,
        corpus_ids=fold.arxiv_ids(),
        posted_ids=set(PostedState.load(state_dir() / "papers-digest-state.json").ids),
        top=cfg.top,
        screen=cfg.screen,
        probe_k=cfg.probe_k,
        seed=seed,
    )
    client = jev_client or JevClient(key=None, min_confidence=cfg.jev_min_confidence)
    run_id = run_id_for(seed, today)
    receipts: list[JevReceipt] = []
    picks, mode_primary, candidates = apply_jev(ranked, client, profile, run_id, receipts, top=cfg.top)
    if receipts:
        write_run_receipts(receipts)
    mode = mode_line(mode_primary, profile_flag(profile))
    feed_name = feed or (Path(feed_file).stem if feed_file else cfg.feeds[0])

    record = RunRecord(
        run_id=run_id,
        ts=datetime.now(UTC).isoformat(timespec="seconds"),
        feed=feed_name,
        mode=mode,
        seed=seed,
        candidates=candidates,
    )

    if post == "slack":
        if not cfg.slack_channel:
            raise SystemExit("slack_channel not configured (docs/slack-setup.md)")
        from .slack import SlackClient, render_pick_message

        sc = slack_client or SlackClient(token=slack_token())
        record.slack_channel = cfg.slack_channel
        for i, p in enumerate(picks):
            msg = render_pick_message(p, i + 1, len(picks), today, feed_name, mode, cfg.why_style)
            ts = sc.post_message(cfg.slack_channel, msg.text)
            for c in record.candidates:
                if c.arxiv == p.arxiv:
                    c.slack_ts = ts
                    break

    if post == "vault":
        digest_dir = Path(cfg.digest_dir).expanduser() if cfg.digest_dir else cfg.expanded_roots[0] / "digests"
        note = render_vault_note(picks, feed_name, total=len(items), today=today, mode=mode,
                                 skipped_corpus=len(ranked.skipped_corpus))
        write_vault_note(note, digest_dir, today)

    state_file = state_dir() / "papers-digest-state.json"
    PostedState.load(state_file).append([p.arxiv for p in picks])
    write_journal(record)

    markdown = render_mrkdwn(picks, feed_name, total=len(items), today=today, mode=mode,
                              skipped_corpus=len(ranked.skipped_corpus))
    return DigestResult(
        markdown=markdown,
        fingerprint=fingerprint_picks(picks),
        mode=mode,
        picks=picks,
        run_id=run_id,
        journal_rows=len(candidates),
    )

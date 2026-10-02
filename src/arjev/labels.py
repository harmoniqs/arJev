"""Labels sync: the three-branch vault-arrival join + the checkbox harvest, all
reducing to the ledger. The 30-day clock is injectable (time-free tests); the
three branches per spec slice 3:

  non-staged vault presence      → saved-implicit (vault-arrival)
  any staged presence (touched
  or not)                        → NO row, the 30-day clock is suspended
  otherwise, 30d never-saved     → unsaved-weak-negative (vault-unsaved)

One human action, one label row: a keep label already in the ledger suppresses
the weak negative (explicit beats implicit)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from .feed import ARXIV, Identity
from .fold import FoldResult
from .ledger import Label, LabelLedger, now_ts
from .state import PostedState

CLOCK_DAYS = 30


def _vault_pair(identity: str) -> Identity:
    """The fold's source-prefixed identity ("arxiv:2601.01001", "doi:10.…" — the
    vault-side anchor, unchanged) split into the (source, id) join pair."""
    source, _, id = identity.partition(":")
    return Identity(source, id)


def arrival_labels(
    fold: FoldResult,
    posted: PostedState,
    journal: list[dict],
    ledger: LabelLedger,
    now: datetime,
    days: int = CLOCK_DAYS,
) -> list[Label]:
    """The vault-arrival join. Reads fold + journal + posted-state; writes only the
    ledger. Idempotent (the ledger dedupes on (arxiv_id, label_type)). The join
    routes on identity pairs: journal rows and posted-state are the arxiv namespace
    (frozen bare-id schemas); the fold carries source-prefixed anchors."""
    postings: dict[Identity, str | None] = {}
    for line in journal:
        for c in line.get("candidates", []):
            if c.get("posted"):
                postings.setdefault(Identity(ARXIV, c["arxiv"]), line.get("ts"))
    new: list[Label] = []
    for arxiv_id in posted.ids:
        if Identity(ARXIV, arxiv_id) not in postings:
            postings[Identity(ARXIV, arxiv_id)] = posted.posting_time(arxiv_id, None)  # legacy: state `updated`
    staged = {_vault_pair(p.identity) for p in fold.papers if p.status == "staged"}
    distilled = {_vault_pair(p.identity) for p in fold.papers if p.status != "staged"}
    for identity, posted_ts in postings.items():
        if identity in distilled:
            if not ledger.has(identity.id, "saved-implicit") and not ledger.has_positive(identity.id):
                new.append(Label(identity.id, "saved-implicit", "vault-arrival", now_ts()))
            continue
        if identity in staged:
            continue  # the clock is suspended while any staged stub exists — kept never flips negative
        if posted_ts is None or ledger.has_positive(identity.id):
            continue
        try:
            posted_at = datetime.fromisoformat(posted_ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if now - posted_at >= timedelta(days=days):
            new.append(Label(identity.id, "unsaved-weak-negative", "vault-unsaved", now_ts()))
    ledger.append_many(new)
    return new


def checkbox_labels(digest_dir: Path, ledger: LabelLedger) -> list[Label]:
    """The vault digest-note harvest: arjev's own `- [x] … [arXiv:<id>](…)` lines are
    keep decisions (source: checkbox). Idempotent."""
    if not digest_dir.is_dir():
        return []
    new: list[Label] = []
    for note in digest_dir.glob("*.md"):
        text = note.read_text(errors="replace")
        if "type: digest" not in text:
            continue
        for line in text.splitlines():
            if not line.startswith("- [x]"):
                continue
            m = re.search(r"\[arXiv:([0-9]{4}\.[0-9]{4,5}|[a-z-]+/\d{7})\]", line)
            if not m:
                continue
            ledger.append(Label(m.group(1), "keep", "checkbox", now_ts()))
            new.append(Label(m.group(1), "keep", "checkbox", now_ts()))
    return new


def labels_sync(cfg, fold: FoldResult, ledger: LabelLedger, now: datetime | None = None) -> list[Label]:
    """The full sync: arrival join + checkbox harvest — returns every new row."""
    from .rerank import journal_path, state_dir

    now = now or datetime.now()
    journal: list[dict] = []
    jp = journal_path()
    if jp.is_file():
        import json

        journal = [json.loads(line) for line in jp.read_text().splitlines() if line.strip()]
    posted = PostedState.load(state_dir() / "papers-digest-state.json")
    new = arrival_labels(fold, posted, journal, ledger, now)
    digest_dir = Path(cfg.digest_dir).expanduser() if cfg.digest_dir else cfg.expanded_roots[0] / "digests"
    return new + checkbox_labels(digest_dir, ledger)

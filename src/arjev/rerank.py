"""Jev wiring: the middle layer over the classified pools, with per-item fail-open and
the digest journal (the durable per-run record: run_id, ts, feed, mode, seed,
candidates with pool membership, lexical score, Jev fields, posted flag)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from .jev import JevClient, JevReceipt, assemble_state, write_receipts
from .rank import RankResult


@dataclass
class Pick:
    arxiv: str
    title: str
    lexical_score: float
    terms: list[str]
    jev_primary: float  # top-2 relevance mass (survivors) or p_true (rescues)
    rescued: str | None  # None | "probe" | "near-miss"
    fail_reason: str | None


@dataclass
class CandidateJournal:
    arxiv: str
    pool: str  # survivor | near-miss | probe | none
    lexical_score: float
    terms: list[str]
    jev: dict | None  # {primitive, confidence, top, fail_reason}
    posted: bool
    rescued: str | None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    slack_ts: str = ""


@dataclass
class RunRecord:
    run_id: str
    ts: str
    feed: str
    mode: str
    seed: str
    candidates: list[CandidateJournal]
    slack_channel: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "ts": self.ts,
                "feed": self.feed,
                "mode": self.mode,
                "seed": self.seed,
                "candidates": [c.__dict__ for c in self.candidates],
                "slack_channel": self.slack_channel,
            },
            sort_keys=True,
        )


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(base) / "arjev"


def journal_path() -> Path:
    return state_dir() / "digest-journal.jsonl"


def run_id_for(seed: str, today: date) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{seed}:{today.isoformat()}:{stamp}".encode()).hexdigest()[:6]
    return f"{stamp}-{digest}"


def apply_jev(rank: RankResult, client: JevClient, profile, run_id: str, receipts: list[JevReceipt],
              top: int) -> tuple[list[Pick], str, list[CandidateJournal]]:
    """Rerank survivors (Score), rescue near-miss and probe items (Noul). Returns
    (picks, primary_mode, candidate journal rows). Fail-open per item, journaled."""
    mode_primary = "lexical-only"
    candidates: list[CandidateJournal] = []
    evaluated: list[Pick] = []
    # survivors stay pick candidates even on fail-open (the lexical ranking IS the
    # fallback); near-miss/probe items enter the picks ONLY on a successful rescue —
    # a failed-open zero-score band item falls out entirely (the live dry-run caught
    # the opposite: they silently took pick slots under an empty profile).
    fail_reasons: dict[str, str] = {}

    for s in rank.pools.survivors:
        answer = _score_or_fail(client, profile, s, run_id, receipts)
        if answer is None:
            evaluated.append(Pick(s.item.arxiv, s.item.title, s.score, s.terms, 0.0, None, "state-overflow"))
            fail_reasons[s.item.arxiv] = "state-overflow"
            continue
        if answer.ok:
            mode_primary = "jev"
            mass = answer.distribution.get("must-read", 0.0) + answer.distribution.get("worth-reading", 0.0)
            evaluated.append(Pick(s.item.arxiv, s.item.title, s.score, s.terms, mass, None, None))
        else:
            evaluated.append(Pick(s.item.arxiv, s.item.title, s.score, s.terms, 0.0, None, answer.fail_reason))
            fail_reasons[s.item.arxiv] = answer.fail_reason

    for pool_name, source in (("near-miss", rank.pools.near_miss), ("probe", rank.pools.probe)):
        for s in source:
            answer = _noul_or_fail(client, profile, s, run_id, receipts)
            if answer is None:
                fail_reasons[s.item.arxiv] = "state-overflow"
                continue
            if not answer.ok:
                fail_reasons[s.item.arxiv] = answer.fail_reason
                continue
            if answer.distribution.get("true", 0.0) >= client.min_confidence:
                mode_primary = "jev"
                evaluated.append(Pick(s.item.arxiv, s.item.title, s.score, s.terms,
                                      answer.distribution.get("true", 0.0), pool_name, None))
            else:
                fail_reasons[s.item.arxiv] = "below-threshold"

    evaluated.sort(key=lambda p: (-p.jev_primary, -p.lexical_score, p.arxiv))
    picks = evaluated[:top]
    picked_ids = {p.arxiv for p in picks}

    pool_of = {}
    for s in rank.pools.survivors:
        pool_of[s.item.arxiv] = "survivor"
    for s in rank.pools.near_miss:
        pool_of[s.item.arxiv] = "near-miss"
    for s in rank.pools.probe:
        pool_of[s.item.arxiv] = "probe"
    pools_all = (rank.pools.survivors, rank.pools.near_miss, rank.pools.probe)
    for s in pools_all[0] + pools_all[1] + pools_all[2]:
        receipt = next((r for r in receipts if r.candidate_arxiv == s.item.arxiv), None)
        candidates.append(CandidateJournal(
            arxiv=s.item.arxiv, pool=pool_of[s.item.arxiv],
            lexical_score=s.score, terms=s.terms,
            jev=_jev_row_from_receipt(receipt, fail_reasons.get(s.item.arxiv)),
            posted=s.item.arxiv in picked_ids,
            rescued=next((p.rescued for p in picks if p.arxiv == s.item.arxiv), None),
            title=s.item.title, authors=list(s.item.authors),
        ))
    # zero-score non-probe items ride the journal too (the calibration denominator pool)
    probe_ids = {s.item.arxiv for s in rank.pools.probe}
    for s in rank.dropped_zero:
        if s in probe_ids:
            continue
        candidates.append(
            CandidateJournal(arxiv=s, pool="none", lexical_score=0.0, terms=[], jev=None, posted=False, rescued=None)
        )
    return picks, mode_primary, candidates


def _jev_row_from_receipt(receipt: JevReceipt | None, fail_reason: str | None) -> dict | None:
    if receipt is None:
        return {"fail_reason": fail_reason} if fail_reason else None
    row = {
        "primitive": receipt.primitive,
        "confidence": receipt.confidence,
        "top": max(receipt.distribution, key=receipt.distribution.get) if receipt.distribution else None,
    }
    if fail_reason:
        row["fail_reason"] = fail_reason
    return row


def _score_or_fail(client, profile, s, run_id, receipts):
    assembly = assemble_state(profile, s)
    if assembly.state is None:
        return None
    return client.score_relevance(assembly.state, s.item.arxiv, run_id, receipts)


def _noul_or_fail(client, profile, s, run_id, receipts):
    assembly = assemble_state(profile, s)
    if assembly.state is None:
        return None
    return client.noul_relevant(assembly.state, s.item.arxiv, run_id, receipts)


def write_journal(record: RunRecord) -> Path:
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    path = journal_path()
    with path.open("a") as f:
        f.write(record.to_json() + "\n")
    return path


def write_run_receipts(receipts: list[JevReceipt]) -> Path:
    return write_receipts(state_dir(), receipts)

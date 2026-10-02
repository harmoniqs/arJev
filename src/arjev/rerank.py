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

from .feed import Identity
from .jev import JevClient, JevReceipt, assemble_state, write_receipts
from .rank import RankResult


@dataclass
class Pick:
    arxiv: str  # identity.id — persisted surfaces (fingerprint, render) keep the bare id
    title: str
    lexical_score: float
    terms: list[str]
    jev_primary: float  # top-2 relevance mass (survivors) or p_true (rescues)
    rescued: str | None  # None | "probe" | "near-miss"
    fail_reason: str | None
    source: str = "arxiv"  # identity.source — the pair travels with the pick

    @property
    def identity(self) -> Identity:
        return Identity(self.source, self.arxiv)


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
    ranking: str = "lexical-first"

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
                "ranking": self.ranking,
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


def apply_jev_first(
    items: list,
    scored_by_id: dict,
    skip: set,
    client: JevClient,
    profile,
    run_id: str,
    receipts: list[JevReceipt],
    top: int,
    pace_s: float = 0.05,
) -> tuple[list[Pick], str, list[CandidateJournal]]:
    """The ranking amendment: Jev at the front line. Every eligible item (not corpus,
    not posted) is Jev-scored; picks rank by top-two-level mass with lexical tiebreak.
    Per-item fail-open falls to the lexical order; the probe is moot (nothing
    unscreened). Pools stay in the journal as lexical classifications. The join
    inputs are identity-keyed: `skip` is the vault's arxiv namespace lifted into
    pairs, `scored_by_id` maps identity pairs to scored items."""
    import time as _time

    mode_primary = "lexical-only"
    evaluated: list[Pick] = []
    fail_reasons: dict[Identity, str] = {}
    # receipt binding: the client appends at most one receipt per call — the pair
    # association is made here, at the call, because the persisted receipt schema
    # (candidate_arxiv, frozen) carries the identity's id half only
    receipt_of: dict[Identity, JevReceipt | None] = {}
    for item in items:
        if item.identity in skip:
            continue
        s = scored_by_id.get(item.identity)
        if s is None:
            continue
        assembly = assemble_state(profile, s)
        if assembly.state is None:
            fail_reasons[item.identity] = "state-overflow"
            receipt_of[item.identity] = None
            evaluated.append(Pick(item.identity.id, item.title, s.score, s.terms, 0.0, None, "state-overflow",
                                  source=item.source))
            continue
        before = len(receipts)
        answer = client.score_relevance(assembly.state, item.identity.id, run_id, receipts)
        receipt_of[item.identity] = receipts[before] if len(receipts) > before else None
        if pace_s:
            _time.sleep(pace_s)
        if answer.ok:
            mode_primary = "jev"
            mass = answer.distribution.get("must-read", 0.0) + answer.distribution.get("worth-reading", 0.0)
            evaluated.append(Pick(item.identity.id, item.title, s.score, s.terms, mass, None, None,
                                  source=item.source))
        else:
            fail_reasons[item.identity] = answer.fail_reason
            evaluated.append(Pick(item.identity.id, item.title, s.score, s.terms, 0.0, None, answer.fail_reason,
                                  source=item.source))
    evaluated.sort(key=lambda p: (-p.jev_primary, -p.lexical_score, p.identity))
    picks = evaluated[:top]
    picked = {p.identity for p in picks}
    # lexical pool labels stay in the journal as calibration denominators
    candidates = [
        CandidateJournal(
            arxiv=p.identity.id, pool=_lexical_pool(p.identity, scored_by_id), lexical_score=p.lexical_score,
            terms=p.terms, jev=_jev_row_from_receipt(
                receipt_of.get(p.identity), fail_reasons.get(p.identity)),
            posted=p.identity in picked, rescued=None, title=p.title, authors=[],
        )
        for p in evaluated
    ]
    return picks, mode_primary, candidates


def _lexical_pool(identity: Identity, scored_by_id: dict) -> str:
    s = scored_by_id.get(identity)
    if s is None:
        return "none"
    if s.score > 0:
        return "survivor" if len(s.terms) > 1 else "near-miss"
    return "probe"


def apply_jev(rank: RankResult, client: JevClient, profile, run_id: str, receipts: list[JevReceipt],
              top: int) -> tuple[list[Pick], str, list[CandidateJournal]]:
    """Rerank survivors (Score), rescue near-miss and probe items (Noul). Returns
    (picks, primary_mode, candidate journal rows). Fail-open per item, journaled.
    Every join — pool membership, posted flags, rescues, receipts — routes through
    the identity pair; journal rows persist the pair's id half (frozen schema)."""
    mode_primary = "lexical-only"
    candidates: list[CandidateJournal] = []
    evaluated: list[Pick] = []
    # survivors stay pick candidates even on fail-open (the lexical ranking IS the
    # fallback); near-miss/probe items enter the picks ONLY on a successful rescue —
    # a failed-open zero-score band item falls out entirely (the live dry-run caught
    # the opposite: they silently took pick slots under an empty profile).
    fail_reasons: dict[Identity, str] = {}
    # receipt binding by observation: the client appends at most one receipt per
    # call — the pair association is made at the call, since the persisted receipt
    # schema (candidate_arxiv, frozen) carries the identity's id half only
    receipt_of: dict[Identity, JevReceipt | None] = {}

    for s in rank.pools.survivors:
        before = len(receipts)
        answer = _score_or_fail(client, profile, s, run_id, receipts)
        receipt_of[s.item.identity] = receipts[before] if len(receipts) > before else None
        if answer is None:
            evaluated.append(Pick(s.item.identity.id, s.item.title, s.score, s.terms, 0.0, None,
                                  "state-overflow", source=s.item.source))
            fail_reasons[s.item.identity] = "state-overflow"
            continue
        if answer.ok:
            mode_primary = "jev"
            mass = answer.distribution.get("must-read", 0.0) + answer.distribution.get("worth-reading", 0.0)
            evaluated.append(Pick(s.item.identity.id, s.item.title, s.score, s.terms, mass, None, None,
                                  source=s.item.source))
        else:
            evaluated.append(Pick(s.item.identity.id, s.item.title, s.score, s.terms, 0.0, None,
                                  answer.fail_reason, source=s.item.source))
            fail_reasons[s.item.identity] = answer.fail_reason

    for pool_name, source in (("near-miss", rank.pools.near_miss), ("probe", rank.pools.probe)):
        for s in source:
            before = len(receipts)
            answer = _noul_or_fail(client, profile, s, run_id, receipts)
            receipt_of[s.item.identity] = receipts[before] if len(receipts) > before else None
            if answer is None:
                fail_reasons[s.item.identity] = "state-overflow"
                continue
            if not answer.ok:
                fail_reasons[s.item.identity] = answer.fail_reason
                continue
            if answer.distribution.get("true", 0.0) >= client.min_confidence:
                mode_primary = "jev"
                evaluated.append(Pick(s.item.identity.id, s.item.title, s.score, s.terms,
                                      answer.distribution.get("true", 0.0), pool_name, None,
                                      source=s.item.source))
            else:
                fail_reasons[s.item.identity] = "below-threshold"

    evaluated.sort(key=lambda p: (-p.jev_primary, -p.lexical_score, p.identity))
    picks = evaluated[:top]
    picked = {p.identity for p in picks}

    pool_of: dict[Identity, str] = {}
    for s in rank.pools.survivors:
        pool_of[s.item.identity] = "survivor"
    for s in rank.pools.near_miss:
        pool_of[s.item.identity] = "near-miss"
    for s in rank.pools.probe:
        pool_of[s.item.identity] = "probe"
    pools_all = (rank.pools.survivors, rank.pools.near_miss, rank.pools.probe)
    for s in pools_all[0] + pools_all[1] + pools_all[2]:
        candidates.append(CandidateJournal(
            arxiv=s.item.identity.id, pool=pool_of[s.item.identity],
            lexical_score=s.score, terms=s.terms,
            jev=_jev_row_from_receipt(receipt_of.get(s.item.identity), fail_reasons.get(s.item.identity)),
            posted=s.item.identity in picked,
            rescued=next((p.rescued for p in picks if p.identity == s.item.identity), None),
            title=s.item.title, authors=list(s.item.authors),
        ))
    # zero-score non-probe items ride the journal too (the calibration denominator pool)
    probe_ids = {s.item.identity for s in rank.pools.probe}
    for identity in rank.dropped_zero:
        if identity in probe_ids:
            continue
        candidates.append(
            CandidateJournal(arxiv=identity.id, pool="none", lexical_score=0.0, terms=[], jev=None,
                             posted=False, rescued=None)
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
    return client.score_relevance(assembly.state, s.item.identity.id, run_id, receipts)


def _noul_or_fail(client, profile, s, run_id, receipts):
    assembly = assemble_state(profile, s)
    if assembly.state is None:
        return None
    return client.noul_relevant(assembly.state, s.item.identity.id, run_id, receipts)


def write_journal(record: RunRecord) -> Path:
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    path = journal_path()
    with path.open("a") as f:
        f.write(record.to_json() + "\n")
    return path


def write_run_receipts(receipts: list[JevReceipt]) -> Path:
    return write_receipts(state_dir(), receipts)

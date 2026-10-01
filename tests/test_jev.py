"""Jev middle layer tests: canonical receipts, state budget, the three fail-open paths,
pool wiring, probe rescue, and the digest journal schema (obligations #2 #3 #5 #8)."""

import json
from pathlib import Path

import pytest

from arjev.config import Config
from arjev.digest import run_digest
from arjev.feed import FeedItem
from arjev.fold import fold_roots
from arjev.jev import (
    HARD_CAP,
    JevClient,
    JevReceipt,
    assemble_state,
    write_receipts,
)
from arjev.profile import build_profile
from arjev.score import score_item
from conftest import RSS, TODAY, VAULT, digest_cfg, isolate_state

FIXTURES = Path(__file__).parent / "fixtures"


class FakeTransport:
    """Recorded-response harness: deterministic distributions, no network, no key."""

    def __init__(self, score_mass=None, noul_true=None, outage=False):
        self.calls = []
        self.score_mass = score_mass or {"must-read": 0.8, "worth-reading": 0.15, "irrelevant": 0.05}
        self.noul_true = {"true": 0.7, "false": 0.3} if noul_true is None else noul_true
        self.outage = outage

    def __call__(self, url, key, payload):
        self.calls.append(payload)
        if self.outage:
            raise ConnectionError("simulated outage")
        question = payload["questions"][0]
        if "must-read" in question["criteria"]:
            return {"answers": [{"id": question["id"], "distribution": self.score_mass}], "model_version": "test-1.0"}
        return {"answers": [{"id": question["id"], "distribution": self.noul_true}], "model_version": "test-1.0"}


def client(transport, min_confidence=0.6):
    return JevClient(key="test-key", min_confidence=min_confidence, transport=transport)


# ── receipts: the canonical schema is structural ─────────────────────────────────

def test_every_call_writes_a_canonical_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    transport = FakeTransport()
    c = client(transport)
    receipts = []
    state = {
        "researcher_taste": {"terms": {"x": 1.0}},
        "candidate": {"title": "t", "abstract": "a", "arxiv": "2601.01011"},
    }
    c.score_relevance(state, "2601.01011", "run-1", receipts)
    c.noul_relevant(state, "2601.01012", "run-1", receipts)
    path = write_receipts(Path(tmp_path / "state") / "arjev", receipts)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    required = {"candidate_arxiv", "run_id", "ts", "primitive", "state_bytes", "distribution",
                "confidence", "latency_ms", "model_version"}
    assert len(rows) == 2
    for row in rows:
        assert required <= set(row), "every receipt carries the canonical schema"
        assert row["candidate_arxiv"], "receipts are candidate-bound"
    assert {r["primitive"] for r in rows} == {"score", "noul"}


def test_receipt_without_candidate_id_is_refused(tmp_path):
    bad = JevReceipt(candidate_arxiv="", run_id="r", ts="t", primitive="score",
                     state_bytes=10, distribution={}, confidence=0.5, latency_ms=1, model_version="x")
    with pytest.raises(ValueError, match="candidate"):
        write_receipts(tmp_path, [bad])


# ── state assembly: the 4096 budget and the overflow ladder ──────────────────────

def _profile_for(vault=VAULT):
    return build_profile(fold_roots([vault], Config()), Config(), TODAY)


def _candidate():
    return score_item(FeedItem(arxiv="2601.01011", title="t", abstract="a" * 100), _profile_for())


def test_state_within_budget():
    assembly = assemble_state(_profile_for(), _candidate())
    assert assembly.state is not None
    assert assembly.state_bytes <= HARD_CAP


def test_state_overflow_ladder_then_skip():
    from arjev.profile import Profile

    huge = Profile(terms={f"term{i:03d}": 100.0 - i for i in range(300)},
                   why_lines=[(None, "w" * 200)] * 40, recent_titles=["t" * 500] * 3)
    assembly = assemble_state(huge, _candidate())
    if assembly.state is None:
        assert assembly.state_bytes > HARD_CAP  # skipped honestly, not silently truncated
    else:
        assert assembly.state_bytes <= HARD_CAP
        assert assembly.dropped_terms > 0 or assembly.dropped_why > 0


def test_state_carries_taste_and_candidate():
    assembly = assemble_state(_profile_for(), _candidate())
    state = assembly.state
    assert "researcher_taste" in state and "candidate" in state
    assert set(state["researcher_taste"]) == {"terms", "why_lines", "recent_titles"}


# ── fail-open: the three paths ───────────────────────────────────────────────────

def test_no_key_digest_is_lexical_only(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s",
                        jev_client=JevClient(key=None))
    assert result.mode == "mode: lexical-only, ok"


def test_outage_fails_open_to_lexical(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s",
                        jev_client=client(FakeTransport(outage=True)))
    assert result.mode == "mode: lexical-only, ok"
    assert result.fingerprint  # the digest still shipped


def test_low_confidence_fails_open_per_item(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    low = FakeTransport(
        score_mass={"irrelevant": 0.45, "borderline": 0.3, "must-read": 0.25},  # top 0.45 < 0.6
        noul_true={"true": 0.5, "false": 0.5},  # top 0.5 < 0.6 — nothing clears the bar
    )
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s",
                        jev_client=client(low))
    assert result.mode == "mode: lexical-only, ok"  # no call cleared the confidence bar
    journal = _journal(tmp_path)
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    survivors = [c for c in rows[-1]["candidates"] if c["pool"] == "survivor"]
    assert survivors and all(c["jev"]["fail_reason"] == "low-confidence" for c in survivors)


def test_jev_mode_when_calls_succeed(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s",
                        jev_client=client(FakeTransport()))
    assert result.mode == "mode: jev, ok"


# ── pools wired; probe rescue ────────────────────────────────────────────────────

def test_score_on_survivors_noul_on_nearmiss_and_probe(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    transport = FakeTransport()
    run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s", jev_client=client(transport))
    scored = [q for p in transport.calls for q in p["questions"]]
    kinds = {"score": 0, "noul": 0}
    for q in scored:
        kinds["score" if "must-read" in q["criteria"] else "noul"] += 1
    assert kinds["score"] == 5  # fixture has 5 survivors in top-screen
    assert kinds["noul"] >= 1   # near-miss and/or probe members


def test_probe_rescue_enters_picks_flagged(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    # probe looks strongly relevant while survivors sit at borderline (below threshold
    # mass) — the rescue must outrank them and take a pick slot
    transport = FakeTransport(
        score_mass={"borderline": 0.65, "irrelevant": 0.35},  # confidence 0.65 ok; top-2 mass 0
        noul_true={"true": 0.9, "false": 0.1},
    )
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s", jev_client=client(transport))
    rescued = [p for p in result.picks if p.rescued == "probe"]
    assert rescued, "a high-relevance probe item must be rescued into the picks"
    assert rescued[0].jev_primary >= max(p.jev_primary for p in result.picks if p.rescued is None)
    assert "rescued by probe" in result.markdown
    assert "no lexical match" in result.markdown


def test_journal_records_pool_membership_and_seed(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="seed-j", jev_client=client(FakeTransport()))
    row = json.loads(_journal(tmp_path).read_text().splitlines()[-1])
    assert {"run_id", "ts", "feed", "mode", "seed", "candidates"} <= set(row)
    assert row["seed"] == "seed-j"
    pools = {c["pool"] for c in row["candidates"]}
    assert "survivor" in pools
    assert any(c["posted"] for c in row["candidates"])
    for c in row["candidates"]:
        if c["pool"] == "probe" and c["jev"]:
            assert c["jev"]["primitive"] == "noul"


def _journal(tmp_path):
    return tmp_path / "state" / "arjev" / "digest-journal.jsonl"


def test_empty_profile_yields_zero_picks_not_probe_fillers(monkeypatch, tmp_path):
    """The live dry-run caught this: with a degraded profile (all-zero scores) and no
    Jev key, fail-open probe items silently occupied pick slots. Fail-open zero-score
    band items fall out of the picks entirely."""
    isolate_state(monkeypatch, tmp_path)
    cfg = Config()
    cfg.roots = []  # empty vault → degraded profile, nothing scores
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s")
    assert result.picks == []
    assert result.mode == "mode: lexical-only, profile-degraded"

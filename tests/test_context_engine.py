"""The context engine (issue #75): budget-greedy state assembly (directives whole,
recency-proportional width, determinism, the hard-cap ladder), candidate-content
enrichment (two-pass finalists, cache-only hermetic), and the calibration joins it
obligates (receipt dedup on the enriched call, the arms instrument)."""

from __future__ import annotations

import json
from datetime import date

from arjev.config import Config
from arjev.feed import FeedItem
from arjev.jev import HARD_CAP, StatePolicy, assemble_state
from arjev.profile import Profile, TasteCard, build_profile
from arjev.score import score_item
from conftest import RSS, TODAY, VAULT, isolate_state
from test_jev import FakeTransport, client, digest_cfg

GREEDY = StatePolicy(policy="budget-greedy")
GREEDY_CONTENT = StatePolicy(policy="budget-greedy", candidate_conclusions=True)


def _profile_for():
    return build_profile(__import__("arjev.fold", fromlist=["fold_roots"]).fold_roots([VAULT], Config()),
                         Config(), TODAY)


def _candidate(arxiv="2601.01011"):
    return score_item(FeedItem(arxiv=arxiv, title="t", abstract="a" * 100), _profile_for())


# ── the greedy assembly ──────────────────────────────────────────────────────────


def test_greedy_directives_ride_whole_not_truncated():
    profile = Profile(directives_body="d" * 2000, terms={"x": 1.0})
    state = assemble_state(profile, _candidate(), GREEDY).state
    assert state["researcher_taste"]["directives"] == "d" * 2000
    # the incumbent still truncates at its own cap — the arms differ honestly
    fixed = assemble_state(profile, _candidate(), StatePolicy()).state
    assert len(fixed["researcher_taste"]["directives"]) == StatePolicy().directives_cap


def test_greedy_tiny_corpus_fits_everything():
    profile = Profile(directives_body="directives", terms={"x": 1.0, "y": 0.5})
    profile.cards = [TasteCard("t1", "w1", "a1", "c1", 0.9, TODAY),
                     TasteCard("t2", "w2", None, None, 0.8, TODAY)]
    state = assemble_state(profile, _candidate(), StatePolicy(policy="budget-greedy", taste_budget=100000)).state
    taste = state["researcher_taste"]
    assert taste["terms"] == {"x": 1.0, "y": 0.5}
    assert [c["title"] for c in taste["cards"]] == ["t1", "t2"]
    assert taste["cards"][0]["abstract"] == "a1" and taste["cards"][0]["conclusions"] == "c1"
    assert "why_lines" not in taste, "cards carry the whys — no duplication in the greedy state"


def test_greedy_recency_width_recent_card_outranks_old():
    """The growth-phase property: when the window can hold one of two equal-weight
    cards, the recent one claims it — the 180-day decay rides the card weight."""
    profile = Profile(terms={})
    profile.cards = [
        TasteCard("old paper", "w", "a", "c", 0.5 ** (300 / 180), date(2026, 1, 1)),
        TasteCard("recent paper", "w", "a", "c", 0.5 ** (90 / 180), date(2026, 7, 1)),
    ]
    state = assemble_state(profile, _candidate(), StatePolicy(policy="budget-greedy", taste_budget=100)).state
    titles = [c["title"] for c in state["researcher_taste"]["cards"]]
    assert "recent paper" in titles
    assert "old paper" not in titles


def test_greedy_true_greedy_skips_big_fits_small():
    """Not first-fit: an oversized card never blocks a fitting term."""
    profile = Profile(terms={"small": 1.0})
    profile.cards = [TasteCard("t", "w" * 400, "a" * 400, "c" * 400, 2.0, TODAY)]
    state = assemble_state(profile, _candidate(), StatePolicy(policy="budget-greedy", taste_budget=30)).state
    assert state["researcher_taste"]["terms"] == {"small": 1.0}
    assert not state["researcher_taste"]["cards"]


def test_greedy_is_deterministic():
    assembly = [assemble_state(_profile_for(), _candidate(), GREEDY) for _ in range(2)]
    assert json.dumps(assembly[0].state, sort_keys=True) == json.dumps(assembly[1].state, sort_keys=True)
    assert assembly[0].state_bytes == assembly[1].state_bytes


def test_greedy_hard_cap_overflow_ladder_then_skip():
    profile = Profile(directives_body="d" * 3000,
                      terms={f"t{i:03d}": float(100 - i) for i in range(300)},
                      recent_titles=["t" * 500] * 3)
    assembly = assemble_state(profile, _candidate(), GREEDY)
    if assembly.state is None:
        assert assembly.state_bytes > HARD_CAP, "skipped honestly, never silently truncated"
    else:
        assert assembly.state_bytes <= HARD_CAP


def test_fixed15_default_shape_is_unchanged():
    """The incumbent policy must be byte-identical in shape: the arms are opt-in."""
    state = assemble_state(_profile_for(), _candidate(), StatePolicy()).state
    assert set(state["researcher_taste"]) == {"directives", "terms", "why_lines", "recent_titles"}
    assert "cards" not in state["researcher_taste"]


def test_candidate_conclusions_ride_only_when_the_arm_is_on():
    profile = Profile(terms={"x": 1.0})
    off = assemble_state(profile, _candidate(), GREEDY, conclusions="c" * 100).state
    on = assemble_state(profile, _candidate(), GREEDY_CONTENT, conclusions="c" * 100).state
    assert "conclusions" not in off["candidate"]
    assert on["candidate"]["conclusions"] == "c" * 100


# ── the enrichment two-pass (jev-first): hermetic through the cache ─────────────


def _rss_ids():
    from arjev.feed import parse_arxiv_rss

    return [i.arxiv for i in parse_arxiv_rss(RSS.read_text())]


def test_jev_first_enrichment_rescores_finalists_with_conclusions(monkeypatch, tmp_path):
    """Pre-populated cache = hermetic: the digest's enrich closure hits the cache for
    every finalist, re-scores each with the conclusions in the state, and the mode
    line says the content arm ran."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.digest import run_digest
    from arjev.paper_content import write_sections_cache

    for arxiv in _rss_ids():
        write_sections_cache(arxiv, {"conclusions": "outlook: the two-cat unit cell next."})
    transport = FakeTransport()
    cfg = digest_cfg()
    cfg.candidate_content = True
    cfg.candidate_pace_s = 0.0
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", jev_client=client(transport))
    first_pass = len(_rss_ids())
    assert len(transport.calls) == first_pass + len(_rss_ids()), "every finalist is re-scored once"
    rescore_states = [p["state"] for p in transport.calls[first_pass:]]
    assert all(s["candidate"]["conclusions"] for s in rescore_states)
    assert "content: finalists" in result.mode


def test_jev_first_without_the_arm_makes_one_call_per_item(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    from arjev.digest import run_digest

    transport = FakeTransport()
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s", jev_client=client(transport))
    assert len(transport.calls) == len(_rss_ids())
    assert "content: finalists" not in result.mode


def test_jev_first_enrichment_fail_open_keeps_first_pass_mass(monkeypatch, tmp_path):
    """The fetch seam injected to fail: every finalist gets no conclusions — the
    enrichment refines nothing and breaks nothing (the first-pass masses stand)."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.digest import run_digest

    monkeypatch.setattr("arjev.digest.candidate_conclusions", lambda arxiv, cache_dir: None)
    transport = FakeTransport()
    cfg = digest_cfg()
    cfg.candidate_content = True
    cfg.candidate_pace_s = 0.0
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", jev_client=client(transport))
    assert len(transport.calls) == len(_rss_ids()), "no conclusions → no re-scores, all first-pass"
    assert result.picks, "fail-open still ships the ranking"


# ── calibration: the enriched receipt supersedes; the arms instrument ───────────


def test_latest_receipts_dedups_the_rescored_pair():
    from arjev.calibrate import _latest_receipts

    receipts = [
        {"run_id": "r1", "candidate_arxiv": "2601.01011", "primitive": "score", "distribution": {"must-read": 0.2}},
        {"run_id": "r1", "candidate_arxiv": "2601.01011", "primitive": "score", "distribution": {"must-read": 0.9}},
        {"run_id": "r1", "candidate_arxiv": "2601.01012", "primitive": "score", "distribution": {"must-read": 0.5}},
    ]
    latest = {(r["candidate_arxiv"], r["distribution"]["must-read"]) for r in _latest_receipts(receipts)}
    assert latest == {("2601.01011", 0.9), ("2601.01012", 0.5)}


def test_calibrate_arms_reports_n_zero_honestly(monkeypatch, tmp_path):
    """No labels → the arms short-circuit before any Jev call, and say so."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.calibrate import calibrate_arms
    from arjev.fold import fold_roots

    cfg = digest_cfg()
    transport = FakeTransport()
    report = calibrate_arms(cfg, fold_roots(cfg.expanded_roots, cfg), client(transport),
                            lambda ids: {}, runs=5)
    assert report.metrics["replay_arms"] == {"n": 0}
    assert any("n = 0" in n for n in report.notes)
    assert transport.calls == [], "zero labeled candidates → zero Jev calls"


def test_calibrate_arms_rescores_labeled_candidates_per_arm(monkeypatch, tmp_path):
    """A labeled, journaled candidate: each arm re-scores it once — the A/B the
    default flip gates on, with n stated."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.calibrate import calibrate_arms
    from arjev.fold import fold_roots
    from arjev.ledger import Label, LabelLedger, now_ts
    from arjev.rerank import journal_path

    ledger = LabelLedger()
    ledger.append(Label(arxiv_id="2601.01011", label_type="keep", source="cli-keep", ts=now_ts()))
    journal_path().parent.mkdir(parents=True, exist_ok=True)
    journal_path().write_text(json.dumps({
        "run_id": "r1", "ts": "t", "feed": "f", "mode": "m", "seed": "s",
        "candidates": [{"arxiv": "2601.01011", "pool": "survivor", "lexical_score": 1.0,
                        "terms": ["x"], "jev": None, "posted": True, "rescued": None,
                        "title": "Jitter-robust control", "authors": []}],
    }) + "\n")
    transport = FakeTransport()
    cfg = digest_cfg()
    report = calibrate_arms(cfg, fold_roots(cfg.expanded_roots, cfg), client(transport),
                            lambda ids: {i: {"title": "t", "abstract": "a"} for i in ids}, runs=5)
    arm_metrics = {k: v for k, v in report.metrics.items() if k.startswith("arm_")}
    assert len(arm_metrics) == 6, "fixed-15 / greedy@4KB / greedy@8KB × content on/off"
    assert all(v["n"] == 1 for v in arm_metrics.values())
    assert all(v["brier"] is not None for v in arm_metrics.values())
    arms_receipts = (tmp_path / "state" / "arjev" / "arms" / "jev-receipts.jsonl")
    assert arms_receipts.is_file(), "arm receipts never join the production file"
    assert len(arms_receipts.read_text().splitlines()) >= 6
    production = tmp_path / "state" / "arjev" / "jev-receipts.jsonl"
    assert not production.is_file(), "the arms run must not touch the production receipts"

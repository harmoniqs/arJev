"""Review tests: the week-in-review is a pure re-read of the journal, receipts,
and label ledger — the same three sources calibrate joins — with every section
n-stated and the whole surface read-only (issue #83)."""

import json
from datetime import date

import pytest

from arjev.rerank import journal_path, state_dir
from arjev.review import review

TODAY = date(2026, 10, 8)
TODAY_S = "2026-10-08T09:00:00+00:00"
OLD_S = "2026-09-20T09:00:00+00:00"


def _cand(arxiv, title, *, jev_conf, lexical, pool="survivor", posted=False, authors=(), top="worth-reading"):
    return {
        "arxiv": arxiv,
        "title": title,
        "jev": (
            {"primitive": "score", "confidence": jev_conf, "top": top} if jev_conf is not None else None
        ),
        "lexical_score": lexical,
        "pool": pool,
        "posted": posted,
        "rescued": None,
        "slack_ts": "",
        "terms": [],
        "authors": list(authors),
    }


def _run(run_id, ts, candidates, ranking="jev-first"):
    return {
        "run_id": run_id,
        "ts": ts,
        "feed": "quant-ph",
        "mode": "mode: jev, ok",
        "seed": "s",
        "slack_channel": None,
        "ranking": ranking,
        "candidates": candidates,
    }


def _write_state(journal: list[dict], receipts: list[dict] | None = None) -> None:
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    journal_path().write_text("".join(json.dumps(j) + "\n" for j in journal))
    if receipts is not None:
        (sd / "jev-receipts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in receipts))


def _seed_ledger(rows: list[tuple[str, str]]) -> None:
    from arjev.ledger import Label, LabelLedger

    ledger = LabelLedger()
    for arxiv, label_type in rows:
        assert ledger.append(
            Label(arxiv_id=arxiv, label_type=label_type, source="cli-keep", ts="2026-10-08T12:00:00+00:00")
        )


# ── the window ───────────────────────────────────────────────────────────────────


def test_window_filters_runs_by_days():
    """--days N keeps only runs whose ts falls inside the window; the counts in
    the report are the window's, never the whole journal's."""
    recent = _run("r2", TODAY_S, [_cand("2610.00001", "recent paper", jev_conf=0.6, lexical=10.0)])
    old = _run("r1", OLD_S, [_cand("2609.00001", "old paper", jev_conf=0.9, lexical=20.0)])
    _write_state([old, recent])
    seven = review(days=7, now=TODAY)
    assert [r["run_id"] for r in seven.window_runs] == ["r2"]
    thirty = review(days=30, now=TODAY)
    assert [r["run_id"] for r in thirty.window_runs] == ["r1", "r2"]


def test_empty_window_is_honest_not_an_error():
    """All runs outside the window renders an empty report naming the window,
    exit-clean — an empty week is information, not a failure."""
    _write_state([_run("r1", OLD_S, [_cand("2609.00001", "old paper", jev_conf=0.9, lexical=1.0)])])
    report = review(days=7, now=TODAY)
    assert report.window_runs == []
    text = report.render()
    assert "no runs in the window" in text


def test_missing_journal_fails_loud():
    """No journal at all is an error, never a silently empty review."""
    with pytest.raises(FileNotFoundError):
        review(days=7, now=TODAY)


# ── the four sections ────────────────────────────────────────────────────────────


def test_the_buried_ranks_never_posted_by_jev_confidence():
    """The cap's casualties, best-first: never-posted candidates ranked by Jev
    confidence; posted candidates never appear; the section states its n."""
    posted = _cand("2610.00009", "posted paper", jev_conf=0.99, lexical=100.0, posted=True)
    buried_mid = _cand("2610.00002", "buried mid", jev_conf=0.5, lexical=1.0)
    buried_best = _cand("2610.00003", "buried best", jev_conf=0.9, lexical=2.0)
    _write_state([_run("r1", TODAY_S, [posted, buried_mid, buried_best])])
    report = review(days=7, now=TODAY)
    assert [c["arxiv"] for c in report.buried] == ["2610.00003", "2610.00002"]
    text = report.render()
    assert "2610.00003" in text and "buried best" in text
    assert "2610.00009" not in text.split("## The Buried", 1)[1].split("##", 1)[0]


def test_the_buried_ranks_by_relevance_not_by_certainty_in_any_label():
    """Found live 2026-10-25: the review ranked by Jev's confidence in its TOP
    label, so papers Jev was 100% sure were *irrelevant* led "The Buried". The
    journal carries (top, confidence); relevance is confidence for a relevant top
    label and 1 - confidence otherwise — the same must-read + worth-reading mass
    the digest ranks by, bounded from the one label the journal keeps."""
    junk = _cand("2610.00040", "speech benchmark", jev_conf=1.0, lexical=1.0, top="irrelevant")
    unsure_good = _cand("2610.00041", "quantum hardware", jev_conf=0.44, lexical=50.0, top="worth-reading")
    must = _cand("2610.00042", "control paper", jev_conf=0.8, lexical=40.0, top="must-read")
    _write_state([_run("r1", TODAY_S, [junk, unsure_good, must])])
    report = review(days=7, now=TODAY)
    assert [c["arxiv"] for c in report.buried] == ["2610.00042", "2610.00041"]  # junk is never "buried"
    assert "2610.00040" not in [c["arxiv"] for c in report.jev_hot]  # nor "jev-hot"
    assert "of 2 relevant, never posted" in report.render()


def test_the_buried_dedupes_across_runs_keeping_best_confidence():
    """The same paper recurring across runs is one buried line, at its best Jev
    confidence — the week's view, not the firehose's."""
    first = _run("r1", "2026-10-06T09:00:00+00:00", [_cand("2610.00003", "recurring", jev_conf=0.4, lexical=1.0)])
    second = _run("r2", TODAY_S, [_cand("2610.00003", "recurring", jev_conf=0.9, lexical=1.0)])
    _write_state([first, second])
    report = review(days=7, now=TODAY)
    assert len(report.buried) == 1
    assert report.buried[0]["jev"]["confidence"] == 0.9


def test_your_people_lists_author_lane_matches_posted_or_not():
    """The week's author-signal matches — candidates carrying matched authors —
    posted or not, one line each with the author named."""
    match_posted = _cand(
        "2610.00010", "tracked person's paper", jev_conf=0.8, lexical=5.0, posted=True, authors=["Ahmad Salmanogli"]
    )
    match_buried = _cand("2610.00011", "another tracked paper", jev_conf=0.3, lexical=5.0, authors=["Sebastien Leger"])
    plain = _cand("2610.00012", "anonymous paper", jev_conf=0.7, lexical=5.0)
    _write_state([_run("r1", TODAY_S, [match_posted, match_buried, plain])])
    report = review(days=7, now=TODAY)
    assert [c["arxiv"] for c in report.people] == ["2610.00010", "2610.00011"]
    text = report.render()
    assert "Ahmad Salmanogli" in text
    assert "2610.00012" not in text.split("## Your People", 1)[1].split("##", 1)[0]


def test_the_divergences_show_both_tails_by_rank_gap():
    """Jev-hot-but-lexical-buried and lexical-hot-but-Jev-cold, by rank gap
    within the run — the two tails, both named, biggest gap first (a
    regression guard: ascending-by-gap once surfaced gap-1 noise as the top)."""
    jev_hot_big = _cand("2610.00020", "jev loved, words buried", jev_conf=0.95, lexical=1.0)
    jev_hot_small = _cand("2610.00024", "jev liked, words shrugged", jev_conf=0.9, lexical=5.0)
    lexical_hot_big = _cand("2610.00021", "words loved, jev cold", jev_conf=0.05, lexical=100.0)
    lexical_hot_small = _cand("2610.00025", "words liked, jev meh", jev_conf=0.5, lexical=10.0)
    _write_state([_run("r1", TODAY_S, [jev_hot_big, jev_hot_small, lexical_hot_big, lexical_hot_small])])
    report = review(days=7, now=TODAY)
    assert [c["arxiv"] for c in report.jev_hot] == ["2610.00020", "2610.00024"]
    assert [c["arxiv"] for c in report.lexical_hot] == ["2610.00021", "2610.00025"]
    text = report.render()
    assert "jev-hot" in text and "lexical-hot" in text


def test_the_divergences_skip_unscored_candidates():
    """A candidate with no Jev row (fail-open) has no divergence to report — it
    never crashes the section and never appears in either tail. The live journal
    also carries {fail_reason}-only rows with no confidence: same rule."""
    unscored = _cand("2610.00030", "jev failed open", jev_conf=None, lexical=10.0)
    unscored_fail_open = _cand("2610.00032", "fail-reason only", jev_conf=None, lexical=10.0)
    unscored_fail_open["jev"] = {"fail_reason": "state overflow"}
    scored = _cand("2610.00031", "scored paper", jev_conf=0.5, lexical=9.0)
    _write_state([_run("r1", TODAY_S, [unscored, unscored_fail_open, scored])])
    report = review(days=7, now=TODAY)
    assert report.jev_hot == [] and report.lexical_hot == []
    # a fail-open row never ranks in the buried: it carries no mass, but the
    # scored never-posted candidate does
    assert [c["arxiv"] for c in report.buried] == ["2610.00031"]


def test_the_weeks_receipts_carry_calibration_headline_with_honest_n():
    """Kept/ignored counts plus the calibration headline (precision@5, Brier n),
    every n stated; an unlabeled week says so plainly instead of reading hollow."""
    posted_kept = _cand("2610.00040", "kept pick", jev_conf=0.9, lexical=10.0, posted=True)
    posted_skipped = _cand("2610.00041", "skipped pick", jev_conf=0.8, lexical=9.0, posted=True)
    _write_state([_run("r1", TODAY_S, [posted_kept, posted_skipped])])
    unlabelled = review(days=7, now=TODAY)
    assert unlabelled.receipts_counts["posted"] == 2
    assert unlabelled.receipts_counts["kept"] == 0
    assert "no labels yet" in unlabelled.render()

    _seed_ledger([("2610.00040", "keep"), ("2610.00041", "skip")])
    labelled = review(days=7, now=TODAY)
    assert labelled.receipts_counts["kept"] == 1
    assert labelled.receipts_counts["skipped"] == 1
    text = labelled.render()
    assert "precision@5" in text
    assert "kept 1" in text and "skipped 1" in text


# ── the invariants ───────────────────────────────────────────────────────────────


def test_review_is_read_only():
    """The review proposes, never stages: journal, receipts, and ledger are
    byte-identical before and after; no new file appears in the state dir."""
    _write_state([_run("r1", TODAY_S, [_cand("2610.00050", "paper", jev_conf=0.7, lexical=1.0, posted=True)])])
    _seed_ledger([("2610.00050", "keep")])
    sd = state_dir()
    before = {p.name: p.read_bytes() for p in sd.iterdir() if p.is_file()}
    review(days=7, now=TODAY)
    after = {p.name: p.read_bytes() for p in sd.iterdir() if p.is_file()}
    assert after == before


def test_review_makes_no_jev_calls_and_no_fetches(monkeypatch):
    """Zero network, zero Jev: any JevClient or fetch surface touched during a
    review is a design violation, and this test fails it loudly."""
    from arjev import jev as jev_mod
    from arjev import paper_content as pc_mod

    def _poisoned(*args, **kwargs):
        raise AssertionError("review must be a pure re-read — no Jev/fetch calls")

    monkeypatch.setattr(jev_mod.JevClient, "score_relevance", _poisoned)
    monkeypatch.setattr(jev_mod.JevClient, "__init__", _poisoned)
    monkeypatch.setattr(pc_mod, "fetch_metadata", _poisoned, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", _poisoned)
    _write_state([_run("r1", TODAY_S, [_cand("2610.00060", "paper", jev_conf=0.7, lexical=1.0)])])
    review(days=7, now=TODAY)


# ── the CLI surface ─────────────────────────────────────────────────────────────


def test_cli_review_prints_the_report(capsys):
    from arjev.cli import main

    _write_state([_run("r1", TODAY_S, [_cand("2610.00070", "paper", jev_conf=0.7, lexical=1.0)])])
    rc = main(["review"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "# arjev week-in-review" in out
    assert "## The Buried" in out and "## The Week's Receipts" in out


def test_cli_review_days_flag():
    from arjev.cli import main

    _write_state(
        [
            _run("r1", OLD_S, [_cand("2609.00001", "old", jev_conf=0.9, lexical=1.0)]),
            _run("r2", TODAY_S, [_cand("2610.00001", "recent", jev_conf=0.5, lexical=1.0)]),
        ]
    )
    rc = main(["review", "--days", "30"])
    assert rc == 0
    # window covers both runs; the report states the window, not just defaults


def test_cli_review_missing_journal_exits_with_plain_error(capsys):
    from arjev.cli import main

    rc = main(["review"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "digest first" in err


def test_post_review_hands_the_report_to_the_client_seam():
    """--post slack routes through post_review's client seam — the ingest/digest
    pattern — so the posting path stays testable offline."""
    from arjev.config import Config
    from arjev.review import post_review

    posted = []

    class _FakeSlack:
        def post_message(self, channel, text):
            posted.append((channel, text))
            return "0000.0001"

    cfg = Config()
    cfg.slack_channel = "C123"
    _write_state([_run("r1", TODAY_S, [_cand("2610.00080", "paper", jev_conf=0.7, lexical=1.0)])])
    report = review(days=7, now=TODAY)
    post_review(cfg, report, slack_client=_FakeSlack())
    assert posted == [("C123", report.render())]


def test_post_review_requires_a_configured_channel():
    """No slack_channel configured is a plain-language error, never a crash."""
    from arjev.config import Config
    from arjev.review import post_review

    _write_state([_run("r1", TODAY_S, [_cand("2610.00080", "paper", jev_conf=0.7, lexical=1.0)])])
    report = review(days=7, now=TODAY)
    with pytest.raises(SystemExit, match="slack-setup"):
        post_review(Config(), report)

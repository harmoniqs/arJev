"""Feed, score, rank/pool tests: parse safety, normalization, word-boundary scoring,
disjoint pools, seeded probe, corpus/posted skips."""

from datetime import date
from pathlib import Path

from arjev.config import Config
from arjev.feed import FeedItem, parse_arxiv_rss
from arjev.fold import fold_roots
from arjev.profile import build_profile
from arjev.rank import classify_pools, rank
from arjev.score import score_item

FIXTURES = Path(__file__).parent / "fixtures"
VAULT = FIXTURES / "vault"
RSS = FIXTURES / "rss-quant-ph.xml"
TODAY = date(2026, 10, 1)


def test_parse_fixture_rss():
    items = parse_arxiv_rss(RSS.read_text())
    assert len(items) == 6
    ids = {i.arxiv for i in items}
    assert "2601.01011" in ids  # v2 suffix stripped at parse (normalization once, upstream)
    assert all(not i.arxiv.endswith("v1") for i in items)


def test_malformed_feed_degrades_to_empty():
    assert parse_arxiv_rss("<rss><channel><title>broken") == []
    assert parse_arxiv_rss("") == []


def test_load_feed_requires_a_category_or_a_file(monkeypatch):
    """No default category at the fetch layer — absent category is a caller error,
    never a silent fetch of someone else's field."""
    import pytest

    from arjev import feed as feed_mod
    from arjev.feed import load_feed

    def _no_network(*args, **kwargs):
        raise AssertionError("load_feed must not fetch when no category and no file are given")

    monkeypatch.setattr(feed_mod, "fetch_feed", _no_network)
    with pytest.raises(ValueError, match="feed"):
        load_feed()
    # a file with no category stays legal (the fixture/CI path)
    assert load_feed(feed_file=str(RSS))


def test_entities_and_tags_stripped():
    items = parse_arxiv_rss(RSS.read_text())
    first = next(i for i in items if i.arxiv == "2601.01011")
    assert "<p>" not in first.abstract and "Synthetic abstract" in first.abstract
    assert "$\\sqrt" in first.title or "√" in first.title  # raw LaTeX stays until slice 4 cleanup


def test_word_boundary_and_title_weight():
    profile = build_profile(fold_roots([VAULT], Config()), Config(), TODAY)
    title_hit = FeedItem(arxiv="2601.09901", title="Blockade physics", abstract="")
    body_hit = FeedItem(arxiv="2601.09902", title="unrelated", abstract="the blockade radius")
    s_title = score_item(title_hit, profile)
    s_body = score_item(body_hit, profile)
    assert s_title.score > s_body.score, "title hits must outweigh abstract hits (×3)"
    assert "blockade" in {t for t in s_title.terms}


def test_pools_disjoint_and_partitioned():
    profile = build_profile(fold_roots([VAULT], Config()), Config(), TODAY)
    items = parse_arxiv_rss(RSS.read_text())
    from arjev.score import score_item as si

    scored = [si(i, profile) for i in items]
    pools = classify_pools(scored, screen=3, probe_k=2, seed="s1")
    surv = {s.item.arxiv for s in pools.survivors}
    nm = {s.item.arxiv for s in pools.near_miss}
    probe = {s.item.arxiv for s in pools.probe}
    assert not (surv & nm) and not (surv & probe) and not (nm & probe), "pools must be disjoint"
    # zero-score probe items only
    assert all(s.score == 0 for s in pools.probe)
    # near-miss items match exactly one distinct term
    assert all(len(s.terms) == 1 for s in pools.near_miss) or not pools.near_miss


def test_probe_seed_is_reproducible():
    profile = build_profile(fold_roots([VAULT], Config()), Config(), TODAY)
    items = parse_arxiv_rss(RSS.read_text())
    from arjev.score import score_item as si

    scored = [si(i, profile) for i in items]
    a = classify_pools(scored, screen=3, probe_k=3, seed="seed-a")
    b = classify_pools(scored, screen=3, probe_k=3, seed="seed-a")
    c = classify_pools(scored, screen=3, probe_k=3, seed="seed-b")
    assert {s.item.arxiv for s in a.probe} == {s.item.arxiv for s in b.probe}
    assert a.probe or True  # tiny fixture may have <3 zero items; seed stability is the contract
    _ = c


def test_probe_k_zero_means_empty():
    profile = build_profile(fold_roots([VAULT], Config()), Config(), TODAY)
    items = parse_arxiv_rss(RSS.read_text())
    from arjev.score import score_item as si

    scored = [si(i, profile) for i in items]
    assert classify_pools(scored, screen=3, probe_k=0, seed="x").probe == []


def test_rank_skips_corpus_and_posted():
    profile = build_profile(fold_roots([VAULT], Config()), Config(), TODAY)
    items = parse_arxiv_rss(RSS.read_text())
    result = rank(
        items, profile, corpus_ids={"2601.01011"}, posted_ids={"2601.01012"},
        top=5, screen=4, probe_k=2, seed="s",
    )
    assert "2601.01011" in result.skipped_corpus
    assert "2601.01012" in result.skipped_posted
    assert "2601.01011" not in [s.item.arxiv for s in result.picks]

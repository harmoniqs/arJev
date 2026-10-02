"""The identity seam (#57): every feed item carries a normalized (source, id) pair
populated once at parse; every join — ranking, journal, labels, keep — routes through
the pair; a hypothetical non-arxiv source flows the join path untouched, while the
fetch path stays arXiv-only and errors loudly on anything else.

Zero behavior change for today's all-arxiv data: the 111-test suite is the freeze.
These tests exercise ONLY the pair routing — no fetcher, no network, no new source."""

from datetime import UTC, datetime

import pytest

from arjev.config import Config
from arjev.feed import ARXIV, FeedItem, Identity, arxiv_namespace, parse_arxiv_rss
from arjev.fold import fold_roots
from arjev.jev import JevClient
from arjev.keep import KeepCandidate, fetch_pdf, scaffold_note
from arjev.labels import arrival_labels
from arjev.ledger import LabelLedger
from arjev.profile import build_profile
from arjev.rank import rank
from arjev.rerank import apply_jev, apply_jev_first
from arjev.score import score_item
from arjev.state import PostedState
from conftest import RSS, TODAY, VAULT
from test_jev import FakeTransport

NOW = datetime(2026, 10, 1, tzinfo=UTC)
# the frozen journal-row schema — the seam may not add fields (byte-identical journal)
JOURNAL_ROW_FIELDS = {"arxiv", "pool", "lexical_score", "terms", "jev", "posted",
                      "rescued", "title", "authors", "slack_ts"}


def _profile():
    return build_profile(fold_roots([VAULT], Config()), Config(), TODAY)


def _client(transport=None):
    return JevClient(key="seam-key", transport=transport or FakeTransport())


# ── the pair is populated at parse, normalized where the item is born ──────────────

def test_parse_populates_the_normalized_pair():
    items = parse_arxiv_rss(RSS.read_text())
    assert items and all(i.source == ARXIV for i in items)
    assert all(i.identity == Identity(ARXIV, i.arxiv) for i in items)
    # the id half was normalized once, upstream: the v2 suffix never survives parse
    twin = next(i for i in items if i.arxiv == "2601.01011")
    assert twin.identity == Identity(ARXIV, "2601.01011")


def test_source_half_normalizes_where_the_item_is_born():
    # a future adapter's items are born at construction — the source is normalized
    # there, so an unnormalized spelling can never leak into the joins
    hypothetical = FeedItem(arxiv="35123456", title="t", abstract="", source="PubMed")
    assert hypothetical.identity == Identity("pubmed", "35123456")


# ── the ranking join observes the pair, not the bare id ───────────────────────────

def test_ranking_join_discriminates_same_id_different_source():
    items = [
        FeedItem(arxiv="2601.01001", title="Synthetic: randomized compiling calibration", abstract=""),
        FeedItem(arxiv="2601.01001", title="Synthetic: randomized compiling calibration", abstract="",
                 source="pubmed"),
    ]
    result = rank(items, _profile(), corpus_ids={"2601.01001"}, posted_ids=set(),
                  top=5, screen=5, probe_k=0, seed="s")
    # the vault corpus is the arxiv namespace: only the arxiv twin is skipped; the
    # pubmed pair flows through — a bare-id join would have skipped both twins
    assert result.skipped_corpus == ["2601.01001"]
    assert {p.item.identity for p in result.picks} == {Identity("pubmed", "2601.01001")}


# ── the journal join: a hypothetical non-arxiv pair flows the whole path ──────────

def test_non_arxiv_pair_flows_the_journal_join():
    pubmed_survivor = FeedItem(arxiv="35123456", title="Synthetic: blockade-assisted compiling",
                               abstract="blockade radius calibration", source="pubmed")
    pubmed_zero = FeedItem(arxiv="35123457", title="Classical simulation of markets", abstract="",
                           source="pubmed")
    items = parse_arxiv_rss(RSS.read_text()) + [pubmed_survivor, pubmed_zero]
    profile = _profile()
    ranked = rank(items, profile, corpus_ids=set(), posted_ids=set(),
                  top=10, screen=8, probe_k=2, seed="s")
    receipts: list = []
    picks, mode, candidates = apply_jev(ranked, _client(), profile, "run-seam", receipts, top=10)
    assert mode == "jev", "the fake transport answers every call"
    # the pubmed survivor is picked with its pair intact, and the pubmed zero-score
    # item rides the probe pool through the same join
    assert {p.identity for p in picks} >= {Identity("pubmed", "35123456"), Identity("pubmed", "35123457")}
    rows = {c.arxiv: c for c in candidates}
    assert rows["35123456"].pool == "survivor" and rows["35123456"].posted
    assert rows["35123456"].jev["primitive"] == "score" and rows["35123456"].jev["top"] == "must-read"
    assert rows["35123457"].pool == "probe" and rows["35123457"].rescued == "probe"
    assert rows["35123457"].jev["primitive"] == "noul"
    # the frozen journal-row schema survives the flow — no field added for the pair
    assert all(set(vars(c)) == JOURNAL_ROW_FIELDS for c in candidates)


def test_jev_first_join_observes_the_pair():
    items = [
        FeedItem(arxiv="2601.01011", title="Synthetic: randomized compiling", abstract=""),
        FeedItem(arxiv="2601.01011", title="Synthetic: randomized compiling", abstract="", source="pubmed"),
    ]
    profile = _profile()
    # the digest convention: the skip set and the score index are identity-keyed;
    # the vault corpus is the arxiv namespace of the pair
    skip = arxiv_namespace({"2601.01011"})
    scored_by_id = {i.identity: score_item(i, profile) for i in items if i.identity not in skip}
    transport = FakeTransport()
    picks, mode, candidates = apply_jev_first(items, scored_by_id, skip, _client(transport), profile,
                                             "run", [], top=5, pace_s=0)
    # only the pubmed twin is eligible — the arxiv twin is vault-known and skipped
    assert len(transport.calls) == 1
    assert {p.identity for p in picks} == {Identity("pubmed", "2601.01011")}
    assert [c.arxiv for c in candidates] == ["2601.01011"]
    assert candidates[0].pool == "survivor" and candidates[0].posted


# ── the labels join observes the pair — the fold is the source-prefixed anchor ────

def test_labels_join_does_not_cross_sources(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "paper-doi.md").write_text(
        "---\ntype: paper\ndoi: \"2601.01001\"\ntitle: \"A DOI twin\"\n"
        "why: \"why not\"\nrating: core\n---\nbody")
    cfg = Config()
    cfg.roots = [str(vault)]
    fold = fold_roots(cfg.expanded_roots, cfg)
    assert {p.identity for p in fold.papers} == {"doi:2601.01001"}
    # an arxiv-namespace posting whose id STRING collides with the doi twin's:
    # the pair join must not let the doi identity absorb the arXiv posting
    ledger = LabelLedger(tmp_path / "l.jsonl")
    posted = PostedState(ids=["2601.01001"], updated="2026-08-20T00:00:00Z", path=tmp_path / "s.json")
    journal = [{"candidates": [{"arxiv": "2601.01001", "posted": True}], "ts": "2026-08-20T13:00:00Z"}]
    new = arrival_labels(fold, posted, journal, ledger, NOW)
    assert [r.label_type for r in new] == ["unsaved-weak-negative"], (
        "the doi twin is a different identity — the arXiv posting stays unsaved")


# ── the keep join observes the pair ───────────────────────────────────────────────

def test_keep_join_discriminates_same_id_different_source(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "paper-existing.md").write_text(
        '---\ntype: paper\narxiv: "2601.01001"\ntitle: "hand-written"\n---\nkeep my note')
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    # the arxiv candidate matches the note that owns the identity pair — never edited
    same = scaffold_note(KeepCandidate("2601.01001", "other title", []), cfg, TODAY, papers_dir=papers)
    assert same == papers / "paper-existing.md"
    # the pubmed twin carries a different identity — it scaffolds its own stub
    twin = scaffold_note(KeepCandidate("2601.01001", "pubmed twin", [], source="pubmed"), cfg, TODAY,
                         papers_dir=papers)
    assert twin != same and twin.is_file()


# ── the fetch path stays arxiv-only and errors loudly on anything else ───────────

def test_fetch_is_arxiv_only_and_errors_loudly(tmp_path):
    # a pubmed-style id must never silently ride the arXiv fetcher
    with pytest.raises(ValueError, match="arXiv-only"):
        fetch_pdf("35123456", tmp_path / "library", fetcher=lambda url: b"")
    target = fetch_pdf("2601.01011", tmp_path / "library", fetcher=lambda url: b"%PDF-1.4 seam")
    assert target.read_bytes().startswith(b"%PDF")

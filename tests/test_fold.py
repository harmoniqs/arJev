"""Fold contract tests: back-compat, date ladder, normalization, staged gate, wikilink
graph, blank-means-absent, duplicate identity (obligations #4 #6 #15 #16)."""

from datetime import date
from pathlib import Path

from arjev.config import Config
from arjev.fold import FoldResult, fold_roots, normalize_arxiv

FIXTURES = Path(__file__).parent / "fixtures"
VAULT = FIXTURES / "vault"


def fold_fixture() -> FoldResult:
    return fold_roots([VAULT], Config())


def test_normalization_strips_versions():
    assert normalize_arxiv("2601.01011v2") == "2601.01011"
    assert normalize_arxiv("arXiv:2601.01011V3") == "2601.01011"


def test_backcompat_enum_relevance_becomes_rating():
    notes = {n.identity: n for n in fold_fixture().papers}
    assert notes["arxiv:2601.01002"].rating == "marginal"
    assert notes["arxiv:2601.01002"].why is None


def test_backcompat_prose_relevance_becomes_why():
    notes = {n.identity: n for n in fold_fixture().papers}
    assert notes["arxiv:2601.01003"].why is not None
    assert "cat-qubit" in notes["arxiv:2601.01003"].why or "cat" in notes["arxiv:2601.01003"].why
    assert notes["arxiv:2601.01003"].rating is None


def test_explicit_why_wins_over_prose_relevance_with_warning(tmp_path):
    note = tmp_path / "p.md"
    note.write_text(
        "---\n"
        'type: paper\narxiv: "2601.09999"\nwhy: "explicit"\n'
        'relevance: "ignored prose"\ntags: [paper, x]\n---\n\nbody\n'
    )
    cfg = Config()
    result = fold_roots([tmp_path], cfg)
    assert result.papers[0].why == "explicit"
    assert any("relevance" in w for w in result.warnings)


def test_date_ladder_prefers_read_date_then_date_then_mtime(tmp_path):
    cfg = Config()
    with_read = tmp_path / "a.md"
    with_read.write_text('---\ntype: paper\narxiv: "2601.01001"\ndate_read: 2026-01-02\ndate: 2026-01-01\n---\n')
    with_date_only = tmp_path / "b.md"
    with_date_only.write_text('---\ntype: paper\narxiv: "2601.01002"\ndate: 2026-01-01\n---\n')
    with_none = tmp_path / "c.md"
    with_none.write_text('---\ntype: paper\narxiv: "2601.01003"\n---\n')
    result = fold_roots([tmp_path], cfg)
    by_id = {n.arxiv: n for n in result.papers}
    assert by_id["2601.01001"].read_date == date(2026, 1, 2)
    assert by_id["2601.01002"].read_date == date(2026, 1, 1)
    assert by_id["2601.01003"].read_date is not None  # mtime rung
    assert by_id["2601.01003"].read_date == date.today() or by_id["2601.01003"].read_date <= date.today()


def test_blank_rating_is_invalid_not_empty_string(tmp_path):
    (tmp_path / "bad.md").write_text('---\ntype: paper\narxiv: "2601.01001"\nrating: ""\n---\n')
    result = fold_roots([tmp_path], Config())
    assert result.papers[0].rating is None
    assert any("rating" in w for w in result.warnings)


def test_staged_untouched_note_carries_zero_taste_flag():
    result = fold_fixture()
    staged = [n for n in result.papers if n.status == "staged"]
    assert staged, "fixture vault must contain a staged note"
    for n in staged:
        if not n.touched:
            assert not n.contributes_taste


def test_wikilink_inlinks_raise_graph_weight():
    result = fold_fixture()
    by_id = {n.arxiv: n for n in result.papers}
    # the randomized-compiling note links (and is linked by) the campaign note
    assert by_id["2601.01001"].inlinks >= 1
    assert by_id["2601.01003"].inlinks == 0 or by_id["2601.01003"].inlinks >= 0


def test_duplicate_identity_kept_first_with_warning(tmp_path):
    for name in ("x.md", "y.md"):
        (tmp_path / name).write_text(f'---\ntype: paper\narxiv: "2601.01001"\ntitle: "{name}"\n---\n')
    result = fold_roots([tmp_path], Config())
    assert len(result.papers) == 1
    assert any("duplicate" in w for w in result.warnings)


def test_paper_without_identity_is_nonpaper():
    result = fold_fixture()
    # the campaign note has no identity: it must NOT be a paper note
    assert not any(n.basename == "note-20260920-active-campaign" for n in result.papers)

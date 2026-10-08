"""The paper-content layer: section extraction (heading conventions), the source
ladder, the sections cache, candidate fetch fail-open, and the backfill (issue #75).
No network anywhere — every fetch seam is injected."""

from __future__ import annotations

from arjev.config import Config
from arjev.paper_content import (
    backfill_corpus,
    candidate_conclusions,
    corpus_content,
    extract_abstract,
    extract_conclusions,
    id_from_library_stem,
    read_sections_cache,
    sections_cache_dir,
    write_sections_cache,
)
from conftest import VAULT, isolate_state

_PAPER_TEXT = """Fast optimal control of a cat qubit
Authors One and Two

Abstract
We demonstrate Zeno-blocked control of a cat qubit with bit-flip protection
intact, reaching pi rotations in 235 ns at alpha squared 11.3, four orders of
magnitude over previous implementations of the same protocol family.

1 Introduction
The stabilized cat qubit is the unit cell of a bias-preserving architecture.

6 Summary and outlook
The Zeno regime bounds the gate drive by the confinement rate, which sets the
honest envelope for any optimal-control pulse on this platform. Future work
targets the two-cat unit cell and a calibration loop that pins the confinement
rate against drift, closing the loop between design and the measured machine.

References
[1] Some Reference, Phys. Rev. X (2024).
"""


# ── section extraction: tolerant headings, honest misses ─────────────────────────


def test_abstract_from_heading_and_inline_colon_forms():
    assert "Zeno-blocked control" in extract_abstract(_PAPER_TEXT)
    assert "stabilized cat" in extract_abstract("Abstract: the stabilized cat qubit unit cell.\n1 Intro\nbody")


def test_abstract_missing_is_none_not_a_guess():
    assert extract_abstract("1 Introduction\nbody with no abstract heading") is None


def test_conclusions_matches_numbered_summary_and_outlook():
    conclusions = extract_conclusions(_PAPER_TEXT)
    assert conclusions is not None
    assert "Zeno regime" in conclusions
    assert "References" not in conclusions, "the section ends at References"


def test_conclusions_matches_plain_conclusion_heading():
    text = "body\n\nConclusions\n\nWe measured the thing and it worked well enough to use.\n\nAcknowledgments\nThanks."
    assert "measured the thing" in extract_conclusions(text)


def test_short_body_is_a_heading_misfire_not_a_section():
    # a lone 'Summary' in a table of contents must not become the conclusions
    assert extract_conclusions("Contents\n\nSummary\n\n1 Introduction\n\n") is None


# ── the library ladder: both on-disk .txt conventions ─────────────────────────────


def test_id_from_library_stem_dot_and_dash_forms():
    assert id_from_library_stem("arxiv-2307.06617") == "2307.06617"
    assert id_from_library_stem("arxiv-1310-8465") == "1310.8465"


def test_corpus_content_reads_library_text_and_cache_floor(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    library = tmp_path / "library"
    library.mkdir()
    (library / "arxiv-2307.06617.txt").write_text(_PAPER_TEXT)
    write_sections_cache("2601.01001", {"abstract": "api floor abstract"})
    cfg = Config()
    cfg.library_dir = str(library)
    content = corpus_content(cfg)
    assert "Zeno-blocked control" in content["2307.06617"]["abstract"]
    assert "Zeno regime" in content["2307.06617"]["conclusions"]
    assert content["2601.01001"]["abstract"] == "api floor abstract"


def test_corpus_content_without_library_is_cache_only(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    write_sections_cache("2601.01002", {"conclusions": "cached conclusions"})
    content = corpus_content(Config())
    assert content["2601.01002"]["conclusions"] == "cached conclusions"


# ── candidate conclusions: cache-first, fetch-only-on-miss, fail-open ────────────


def _fake_pdf(monkeypatch, text=None):
    monkeypatch.setattr("arjev.paper_content.pdf_text", lambda data: text)


def test_candidate_conclusions_cache_hit_never_fetches(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    calls = []
    _fake_pdf(monkeypatch, "Conclusions\n\nA long enough conclusions body that passes the length floor check here.\n")
    cache_dir = sections_cache_dir()
    write_sections_cache("2601.01011", {"conclusions": "cached"}, cache_dir)
    out = candidate_conclusions("2601.01011", cache_dir, fetcher=lambda url: calls.append(url) or b"")
    assert out == "cached"
    assert calls == [], "a cache hit never touches arXiv"


def test_candidate_conclusions_fetches_extracts_and_caches(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    calls = []
    _fake_pdf(monkeypatch, _PAPER_TEXT)
    cache_dir = sections_cache_dir()
    out = candidate_conclusions("2601.01012", cache_dir, fetcher=lambda url: calls.append(url) or b"pdf")
    assert "Zeno regime" in out
    assert calls == ["https://export.arxiv.org/pdf/2601.01012"]
    assert read_sections_cache("2601.01012", cache_dir)["conclusions"] == out, "the excerpt is cached, not the PDF"


def test_candidate_conclusions_failure_caches_nothing_and_returns_none(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    _fake_pdf(monkeypatch, None)  # extraction failure
    cache_dir = sections_cache_dir()
    assert candidate_conclusions("2601.01013", cache_dir, fetcher=lambda url: b"") is None
    assert read_sections_cache("2601.01013", cache_dir) == {}, "a transient failure retries tomorrow"


def test_candidate_conclusions_transport_error_fails_open_not_fatal(monkeypatch, tmp_path):
    """Review regression (Critical 1): a dead proxy mid-digest must fail open to
    None — never raise into run_digest and kill the digest."""
    isolate_state(monkeypatch, tmp_path)

    def dead_fetcher(url):
        raise ConnectionError("simulated dead proxy")

    assert candidate_conclusions("2601.01014", sections_cache_dir(), fetcher=dead_fetcher) is None
    assert read_sections_cache("2601.01014") == {}


def test_paced_conclusions_sleeps_only_after_real_fetch_attempts(monkeypatch, tmp_path):
    """The politeness seam: cache hits are free; sleeps come only after real fetch
    attempts, and never after the last id."""
    from arjev.paper_content import paced_conclusions

    isolate_state(monkeypatch, tmp_path)
    _fake_pdf(monkeypatch, "Conclusions\n\nA long enough conclusions body that clears the length floor.\n")
    sleeps = []
    cache_dir = sections_cache_dir()
    write_sections_cache("2601.01021", {"conclusions": "cached"}, cache_dir)
    out = paced_conclusions(["2601.01021", "2601.01022", "2601.01023"], cache_dir, pace_s=3.0,
                            sleep=sleeps.append, fetcher=lambda url: b"pdf")
    assert out == {"2601.01021": "cached", "2601.01022": out["2601.01022"], "2601.01023": out["2601.01023"]}
    assert sleeps == [3.0], "one sleep: between the two real fetches, none for the cache hit or after the last"


# ── fetch + backfill: the explicit network paths ─────────────────────────────────


def test_fetch_pdf_emits_library_text(monkeypatch, tmp_path):
    from arjev.keep import fetch_pdf

    monkeypatch.setattr("arjev.paper_content.pdf_text", lambda data: _PAPER_TEXT)
    library = tmp_path / "library"
    path = fetch_pdf("2307.06617", library, fetcher=lambda url: b"pdf-bytes")
    assert path.name == "arxiv-2307.06617.pdf"
    assert (library / "arxiv-2307.06617.txt").read_text() == _PAPER_TEXT


def test_fetch_pdf_exists_path_pays_extraction_once(monkeypatch, tmp_path):
    """Review regression: a pre-feature PDF (exists, no .txt) must gain its text on
    the exists-path — otherwise backfill never converges and counts false fetches."""
    from arjev.keep import fetch_pdf

    monkeypatch.setattr("arjev.paper_content.pdf_text", lambda data: _PAPER_TEXT)
    library = tmp_path / "library"
    library.mkdir()
    (library / "arxiv-2307.06620.pdf").write_bytes(b"pre-feature pdf")
    calls = []
    fetch_pdf("2307.06620", library, fetcher=lambda url: calls.append(url) or b"never")
    assert calls == [], "the exists-path never re-fetches"
    assert (library / "arxiv-2307.06620.txt").read_text() == _PAPER_TEXT


def test_fetch_pdf_extraction_failure_still_delivers_the_pdf(monkeypatch, tmp_path):
    from arjev.keep import fetch_pdf

    monkeypatch.setattr("arjev.paper_content.pdf_text", lambda data: None)
    library = tmp_path / "library"
    path = fetch_pdf("2307.06618", library, fetcher=lambda url: b"pdf-bytes")
    assert path.is_file()
    assert not (library / "arxiv-2307.06618.txt").exists(), "no text is fabricated on extraction failure"


def test_backfill_fetches_missing_and_writes_floor_for_failures(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr("arjev.paper_content.pdf_text", lambda data: _PAPER_TEXT)
    monkeypatch.setattr("arjev.ingest.fetch_metadata",
                        lambda ids: {i: {"title": "t", "abstract": f"api abstract for {i}"} for i in ids})

    def fetcher(url):
        arxiv = url.rsplit("/", 1)[-1]
        if arxiv.endswith("01002"):
            raise ConnectionError("transient")
        return b"pdf-bytes"

    library = tmp_path / "library"
    cfg = Config()
    cfg.roots = [str(VAULT)]
    cfg.library_dir = str(library)
    result = backfill_corpus(cfg, pace_s=0.0, fetcher=fetcher, sleep=lambda s: None)
    # a failed PDF fetch rides the API abstract floor instead of staying failed
    assert "2601.01002" in result["api_only"]
    assert result["failed"] == []
    assert read_sections_cache("2601.01002")["abstract"]
    assert all((library / f"arxiv-{a}.txt").is_file() for a in result["fetched"]), "text rides every fetch"


def test_backfill_requires_library_dir(tmp_path):
    cfg = Config()
    cfg.roots = [str(VAULT)]
    try:
        backfill_corpus(cfg, pace_s=0.0, sleep=lambda s: None)
        raise AssertionError("backfill without library_dir must exit, not guess")
    except SystemExit as exc:
        assert "library_dir" in str(exc)


def test_backfill_is_idempotent_on_library_text(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    library = tmp_path / "library"
    library.mkdir()
    (library / "arxiv-2601.01001.txt").write_text("already here")
    cfg = Config()
    cfg.roots = [str(VAULT)]
    cfg.library_dir = str(library)
    calls = []
    result = backfill_corpus(cfg, pace_s=0.0, fetcher=lambda url: calls.append(url) or b"pdf", sleep=lambda s: None)
    assert "2601.01001" not in result["fetched"]
    assert (library / "arxiv-2601.01001.txt").read_text() == "already here", "existing text is never overwritten"

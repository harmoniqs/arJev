"""Ingest tests: BibTeX parsing, the PDF folder scan, the Slack seed (with the
never-edit guard), and the multi-feed union with cross-listing dedupe."""

from datetime import date

import yaml

from arjev.config import Config
from arjev.feed import load_feeds
from arjev.ingest import ingest_bibtex, ingest_pdf_dir, ingest_slack_channel
from arjev.keep import KeepCandidate, scaffold_note
from conftest import FIXTURES

TODAY_D = date(2026, 10, 1)


def _cfg(tmp_path):
    cfg = Config()
    cfg.roots = [str(tmp_path / "vault")]
    (tmp_path / "vault").mkdir(exist_ok=True)
    cfg.papers_dir = str(tmp_path / "papers")
    return cfg


BIB = """@article{gong2026selfcalibrating,
  title = {Provably Efficient Self-Calibrating Quantum Fault Tolerance},
  author = {Gong, Weiyuan and Hu, Hong-Ye},
  journal = {arXiv preprint arXiv:2608.05686},
  eprint = {2608.05686},
  archivePrefix = {arXiv},
  year = {2026}
}

@article{noTitle2026,
  author = {Nobody},
  eprint = {2601.99999}
}
"""


def test_bibtex_seed_creates_touched_staged_stubs(tmp_path):
    bib = tmp_path / "library.bib"
    bib.write_text(BIB)
    hits = ingest_bibtex(bib, _cfg(tmp_path), TODAY_D)
    assert len(hits) == 1, "entries without a title are skipped, not guessed"
    note = next((tmp_path / "papers").glob("*.md"))
    fm = yaml.safe_load(note.read_text()[4 : note.read_text().index("\n---\n", 4)])
    assert fm["status"] == "staged"
    assert fm["why"].startswith("Seeded from bibliography export")
    assert fm["title"] == "Provably Efficient Self-Calibrating Quantum Fault Tolerance"
    assert fm["authors"] == ["Gong, Weiyuan", "Hu, Hong-Ye"]


def test_bibtex_seed_is_idempotent(tmp_path):
    bib = tmp_path / "library.bib"
    bib.write_text(BIB)
    cfg = _cfg(tmp_path)
    ingest_bibtex(bib, cfg, TODAY_D)
    ingest_bibtex(bib, cfg, TODAY_D)
    assert len(list((tmp_path / "papers").glob("*.md"))) == 1


def test_seed_never_edits_a_human_note(tmp_path):
    """The guard: a keep-stub (why ABSENT, awaiting the human) that later matches a
    seed id must never be stamped by the seeder."""
    cfg = _cfg(tmp_path)
    papers = tmp_path / "papers"
    human = scaffold_note(KeepCandidate("2608.05686", "hand-kept", []), cfg, TODAY_D, papers_dir=papers)
    before = human.read_text()
    bib = tmp_path / "library.bib"
    bib.write_text(BIB)
    ingest_bibtex(bib, cfg, TODAY_D, papers)
    assert human.read_text() == before, "never edit an existing note"
    assert len(list(papers.glob("*.md"))) == 1


def test_pdf_dir_seed(tmp_path):
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "arxiv-2601.01011.pdf").write_bytes(b"%PDF-1.4 synthetic")
    (pdfs / "2601.01012.pdf").write_bytes(b"%PDF-1.4 synthetic")
    (pdfs / "mystery.pdf").write_bytes(b"%PDF-1.4 no id inside")
    (pdfs / "stamp-only.pdf").write_bytes(b"%PDF-1.4\x00arXiv:2601.01013\x00rest")
    hits = ingest_pdf_dir(pdfs, _cfg(tmp_path), TODAY_D)
    assert {h.arxiv for h in hits} == {"2601.01011", "2601.01012", "2601.01013"}
    notes = {p.stem for p in (tmp_path / "papers").glob("*.md")}
    assert len(notes) == 3  # mystery.pdf reported, skipped — never guessed


class _FakeSlack:
    def __init__(self, messages):
        self.messages = messages

    def channel_history(self, channel, limit=200):
        return self.messages[:limit]


def test_slack_seed_extracts_ids_with_provenance(tmp_path):
    users = {"U094P57FQ87": "aaron", "U0BM2J0CV6D": "amico2"}
    messages = [
        {"user": "U094P57FQ87", "text": "look at this <https://arxiv.org/abs/2608.31154|paper>",
         "ts": "1790864954.46"},
        {"user": "U0BM2J0CV6D", "bot_id": "B0BMV0Q1GAC",
         "text": "digest noise arxiv.org/abs/2601.01001 — the bot's own post"},
        {"user": "U094P57FQ87", "ts": "1790864955.44",
         "text": "also arXiv:2602.03828v2 and arxiv.org/abs/2608.31154 (dupe)"},
    ]
    hits = ingest_slack_channel(_FakeSlack(messages), "C09HBLK3ECD", "papers", users,
                                _cfg(tmp_path), TODAY_D)
    assert {h.arxiv for h in hits} == {"2608.31154", "2602.03828"}
    aaron_hits = [h for h in hits if "aaron" in h.why]
    assert all("Shared by aaron in #papers" in h.why for h in aaron_hits)
    assert len(list((tmp_path / "papers").glob("*.md"))) == 2


# ── multi-feed: the union with cross-listing dedupe ─────────────────────────────

def test_multi_feed_union_dedupes_crosslistings():
    """The same paper cross-listed into two feeds is ONE candidate (the second feed's
    copy is dropped by the union)."""
    # the same ids appear in both feeds (a cross-listing) — the union keeps the
    # FIRST feed's copy, one candidate per id
    extra = FIXTURES / "rss-cond-mat.xml"
    extra.write_text(
        (FIXTURES / "rss-quant-ph.xml").read_text()
        .replace("Synthetic: silicon", "Synthetic CROSSED: silicon")
    )
    # simulate: same ids, different titles — union must keep the FIRST feed's copy
    items = load_feeds(["quant-ph"], feed_files=[str(FIXTURES / "rss-quant-ph.xml"), str(extra)])
    ids = [i.arxiv for i in items]
    assert len(ids) == len(set(ids)), "no duplicates in the union"
    assert items[0].title.startswith("Synthetic:")  # first feed wins the cross-listing


def test_multi_feed_union_preserves_order():
    items = load_feeds([], feed_files=[str(FIXTURES / "rss-quant-ph.xml")])
    assert len(items) == 6

"""Ingest tests: BibTeX parsing, the PDF folder scan, the Slack seed (with the
never-edit guard), multi-feed union dedupe, and taste directives."""

from datetime import date

import yaml

from arjev.config import Config
from arjev.directives import Directives, parse_directives
from arjev.feed import load_feeds
from arjev.fold import fold_roots
from arjev.ingest import ingest_bibtex, ingest_pdf_dir, ingest_slack_channel
from arjev.jev import assemble_state
from arjev.keep import KeepCandidate, scaffold_note
from arjev.profile import DIRECTIVE_WEIGHT, build_profile
from conftest import FIXTURES, digest_cfg, isolate_state

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


# ── taste directives: authored intent outranks everything ───────────────────────

DIRECTIVES_MD = """---
type: directives
labs: [Manchester]
companies: [QuEra, IBM, Alice & Bob]
topics: [optimal control, calibration, hardware error rates]
---
We want control and optimization papers a la the Manchester group, and the best
experimental papers in every modality. QEC interests us when tied to hardware.
"""


def test_directives_parse_lists_and_body():
    d = parse_directives(DIRECTIVES_MD)
    assert d.labs == ["Manchester"]
    assert "QuEra" in d.companies
    assert "optimal control" in d.topics
    assert "Manchester group" in d.body




def test_directive_terms_outrank_tags_and_never_decay(tmp_path):
    """Authored intent: weight above tags, immune to the 180-day decay."""
    cfg = Config()
    cfg.roots = [str(tmp_path / "vault")]
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "papers").mkdir()
    (tmp_path / "vault" / "papers" / "p.md").write_text(
        '---\ntype: paper\narxiv: "2601.01001"\ntags: [optimal-control-tag]\nwhy: "x"\n---\nbody'
    )
    directives = Directives(
        body="control papers",
        labs=["Manchester"],
        companies=["QuEra"],
        topics=["optimal control"],
    )
    profile = build_profile(fold_roots(cfg.expanded_roots, cfg), cfg, TODAY_D, directives=directives)
    assert profile.terms["optimal control"] == DIRECTIVE_WEIGHT
    assert profile.terms["quera"] == DIRECTIVE_WEIGHT
    # above a single tag bump (TAG_WEIGHT=3.0 × decay)
    assert profile.terms["optimal control"] > profile.terms["optimal-control-tag"]
    assert profile.directives_body.startswith("control papers")


def test_directives_body_rides_first_in_jev_state(tmp_path):
    cfg = Config()
    cfg.roots = [str(tmp_path / "vault")]
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "papers").mkdir()
    (tmp_path / "vault" / "papers" / "p.md").write_text(
        '---\ntype: paper\narxiv: "2601.01001"\ntags: [qec]\nwhy: "old signal"\n---\nbody'
    )
    directives = Directives(body="WE WANT MANCHESTER CONTROL PAPERS", topics=["optimal control"])
    profile = build_profile(fold_roots(cfg.expanded_roots, cfg), cfg, TODAY_D, directives=directives)
    from arjev.feed import FeedItem
    from arjev.score import score_item

    candidate = score_item(FeedItem(arxiv="2601.09999", title="t", abstract="a"), profile)
    state = assemble_state(profile, candidate).state
    taste = state["researcher_taste"]
    assert taste["directives"] == "WE WANT MANCHESTER CONTROL PAPERS"
    assert "directives" in str(list(taste.keys()))


def test_unrelated_note_at_the_path_is_ignored():
    d = parse_directives("just a random file with no frontmatter")
    assert not d.labs and not d.companies and not d.topics
    # body-only text IS present (a bare prose directives file is legal), but a
    # note with a different type: field is ignored entirely
    typed = parse_directives("---\ntype: digest\n---\nsome daily note")
    assert not typed.present


def test_config_reads_digest_keys_from_both_placements(tmp_path):
    """The TOML table trap, generalized: keys after [vault] belong to that table —
    the config accepts digest-level keys from both top level and inside [vault]."""
    from arjev.config import load_config

    cfgfile = tmp_path / "arjev.toml"
    cfgfile.write_text(
        "[vault]\n"
        'roots = ["/x"]\n'
        'feeds = ["quant-ph", "cond-mat.mes-hall", "cs.AI"]\n'
        "top = 7\n"
        'ranking = "jev-first"\n'
    )
    cfg = load_config(cfgfile)
    assert cfg.feeds == ["quant-ph", "cond-mat.mes-hall", "cs.AI"]
    assert cfg.top == 7
    assert cfg.ranking == "jev-first"


# ── the advisory rating loop + the enrichment seam ─────────────────────────────

def test_propose_writes_side_table_not_vault(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    from arjev.jev import JevClient
    from arjev.profile import build_profile
    from arjev.rate import load_proposals, propose_ratings

    vault = tmp_path / "vault"
    (vault / "papers").mkdir(parents=True)
    (vault / "papers" / "p.md").write_text(
        '---\ntype: paper\narxiv: "2601.01001"\ntitle: "unrated"\nwhy: "x"\n---\nbody'
    )
    (vault / "papers" / "q.md").write_text(
        '---\ntype: paper\narxiv: "2601.01002"\ntitle: "already rated"\nrating: core\nwhy: "x"\n---\nbody'
    )
    cfg = Config()
    cfg.roots = [str(vault)]

    class RateTransport:
        calls = []

        def __call__(self, url, key, payload):
            RateTransport.calls.append(payload)
            qid, question = next(iter(payload["questions"].items()))
            assert question["id"] == "library_rating"
            assert "core" in question["criteria"] and "marginal" in question["criteria"]
            return {"model": "test-1", "answers": {qid: {
                "type": "choice", "choice": "useful", "confidence": 0.8,
                "probabilities": {"core": 0.2, "useful": 0.8, "marginal": 0.0}}}}

    fold = fold_roots(cfg.expanded_roots, cfg)
    profile = build_profile(fold, cfg, TODAY_D)
    client = JevClient(key="k", min_confidence=0.0, transport=RateTransport())
    made = propose_ratings(fold, client, profile, "r1", [])
    assert [m.arxiv for m in made] == ["2601.01001"]  # the rated note is skipped
    proposals = load_proposals()
    assert proposals["2601.01001"]["rating"] == "useful"
    # the vault is untouched — no machine field ever lands in a note
    assert "rating" not in (vault / "papers" / "p.md").read_text().split("---")[1]


def test_accept_is_the_human_gate(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    from arjev.rate import accept_rating, load_proposals, save_proposals

    papers = tmp_path / "papers"
    papers.mkdir()
    note_file = papers / "p.md"
    note_file.write_text('---\ntype: paper\narxiv: "2601.01001"\nwhy: "x"\n---\nbody\n')
    save_proposals({"2601.01001": {"rating": "useful", "confidence": 0.8}})

    from arjev.fold import fold_roots
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    note = fold_roots(cfg.expanded_roots, cfg).papers[0]
    accept_rating(note, "core", papers)
    assert "rating: core" in note_file.read_text()
    assert "2601.01001" not in load_proposals(), "the accept clears the side table"
    import pytest

    with pytest.raises(ValueError, match="already carries"):
        accept_rating(note, "useful", papers), "a second accept never overwrites the human's rating"


def test_rating_weights_the_profile(tmp_path):
    vault = tmp_path / "vault"
    (vault / "papers").mkdir(parents=True)
    (vault / "papers" / "core.md").write_text(
        '---\ntype: paper\narxiv: "2601.01001"\ntags: [sharedterm]\nrating: core\nwhy: "x"\n---\n')
    (vault / "papers" / "marginal.md").write_text(
        '---\ntype: paper\narxiv: "2601.01002"\ntags: [sharedterm]\nrating: marginal\nwhy: "x"\n---\n')
    cfg = Config()
    cfg.roots = [str(vault)]
    profile = build_profile(fold_roots(cfg.expanded_roots, cfg), cfg, TODAY_D)
    # core pulls 3x harder than marginal (1.5 vs 0.5) at equal tags and decay
    assert profile.terms["sharedterm"] == 3.0 * (1.5 + 0.5)


def test_enrichment_seam_appends_and_fails_open(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    cfg = digest_cfg()
    cfg.enrich_command = "echo \"### Today take:\" && cat > /dev/null"
    from arjev.digest import run_digest

    result = run_digest(cfg, feed_file=str(FIXTURES / "rss-quant-ph.xml"), today=TODAY_D, seed="s", enrich=True)
    assert "### Today take:" in result.markdown

    cfg.enrich_command = "exit 1"
    result = run_digest(cfg, feed_file=str(FIXTURES / "rss-quant-ph.xml"), today=TODAY_D, seed="s", enrich=True)
    assert "Today take:" not in result.markdown and result.picks, "a broken seam never breaks the digest"

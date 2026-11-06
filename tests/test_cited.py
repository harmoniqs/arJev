"""The cited-by-me seed (issue #122): a BibTeX export of the researcher's OWN papers
→ each paper's reference list from the Semantic Scholar Graph API → one staged note
per cited work (arXiv id or DOI), its why-line naming the citing paper(s); the own
papers staged too, marked authored. Idempotent, never-editing, fail-open, and every
unresolved paper or identifier-less work is counted — never silently dropped.

All network goes through an injected httpx transport (recorded-shape responses)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import yaml

from arjev.cited import S2Client, ingest_cited_by_me, parse_own_papers
from arjev.cli import main
from arjev.config import Config
from arjev.fold import fold_roots
from arjev.inspect import run_inspect

TODAY = date(2026, 11, 5)

OWN_BIB = """@article{turner2022generalized,
  title={A generalized expansion method for computing Laplace-Beltrami eigenfunctions on manifolds},
  author={Turner, Jackson C and Cherkaev, Elena and Wang, Dong},
  journal={arXiv preprint arXiv:2210.10982},
  year={2022}
}

@article{kao2023flat,
  title={Flat tori with large Laplacian eigenvalues in dimensions up to eight},
  author={Kao, Chiu-Yen and Osting, Braxton and Turner, Jackson C},
  journal={SIAM Journal on Applied Algebra and Geometry},
  volume={7},
  number={1},
  pages={172--193},
  year={2023},
  doi={10.1137/22M1479658}
}

@article{crews2026ideal,
  title={On the ideal magnetohydrodynamic stability of the sheared-flow Z pinch},
  author={Crews, Daniel W and Turner, Jackson C},
  journal={Physics of Plasmas},
  year={2026}
}

@phdthesis{turner2026thesis,
  title={Resonance-induced Nonlinear Bound States and their Orbital Stability},
  author={Turner, Jackson C},
  school={Columbia University},
  year={2026}
}
"""


def _ref(title, arxiv=None, doi=None, authors=("A. Author",)):
    ext = {"CorpusId": 1}
    if arxiv:
        ext["ArXiv"] = arxiv
    if doi:
        ext["DOI"] = doi
    return {"citedPaper": {"paperId": "p" + title[:6], "externalIds": ext, "title": title,
                           "authors": [{"name": a} for a in authors]}}


REFS = {
    # the arXiv preprint: one arXiv-only ref, one ref shared with the SIAM paper, one no-id ref
    "ARXIV:2210.10982": [
        _ref("Dirichlet partitions in arbitrary domains", arxiv="2108.11552", doi="10.48550/arXiv.2108.11552"),
        _ref("Shared spectral geometry reference", arxiv="1905.00001", doi="10.1000/shared"),
        {"citedPaper": {"paperId": None, "externalIds": None, "title": "An unindexed lecture note", "authors": []}},
    ],
    # the SIAM paper by DOI: a DOI-only ref and the shared one
    "DOI:10.1137/22M1479658": [
        _ref("Extremal lattices and Laplace eigenvalues", doi="10.1007/s00039-099-0001"),
        _ref("Shared spectral geometry reference", arxiv="1905.00001", doi="10.1000/shared"),
    ],
    # the Z-pinch paper resolves by exact-title match (no id in the export)
    "S2:zpinch": [
        _ref("Sheared flow stabilization of the m=1 kink mode", doi="10.1063/1.873001"),
    ],
}

MATCHES = {
    "On the ideal magnetohydrodynamic stability of the sheared-flow Z pinch": {
        "paperId": "zpinch", "title": "On the ideal magnetohydrodynamic stability of the sheared-flow Z pinch",
        "externalIds": {"DOI": "10.1063/5.0200001"}},
    # the thesis: the API's best match is a DIFFERENT paper — must be rejected, not guessed
    "Resonance-induced Nonlinear Bound States and their Orbital Stability": {
        "paperId": "other", "title": "Resonance-induced nonlinear bound states", "externalIds": {}},
}


class FakeS2:
    def __init__(self, refs=REFS, matches=MATCHES, fail=()):
        self.refs, self.matches, self.fail = refs, matches, set(fail)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/paper/search/match"):
            hit = self.matches.get(request.url.params["query"])
            return httpx.Response(200, json={"data": [hit]}) if hit else httpx.Response(404, json={"error": "nf"})
        ref = path.split("/paper/", 1)[1].rsplit("/references", 1)[0]
        ref = ref if ":" in ref else f"S2:{ref}"
        if ref in self.fail:
            return httpx.Response(500, json={"error": "boom"})
        if ref not in self.refs:
            return httpx.Response(404, json={"error": "Paper not found"})
        offset = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", 1000))
        data = self.refs[ref][offset: offset + limit]
        body = {"offset": offset, "data": data}
        if offset + limit < len(self.refs[ref]):
            body["next"] = offset + limit
        return httpx.Response(200, json=body)

    def client(self, **kw):
        return S2Client(http_transport=httpx.MockTransport(self), sleep=lambda s: None, **kw)


def _cfg(tmp_path) -> Config:
    cfg = Config()
    (tmp_path / "vault").mkdir(exist_ok=True)
    cfg.roots = [str(tmp_path / "vault")]
    cfg.papers_dir = str(tmp_path / "vault" / "papers")
    return cfg


def _bib(tmp_path) -> Path:
    path = tmp_path / "scholar.bib"
    path.write_text(OWN_BIB)
    return path


def _notes(tmp_path) -> dict[str, dict]:
    out = {}
    for note in (tmp_path / "vault" / "papers").glob("*.md"):
        text = note.read_text()
        fm = yaml.safe_load(text[4: text.index("\n---\n", 4)])
        out[fm.get("arxiv") or fm.get("doi")] = fm
    return out


# ── parsing the researcher's own export ─────────────────────────────────────────

def test_own_papers_parse_every_entry_type_and_identifier_form():
    papers = parse_own_papers(OWN_BIB)
    assert [p.title[:20] for p in papers] == ["A generalized expans", "Flat tori with large",
                                              "On the ideal magneto", "Resonance-induced No"]
    assert papers[0].arxiv == "2210.10982", "Scholar puts the arXiv id in the journal field"
    assert papers[1].doi == "10.1137/22M1479658"
    assert papers[2].arxiv is None and papers[2].doi is None
    assert papers[3].kind == "phdthesis"


def test_doi_urls_and_eprint_fields_normalize():
    papers = parse_own_papers(
        "@article{a,\n  title={T},\n  doi={https://doi.org/10.1/ABC},\n  eprint={2401.00001v2}\n}\n")
    assert papers[0].doi == "10.1/ABC" and papers[0].arxiv == "2401.00001"


# ── the seed ────────────────────────────────────────────────────────────────────

def test_cited_works_are_staged_with_the_citing_paper_in_the_why(tmp_path):
    report = ingest_cited_by_me(_bib(tmp_path), _cfg(tmp_path), TODAY, client=FakeS2().client())
    notes = _notes(tmp_path)
    dirichlet = notes["2108.11552"]
    assert dirichlet["status"] == "staged" and dirichlet["seed"] == "cited"
    assert dirichlet["why"].startswith("Cited in your paper “A generalized expansion method")
    doi_only = notes["10.1007/s00039-099-0001"]
    assert doi_only["seed"] == "cited" and "arxiv" not in doi_only
    assert "Flat tori with large Laplacian eigenvalues" in doi_only["why"]
    assert notes["10.1063/1.873001"]["why"].startswith("Cited in your paper “On the ideal magnetohydrodynamic")
    assert report.cited_seeded == 4


def test_a_work_cited_by_several_papers_is_one_note_naming_every_citer(tmp_path):
    ingest_cited_by_me(_bib(tmp_path), _cfg(tmp_path), TODAY, client=FakeS2().client())
    shared = _notes(tmp_path)["1905.00001"]
    assert "A generalized expansion method" in shared["why"]
    assert "Flat tori with large Laplacian eigenvalues" in shared["why"]
    assert sum(1 for k in _notes(tmp_path) if k == "1905.00001") == 1


def test_own_papers_are_staged_as_authored(tmp_path):
    report = ingest_cited_by_me(_bib(tmp_path), _cfg(tmp_path), TODAY, client=FakeS2().client())
    notes = _notes(tmp_path)
    assert notes["2210.10982"]["seed"] == "authored"
    assert notes["10.1137/22M1479658"]["seed"] == "authored"
    assert notes["10.1063/5.0200001"]["seed"] == "authored", "a title-matched paper takes the API's DOI"
    assert notes["2210.10982"]["why"].startswith("Your paper")
    assert report.authored_seeded == 3


def test_seeded_notes_fold_as_identity_bearing_taste(tmp_path):
    cfg = _cfg(tmp_path)
    ingest_cited_by_me(_bib(tmp_path), cfg, TODAY, client=FakeS2().client())
    fold = fold_roots(cfg.expanded_roots, cfg)
    identities = {p.identity for p in fold.papers}
    assert "arxiv:2108.11552" in identities and "doi:10.1007/s00039-099-0001" in identities
    assert all(p.contributes_taste for p in fold.papers), "seeds are touched: their why is provenance"
    assert not fold.warnings


def test_rerun_changes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    ingest_cited_by_me(_bib(tmp_path), cfg, TODAY, client=FakeS2().client())
    before = {p.name: p.read_text() for p in (tmp_path / "vault" / "papers").glob("*.md")}
    again = ingest_cited_by_me(_bib(tmp_path), cfg, date(2026, 12, 1), client=FakeS2().client())
    after = {p.name: p.read_text() for p in (tmp_path / "vault" / "papers").glob("*.md")}
    assert after == before, "rerun_new_notes == 0, and nothing is edited"
    assert again.cited_seeded == 0 and again.authored_seeded == 0
    assert again.already_present == 7


def test_a_work_already_in_any_root_is_not_duplicated_or_edited(tmp_path):
    cfg = _cfg(tmp_path)
    other_root = tmp_path / "team"
    other_root.mkdir()
    human = '---\ntype: paper\ndoi: "10.1000/shared"\ntitle: "Mine"\nwhy: "human words"\n---\n\nbody\n'
    (other_root / "shared.md").write_text(human)
    cfg.roots.append(str(other_root))
    report = ingest_cited_by_me(_bib(tmp_path), cfg, TODAY, client=FakeS2().client())
    assert "1905.00001" not in _notes(tmp_path), "the DOI already owns the work — no second note"
    assert (other_root / "shared.md").read_text() == human
    assert report.already_present == 1


def test_unresolved_papers_and_identifierless_works_are_reported(tmp_path):
    report = ingest_cited_by_me(_bib(tmp_path), _cfg(tmp_path), TODAY, client=FakeS2().client())
    assert report.unresolved == ["Resonance-induced Nonlinear Bound States and their Orbital Stability"], \
        "a non-exact title match is rejected and reported, never guessed"
    assert report.no_identifier == 1
    lines = report.summary_lines()
    assert any("1 own paper unresolved" in ln and "Resonance-induced" in ln for ln in lines)
    assert any("1 cited work without an arXiv id or DOI" in ln for ln in lines)


def test_an_api_failure_fails_open_and_is_reported(tmp_path):
    fake = FakeS2(fail={"DOI:10.1137/22M1479658"})
    report = ingest_cited_by_me(_bib(tmp_path), _cfg(tmp_path), TODAY, client=fake.client())
    assert "Flat tori with large Laplacian eigenvalues in dimensions up to eight" in report.unresolved
    assert "2108.11552" in _notes(tmp_path), "the other papers still seed"


def test_references_paginate(tmp_path):
    refs = {"ARXIV:2401.00001": [_ref(f"Work {i}", arxiv=f"2301.{i:05d}") for i in range(5)]}
    fake = FakeS2(refs=refs, matches={})
    bib = tmp_path / "one.bib"
    bib.write_text("@article{a,\n  title={Mine},\n  eprint={2401.00001}\n}\n")
    client = S2Client(http_transport=httpx.MockTransport(fake), sleep=lambda s: None, page=2)
    report = ingest_cited_by_me(bib, _cfg(tmp_path), TODAY, client=client)
    assert report.cited_seeded == 5
    assert [r.url.params.get("offset") for r in fake.requests] == ["0", "2", "4"]


def test_the_client_paces_and_sends_an_optional_key():
    fake = FakeS2()
    sleeps = []
    client = S2Client(http_transport=httpx.MockTransport(fake), sleep=sleeps.append, key="k-123", pace_s=1.5)
    client.references("ARXIV:2210.10982")
    client.references("DOI:10.1137/22M1479658")
    assert fake.requests[0].headers["x-api-key"] == "k-123"
    assert sleeps and all(s <= 1.5 for s in sleeps)
    assert "fields" in fake.requests[0].url.params


def test_ratelimited_calls_back_off_then_succeed():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "Too Many Requests"})
        return httpx.Response(200, json={"offset": 0, "data": []})

    sleeps = []
    client = S2Client(http_transport=httpx.MockTransport(handler), sleep=sleeps.append)
    assert client.references("ARXIV:2210.10982") == []
    assert calls["n"] == 2 and sleeps


# ── surfaces ─────────────────────────────────────────────────────────────────────

def test_inspect_counts_notes_from_the_seed(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.feeds = ["math.AP"]
    ingest_cited_by_me(_bib(tmp_path), cfg, TODAY, client=FakeS2().client())
    lines = run_inspect(cfg).lines
    assert "fold cited-by-me: 7 (3 authored, 4 cited)" in lines


def test_cli_ingest_cited_by_me(monkeypatch, tmp_path, capsys):
    import arjev.cited as cited

    fake = FakeS2()
    monkeypatch.setattr(cited, "S2Client", lambda **kw: fake.client())
    cfg_path = tmp_path / "arjev.toml"
    (tmp_path / "vault").mkdir()
    cfg_path.write_text(f'[vault]\nroots = ["{tmp_path / "vault"}"]\nfeeds = ["math.AP"]\n')
    rc = main(["ingest", "--cited-by-me", str(_bib(tmp_path)), "--config", str(cfg_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cited-by-me: 4 cited works and 3 of your papers seeded" in out
    assert "1 own paper unresolved" in out
    assert len(list((tmp_path / "vault" / "papers").glob("*.md"))) == 7


def test_key_file_is_read_from_the_env(monkeypatch, tmp_path):
    from arjev.cited import s2_key

    key = tmp_path / "s2.key"
    key.write_text("abc\n")
    monkeypatch.setenv("ARJEV_S2_KEY_FILE", str(key))
    assert s2_key() == "abc"
    monkeypatch.delenv("ARJEV_S2_KEY_FILE")
    assert s2_key() is None, "no key is fine — the API is free without one"


def test_why_lines_are_valid_yaml_even_with_quotes(tmp_path):
    refs = {"ARXIV:2401.00001": [_ref('A "quoted" title', arxiv="2301.00001")]}
    bib = tmp_path / "one.bib"
    bib.write_text('@article{a,\n  title={My "quoted" paper},\n  eprint={2401.00001}\n}\n')
    ingest_cited_by_me(bib, _cfg(tmp_path), TODAY, client=FakeS2(refs=refs, matches={}).client())
    notes = _notes(tmp_path)
    assert "My 'quoted' paper" in notes["2301.00001"]["why"]
    json.dumps(notes, default=str)  # parsed cleanly

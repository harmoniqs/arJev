"""Slice 3 tests: the keep roundtrip, posted-state preservation, the three-branch
arrival join (clock suspension included), the checkbox harvest, posted-skip wiring,
and `arjev fetch` (obligations #1 #7 #23 #24)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from arjev.config import Config
from arjev.fold import fold_roots
from arjev.keep import KeepCandidate, fetch_pdf, keep, scaffold_note
from arjev.labels import arrival_labels, checkbox_labels, labels_sync
from arjev.ledger import Label, LabelLedger, now_ts
from arjev.state import PostedState
from conftest import TODAY, VAULT, isolate_state

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def test_keep_roundtrip_scaffold_and_label(tmp_path):
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    ledger = LabelLedger(tmp_path / "ledger.jsonl")
    candidate = KeepCandidate(arxiv="2601.01011", title="Synthetic: randomized compiling study",
                               authors=["A. Synthetic", "B. Example"])
    path = keep(candidate, ledger, cfg, TODAY)
    assert path.is_file()
    # frontmatter contract: status staged, rating ABSENT, why ABSENT
    text = path.read_text()
    fm = yaml.safe_load(text[4 : text.index("\n---\n", 4)])
    assert fm["status"] == "staged"
    assert "rating" not in fm and "why" not in fm
    assert fm["arxiv"] == "2601.01011"
    # one human action, one label row — and the second keep duplicates nothing
    rows = ledger.rows()
    assert len(rows) == 1 and rows[0].label_type == "keep" and rows[0].source == "cli-keep"
    keep(candidate, ledger, cfg, TODAY)
    assert len(ledger.rows()) == 1
    assert len(list((tmp_path / "papers").glob("*.md"))) == 1


def test_scaffold_never_overwrites_an_existing_note(tmp_path):
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    papers = tmp_path / "papers"
    papers.mkdir()
    existing = papers / "paper-existing.md"
    existing.write_text('---\ntype: paper\narxiv: "2601.01011"\ntitle: "hand-written"\n---\nkeep my note')
    path = scaffold_note(KeepCandidate("2601.01011", "other title", []), cfg, TODAY, papers_dir=papers)
    assert path == existing
    assert "hand-written" in existing.read_text()


def test_posted_state_preserves_every_id():
    fixture = Path(__file__).parent / "fixtures" / "posted-state.json"
    before = list(PostedState.load(fixture).ids)
    saved = tmp_copy_and_save(fixture, ["2601.02001", "2601.01001"])  # one new, one duplicate
    assert set(before) <= set(saved["posted"])  # acceptance: posted_ids_lost == 0
    assert saved["posted"].count("2601.01001") == 1  # dedupe, no corruption
    assert set(saved) == {"posted", "updated"}  # schema-identical


def tmp_copy_and_save(fixture: Path, new_ids: list[str]) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "state.json"
        copy.write_text(fixture.read_text())
        state = PostedState.load(copy)
        state.append(new_ids, now="2026-10-01T00:00:00Z")
        return json.loads(copy.read_text())


def _journal_line(candidates: list[dict], ts: str = "2026-09-01T13:00:00Z") -> str:
    return json.dumps({"run_id": "r", "ts": ts, "feed": "quant-ph", "mode": "m", "seed": "s",
                       "candidates": candidates})


def test_arrival_branch_saved_implicit(tmp_path):
    fold = fold_roots([VAULT], Config())
    ledger = LabelLedger(tmp_path / "l.jsonl")
    posted = PostedState(ids=["2601.01001"], updated="2026-08-01T00:00:00Z", path=tmp_path / "s.json")
    # 2601.01001 exists in the fixture vault as a distilled note → saved-implicit
    arrival_labels(fold, posted, [json.loads(_journal_line([{"arxiv": "2601.01001", "posted": True}]))], ledger, NOW)
    rows = ledger.rows()
    assert any(r.arxiv_id == "2601.01001" and r.label_type == "saved-implicit" for r in rows)


def test_arrival_branch_staged_suspends_the_clock(tmp_path):
    fold = fold_roots([VAULT], Config())
    ledger = LabelLedger(tmp_path / "l.jsonl")
    # the fixture's staged stub id, posted 40 days ago, still staged → NO row, ever
    posted = PostedState(ids=["2601.01007"], updated="2026-08-20T00:00:00Z", path=tmp_path / "s.json")
    journal = [json.loads(_journal_line([{"arxiv": "2601.01007", "posted": True}], ts="2026-08-20T13:00:00Z"))]
    arrival_labels(fold, posted, journal, ledger, NOW)
    assert [r for r in ledger.rows() if r.arxiv_id == "2601.01007"] == [], "a kept paper never flips negative"


def test_arrival_branch_thirty_day_weak_negative(tmp_path):
    fold = fold_roots([VAULT], Config())
    ledger = LabelLedger(tmp_path / "l.jsonl")
    posted = PostedState(ids=["2601.09999"], updated="2026-08-20T00:00:00Z", path=tmp_path / "s.json")
    journal = [json.loads(_journal_line([{"arxiv": "2601.09999", "posted": True}], ts="2026-08-20T13:00:00Z"))]
    # 40 days elapsed, no vault presence, no explicit label → weak negative
    arrival_labels(fold, posted, journal, ledger, NOW)
    assert any(r.label_type == "unsaved-weak-negative" and r.arxiv_id == "2601.09999" for r in ledger.rows())
    # before the 30-day mark: nothing
    fresh = LabelLedger(tmp_path / "l2.jsonl")
    journal_fresh = [json.loads(_journal_line([{"arxiv": "2601.09999", "posted": True}], ts="2026-09-20T13:00:00Z"))]
    arrival_labels(fold, posted, journal_fresh, fresh, NOW)
    assert fresh.rows() == []


def test_explicit_keep_suppresses_the_weak_negative(tmp_path):
    fold = fold_roots([VAULT], Config())
    ledger = LabelLedger(tmp_path / "l.jsonl")
    ledger.append(Label("2601.09998", "keep", "cli-keep", now_ts()))
    posted = PostedState(ids=["2601.09998"], updated="2026-08-20T00:00:00Z", path=tmp_path / "s.json")
    journal = [json.loads(_journal_line([{"arxiv": "2601.09998", "posted": True}], ts="2026-08-20T13:00:00Z"))]
    arrival_labels(fold, posted, journal, ledger, NOW)
    assert [r for r in ledger.rows() if r.label_type == "unsaved-weak-negative"] == []


def test_legacy_ids_take_state_updated_in_memory(tmp_path):
    fold = fold_roots([VAULT], Config())
    ledger = LabelLedger(tmp_path / "l.jsonl")
    # posted id with NO journal line: the legacy rule — file `updated` is its posting ts
    posted = PostedState(ids=["2601.08888"], updated="2026-08-20T00:00:00Z", path=tmp_path / "s.json")
    arrival_labels(fold, posted, [], ledger, NOW)
    assert any(r.arxiv_id == "2601.08888" and r.label_type == "unsaved-weak-negative" for r in ledger.rows())
    # and nothing was stamped back
    assert not (tmp_path / "s.json").exists()


def test_checkbox_harvest(tmp_path):
    ledger = LabelLedger(tmp_path / "l.jsonl")
    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    (digest_dir / "2026-09-30.md").write_text(
        "---\ntype: digest\ndate: 2026-09-30\nmode: mode: jev, ok\n---\n"
        "# picks\n\n"
        "- [x] Checked title — [arXiv:2601.01011](https://arxiv.org/abs/2601.01011) · `terms`\n"
        "- [ ] Unchecked — [arXiv:2601.01012](https://arxiv.org/abs/2601.01012) · `terms`\n"
    )
    new = checkbox_labels(digest_dir, ledger)
    assert [r.arxiv_id for r in new] == ["2601.01011"]
    assert ledger.rows()[0].source == "checkbox"
    checkbox_labels(digest_dir, ledger)  # idempotent
    assert len(ledger.rows()) == 1


def test_labels_sync_end_to_end(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    from arjev.digest import run_digest
    from arjev.rerank import journal_path, state_dir

    cfg = Config()
    cfg.roots = [str(VAULT)]
    cfg.digest_dir = str(tmp_path / "digests")  # never write into the fixture vault
    result = run_digest(cfg, feed_file=str(Path(__file__).parent / "fixtures" / "rss-quant-ph.xml"),
                        today=TODAY, seed="s", post="vault")
    assert result.picks, "the fixture vault + RSS produce picks"
    # posted ids landed in the state file (schema-identical)
    state = json.loads((state_dir() / "papers-digest-state.json").read_text())
    assert {p.arxiv for p in result.picks} <= set(state["posted"])
    # a 40-day-old journal line for one of them → the sync emits the weak negative
    # (the join takes the FIRST posting per id, so the original line's ts is edited)
    old_ts = (NOW - timedelta(days=40)).isoformat()
    jp = journal_path()
    lines = [json.loads(line) for line in jp.read_text().splitlines()]
    lines[-1]["ts"] = old_ts
    jp.write_text("".join(json.dumps(line) + "\n" for line in lines))
    ledger = LabelLedger()
    from arjev.fold import fold_roots
    new = labels_sync(cfg, fold_roots(cfg.expanded_roots, cfg), ledger, now=NOW)
    assert any(r.label_type == "unsaved-weak-negative" for r in new)


def test_fetch_pdf_seam(tmp_path):
    target = fetch_pdf("2601.01011", tmp_path / "library", fetcher=lambda url: b"%PDF-1.4 synthetic")
    assert target.read_bytes().startswith(b"%PDF")
    # idempotent — the second call does not re-fetch
    calls = []
    fetch_pdf("2601.01011", tmp_path / "library", fetcher=lambda url: (calls.append(1), b"%PDF")[1])
    assert calls == []


def test_vocabulary_is_closed(tmp_path):
    import pytest

    ledger = LabelLedger(tmp_path / "l.jsonl")
    with pytest.raises(ValueError, match="label_type"):
        ledger.append(Label("2601.01001", "love", "cli-keep", now_ts()))
    with pytest.raises(ValueError, match="source"):
        ledger.append(Label("2601.01001", "keep", "telepathy", now_ts()))

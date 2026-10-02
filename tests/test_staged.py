"""The `arjev staged` worklist (issue #56): exactly the staged-status notes, one
stable line each (id, title, kept-when, kept-by), the staged → written flip exits
the list, and a written body enters the fold as an authored note's would."""

from datetime import date
from pathlib import Path

from arjev.config import Config
from arjev.fold import fold_roots, staged_worklist
from conftest import VAULT

TODAY = date(2026, 10, 1)

STAGED_LINE = (
    "2601.01007 | Synthetic staged stub: scaffolded by arjev, awaiting human touch | 2026-09-29 | cli-keep"
)


def _kept_by(ledger) -> dict[str, str]:
    """The kept-by join the CLI performs: arxiv id → the keep row's source."""
    return {r.arxiv_id: r.source for r in ledger.rows() if r.label_type == "keep"}


def test_worklist_lists_exactly_the_staged_notes():
    fold = fold_roots([VAULT], Config())
    # the fixture vault folds 7 papers; exactly one is staged — one line, nothing else
    assert staged_worklist(fold, {"2601.01007": "cli-keep"}) == [STAGED_LINE]


def test_worklist_without_a_keep_row_shows_kept_by_dash():
    fold = fold_roots([VAULT], Config())
    lines = staged_worklist(fold)
    assert lines == [STAGED_LINE.rsplit("|", 1)[0].rstrip() + " | -"]


def test_note_flipped_to_written_leaves_the_worklist(tmp_path):
    # the keep scaffold (one human action: label row + staged stub), then the agent's
    # ordinary frontmatter flip — staged → written is never a tool operation
    from arjev.keep import KeepCandidate, keep
    from arjev.ledger import LabelLedger

    cfg = Config()
    cfg.roots = [str(tmp_path)]
    ledger = LabelLedger(tmp_path / "ledger.jsonl")
    path = keep(KeepCandidate("2601.01011", "Synthetic: randomized compiling study", []), ledger, cfg, TODAY)
    fold = fold_roots([tmp_path], cfg)
    assert staged_worklist(fold, _kept_by(ledger)) == [
        f"2601.01011 | Synthetic: randomized compiling study | {TODAY.isoformat()} | cli-keep"
    ]
    # the flip: an ordinary frontmatter edit, made by the hand that writes the prose
    path.write_text(path.read_text().replace("status: staged", "status: written"))
    assert staged_worklist(fold_roots([tmp_path], cfg), _kept_by(ledger)) == []


def test_written_body_enters_the_fold_like_an_authored_note(tmp_path):
    # issue #56's fold edge: once flipped, the body contributes taste identically to
    # an authored note's — staged stubs contribute zero until touched, written is ordinary
    from arjev.profile import build_profile

    cfg = Config()
    body = "The zetaflopper manifold admits a flat connection under torsion constraints."
    fm = "---\ntype: paper\narxiv: \"2601.01011\"\ntitle: \"t\"\ndate_read: 2026-09-30\n%s\n---\n\n" + body
    for name, status in (("written", "status: written"), ("authored", ""), ("staged", "status: staged")):
        vault = tmp_path / name
        vault.mkdir()
        (vault / "p.md").write_text(fm % status)
    written = build_profile(fold_roots([tmp_path / "written"], cfg), cfg, TODAY)
    authored = build_profile(fold_roots([tmp_path / "authored"], cfg), cfg, TODAY)
    staged = build_profile(fold_roots([tmp_path / "staged"], cfg), cfg, TODAY)
    # written == authored, term for term (identically — not merely "also nonzero")
    assert dict(written.terms) == dict(authored.terms)
    assert written.weight("zetaflopper") == authored.weight("zetaflopper") > 0
    assert staged.weight("zetaflopper") == 0.0, "an untouched staged stub still contributes zero taste"


# ── the verb surface ─────────────────────────────────────────────────────────────

def _config(tmp_path: Path, roots: list[str]) -> Path:
    config = tmp_path / "arjev.toml"
    config.write_text("[vault]\nroots = [" + ", ".join(f'"{r}"' for r in roots) + "]\n")
    return config


def test_cli_staged_prints_the_worklist(capsys, monkeypatch, tmp_path):
    from conftest import isolate_state

    isolate_state(monkeypatch, tmp_path)
    from arjev.cli import main
    from arjev.ledger import Label, LabelLedger, now_ts

    ledger = LabelLedger()
    ledger.append(Label("2601.01007", "keep", "cli-keep", now_ts()))
    rc = main(["staged", "--config", str(_config(tmp_path, [str(VAULT)]))])
    assert rc == 0
    assert capsys.readouterr().out.strip() == STAGED_LINE


def test_cli_staged_empty_vault_is_an_empty_worklist_and_zero_exit(capsys, tmp_path):
    # an empty worklist is not an error condition (issue #56: pull-shaped, zero exit)
    from arjev.cli import main

    empty = tmp_path / "empty-vault"
    empty.mkdir()
    rc = main(["staged", "--config", str(_config(tmp_path, [str(empty)]))])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_cli_staged_never_writes(capsys, monkeypatch, tmp_path):
    # the verb is read-only: no vault byte changes, no ledger append (the flip is the
    # agent's ordinary frontmatter edit — the tool never writes, and there is no --write)
    from conftest import isolate_state

    isolate_state(monkeypatch, tmp_path)
    from arjev.cli import main
    from arjev.ledger import Label, LabelLedger, now_ts

    ledger = LabelLedger()
    ledger.append(Label("2601.01007", "keep", "cli-keep", now_ts()))
    ledger_bytes = ledger.path.read_bytes()

    def snapshot() -> dict[Path, bytes]:
        return {p: p.read_bytes() for p in VAULT.rglob("*") if p.is_file()}

    before = snapshot()
    rc = main(["staged", "--config", str(_config(tmp_path, [str(VAULT)]))])
    assert rc == 0
    capsys.readouterr()
    assert snapshot() == before, "the fixture vault must never be written to"
    assert ledger.path.read_bytes() == ledger_bytes, "the verb must not append ledger rows"

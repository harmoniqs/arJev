"""`arjev inspect` (issue #55): the read-only verification verb — two blocks with
stable, machine-greppable line shapes (the runbook greps them verbatim), nonzero
exit iff a blocking condition holds (no feeds · no roots · zero identity-bearing
notes), and never a single write, even when blocking."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from arjev.config import Config, load_config
from arjev.inspect import BLOCK_NO_FEEDS, BLOCK_NO_IDENTITY, BLOCK_NO_ROOTS, run_inspect
from conftest import RSS, TODAY, VAULT, isolate_state

# every checklist slot, mirroring the init template's slot names verbatim (issue #54:
# the comment structure is the contract the runbook cites slot-by-slot)
CHECKLIST_SLOTS = [
    "roots", "include", "type", "half_life_days", "feeds", "top", "screen", "probe_k",
    "directives_path", "state_policy", "taste_budget_bytes", "candidate_content",
    "identity", "read_date", "rating", "why", "tags", "status",
    "digest_dir", "library_dir",
]

PAPER = (
    "---\n"
    'type: paper\narxiv: "2601.01001"\ntitle: "t"\ndate_read: 2026-09-30\nwhy: "w"\n'
    "---\n\nbody\n"
)


def _vault(tmp_path: Path, name="vault", notes=(PAPER,)) -> Path:
    vault = tmp_path / name
    vault.mkdir()
    for i, note in enumerate(notes):
        (vault / f"p{i}.md").write_text(note)
    return vault


def _cfg(roots, feeds) -> Config:
    cfg = Config()
    cfg.roots = roots
    cfg.feeds = feeds
    return cfg


def _fold_lines(report) -> list[str]:
    return [ln for ln in report.lines if ln.startswith("fold ") or ln.startswith("warning: ")]


# ── the checklist state block ───────────────────────────────────────────────────


def test_checklist_block_reports_every_init_template_slot(tmp_path):
    """The slot names ARE the init template's, verbatim and in template order — the
    checklist block is the template's state, so the runbook cites one name for both."""
    from arjev.init import init_config

    path = init_config(str(VAULT), config_path=tmp_path / "arjev.toml")
    report = run_inspect(load_config(path), today=TODAY)
    slot_lines = [ln for ln in report.lines if ln.startswith("slot ")]
    assert [ln[len("slot "):].split(":")[0] for ln in slot_lines] == CHECKLIST_SLOTS
    assert f"slot roots: set ({VAULT})" in report.lines
    assert "slot feeds: empty" in report.lines
    assert "slot type: set (paper)" in report.lines
    assert "slot identity: set (arxiv, doi)" in report.lines
    assert "slot directives_path: empty" in report.lines
    assert "slot digest_dir: empty" in report.lines


def test_every_line_shape_is_stable_and_greppable():
    """Line shapes are contract: the runbook greps them, so every line matches one
    of the two closed shapes — nothing free-form ever appears."""
    report = run_inspect(_cfg([str(VAULT)], ["quant-ph"]), today=TODAY)
    assert report.lines, "inspect always prints its blocks"
    for ln in report.lines:
        assert re.fullmatch(r"slot [a-z_]+: (set|empty)( \(.*\))?", ln) \
            or re.fullmatch(r"fold [a-z-]+: .+", ln) \
            or ln.startswith("warning: "), f"unstable line shape: {ln!r}"


# ── the fold view block ─────────────────────────────────────────────────────────


def test_fold_view_block_on_the_fixture_vault():
    """What the config actually sees: the fixture vault folds 7 identity-bearing
    paper notes out of 9 scanned files (7 papers + 1 campaign + 1 digest), all
    type-matched, one staged stub, no directives, no warnings."""
    report = run_inspect(_cfg([str(VAULT)], ["quant-ph"]), today=TODAY)
    assert _fold_lines(report) == [
        "fold scanned: 9",
        "fold type-matched: 7",
        "fold identity-bearing: 7",
        "fold profile-terms: 69",
        "fold taste-cards: 3",
        "fold staged: 1",
        "fold directives: none",
        "fold warnings: none",
    ]


def test_fold_warnings_surface_verbatim(tmp_path):
    """The fold's own warning-collection path feeds the warnings block — verbatim,
    one warning per line, prefixed but never reworded."""
    vault = _vault(tmp_path, notes=(PAPER, PAPER))  # duplicate identity
    report = run_inspect(_cfg([str(vault)], ["quant-ph"]), today=TODAY)
    assert "fold warnings: 1" in report.lines
    assert "warning: duplicate identity arxiv:2601.01001: p1.md (kept first)" in report.lines


def test_directives_loaded_line(tmp_path):
    vault = _vault(tmp_path)
    (vault / "arjev-directives.md").write_text(
        "---\ntype: directives\nlabs: [quobly]\ntopics: [silicon]\n---\nprefer hardware-tied work\n"
    )
    report = run_inspect(_cfg([str(vault)], ["quant-ph"]), today=TODAY)
    assert "fold directives: loaded (2 terms)" in report.lines
    assert "fold scanned: 2" in report.lines  # the paper note + the directives note


def test_type_mismatch_is_advisory_not_blocking():
    """The adoption diagnostic: identity mapping landed but the type slot didn't —
    the fold still sees the notes (identity is the discriminator), so this is
    advisory; only the three closed conditions block."""
    cfg = _cfg([str(VAULT)], ["quant-ph"])
    cfg.discriminator_type = "journalArticle"
    report = run_inspect(cfg, today=TODAY)
    assert "fold type-matched: 0" in report.lines
    assert "fold identity-bearing: 7" in report.lines
    assert report.blocked == []


# ── the blocking matrix (each condition alone + none + all) ──────────────────────


def test_matrix_none_blocks_nothing(tmp_path):
    vault = _vault(tmp_path)
    assert run_inspect(_cfg([str(vault)], ["quant-ph"]), today=TODAY).blocked == []


def test_matrix_no_feeds_alone(tmp_path):
    vault = _vault(tmp_path)
    report = run_inspect(_cfg([str(vault)], []), today=TODAY)
    assert report.blocked == [BLOCK_NO_FEEDS]
    # cross-slice: the blocking row cites the checklist slot name from the init
    # template (issue #54) — the slot the digest's own error names (issue #53)
    assert "slot feeds: empty" in report.lines


def test_matrix_no_roots(tmp_path):
    """No roots cannot be alone: the roots are the fold's only source, so no roots
    necessarily means zero identity-bearing notes — the issue's closed matrix
    collapses this pair by construction; both lines fire, in fixed order."""
    report = run_inspect(_cfg([], ["quant-ph"]), today=TODAY)
    assert report.blocked == [BLOCK_NO_ROOTS, BLOCK_NO_IDENTITY]


def test_matrix_zero_identity_bearing_alone(tmp_path):
    empty = tmp_path / "empty-vault"
    empty.mkdir()
    report = run_inspect(_cfg([str(empty)], ["quant-ph"]), today=TODAY)
    assert report.blocked == [BLOCK_NO_IDENTITY]


def test_matrix_all_three(tmp_path):
    report = run_inspect(_cfg([], []), today=TODAY)
    assert report.blocked == [BLOCK_NO_FEEDS, BLOCK_NO_ROOTS, BLOCK_NO_IDENTITY]


# ── green means the digest will not fail on configuration ──────────────────────


def test_green_inspect_means_a_digest_will_not_fail_on_configuration(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    from arjev.digest import run_digest

    cfg = _cfg([str(VAULT)], ["quant-ph"])
    assert run_inspect(cfg, today=TODAY).blocked == []
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, post="stdout")
    assert result.picks, "a green config digests"


def test_feeds_blocking_agrees_with_the_digest(monkeypatch, tmp_path):
    """The feeds row of the matrix is the digest's own hard requirement (issue #53):
    inspect blocks on empty feeds exactly where digest exits naming the slot."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.digest import run_digest

    cfg = _cfg([str(VAULT)], [])
    assert run_inspect(cfg, today=TODAY).blocked == [BLOCK_NO_FEEDS]
    with pytest.raises(SystemExit, match="feeds"):
        run_digest(cfg, today=TODAY, post="stdout")


# ── the verb surface ─────────────────────────────────────────────────────────────


def _write_config(tmp_path: Path, body: str) -> Path:
    config = tmp_path / "arjev.toml"
    config.write_text(body)
    return config


def test_cli_inspect_green_exits_zero_and_prints_both_blocks(capsys, tmp_path):
    from arjev.cli import main

    config = _write_config(tmp_path, f'[vault]\nroots = ["{VAULT}"]\nfeeds = ["quant-ph"]\n')
    rc = main(["inspect", "--config", str(config)])
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"slot roots: set ({VAULT})"
    assert "slot feeds: set (quant-ph)" in out
    assert "fold identity-bearing: 7" in out
    assert "fold warnings: none" in out
    # the CLI runs unpinned: the term count line must still be present and shaped
    assert any(re.fullmatch(r"fold profile-terms: \d+", ln) for ln in out)


def test_cli_inspect_blocked_exits_nonzero_but_still_prints_both_blocks(capsys, tmp_path):
    """Blocking suppresses nothing: the exit code carries the block, stderr says
    why, and stdout still shows the full state — the doctor's job is the report."""
    from arjev.cli import main

    config = _write_config(tmp_path, f'[vault]\nroots = ["{VAULT}"]\nfeeds = []\n')
    rc = main(["inspect", "--config", str(config)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "slot feeds: empty" in captured.out
    assert "fold identity-bearing: 7" in captured.out
    assert "blocked: no feeds configured" in captured.err


def test_cli_inspect_never_writes_even_when_blocking(capsys, monkeypatch, tmp_path):
    """Read-only is the invariant that holds hardest when there is the most to
    complain about: the blocked run must not change one byte — vault, config, or
    state — anywhere it can reach."""
    isolate_state(monkeypatch, tmp_path)  # any state write lands inside the snapshot
    from arjev.cli import main

    vault = tmp_path / "vault"
    shutil.copytree(VAULT, vault)
    config = _write_config(tmp_path, f'[vault]\nroots = ["{vault}"]\nfeeds = []\n')

    def snapshot():
        return {str(p.relative_to(tmp_path)): (p.read_bytes() if p.is_file() else None)
                for p in tmp_path.rglob("*")}

    before = snapshot()
    rc = main(["inspect", "--config", str(config)])
    assert rc == 1
    capsys.readouterr()
    assert snapshot() == before, "inspect must not write a single byte — even when blocking"

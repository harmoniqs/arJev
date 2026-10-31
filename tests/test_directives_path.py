"""Issue #118: `directives_path` is read, not just parsed. Precedence is the
ARJEV_DIRECTIVES_FILE env, then `directives_path`, then arjev-directives.md at the
first root that has one; a set-but-missing `directives_path` is reported by
`arjev inspect` as a warning (advisory, never blocking); neither set = unchanged."""

from __future__ import annotations

from pathlib import Path

import pytest

from arjev.config import Config
from arjev.directives import load_directives
from arjev.inspect import run_inspect
from conftest import TODAY, VAULT


def _note(path: Path, topic: str) -> Path:
    path.write_text(f"---\ntype: directives\ntopics: [{topic}]\n---\n\nbody {topic}\n")
    return path


def _cfg(root: Path, directives_path: Path | None = None) -> Config:
    cfg = Config()
    cfg.roots = [str(root)]
    cfg.directives_path = str(directives_path) if directives_path else None
    return cfg


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("ARJEV_DIRECTIVES_FILE", raising=False)


def test_directives_path_is_read_when_the_file_exists(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    team = _note(tmp_path / "team-directives.md", "from-config")
    assert load_directives(_cfg(root, team)).topics == ["from-config"]


def test_directives_path_beats_the_root_file(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    _note(root / "arjev-directives.md", "from-root")
    team = _note(tmp_path / "team-directives.md", "from-config")
    assert load_directives(_cfg(root, team)).topics == ["from-config"]


def test_env_beats_directives_path_and_the_root_file(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    _note(root / "arjev-directives.md", "from-root")
    team = _note(tmp_path / "team-directives.md", "from-config")
    env = _note(tmp_path / "env-directives.md", "from-env")
    monkeypatch.setenv("ARJEV_DIRECTIVES_FILE", str(env))
    assert load_directives(_cfg(root, team)).topics == ["from-env"]


def test_neither_set_reads_the_root_file_as_before(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    _note(root / "arjev-directives.md", "from-root")
    assert load_directives(_cfg(root)).topics == ["from-root"]


def test_neither_set_and_no_file_degrades_to_empty(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    assert not load_directives(_cfg(root)).present


def test_a_missing_directives_path_falls_back_to_the_root_file(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    _note(root / "arjev-directives.md", "from-root")
    assert load_directives(_cfg(root, tmp_path / "nope.md")).topics == ["from-root"]


def test_directives_path_expands_the_home_shorthand(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "vault"
    root.mkdir()
    _note(tmp_path / "d.md", "from-home")
    cfg = _cfg(root)
    cfg.directives_path = "~/d.md"
    assert load_directives(cfg).topics == ["from-home"]


def test_inspect_reports_a_missing_directives_path_without_blocking(tmp_path):
    cfg = Config()
    cfg.roots = [str(VAULT)]
    cfg.feeds = ["quant-ph"]
    missing = tmp_path / "nope.md"
    cfg.directives_path = str(missing)
    report = run_inspect(cfg, today=TODAY)
    assert f"warning: directives_path does not exist: {missing}" in report.lines
    assert "fold warnings: 1" in report.lines
    assert report.blocked == []


def test_inspect_is_quiet_when_directives_path_exists(tmp_path):
    cfg = Config()
    cfg.roots = [str(VAULT)]
    cfg.feeds = ["quant-ph"]
    cfg.directives_path = str(_note(tmp_path / "d.md", "x"))
    report = run_inspect(cfg, today=TODAY)
    assert "fold warnings: none" in report.lines
    assert not [ln for ln in report.lines if ln.startswith("warning: ")]
    assert "fold directives: loaded (1 terms)" in report.lines

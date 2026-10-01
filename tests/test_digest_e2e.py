"""End-to-end digest tests: determinism (fingerprint), init bootstrap, mode strings,
vault-note sink, and the no-key fail-open path (acceptance metrics for slice 1)."""

import os
from datetime import date
from pathlib import Path

from arjev.config import Config
from arjev.digest import run_digest
from arjev.init import init_config

FIXTURES = Path(__file__).parent / "fixtures"
VAULT = FIXTURES / "vault"
RSS = FIXTURES / "rss-quant-ph.xml"
TODAY = date(2026, 10, 1)


def digest_cfg() -> Config:
    cfg = Config()
    cfg.roots = [str(VAULT)]
    return cfg


def test_fingerprint_deterministic_two_runs():
    a = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="2026-10-01")
    b = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="2026-10-01")
    assert a.fingerprint == b.fingerprint
    assert a.markdown == b.markdown


def test_no_key_mode_is_lexical_only_ok():
    env_key = os.environ.pop("ARJEV_JEV_KEY", None)
    try:
        result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s")
        assert result.mode == "mode: lexical-only, ok"
        assert "mode: lexical-only, ok" in result.markdown
    finally:
        if env_key is not None:
            os.environ["ARJEV_JEV_KEY"] = env_key


def test_init_bootstrap_produces_runnable_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = init_config(str(VAULT), smoke=(str(RSS), "stdout"))
    assert path.is_file()
    assert "roots" in path.read_text()
    # smoke ran a full digest through the written config without raising


def test_init_smoke_vault_sink_writes_digest_note(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    cfg = digest_cfg()
    cfg.digest_dir = str(tmp_path / "digests")
    run_digest(cfg, feed_file=str(RSS), post="vault", today=TODAY, seed="s")
    note = tmp_path / "digests" / "2026-10-01.md"
    assert note.is_file()
    content = note.read_text()
    assert "type: digest" in content
    assert "- [ ]" in content, "vault note carries checkboxes (the slice-3 checkbox source)"
    assert "mode: lexical-only" in content
    # idempotent re-run does not duplicate or crash
    run_digest(cfg, feed_file=str(RSS), post="vault", today=TODAY, seed="s")
    assert note.read_text() == content


def test_corpus_papers_never_picked():
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s")
    picked = set()
    for line in result.markdown.splitlines():
        if "arxiv.org/abs/" in line and line[0].isdigit():
            picked.add(line.split("abs/")[1].split("|")[0].split(")")[0])
    assert picked  # the fixture profile matches something
    corpus_ids = {"2601.01001", "2601.01002", "2601.01003", "2601.01004", "2601.01005", "2601.01006", "2601.01007"}
    assert not picked & corpus_ids

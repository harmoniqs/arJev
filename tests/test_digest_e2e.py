"""End-to-end digest tests: determinism (fingerprint), init bootstrap, mode strings,
vault-note sink, and the no-key fail-open path (acceptance metrics for slice 1)."""

import os

import pytest

from arjev.digest import run_digest
from arjev.init import init_config
from conftest import RSS, TODAY, VAULT, digest_cfg, isolate_state


def test_no_feeds_config_fails_digest_naming_the_slot(monkeypatch, tmp_path):
    """Fail-loud over silent-default: a config with no feeds is a CONFIG error —
    the digest names the missing slot and never ranks a default category."""
    from arjev import feed as feed_mod

    def _no_network(*args, **kwargs):
        raise AssertionError("an empty-feeds config must fail before any fetch")

    monkeypatch.setattr(feed_mod, "fetch_feed", _no_network)
    isolate_state(monkeypatch, tmp_path)
    cfg = digest_cfg()  # feeds == [] under field-neutral defaults
    with pytest.raises(SystemExit, match="feeds"):
        run_digest(cfg, today=TODAY)


def test_fingerprint_deterministic_two_runs(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    a = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="2026-10-01")
    b = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="2026-10-01")
    assert a.fingerprint == b.fingerprint
    assert a.markdown == b.markdown


def test_no_key_mode_is_lexical_only_ok(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    env_key = os.environ.pop("ARJEV_JEV_KEY", None)
    try:
        result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s")
        assert result.mode == "mode: lexical-only, ok"
        assert "mode: lexical-only, ok" in result.markdown
    finally:
        if env_key is not None:
            os.environ["ARJEV_JEV_KEY"] = env_key


def test_seed_fallback_carries_no_category(monkeypatch, tmp_path):
    """Field-neutral seed: with no explicit feed/feed-file the seed fallback never
    injects a category string — it names the config slot, not someone's field."""
    import json

    from arjev import feed as feed_mod

    monkeypatch.setattr(feed_mod, "fetch_feed", lambda url, timeout=30.0: RSS.read_text())
    isolate_state(monkeypatch, tmp_path)
    cfg = digest_cfg()
    cfg.feeds = ["quant-ph"]  # configured feeds are legitimate; the seed must not echo them
    run_digest(cfg, today=TODAY)  # no seed, no feed, no feed_file → the fallback path
    journal = tmp_path / "state" / "arjev" / "digest-journal.jsonl"
    row = json.loads(journal.read_text().splitlines()[-1])
    assert "quant-ph" not in row["seed"]
    assert row["seed"].endswith(TODAY.isoformat()), "the seed stays date-stable"


def test_init_bootstrap_produces_runnable_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = init_config(str(VAULT), smoke=(str(RSS), "stdout"))
    assert path.is_file()
    assert "roots" in path.read_text()
    # smoke ran a full digest through the written config without raising


def test_init_smoke_vault_sink_writes_digest_note(tmp_path, monkeypatch):
    isolate_state(monkeypatch, tmp_path)
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


def test_corpus_papers_never_picked(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    result = run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s")
    picked = set()
    for line in result.markdown.splitlines():
        if "arxiv.org/abs/" in line and line[0].isdigit():
            picked.add(line.split("abs/")[1].split("|")[0].split(")")[0])
    assert picked  # the fixture profile matches something
    corpus_ids = {"2601.01001", "2601.01002", "2601.01003", "2601.01004", "2601.01005", "2601.01006", "2601.01007"}
    assert not picked & corpus_ids


def test_stdout_run_does_not_consume_posted_ids(monkeypatch, tmp_path):
    """The live integration caught this: a --post stdout preview appended its picks
    to the posted-state, so the real post the same day would have skipped them all."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.rerank import state_dir
    from arjev.state import PostedState

    run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s", post="stdout")
    state = PostedState.load(state_dir() / "papers-digest-state.json")
    assert state.ids == [], "stdout previews must not consume posted ids"

    run_digest(digest_cfg(), feed_file=str(RSS), today=TODAY, seed="s", post="vault")
    state = PostedState.load(state_dir() / "papers-digest-state.json")
    assert len(state.ids) == 5, "durable posts consume ids exactly once"

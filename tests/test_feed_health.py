"""Issue #70: an empty feed is a fetch failure, not a quiet day. All-dead exits
loud; partial-dead warns in the digest; healthy feeds render unchanged."""

from datetime import date
from pathlib import Path

import pytest

from arjev.config import Config
from arjev.digest import run_digest

RSS_OK = "/home/aaron/armonia/repos/arjev/tests/fixtures/rss-quant-ph.xml"


def test_all_feeds_dead_is_a_loud_failure(monkeypatch, state_sandbox, tmp_path):
    from arjev import feed as feed_mod

    monkeypatch.setattr(feed_mod, "fetch_feed", lambda url: "<rss></rss>")
    cfg = Config()
    cfg.feeds = ["quant-ph"]
    cfg.roots = [str(tmp_path)]
    with pytest.raises(SystemExit, match="outage"):
        run_digest(cfg, today=date(2026, 10, 4))


def test_partial_dead_warns_in_the_digest(monkeypatch, state_sandbox, tmp_path):
    from arjev import feed as feed_mod

    fixture_text = Path("/home/aaron/armonia/repos/arjev/tests/fixtures/rss-cond-mat.xml").read_text()
    def fake(url):
        # cond-mat lives, quant-ph is dead
        if "quant-ph" in url:
            return "<rss></rss>"
        return fixture_text
    monkeypatch.setattr(feed_mod, "fetch_feed", fake)
    cfg = Config()
    cfg.feeds = ["quant-ph", "cond-mat.mes-hall"]
    cfg.roots = [str(tmp_path)]
    result = run_digest(cfg, today=date(2026, 10, 4))
    assert "fetch-warning" in result.mode
    assert "quant-ph" in result.mode


def test_healthy_feeds_render_unchanged(monkeypatch, state_sandbox, tmp_path):
    from arjev import feed as feed_mod

    fixture_text = Path(RSS_OK).read_text()
    monkeypatch.setattr(feed_mod, "fetch_feed", lambda url: fixture_text)
    cfg = Config()
    cfg.feeds = ["quant-ph"]
    cfg.roots = [str(tmp_path)]
    result = run_digest(cfg, today=date(2026, 10, 4))
    assert "fetch-warning" not in result.mode


def test_quiet_day_still_renders_when_items_were_fetched(state_sandbox, tmp_path):
    # items fetched, none matched a thin profile — the honest quiet day, unchanged
    cfg = Config()
    cfg.feeds = []
    cfg.roots = [str(tmp_path)]
    result = run_digest(cfg, feed_file=RSS_OK, today=date(2026, 10, 4))
    assert result.markdown != ""

"""Shared fixtures: fixture vault/RSS paths, the pinned test date, state isolation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from arjev.config import Config

FIXTURES = Path(__file__).parent / "fixtures"
VAULT = FIXTURES / "vault"
RSS = FIXTURES / "rss-quant-ph.xml"
TODAY = date(2026, 10, 1)


def digest_cfg() -> Config:
    from arjev.config import Config

    cfg = Config()
    cfg.roots = [str(VAULT)]
    return cfg


def isolate_state(monkeypatch, tmp_path):
    """Runtime artifacts (journal, receipts) must never touch the real home."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def _no_live_state_or_credentials(monkeypatch, tmp_path):
    """A test suite must never touch the operator's real keys OR her real state
    dir. Credential clearing was autouse already; state isolation (XDG_STATE_HOME
    -> tmp) was per-fixture only, and a bare run_digest test wrote a fixture run
    into the LIVE journal (found 2026-10-02: run 20261002T160824Z). Both are
    autouse now — no test can inherit the machine, period."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for var in ("ARJEV_JEV_KEY", "ARJEV_JEV_KEY_FILE", "ARJEV_JEV_DISABLED", "ARJEV_SLACK_TOKEN"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def state_sandbox(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    return tmp_path / "state" / "arjev"

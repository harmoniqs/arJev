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


def _pdf_bytes(lines):
    """A minimal valid single-page PDF carrying exactly `lines` of Helvetica
    text — pypdf extracts them verbatim, so the parse runs on realistic input."""

    def esc(s):
        return s.replace("(", "\\(").replace(")", "\\)")

    page = ("/Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >>")
    content = "BT /F1 10 Tf 72 720 Td\n" + "".join(f"({esc(line)}) Tj 0 -14 Td\n" for line in lines) + "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<<{page}>>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = ["%PDF-1.4"]
    offsets = [0]
    for i, body in enumerate(objs, 1):
        offsets.append(offsets[-1] + len(out[-1]) + 1)
        out.append(f"{i} 0 obj\n{body}\nendobj")
    xref_pos = sum(len(entry) + 1 for entry in out)
    entries = "".join(f"{off:010d} 00000 n \n" for off in offsets[1:])
    trailer = f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n{entries}trailer\n"
    out.append(f"{trailer}<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF")
    return ("\n".join(out)).encode()

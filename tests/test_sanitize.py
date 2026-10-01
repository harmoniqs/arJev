"""Fixture sanitization gates (obligation #13): recorded payloads are sanitized before
commit, and the committed synthetic payloads are provably clean."""

from arjev.sanitize import ensure_sanitized, sanitize

DIRTY = {
    "channel": "C09HBLK3ECD",
    "user": "U08S0814CLA",
    "reactions": [{"user": "U08SWT113T6", "name": "thumbsup"}],
    "nested": {"team": "T0ABCDEF1", "ok": "plain text"},
    "auth": "xoxb-123456789-abcdef",
}


def test_sanitize_replaces_all_id_kinds():
    clean = sanitize(DIRTY)
    assert clean["channel"] == "C0000000SYN"
    assert clean["user"] == "U0000000SYN"
    assert clean["reactions"][0]["user"] == "U0000000SYN"
    assert clean["nested"]["team"] == "X0000000SYN"
    assert clean["nested"]["ok"] == "plain text"


def test_sanitize_drops_secret_values_and_fields():
    clean = sanitize({"token": "xoxb-secret", "note": "Bearer abc123", "why": "fine"})
    assert clean["token"] == "<dropped-secret>"
    assert clean["note"] == "<sanitized-secret>"
    assert clean["why"] == "fine"


def test_ensure_sanitized_raises_on_dirty_payload():
    import pytest

    with pytest.raises(ValueError):
        ensure_sanitized({"channel": "C09HBLK3ECD"})


def test_ensure_sanitized_passes_clean_payload():
    ensure_sanitized({"channel": "C0000000SYN", "text": "arXiv:2601.01011 — synthetic"})

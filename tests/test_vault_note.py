"""The vault digest note's frontmatter must be valid YAML (issue #117): the composite
mode line `mode: <primary>, <profile>` is shown verbatim to humans (Slack, stdout), but
the frontmatter `mode` key holds the bare value, with no second `mode:` prefix."""

import yaml

from arjev.digest import run_digest
from conftest import RSS, TODAY, digest_cfg, isolate_state
from test_slack import FakeSlack


def _frontmatter(text):
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_vault_note_frontmatter_is_valid_yaml_with_prefix_free_mode(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    cfg = digest_cfg()
    cfg.digest_dir = str(tmp_path / "digests")
    cfg.slack_channel = "C0000000SYN"
    fake = FakeSlack()
    run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack,vault", slack_client=fake.client())

    text = (tmp_path / "digests" / "2026-10-01.md").read_text()
    meta = _frontmatter(text)
    assert isinstance(meta, dict)
    assert isinstance(meta["mode"], str)
    assert not meta["mode"].startswith("mode:")
    assert meta["type"] == "digest"

    # the human-facing composite line is unchanged in the note body and in Slack
    composite = f"mode: {meta['mode']}"
    assert f"`{composite}`" in text
    header = next(p for m, p in fake.calls if m == "chat.postMessage")
    assert f" · {composite} · " in header["text"]

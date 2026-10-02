"""Init checklist-file tests (issue #54): the written template IS the setup checklist —
field-neutral, fully-commented, every decision slot explained at the slot. All content
assertions target the WRITTEN file (external behavior — the comment structure is the
contract the runbook cites slot-by-slot)."""

from __future__ import annotations

import tomllib

import pytest

from arjev.init import init_config
from conftest import RSS, VAULT


def write_config(tmp_path) -> "object":
    """Init on the fixture vault; return the written file's text."""
    path = init_config(str(VAULT), config_path=tmp_path / "arjev.toml")
    return path.read_text()


def test_init_never_rewrites_existing_config(tmp_path):
    """Idempotence invariant: an existing config is never clobbered — a user's
    hand edits must survive a re-run of init."""
    path = tmp_path / "arjev.toml"
    init_config(str(VAULT), config_path=path)
    edited = path.read_text() + "\n# my hand edit\n"
    path.write_text(edited)
    with pytest.raises(FileExistsError, match="never rewrites"):
        init_config(str(VAULT), config_path=path)
    assert path.read_text() == edited


def test_feeds_slot_is_empty_and_points_at_the_taxonomy(tmp_path):
    """The feeds decision starts EMPTY — arJev ranks only what you configure and
    never defaults to a category; the comment names where the categories live.
    Placement is part of the contract: feeds sits in [vault] where the loader
    reads it (the key-placement lesson — a feeds line under [vault.fields] is
    silently dead)."""
    content = write_config(tmp_path)
    assert "\nfeeds = []" in content, "the written feeds slot is empty"
    vault = tomllib.loads(content)["vault"]
    assert vault["feeds"] == []
    assert "https://arxiv.org/category_taxonomy" in content, "the feeds comment points at the category taxonomy"
"""Init checklist-file tests (issue #54): the written template IS the setup checklist —
field-neutral, fully-commented, every decision slot explained at the slot. All content
assertions target the WRITTEN file (external behavior — the comment structure is the
contract the runbook cites slot-by-slot)."""

from __future__ import annotations

import re
import shutil
import tomllib

import pytest

from arjev.init import init_config
from conftest import RSS, TODAY, VAULT, isolate_state

# every decision slot the checklist-file must carry (the runbook cites these slot-by-slot)
DECISION_SLOTS = [
    "roots", "include", "type", "half_life_days", "feeds", "top", "screen", "probe_k",
    "directives_path", "identity", "read_date", "rating", "why", "tags", "status",
    "digest_dir", "library_dir",
]


def write_config(tmp_path) -> str:
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


def test_no_lab_name_anywhere_in_the_template(tmp_path):
    """Field-neutral means field-neutral: the template presumes no lab, no schema
    owner — a researcher in any arXiv-served field reads it as theirs."""
    content = write_config(tmp_path)
    assert "harmoniqs" not in content.lower(), "zero lab names in the template"


def _slot_lines(content: str) -> list[tuple[str, int]]:
    """(key, line index) for every decision-slot line — an active assignment or a
    commented optional slot. Example-block lines are indented past `# ` and so
    never match; table headers and prose comments carry no `= ` after a bare key."""
    return [
        (m.group(1), i)
        for i, line in enumerate(content.splitlines())
        if (m := re.fullmatch(r"(?:# )?([a-z_]+) = .*", line))
    ]


def test_every_decision_slot_is_present(tmp_path):
    content = write_config(tmp_path)
    keys = {key for key, _ in _slot_lines(content)}
    assert keys, "the template carries decision slots"
    for slot in DECISION_SLOTS:
        assert slot in keys, f"decision slot {slot} is missing from the checklist-file"


def test_every_slot_carries_a_one_line_comment_naming_it_exactly(tmp_path):
    """The comment structure is a contract: each slot's explanation sits on the one
    line directly above it, and its first token is the config key — exactly. The
    runbook cites slots by name, so a comment naming `arxiv id field` for the key
    `identity` would break the citation."""
    content = write_config(tmp_path)
    lines = content.splitlines()
    for key, i in _slot_lines(content):
        assert lines[i - 1].startswith(f"# {key} "), (
            f"slot {key} must be preceded by a one-line comment naming it exactly (line {i + 1})"
        )


def test_three_field_remap_examples(tmp_path):
    """Three different fields — a physics vault, a Zotero-style vault, an econ
    vault — each shows how its [vault.fields] identity/type remapping would look,
    so a fresh user can see the schema is theirs to map, not a given."""
    content = write_config(tmp_path)
    lowered = content.lower()
    for marker in ("physics vault", "zotero-style vault", "econ vault"):
        assert marker in lowered, f"the template shows a {marker} remap example"
    example_identity_lines = [ln for ln in content.splitlines() if re.fullmatch(r"#\s+identity = .*", ln)]
    assert len(example_identity_lines) == 3, "each example carries its own identity remap"
    remaps = {ln.split("=", 1)[1].strip() for ln in example_identity_lines}
    assert len(remaps) == 3, "the three examples map three different schemas"


def test_smoke_runs_the_digest_through_the_written_config(tmp_path, monkeypatch):
    """Bootstrap acceptance: the smoke must run through the WRITTEN config — the
    written file is the thing that has to be runnable. Observable without mocks:
    a vault-sink smoke writes the digest note under the vault init was given
    (the written config's roots); the in-memory-defaults path has no roots and
    cannot (it crashes at the vault sink instead)."""
    isolate_state(monkeypatch, tmp_path)
    vault = tmp_path / "vault"
    shutil.copytree(VAULT, vault)
    path = init_config(str(vault), config_path=tmp_path / "arjev.toml", smoke=(str(RSS), "vault"))
    assert path.is_file()
    assert list((vault / "digests").glob("*.md")), \
        "the smoke digested through the written config into the configured vault"


def test_written_config_is_runnable_or_plainly_blocking(tmp_path, monkeypatch):
    """The checklist-file's two legal states: with a feed the written config runs
    a full digest; with no feeds and no feed file it exits naming the missing
    slot — never a silent default-category digest."""
    isolate_state(monkeypatch, tmp_path)
    from arjev.config import load_config
    from arjev.digest import run_digest

    path = init_config(str(VAULT), config_path=tmp_path / "arjev.toml")
    cfg = load_config(path)
    assert cfg.feeds == []
    assert (cfg.top, cfg.screen, cfg.probe_k, cfg.half_life_days) == (5, 40, 20, 180.0)
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, post="stdout")
    assert result.picks, "the written config runs a full digest through the fixture"
    with pytest.raises(SystemExit, match="feeds"):
        run_digest(cfg, today=TODAY)

"""arjev init: write the config from the static template (no TOML-writer dependency —
the template IS a string), then optionally run a fixture smoke so a successful init
provably yields a runnable config (acceptance: init.bootstrap_failures == 0)."""

from __future__ import annotations

from pathlib import Path

from .config import Config, default_config_path

TEMPLATE = """# arJev configuration — schema of record: config/specs/spec-20260901…-arjev-v1.md (harmoniqs/arJev)
# The default field mapping is the Harmoniqs paper-note schema; remap [vault.fields]
# for any Obsidian/Zotero vault.

[vault]
roots = ["{roots}"]
include = "**/*.md"
type = "paper"
half_life_days = 180.0
# feeds — arXiv categories to rank; the full category list: https://arxiv.org/category_taxonomy
feeds = []
top = 5
screen = 40
probe_k = 20

[vault.fields]
identity = ["arxiv", "doi"]
read_date = "date_read"
rating = "rating"
why = "why"
tags = "tags"
status = "status"

# digest_dir = "/path/to/vault/digests"   # default: <first root>/digests
# library_dir = "/path/to/pdf/library"    # used by `arjev fetch` (slice 3)
"""


def init_config(roots: str, config_path: Path | None = None, smoke: tuple[str, str] | None = None) -> Path:
    """Write the config; smoke = (feed_file, post) runs a digest through it.
    Init never rewrites: an existing config raises FileExistsError (a user's hand
    edits survive re-runs; editing is by hand or the agent, never by init)."""
    path = config_path or default_config_path()
    if path.is_file():
        raise FileExistsError(f"config already exists at {path} — init never rewrites an existing config; edit it by hand")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(roots=roots))
    if smoke is not None:
        from .digest import run_digest

        feed_file, post = smoke
        run_digest(Config(), feed_file=feed_file, post=post)
    return path

"""arjev init: write the config from the static template (no TOML-writer dependency —
the template IS a string), then optionally run a fixture smoke so a successful init
provably yields a runnable config (acceptance: init.bootstrap_failures == 0)."""

from __future__ import annotations

from pathlib import Path

from .config import Config, default_config_path

TEMPLATE = """# arJev configuration — this file is the setup checklist: every slot below is a
# decision you make, and each slot carries its one-line explanation. arJev ranks
# only what you configure and never defaults to a field.

[vault]
# roots — vault folders scanned recursively for paper notes; one path per root.
roots = ["{roots}"]
# include — glob, relative to each root, selecting which files are scanned for notes.
include = "**/*.md"
# type — the frontmatter `type` value that marks a note as a paper; never a taste term.
type = "paper"
# half_life_days — taste decay: a read counts half as much after this many days.
half_life_days = 180.0
# feeds — the arXiv categories you follow; the full list: https://arxiv.org/category_taxonomy
feeds = []
# top — papers shown in the digest.
top = 5
# screen — candidates screened per run before ranking down to top.
screen = 40
# probe_k — synonym-probe pool size (the recall pass that feeds the Jev ranking).
probe_k = 20
# directives_path — your taste directives, written in plain English; default: arjev-directives.md at the first root.
# directives_path = "/absolute/path/to/arjev-directives.md"

[vault.fields]
# identity — frontmatter field(s) holding the paper id; the first present one wins.
identity = ["arxiv", "doi"]
# read_date — frontmatter field for when you read it; fallback: `date`, then file mtime.
read_date = "date_read"
# rating — frontmatter field for your verdict: core, useful, or marginal.
rating = "rating"
# why — frontmatter field for your one-line reason — the taste signal.
why = "why"
# tags — frontmatter field listing tags; each counts toward taste.
tags = "tags"
# status — frontmatter field for staged vs written; a written note's body feeds taste.
status = "status"

# [vault.fields] remaps to any note schema — three fields, three examples
# (type is the [vault] discriminator, shown here with each mapping):
# a physics vault — [vault] type = "paper"; its [vault.fields]:
#   identity = ["arxiv", "doi"]
#   read_date = "date_read"
#   rating = "rating"
#   why = "why"
#   tags = "tags"
#   status = "status"
# a Zotero-style vault — [vault] type = "journalArticle"; its [vault.fields]:
#   identity = ["doi", "arxiv"]
#   read_date = "dateAdded"
#   tags = "keywords"
# an econ vault — [vault] type = "note"; its [vault.fields]:
#   identity = ["arxiv"]
#   why = "takeaway"
#   tags = "topics"

# digest_dir — where digest notes land; default: digests under the first root.
# digest_dir = "/path/to/vault/digests"
# library_dir — where `arjev fetch` saves PDFs.
# library_dir = "/path/to/pdf/library"
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

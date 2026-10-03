"""Issue #66: the author-signal lane. Tracked-people papers score high; the
roster matches only the authors field; zero roster = zero behavior change."""

from datetime import date

from arjev.config import Config
from arjev.directives import parse_directives
from arjev.feed import FeedItem
from arjev.fold import fold_roots
from arjev.profile import build_profile
from arjev.score import _name_match, score_item

TODAY = date(2026, 10, 2)
ABSTRACT = "We study a superconducting circuit and report a gate."  # constant across both


def _cfg_with_directives(tmp_path, text):
    (tmp_path / "arjev-directives.md").write_text(text)
    (tmp_path / "papers").mkdir(exist_ok=True)
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    return cfg


def test_a_tracked_author_scores_higher_than_a_stranger(tmp_path):
    cfg = _cfg_with_directives(tmp_path, """---
type: directives
authors: ["D. I. Schuster"]
---

We track people.
""")
    from arjev.directives import load_directives
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY, directives=load_directives(cfg))
    ours = score_item(FeedItem(arxiv="1.1", title="A superconducting circuit paper", abstract=ABSTRACT,
                               authors=["D. I. Schuster", "A. Collaborator"]), profile)
    stranger = score_item(FeedItem(arxiv="1.2", title="A superconducting circuit paper", abstract=ABSTRACT,
                                   authors=["R. Stranger"]), profile)
    assert ours.score > stranger.score
    assert "d. i. schuster" in ours.terms  # the why-line shows the roster hit


def test_matching_matrix():
    assert _name_match("D. I. Schuster", ["D. I. Schuster"])           # exact
    assert _name_match("Schuster", ["D. I. Schuster"])                 # surname-only: any initial
    assert _name_match("D. Schuster", ["David I. Schuster"])           # initial agreement
    assert not _name_match("D. I. Schuster", ["T. Schuster"])          # initial mismatch
    assert not _name_match("D. I. Schuster", ["D. I. Schusterberg"])   # surname must match fully
    assert not _name_match("D. I. Schuster", [])                       # absent: zero, no error
    assert not _name_match("", ["Anyone"])                              # empty roster entry


def test_the_roster_never_fires_on_a_mere_abstract_mention(tmp_path):
    cfg = _cfg_with_directives(tmp_path, """---
type: directives
authors: ["Schuster"]
---
body
""")
    from arjev.directives import load_directives
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY, directives=load_directives(cfg))
    mentions = score_item(FeedItem(arxiv="2.1", title="A theory of the Schuster noise model",
                                   abstract="The Schuster model is studied.", authors=["R. Stranger"]), profile)
    assert "schuster" not in mentions.terms
    by_name = score_item(FeedItem(arxiv="2.2", title="A theory of noise", abstract=ABSTRACT,
                                   authors=["M. Schuster"]), profile)
    assert "schuster" in by_name.terms  # surname-only follow: any Schuster counts


def test_state_carries_authors(tmp_path):
    from arjev.jev import assemble_state
    from arjev.score import score_item
    cfg = _cfg_with_directives(tmp_path, """---
type: directives
authors: ["D. I. Schuster"]
---
body
""")
    from arjev.directives import load_directives
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY, directives=load_directives(cfg))
    scored = score_item(FeedItem(arxiv="3.1", title="A superconducting circuit paper", abstract=ABSTRACT,
                                 authors=["D. I. Schuster"]), profile)
    assembly = assemble_state(profile, scored)
    assert assembly.state is not None
    assert assembly.state["candidate"]["authors"] == ["D. I. Schuster"]


def test_zero_roster_is_inert():
    assert parse_directives("---\ntype: directives\n---\nbody").authors == []
    assert parse_directives("no frontmatter at all").authors == []

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


def test_accents_never_break_matching():
    # the registry carries accented names; feeds print folded forms — and vice versa
    assert _name_match("Esperanza Cuenca-Gómez", ["E. Cuenca-Gomez"])
    assert _name_match("R. Lescanne", ["Raphaël Lescanne"])
    assert _name_match("Loïc Henriet", ["L. Henriet"])


def test_zero_roster_is_inert():
    assert parse_directives("---\ntype: directives\n---\nbody").authors == []
    assert parse_directives("no frontmatter at all").authors == []


def test_group_suffix_matches_as_if_bare(tmp_path):
    # issue #87: "Name — Group" roster entries — the matching rule ignores the
    # suffix, scoring is unchanged, and the group rides separately for the who-line
    from arjev.directives import split_group

    assert split_group("D. I. Schuster — Stanford") == ("D. I. Schuster", "Stanford")
    assert split_group("D. I. Schuster") == ("D. I. Schuster", None)
    assert _name_match("D. I. Schuster — Stanford", ["D. I. Schuster"])
    assert not _name_match("D. I. Schuster — Stanford", ["T. Schuster"])

    suffixed = _cfg_with_directives(tmp_path, """---
type: directives
authors: ["D. I. Schuster — Stanford"]
---
body
""")
    from arjev.directives import load_directives
    profile = build_profile(fold_roots([tmp_path], suffixed), suffixed, TODAY, directives=load_directives(suffixed))
    scored = score_item(FeedItem(arxiv="4.1", title="A superconducting circuit paper", abstract=ABSTRACT,
                                  authors=["D. I. Schuster", "A. Collaborator"]), profile)
    assert "d. i. schuster" in scored.terms  # the why-line term stays the bare name
    assert "stanford" not in scored.terms      # the group never leaks into scoring terms
    assert load_directives(suffixed).author_groups() == {"D. I. Schuster": "Stanford"}


def test_group_suffix_leaves_scoring_bit_identical(tmp_path):
    # the machine gate author_lane_score_delta_with_group_suffix == 0
    def _score(cfg):
        from arjev.directives import load_directives
        profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY, directives=load_directives(cfg))
        return score_item(FeedItem(arxiv="5.1", title="A superconducting circuit paper", abstract=ABSTRACT,
                                   authors=["D. I. Schuster", "A. Collaborator"]), profile).score

    bare = _cfg_with_directives(tmp_path, """---
type: directives
authors: ["D. I. Schuster"]
---
body
""")
    bare_score = _score(bare)
    assert bare_score > 0.0
    (tmp_path / "arjev-directives.md").write_text("""---
type: directives
authors: ["D. I. Schuster — Stanford"]
---
body
""")
    assert _score(bare) == bare_score  # the suffixed roster scores bit-identically

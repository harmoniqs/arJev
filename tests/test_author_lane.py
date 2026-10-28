"""Issue #66: the author-signal lane. Tracked-people papers score high; the
roster matches only the authors field; zero roster = zero behavior change.
Issue #98: roster from people-card directory — each card's name + org become
a tracked author; TBD/empty org → bare entry; duplicates are merged."""

from datetime import date

from arjev.config import Config
from arjev.directives import load_people_cards, parse_directives
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


# ---------------------------------------------------------------------------
# Issue #98: people-card directory
# ---------------------------------------------------------------------------

def _make_cards_dir(tmp_path):
    """Create a fixture people-card directory under tmp_path/people/."""
    cards = tmp_path / "people"
    cards.mkdir(exist_ok=True)
    # Card with name and organization → "Name — Org" roster entry
    (cards / "alice.md").write_text(
        "---\nname: Alice Researcher\norganization: QuantumCorp\n---\nAlice's page.\n"
    )
    # Card with name and TBD organization → bare entry (no group)
    (cards / "bob.md").write_text(
        "---\nname: B. Builder\norganization: TBD\n---\nBob's page.\n"
    )
    # Card with name and empty organization → bare entry
    (cards / "carol.md").write_text(
        "---\nname: C. Carol\norganization:\n---\nCarol's page.\n"
    )
    # Card with no organization key at all → bare entry
    (cards / "dave.md").write_text(
        "---\nname: D. Dave\n---\nDave's page.\n"
    )
    return cards


def test_load_people_cards_basic(tmp_path):
    """load_people_cards returns entries in 'Name — Group' or bare form."""
    cards = _make_cards_dir(tmp_path)
    entries = load_people_cards(cards)
    names = {e.split(" — ")[0] if " — " in e else e for e in entries}
    assert "Alice Researcher" in names
    assert "B. Builder" in names
    assert "C. Carol" in names
    assert "D. Dave" in names


def test_load_people_cards_org_becomes_group(tmp_path):
    """A card with a real organization becomes a 'Name — Org' entry."""
    cards = _make_cards_dir(tmp_path)
    entries = load_people_cards(cards)
    alice_entry = next((e for e in entries if "Alice Researcher" in e), None)
    assert alice_entry is not None
    assert alice_entry == "Alice Researcher — QuantumCorp"


def test_load_people_cards_tbd_org_is_bare(tmp_path):
    """TBD organization → bare entry, no group suffix."""
    cards = _make_cards_dir(tmp_path)
    entries = load_people_cards(cards)
    bob_entry = next((e for e in entries if "B. Builder" in e), None)
    assert bob_entry == "B. Builder"


def test_load_people_cards_empty_org_is_bare(tmp_path):
    """Empty organization → bare entry, no group suffix."""
    cards = _make_cards_dir(tmp_path)
    entries = load_people_cards(cards)
    carol_entry = next((e for e in entries if "C. Carol" in e), None)
    assert carol_entry == "C. Carol"


def test_load_people_cards_missing_org_key_is_bare(tmp_path):
    """Card without organization key → bare entry."""
    cards = _make_cards_dir(tmp_path)
    entries = load_people_cards(cards)
    dave_entry = next((e for e in entries if "D. Dave" in e), None)
    assert dave_entry == "D. Dave"


def test_directives_people_cards_dir_merges_into_authors(tmp_path):
    """When directives frontmatter names a people_cards_dir, those cards' authors
    merge into the directives.authors list."""
    cards = _make_cards_dir(tmp_path)
    directives_text = f"""---
type: directives
people_cards_dir: {cards}
---
body
"""
    d = parse_directives(directives_text, base_path=tmp_path)
    names = {(e.split(" — ")[0] if " — " in e else e) for e in d.authors}
    assert "Alice Researcher" in names
    assert "B. Builder" in names


def test_directives_people_cards_dir_deduplicates(tmp_path):
    """A name in both directives.authors and the cards appears exactly once."""
    cards = _make_cards_dir(tmp_path)
    directives_text = f"""---
type: directives
authors: ["Alice Researcher — QuantumCorp"]
people_cards_dir: {cards}
---
body
"""
    d = parse_directives(directives_text, base_path=tmp_path)
    alice_entries = [e for e in d.authors if "Alice Researcher" in e]
    assert len(alice_entries) == 1


def test_directives_people_cards_dir_deduplicates_bare_vs_grouped(tmp_path):
    """A bare name in authors list deduplicates against the same name with org from cards."""
    cards = _make_cards_dir(tmp_path)
    directives_text = f"""---
type: directives
authors: ["Alice Researcher"]
people_cards_dir: {cards}
---
body
"""
    d = parse_directives(directives_text, base_path=tmp_path)
    alice_entries = [e for e in d.authors if "Alice Researcher" in e]
    assert len(alice_entries) == 1


def test_people_cards_roster_scores_as_tracked_author(tmp_path):
    """A paper by an author in the people-cards roster scores higher than a stranger."""
    cards = _make_cards_dir(tmp_path)
    directives_text = f"""---
type: directives
people_cards_dir: {cards}
---
body
"""
    (tmp_path / "arjev-directives.md").write_text(directives_text)
    (tmp_path / "papers").mkdir(exist_ok=True)
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    from arjev.directives import load_directives
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY, directives=load_directives(cfg))
    tracked = score_item(FeedItem(arxiv="6.1", title="A superconducting circuit paper",
                                  abstract=ABSTRACT, authors=["Alice Researcher"]), profile)
    stranger = score_item(FeedItem(arxiv="6.2", title="A superconducting circuit paper",
                                   abstract=ABSTRACT, authors=["R. Stranger"]), profile)
    assert tracked.score > stranger.score


def test_people_cards_group_shown_in_author_groups(tmp_path):
    """author_groups() includes group from people card."""
    cards = _make_cards_dir(tmp_path)
    directives_text = f"""---
type: directives
people_cards_dir: {cards}
---
body
"""
    d = parse_directives(directives_text, base_path=tmp_path)
    groups = d.author_groups()
    assert groups.get("Alice Researcher") == "QuantumCorp"
    assert "B. Builder" not in groups  # TBD → no group


def test_load_people_cards_nonexistent_dir_returns_empty(tmp_path):
    """A missing people-card directory silently returns an empty list (fail-open)."""
    from arjev.directives import load_people_cards
    entries = load_people_cards(tmp_path / "nonexistent")
    assert entries == []


def test_load_people_cards_skips_cards_without_name(tmp_path):
    """A card file without a 'name' field is skipped."""
    cards = tmp_path / "people2"
    cards.mkdir()
    (cards / "noname.md").write_text("---\norganization: Acme\n---\nbody\n")
    (cards / "valid.md").write_text("---\nname: Valid Person\norganization: Acme\n---\nbody\n")
    from arjev.directives import load_people_cards
    entries = load_people_cards(cards)
    assert len(entries) == 1
    assert "Valid Person" in entries[0]

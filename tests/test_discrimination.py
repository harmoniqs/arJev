"""Issue #61: discrimination beats raw frequency in the taste profile.
Body/title-sourced weights carry an IDF-style selectivity factor; function
words stop being terms; capped-to-zero terms match nothing."""

from __future__ import annotations

import math
from datetime import date

from arjev.config import Config
from arjev.feed import FeedItem
from arjev.fold import fold_roots
from arjev.profile import STOPWORDS, _idf_factor, build_profile
from arjev.score import score_item

TODAY = date(2026, 10, 1)


def _note(tmp_path, name, arxiv, body, why="a reason", tags=(), rating="core"):
    p = tmp_path / "papers" / f"{name}.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(
        f"""---
type: paper
arxiv: "{arxiv}"
title: "{name}"
date: 2026-10-01
date_read: 2026-10-01
status: written
rating: "{rating}"
why: "{why}"
tags: [paper{', ' + ', '.join(tags) if tags else ''}]
---

{body}
"""
    )


def _feed_item(arxiv, title, abstract):
    return FeedItem(arxiv=arxiv, title=title, abstract=abstract)


def test_a_rare_term_outranks_a_generic_one_with_the_same_raw_count(tmp_path):
    # "quantum" appears once in each of 6 notes (df=6); "counterdiabatic" once in 2 (df=2)
    for i in range(6):
        body = "quantum counterdiabatic" if i < 2 else "quantum"
        _note(tmp_path, f"note{i}", f"2601.{i:05d}", body)
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    cfg.discriminator_type = "paper"
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY)
    assert profile.weight("counterdiabatic") > profile.weight("quantum")


def test_idf_factor_is_selectivity_not_frequency():
    doc_freq = {"generic": 50, "rare": 2}
    n = 60
    assert _idf_factor(doc_freq, "rare", n) > _idf_factor(doc_freq, "generic", n)
    # the mid-band shrinks toward the floor — a df=50/60 word never outranks
    # neutral by much, while a df=2/60 word carries multiple units of selectivity
    assert _idf_factor(doc_freq, "generic", n) <= 1.2
    assert _idf_factor(doc_freq, "rare", n) >= 2.0


def test_idf_floor_keeps_a_small_vault_stable():
    # a df=1 term in a 2-note vault must not explode the weight
    assert _idf_factor({}, "anything", 2) == max(1.0, math.log(2 / 1) + 1.0)


def test_until_and_observed_function_words_never_become_terms(tmp_path):
    for word in ["until", "since", "whether", "because", "without"]:
        assert word in STOPWORDS
    _note(tmp_path, "prosey", "2601.00001", "Until the solver converges, whether it likes it or not.")
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    cfg.discriminator_type = "paper"
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY)
    for word in ["until", "whether"]:
        assert profile.weight(word) == 0.0


def test_capped_to_zero_terms_match_nothing_in_why_lines(tmp_path):
    # "quantum" saturates (df = all 5 notes -> cap removes its body weight);
    # "magnon" appears in only 2 of 5 — the discriminating term, kept by idf
    for i in range(5):
        body = "quantum magnon" if i < 2 else "quantum"
        _note(tmp_path, f"note{i}", f"2602.{i:05d}", body)
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    cfg.discriminator_type = "paper"
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY)
    assert profile.terms["quantum"] == 0.0  # saturation cap fired
    assert profile.weight("magnon") > 0.0  # the rare term survived
    scored = score_item(_feed_item("2603.00001", "quantum magnon dynamics", "quantum magnon physics"), profile)
    assert "quantum" not in scored.terms
    assert "magnon" in scored.terms


def test_authored_semantics_keep_flat_weights(tmp_path):
    # a DELIBERATE tag is taste regardless of corpus frequency — idf applies to
    # body/title-sourced weight only
    for i in range(5):
        _note(tmp_path, f"note{i}", f"2604.{i:05d}", "flunkybodyword", tags=("flunkytag",))
    cfg = Config()
    cfg.roots = [str(tmp_path)]
    cfg.discriminator_type = "paper"
    profile = build_profile(fold_roots([tmp_path], cfg), cfg, TODAY)
    assert profile.weight("flunkytag") > 0  # tag weight rides untouched

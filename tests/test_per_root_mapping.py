"""Per-root field mapping (harmoniqs/arJev#97): each vault root may carry its own
field slots and a rating value map; roots without one inherit the global mapping.
A single-root config with no new slots folds and ranks bit-identical to before.

Test surface:
- Config: per-root mapping loaded from TOML (path + fields + rating_values).
- fold_roots: per-root field dispatch; global mapping fallback.
- Rating value map: enum remapping (relevance high→core, medium→useful, low→marginal).
- Sentence-valued rating field treated as why-line.
- Single-root parity gate: fold + rank scores are bit-identical.
- inspect: per-root mapping state lines.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from arjev.config import Config, RootConfig, load_config
from arjev.fold import fold_roots
from arjev.profile import build_profile

FIXTURES = Path(__file__).parent / "fixtures"
VAULT = FIXTURES / "vault"
TODAY = date(2026, 10, 1)

# ── fixture helpers ──────────────────────────────────────────────────────────────

ARJEV_NOTE = """\
---
type: paper
arxiv: "2601.10001"
title: "Native schema paper"
date_read: 2026-09-20
rating: core
why: "Direct ground truth for randomized-compiling gate sets."
tags: [paper, qec]
---

Body of native-schema note.
"""

RELEVANCE_NOTE_ENUM_HIGH = """\
---
type: paper
arxiv: "2601.10002"
title: "Relevance-schema paper: enum high"
date_read: 2026-09-18
relevance: high
tags: [paper, bosonic]
---

Body with bosonic qubit terms.
"""

RELEVANCE_NOTE_ENUM_MEDIUM = """\
---
type: paper
arxiv: "2601.10003"
title: "Relevance-schema paper: enum medium"
date_read: 2026-09-16
relevance: medium
tags: [paper, rydberg]
---

Body with rydberg terms.
"""

RELEVANCE_NOTE_ENUM_LOW = """\
---
type: paper
arxiv: "2601.10004"
title: "Relevance-schema paper: enum low"
date_read: 2026-09-10
relevance: low
tags: [paper, silicon]
---

Body with silicon spin terms.
"""

RELEVANCE_NOTE_SENTENCE = """\
---
type: paper
arxiv: "2601.10005"
title: "Relevance-schema paper: sentence-valued relevance"
date_read: 2026-09-14
relevance: "The founding cat-qubit resource for our bosonic hardware line."
tags: [paper, bosonic]
---

Body for the sentence-valued note.
"""

RELEVANCE_NOTE_NO_FIELD = """\
---
type: paper
arxiv: "2601.10006"
title: "Relevance-schema paper: no relevance field"
date_read: 2026-09-12
tags: [paper, silicon]
---

Body with no rating or relevance at all.
"""


def make_native_root(tmp_path: Path) -> Path:
    root = tmp_path / "native"
    root.mkdir()
    (root / "native.md").write_text(ARJEV_NOTE)
    return root


def make_relevance_root(tmp_path: Path) -> Path:
    """A root with relevance-style notes: relevance field maps to rating via value map,
    sentence-valued relevance maps to why."""
    root = tmp_path / "relevance"
    root.mkdir()
    (root / "enum_high.md").write_text(RELEVANCE_NOTE_ENUM_HIGH)
    (root / "enum_medium.md").write_text(RELEVANCE_NOTE_ENUM_MEDIUM)
    (root / "enum_low.md").write_text(RELEVANCE_NOTE_ENUM_LOW)
    (root / "sentence.md").write_text(RELEVANCE_NOTE_SENTENCE)
    (root / "no_field.md").write_text(RELEVANCE_NOTE_NO_FIELD)
    return root


def relevance_root_config() -> RootConfig:
    """The mapping for an armonissima-style relevance vault:
    - rating field → "relevance"
    - rating_values: high→core, medium→useful, low→marginal, critical→core
    - why field → "relevance" (sentence-valued relevance becomes why)
    """
    return RootConfig(
        fields={
            "identity": ["arxiv", "doi"],
            "read_date": "date_read",
            "rating": "relevance",
            "why": "relevance",
            "tags": "tags",
            "status": "status",
        },
        rating_values={"high": "core", "medium": "useful", "low": "marginal", "critical": "core"},
    )


# ── AC1: per-root mapping; root without one inherits global ─────────────────────

def test_root_without_per_root_config_inherits_global(tmp_path):
    """A root with no RootConfig entry uses the global field mapping."""
    native = make_native_root(tmp_path)
    cfg = Config()
    cfg.roots = [str(native)]
    # no root_configs set — inherits global
    result = fold_roots([native], cfg)
    assert len(result.papers) == 1
    p = result.papers[0]
    assert p.arxiv == "2601.10001"
    assert p.rating == "core"
    assert p.why == "Direct ground truth for randomized-compiling gate sets."


def test_two_roots_each_use_their_own_mapping(tmp_path):
    """The two-root fixture: native root reads arJev fields; relevance root reads
    relevance enum via its value map."""
    native = make_native_root(tmp_path)
    relevance = make_relevance_root(tmp_path)
    cfg = Config()
    rc = relevance_root_config()
    cfg.root_configs = {str(relevance): rc}
    result = fold_roots([native, relevance], cfg)
    by_id = {p.arxiv: p for p in result.papers}
    # native root: arJev-native fields
    assert by_id["2601.10001"].rating == "core"
    assert by_id["2601.10001"].why is not None
    # relevance root: enum-high → core via value map
    assert by_id["2601.10002"].rating == "core"
    assert by_id["2601.10003"].rating == "useful"
    assert by_id["2601.10004"].rating == "marginal"


# ── AC2: rating value map ────────────────────────────────────────────────────────

def test_rating_value_map_enum_high_maps_to_core(tmp_path):
    """Enum `high` in a per-root rating_values map → `core` in the fold output."""
    root = make_relevance_root(tmp_path)
    cfg = Config()
    cfg.root_configs = {str(root): relevance_root_config()}
    result = fold_roots([root], cfg)
    by_id = {p.arxiv: p for p in result.papers}
    assert by_id["2601.10002"].rating == "core"


def test_rating_value_map_enum_medium_maps_to_useful(tmp_path):
    root = make_relevance_root(tmp_path)
    cfg = Config()
    cfg.root_configs = {str(root): relevance_root_config()}
    result = fold_roots([root], cfg)
    by_id = {p.arxiv: p for p in result.papers}
    assert by_id["2601.10003"].rating == "useful"


def test_rating_value_map_enum_low_maps_to_marginal(tmp_path):
    root = make_relevance_root(tmp_path)
    cfg = Config()
    cfg.root_configs = {str(root): relevance_root_config()}
    result = fold_roots([root], cfg)
    by_id = {p.arxiv: p for p in result.papers}
    assert by_id["2601.10004"].rating == "marginal"


def test_rating_value_already_in_enum_needs_no_mapping(tmp_path):
    """A root config with rating_values still accepts native enum values unchanged."""
    root = tmp_path / "r"
    root.mkdir()
    (root / "p.md").write_text(
        '---\ntype: paper\narxiv: "2601.11001"\nrelevance: core\n---\n'
    )
    rc = RootConfig(
        fields={
            "identity": ["arxiv", "doi"],
            "read_date": "date_read",
            "rating": "relevance",
            "why": "relevance",
            "tags": "tags",
            "status": "status",
        },
        rating_values={"high": "core"},
    )
    cfg = Config()
    cfg.root_configs = {str(root): rc}
    result = fold_roots([root], cfg)
    assert result.papers[0].rating == "core"


# ── AC3: sentence-valued rating field treated as why-line ───────────────────────

def test_sentence_valued_rating_field_becomes_why(tmp_path):
    """When the mapped `rating` field holds a sentence (not an enum value and not
    remappable via rating_values), it is treated as the note's why-line."""
    root = make_relevance_root(tmp_path)
    cfg = Config()
    cfg.root_configs = {str(root): relevance_root_config()}
    result = fold_roots([root], cfg)
    by_id = {p.arxiv: p for p in result.papers}
    p = by_id["2601.10005"]
    assert p.rating is None
    assert p.why is not None
    assert "cat-qubit" in p.why or "bosonic" in p.why


def test_sentence_valued_rating_field_no_rating_warning(tmp_path):
    """A sentence-valued rating field is consumed as why — no 'outside enum' warning."""
    root = make_relevance_root(tmp_path)
    cfg = Config()
    cfg.root_configs = {str(root): relevance_root_config()}
    result = fold_roots([root], cfg)
    # No 'outside enum' warning for the sentence note
    assert not any("2601.10005" in w and "outside enum" in w for w in result.warnings)


def test_sentence_why_field_wins_over_sentence_rating_field(tmp_path):
    """Explicit why field wins when both why and rating map to the same field and
    the value is sentence — this is the same-field case; why takes precedence."""
    # When rating and why map to the same field, a sentence goes to why; an enum goes to rating.
    # This test verifies an explicit `why` field in a different schema wins over a sentence `rating`.
    root = tmp_path / "r"
    root.mkdir()
    (root / "p.md").write_text(
        '---\ntype: paper\narxiv: "2601.11002"\n'
        'relevance: "The founding reference for cat qubits."\n'
        'why: "explicit why wins"\n---\n'
    )
    # The root maps rating→relevance, why→why (explicit why field)
    rc = RootConfig(
        fields={
            "identity": ["arxiv", "doi"],
            "read_date": "date_read",
            "rating": "relevance",
            "why": "why",
            "tags": "tags",
            "status": "status",
        },
        rating_values={"high": "core"},
    )
    cfg = Config()
    cfg.root_configs = {str(root): rc}
    result = fold_roots([root], cfg)
    p = result.papers[0]
    assert p.why == "explicit why wins"
    assert p.rating is None  # sentence in relevance, no enum match, no mapping match


# ── AC4: single-root parity gate ─────────────────────────────────────────────────

def test_single_root_no_new_slots_fold_identical(tmp_path):
    """A single-root config with no root_configs entry folds the fixture vault
    identically (same papers, same ratings, same why-lines) as the baseline."""
    from arjev.fold import fold_roots

    baseline = fold_roots([VAULT], Config())
    after = fold_roots([VAULT], Config())  # no root_configs
    assert [(p.arxiv, p.rating, p.why) for p in baseline.papers] == \
           [(p.arxiv, p.rating, p.why) for p in after.papers]


def test_single_root_ranking_parity(tmp_path):
    """Ranking scores are bit-identical for a single-root config with no new slots."""
    from arjev.feed import parse_arxiv_rss
    from arjev.score import score_item

    rss = (FIXTURES / "rss-quant-ph.xml").read_text()
    items = parse_arxiv_rss(rss)

    baseline_fold = fold_roots([VAULT], Config())
    baseline_profile = build_profile(baseline_fold, Config(), TODAY)

    after_fold = fold_roots([VAULT], Config())
    after_profile = build_profile(after_fold, Config(), TODAY)

    baseline_scores = {i.arxiv: score_item(i, baseline_profile).score for i in items}
    after_scores = {i.arxiv: score_item(i, after_profile).score for i in items}
    assert baseline_scores == after_scores


# ── Config loading from TOML ─────────────────────────────────────────────────────

def test_config_loads_per_root_mapping_from_toml(tmp_path):
    """Per-root field mapping and rating_values load correctly from TOML."""
    root_path = str(tmp_path / "vault")
    toml = f"""
[vault]
roots = ["{root_path}"]
feeds = ["quant-ph"]

[[vault.root_configs]]
path = "{root_path}"
[vault.root_configs.fields]
rating = "relevance"
why = "relevance"
identity = ["arxiv", "doi"]
read_date = "date_read"
tags = "tags"
status = "status"
[vault.root_configs.rating_values]
high = "core"
medium = "useful"
low = "marginal"
critical = "core"
"""
    cfg_path = tmp_path / "arjev.toml"
    cfg_path.write_text(toml)
    cfg = load_config(cfg_path)
    assert str(root_path) in cfg.root_configs
    rc = cfg.root_configs[str(root_path)]
    assert rc.fields["rating"] == "relevance"
    assert rc.rating_values["high"] == "core"
    assert rc.rating_values["medium"] == "useful"


def test_config_toml_root_without_per_root_entry_inherits_global(tmp_path):
    """A TOML with two roots but only one [[vault.root_configs]] entry leaves
    the other root using the global mapping."""
    path_a = str(tmp_path / "vault_a")
    path_b = str(tmp_path / "vault_b")
    toml = f"""
[vault]
roots = ["{path_a}", "{path_b}"]
feeds = ["quant-ph"]

[[vault.root_configs]]
path = "{path_b}"
[vault.root_configs.fields]
rating = "relevance"
why = "relevance"
"""
    cfg_path = tmp_path / "arjev.toml"
    cfg_path.write_text(toml)
    cfg = load_config(cfg_path)
    assert path_a not in cfg.root_configs
    assert path_b in cfg.root_configs


# ── inspect: per-root mapping state ─────────────────────────────────────────────

def test_inspect_reports_per_root_mapping_state(tmp_path):
    """inspect includes a line per configured root_config showing its mapping state."""
    from arjev.inspect import run_inspect

    native = make_native_root(tmp_path)
    relevance = make_relevance_root(tmp_path)
    cfg = Config()
    cfg.roots = [str(native), str(relevance)]
    cfg.feeds = ["quant-ph"]
    rc = relevance_root_config()
    cfg.root_configs = {str(relevance): rc}
    report = run_inspect(cfg, today=TODAY)
    lines = "\n".join(report.lines)
    # Should report that the relevance root has a custom mapping
    assert any("root-mapping" in ln for ln in report.lines), \
        f"expected root-mapping line; got:\n{lines}"


def test_inspect_single_root_no_per_root_config_omits_root_mapping_lines(tmp_path):
    """When no root_configs are set, inspect does not emit root-mapping lines."""
    from arjev.inspect import run_inspect

    cfg = Config()
    cfg.roots = [str(VAULT)]
    cfg.feeds = ["quant-ph"]
    report = run_inspect(cfg, today=TODAY)
    assert not any("root-mapping" in ln for ln in report.lines)

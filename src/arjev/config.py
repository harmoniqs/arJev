"""Config: arjev.toml (tomllib reads; the static template writer lives in init.py).
The default field mapping is the Harmoniqs paper-note schema; every mapped name is
remappable so any Obsidian/Zotero vault works (spec: Paper-note schema v2).

Per-root field mapping (harmoniqs/arJev#97): a [[vault.root_configs]] table array
lets each root carry its own field slots and an optional rating value map. A root
without an entry inherits the global [vault.fields] mapping unchanged.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_FIELDS = {
    "identity": ["arxiv", "doi"],
    "read_date": "date_read",
    "rating": "rating",
    "why": "why",
    "tags": "tags",
    "status": "status",
}


@dataclass
class RootConfig:
    """Per-root field mapping and optional rating value map (issue #97).

    `fields` mirrors the global mapping slots (identity, read_date, rating, why,
    tags, status); absent slots inherit from the global mapping at fold time.
    `rating_values` maps source enum values to the canonical RATING_ENUM set
    (e.g. {"high": "core", "medium": "useful", "low": "marginal"}).
    """

    fields: dict[str, Any] = field(default_factory=dict)
    rating_values: dict[str, str] = field(default_factory=dict)


def _expand(p: str) -> str:

    return str(Path(p).expanduser()) if p.startswith("~") else p


@dataclass
class Config:
    roots: list[str] = field(default_factory=list)
    include: str = "**/*.md"
    discriminator_type: str = "paper"
    fields: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FIELDS))
    # Per-root field mapping (issue #97): keyed by the expanded root path string.
    # A root absent from this dict inherits the global `fields` mapping unchanged.
    root_configs: dict[str, RootConfig] = field(default_factory=dict)
    half_life_days: float = 180.0
    # field-neutral: no category is ever defaulted — a missing feeds list is a
    # config error the digest names plainly (issue #53)
    feeds: list[str] = field(default_factory=list)
    top: int = 5
    screen: int = 40
    probe_k: int = 20
    digest_dir: str | None = None
    library_dir: str | None = None
    papers_dir: str | None = None
    note_template: str | None = None
    jev_min_confidence: float = 0.6
    ranking: str = "jev-first"  # jev-first | lexical-first
    state_policy: str = "fixed-15"  # fixed-15 | budget-greedy (the Jev state assembly)
    taste_budget_bytes: int = 2500  # the taste half of the Jev state, greedy policy
    candidate_content: bool = False  # finalist conclusions enrichment (candidate half)
    candidate_pace_s: float = 3.0  # politeness gap between candidate PDF fetches
    directives_path: str | None = None  # default: <roots[0]>/arjev-directives.md
    enrich_command: str | None = None  # the text-generation seam (docs/amicode-integration.md)
    jev_pace_s: float = 0.05  # politeness gap between Jev calls in jev-first
    slack_channel: str | None = None
    slack_keepers: list[str] = field(default_factory=list)
    why_style: str = "terms"  # terms | opaque | none
    who_style: str = "authors"  # full | authors | none — issue #87; the PDF fetch stays opt-in
    emoji_map: dict[str, str] = field(default_factory=lambda: {"thumbsup": "keep", "eyes": "read-later", "x": "skip"})

    @property
    def expanded_roots(self) -> list[Path]:
        return [Path(_expand(r)) for r in self.roots]


def default_config_path() -> Path:
    import os

    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "arjev" / "arjev.toml"


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    raw: dict[str, Any] = {}
    if path.is_file():
        with path.open("rb") as f:
            raw = tomllib.load(f)
    cfg = Config()
    vault = raw.get("vault", {})
    cfg.roots = [_expand(r) for r in vault.get("roots", [])]
    cfg.include = vault.get("include", cfg.include)
    if "type" in vault:
        cfg.discriminator_type = vault["type"]
    fields = {**DEFAULT_FIELDS, **vault.get("fields", {})}
    if isinstance(fields["identity"], str):
        fields["identity"] = [fields["identity"]]
    cfg.fields = fields
    cfg.half_life_days = float(vault.get("half_life_days", cfg.half_life_days))
    # TOML: keys written after a [table] header belong to that table — accept
    # both placements for every digest-level key (the papers_dir lesson, generalized)
    for key in ("top", "screen", "probe_k"):
        setattr(cfg, key, int(raw.get(key, vault.get(key, getattr(cfg, key)))))
    cfg.feeds = list(raw.get("feeds", vault.get("feeds", cfg.feeds)))
    if "ranking" in vault and "ranking" not in raw:
        cfg.ranking = vault["ranking"]
    for key in ("digest_dir", "library_dir", "papers_dir", "note_template"):
        # TOML: keys written after [vault] belong to that table — accept both placements
        setattr(cfg, key, raw.get(key) or vault.get(key))
    jev = raw.get("jev", {})
    cfg.jev_min_confidence = float(jev.get("min_confidence", cfg.jev_min_confidence))
    cfg.ranking = raw.get("ranking", cfg.ranking)
    if cfg.ranking not in ("jev-first", "lexical-first"):
        raise ValueError(f"ranking must be jev-first or lexical-first, got {cfg.ranking!r}")
    cfg.jev_pace_s = float(jev.get("pace_s", cfg.jev_pace_s))
    cfg.state_policy = str(jev.get("state_policy", cfg.state_policy))
    if cfg.state_policy not in ("fixed-15", "budget-greedy"):
        raise ValueError(f"state_policy must be fixed-15 or budget-greedy, got {cfg.state_policy!r}")
    cfg.taste_budget_bytes = int(jev.get("taste_budget_bytes", cfg.taste_budget_bytes))
    cfg.candidate_content = bool(jev.get("candidate_content", cfg.candidate_content))
    cfg.candidate_pace_s = float(jev.get("candidate_pace_s", cfg.candidate_pace_s))
    cfg.directives_path = raw.get("directives_path") or vault.get("directives_path")
    cfg.enrich_command = raw.get("enrich_command") or vault.get("enrich_command")
    # Per-root field mapping (issue #97): [[vault.root_configs]] array of tables.
    # Each entry must carry a `path` key; `fields` and `rating_values` are optional.
    for rc_raw in vault.get("root_configs", []):
        rc_path = rc_raw.get("path")
        if not rc_path:
            continue
        rc_path = _expand(str(rc_path))
        rc_fields_raw = rc_raw.get("fields", {})
        rc_fields: dict[str, Any] = {}
        if rc_fields_raw:
            rc_fields = dict(rc_fields_raw)
            if "identity" in rc_fields and isinstance(rc_fields["identity"], str):
                rc_fields["identity"] = [rc_fields["identity"]]
        rc_rating_values = {str(k): str(v) for k, v in rc_raw.get("rating_values", {}).items()}
        cfg.root_configs[rc_path] = RootConfig(fields=rc_fields, rating_values=rc_rating_values)
    slack = raw.get("slack", {})
    cfg.slack_channel = slack.get("channel")
    cfg.slack_keepers = list(slack.get("keepers", []))
    cfg.why_style = slack.get("why_style", cfg.why_style)
    cfg.who_style = slack.get("who_style", cfg.who_style)
    if "emoji_map" in slack:
        cfg.emoji_map = dict(slack["emoji_map"])
    return cfg

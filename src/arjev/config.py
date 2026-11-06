"""Config: arjev.toml (tomllib reads; the static template writer lives in init.py).
The default field mapping is the Harmoniqs paper-note schema; every mapped name is
remappable so any Obsidian/Zotero vault works (spec: Paper-note schema v2)."""

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


def _expand(p: str) -> str:

    return str(Path(p).expanduser()) if p.startswith("~") else p


@dataclass
class Lane:
    """One personal lane (issue #121): a recipient and the roots and feeds that
    rank for them. Nothing falls through from the shared config — a personal lane
    never folds another researcher's vault, and a category is never defaulted."""

    name: str
    recipient: str | None = None  # the Slack member id the picks are DM'd to
    roots: list[str] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)
    top: int | None = None
    papers_dir: str | None = None
    digest_dir: str | None = None
    directives_path: str | None = None


@dataclass
class Config:
    roots: list[str] = field(default_factory=list)
    include: str = "**/*.md"
    discriminator_type: str = "paper"
    fields: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FIELDS))
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
    lanes: dict[str, Lane] = field(default_factory=dict)  # [lanes.<name>] tables (issue #121)
    lane: str | None = None  # set on a lane's derived config — the state scope it runs in
    slack_recipient: str | None = None  # a lane's DM recipient (set on the derived config only)

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
    slack = raw.get("slack", {})
    cfg.slack_channel = slack.get("channel")
    cfg.slack_keepers = list(slack.get("keepers", []))
    cfg.why_style = slack.get("why_style", cfg.why_style)
    cfg.who_style = slack.get("who_style", cfg.who_style)
    if "emoji_map" in slack:
        cfg.emoji_map = dict(slack["emoji_map"])
    cfg.lanes = {name: _parse_lane(name, table) for name, table in raw.get("lanes", {}).items()}
    return cfg


def _parse_lane(name: str, table: dict[str, Any]) -> Lane:
    from .lanes import validate_lane_name

    validate_lane_name(name)
    top = table.get("top")
    return Lane(
        name=name,
        recipient=table.get("recipient"),
        roots=[_expand(r) for r in table.get("roots", [])],
        feeds=list(table.get("feeds", [])),
        top=int(top) if top is not None else None,
        papers_dir=table.get("papers_dir"),
        digest_dir=table.get("digest_dir"),
        directives_path=table.get("directives_path"),
    )


def lane_config(cfg: Config, name: str) -> Config:
    """The lane's own Config: the shared one's ranking knobs and field mapping,
    with the lane's roots, feeds and output dirs, the recipient's DM as the only
    Slack target, and the recipient as the only keeper. The base is not mutated."""
    import copy

    lane = cfg.lanes.get(name)
    if lane is None:
        known = ", ".join(sorted(cfg.lanes)) or "none configured"
        raise SystemExit(f"no lane {name!r} in the config (lanes: {known})")
    derived = copy.deepcopy(cfg)
    derived.lanes = {}
    derived.lane = name
    derived.roots = list(lane.roots)
    derived.feeds = list(lane.feeds)
    if lane.top is not None:
        derived.top = lane.top
    derived.papers_dir = lane.papers_dir
    derived.digest_dir = lane.digest_dir
    derived.directives_path = lane.directives_path
    derived.slack_channel = None  # a lane never posts to the shared channel
    derived.slack_recipient = lane.recipient
    derived.slack_keepers = [lane.recipient] if lane.recipient else []
    return derived

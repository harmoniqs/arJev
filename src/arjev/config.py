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
class Config:
    roots: list[str] = field(default_factory=list)
    include: str = "**/*.md"
    discriminator_type: str = "paper"
    fields: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FIELDS))
    half_life_days: float = 180.0
    feeds: list[str] = field(default_factory=lambda: ["quant-ph"])
    top: int = 5
    screen: int = 40
    probe_k: int = 20
    digest_dir: str | None = None
    library_dir: str | None = None
    papers_dir: str | None = None
    note_template: str | None = None
    jev_min_confidence: float = 0.6

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
    for key in ("top", "screen", "probe_k"):
        setattr(cfg, key, int(raw.get(key, getattr(cfg, key))))
    cfg.feeds = list(raw.get("feeds", cfg.feeds))
    cfg.digest_dir = raw.get("digest_dir")
    cfg.library_dir = raw.get("library_dir")
    cfg.papers_dir = raw.get("papers_dir")
    cfg.note_template = raw.get("note_template")
    cfg.jev_min_confidence = float(raw.get("jev", {}).get("min_confidence", cfg.jev_min_confidence))
    return cfg

"""The who-line's affiliation seam (issue #87): authors as the feed reports
them, affiliations as the paper's own PDF prints them — a paper-level set,
never bound per author, dropped on parse ambiguity. Attribution doctrine in
ADR 0002: the paper's printed claim or human curation, never inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WhoInfo:
    """Per-pick attribution for rendering. `hits` are tracked-people matches
    (name, curated group or None); `affiliations` are already tail-trimmed,
    deduped, and capped; `more_affiliations` is the k beyond the cap."""

    authors: list[str] = field(default_factory=list)
    hits: list[tuple[str, str | None]] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    more_affiliations: int = 0
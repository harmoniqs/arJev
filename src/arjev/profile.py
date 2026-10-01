"""The taste profile: the fold's demonstrated taste, recency-decayed, graph-weighted.
Only notes that pass the staged gate contribute (untouched staged stubs are invisible).

Signals per contributing note (spec: tags · why-lines · body terms · wikilink weights
· 180d-half-life decay):
- tags: weight TAG_WEIGHT each (deliberate signals; the discriminator value "paper"
  is not a taste term — it's the type, not a preference).
- title + body tokens: weight BODY_WEIGHT per occurrence, minus stopwords, len >= 3.
- why lines: kept verbatim (capped later in Jev state), recency-sorted for state assembly.
- decay: weight × 0.5^(days/half_life); no read_date (ladder exhausted) → weight 1.
- graph: everything scales by (1 + 0.5 × min(3, inlinks)).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .fold import FoldResult

TAG_WEIGHT = 3.0
BODY_WEIGHT = 1.0
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has", "have",
    "had", "not", "but", "its", "into", "about", "over", "under", "between", "through",
    "which", "their", "these", "those", "such", "than", "then", "them", "they", "our", "one",
    "two", "can", "may", "also", "more", "most", "other", "paper", "note", "using", "based",
    "synthetic", "benchmark", "abstract", "summary", "citation", "exercise", "exercises",
    "fixture", "deliberately",  # fixture hygiene: never let fixture scaffolding become taste
}
DEGRADED_MIN_NOTES = 5


def _decay(read_date: date | None, now: date, half_life_days: float) -> float:
    if read_date is None:
        return 1.0
    days = max(0.0, (now - read_date).days)
    return 0.5 ** (days / half_life_days)


def _tokens(text: str) -> list[str]:
    out = []
    for tok in text.lower().replace("|", " ").split():
        tok = tok.strip(".,;:!?()[]{}\"'")
        if len(tok) >= 3 and tok.isalnum() and tok not in STOPWORDS:
            out.append(tok)
    return out


@dataclass
class Profile:
    terms: dict[str, float] = field(default_factory=dict)
    why_lines: list[tuple[date | None, str]] = field(default_factory=list)
    recent_titles: list[str] = field(default_factory=list)
    note_count: int = 0
    degraded: bool = True

    def weight(self, term: str) -> float:
        return self.terms.get(term.lower().strip(), 0.0)


def _bump(profile: Profile, term: str, weight: float, mult: float, cfg) -> None:
    t = term.lower().strip()
    if t and t != cfg.discriminator_type:
        profile.terms[t] = profile.terms.get(t, 0.0) + weight * mult


def build_profile(fold: FoldResult, cfg, now: date) -> Profile:
    """The lab's demonstrated taste. An untouched staged note contributes nothing."""
    profile = Profile()
    contributing = [p for p in fold.papers if p.contributes_taste]
    profile.note_count = len(fold.papers)
    profile.degraded = len(fold.papers) < DEGRADED_MIN_NOTES or not any(p.why for p in contributing)
    for note in contributing:
        mult = _decay(note.read_date, now, cfg.half_life_days) * (1 + 0.5 * min(3, note.inlinks))
        for tag in note.tags:
            _bump(profile, tag, TAG_WEIGHT, mult, cfg)
        for tok in _tokens(note.title):
            _bump(profile, tok, BODY_WEIGHT, mult, cfg)
        for tok in _tokens(note.body):
            _bump(profile, tok, BODY_WEIGHT, mult, cfg)
        if note.why:
            profile.why_lines.append((note.read_date, note.why))
    profile.why_lines.sort(key=lambda pair: pair[0] or date.min, reverse=True)
    dated = sorted(contributing, key=lambda p: p.read_date or date.min, reverse=True)
    profile.recent_titles = [p.title for p in dated[:3]]
    return profile


def profile_flag(profile: Profile) -> str:
    return "profile-degraded" if profile.degraded else "ok"


def staged_audit(fold: FoldResult, cfg, now: date | None = None) -> list[str]:
    """The staged-gate fold self-audit (spec slice 5): the gate holds iff the taste
    profile built WITH untouched staged notes present equals the profile built
    WITHOUT them. The equivalence form is exact — no shared-term false positives
    (the strict-overlap reading flags every schema-discussing note), and it
    detects a broken gate directly (a leaked stub's terms make the two differ)."""
    now = now or date.today()
    base = build_profile(fold, cfg, now)
    untouched = [p for p in fold.papers if p.status == "staged" and not p.touched]
    if not untouched:
        return []
    clean = FoldResult(papers=[p for p in fold.papers if p not in untouched], warnings=fold.warnings)
    reference = build_profile(clean, cfg, now)
    extra = {t for t, w in base.terms.items() if abs(reference.terms.get(t, 0.0) - w) > 1e-9}
    if not extra:
        return []
    stub_names = ", ".join(p.file.name for p in untouched)
    return [f"staged gate leak: terms {sorted(extra)} carry weight from untouched staged notes ({stub_names})"]

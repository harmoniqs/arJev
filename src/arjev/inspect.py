"""arjev inspect: the read-only verification verb (issue #55) — the agent's
acceptance check, the self-server's edit-verify loop, the operator's doctor.

Two blocks, stable machine-greppable line shapes (the runbook greps them verbatim):
- checklist state: every init-template decision slot with set/empty status — the
  slot names mirror the template's verbatim, so one name serves both surfaces;
- the fold's view: what the config actually sees in the vault, with the fold's
  own warnings surfacing verbatim.

Exit is nonzero iff a blocking condition holds. The set is closed — no feeds,
no roots, zero identity-bearing notes — everything else is advisory. Blocking is
deliberately stricter than digest-fatal: a digest on an unmapped vault runs
degraded rather than failing, but an adoption check that passes there proves
nothing, so inspect blocks where the digest would merely be meaningless.

The verb never writes: the fold, the profile, and the directives load are all
read-only, and no state, journal, or receipt path is touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .directives import Directives, load_directives
from .fold import FoldResult, fold_roots, staged_worklist
from .profile import Profile, build_profile

BLOCK_NO_FEEDS = "blocked: no feeds configured"
BLOCK_NO_ROOTS = "blocked: no roots configured"
BLOCK_NO_IDENTITY = "blocked: zero identity-bearing notes"


@dataclass
class InspectReport:
    lines: list[str] = field(default_factory=list)  # stdout — the two blocks, stable shapes
    blocked: list[str] = field(default_factory=list)  # stderr — one line per blocking condition


def run_inspect(cfg: Config, today: date | None = None) -> InspectReport:
    today = today or date.today()
    fold = fold_roots(cfg.expanded_roots, cfg)
    directives = load_directives(cfg)
    profile = build_profile(fold, cfg, today, directives=directives)
    report = InspectReport(
        lines=_checklist_lines(cfg)
        + _fold_lines(fold, profile, len(staged_worklist(fold)), directives)
    )
    if not cfg.feeds:
        report.blocked.append(BLOCK_NO_FEEDS)
    if not cfg.roots:
        report.blocked.append(BLOCK_NO_ROOTS)
    if not fold.papers:
        report.blocked.append(BLOCK_NO_IDENTITY)
    return report


def _checklist_lines(cfg: Config) -> list[str]:
    """One stable line per init-template decision slot, in template order —
    `slot <name>: set (<value>)` or `slot <name>: empty`."""
    slots = [
        ("roots", bool(cfg.roots), ", ".join(cfg.roots)),
        ("include", True, cfg.include),
        ("type", True, cfg.discriminator_type),
        ("half_life_days", True, str(cfg.half_life_days)),
        ("feeds", bool(cfg.feeds), ", ".join(cfg.feeds)),
        ("top", True, str(cfg.top)),
        ("screen", True, str(cfg.screen)),
        ("probe_k", True, str(cfg.probe_k)),
        ("directives_path", cfg.directives_path is not None, cfg.directives_path or ""),
        ("identity", bool(cfg.fields["identity"]), ", ".join(cfg.fields["identity"])),
        ("read_date", True, cfg.fields["read_date"]),
        ("rating", True, cfg.fields["rating"]),
        ("why", True, cfg.fields["why"]),
        ("tags", True, cfg.fields["tags"]),
        ("status", True, cfg.fields["status"]),
        ("digest_dir", cfg.digest_dir is not None, cfg.digest_dir or ""),
        ("library_dir", cfg.library_dir is not None, cfg.library_dir or ""),
    ]
    return [
        f"slot {name}: {'set' if is_set else 'empty'}" + (f" ({value})" if is_set and value else "")
        for name, is_set, value in slots
    ]


def _fold_lines(fold: FoldResult, profile: Profile, staged: int, directives: Directives) -> list[str]:
    """The fold's view: the scan funnel, the profile it yields, and the fold's
    warnings verbatim — `warning: <text>`, one per line, never reworded."""
    lines = [
        f"fold scanned: {fold.scanned}",
        f"fold type-matched: {fold.type_matched}",
        f"fold identity-bearing: {len(fold.papers)}",
        f"fold profile-terms: {len(profile.terms)}",
        f"fold staged: {staged}",
    ]
    if directives.present:
        lines.append(f"fold directives: loaded ({len(directives.all_terms())} terms)")
    else:
        lines.append("fold directives: none")
    lines.append(f"fold warnings: {len(fold.warnings) if fold.warnings else 'none'}")
    return lines + [f"warning: {w}" for w in fold.warnings]

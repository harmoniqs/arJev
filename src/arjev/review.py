"""`arjev review`: the week-in-review — a pure re-read of the digest journal,
Jev receipts, and label ledger (the same three sources calibrate joins), with
zero fetches and zero Jev calls. The daily digest is capped at top-5 and sees
one day of the firehose; the review looks across the window: the cap's
casualties, your people, the Jev-vs-lexical divergences, the week's receipts.
Read-only — it proposes, never stages; every count states its n (issue #83)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from .calibrate import (
    NEGATIVE_TYPES,
    POSITIVE_TYPES,
    _brier,
    _latest_receipts,
    _load_receipts,
    _precision_at_5,
)
from .config import Config
from .ledger import Label, LabelLedger
from .rerank import journal_path

BURIED_LIMIT = 10
DIVERGENCE_LIMIT = 5


@dataclass
class Review:
    days: int
    window_runs: list[dict] = field(default_factory=list)
    buried: list[dict] = field(default_factory=list)
    buried_total: int = 0
    people: list[dict] = field(default_factory=list)
    jev_hot: list[dict] = field(default_factory=list)
    lexical_hot: list[dict] = field(default_factory=list)
    receipts_counts: dict = field(default_factory=dict)
    calibration: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"# arjev week-in-review — {self.days} days", ""]
        if self.window_runs:
            lines.append(
                f"window: {len(self.window_runs)} run(s), {self.window_runs[0]['ts']} → {self.window_runs[-1]['ts']}"
            )
        else:
            lines.append("window: no runs in the window — an empty week is information, not a failure")
        lines.append("")

        buried_header = (
            f"## The Buried — the cap's casualties (top {len(self.buried)} of "
            f"{self.buried_total} relevant, never posted)"
        )
        lines.append(buried_header)
        if self.buried:
            lines.extend(
                f"- {c['arxiv']} — {c['title']} (jev {c['jev'].get('top')} {c['jev']['confidence']:.2f}, "
                f"pool {c['pool']})" for c in self.buried
            )
        else:
            lines.append("- nothing buried this window")
        lines.append("")

        lines.append(f"## Your People — author-lane matches this window (n={len(self.people)})")
        if self.people:
            lines.extend(
                f"- {c['arxiv']} — {c['title']} — {', '.join(c['authors'])} (posted)"
                if c.get("posted")
                else f"- {c['arxiv']} — {c['title']} — {', '.join(c['authors'])}"
                for c in self.people
            )
        else:
            lines.append("- no roster matches this window")
        lines.append("")

        lines.append(f"## The Divergences — Jev vs the words (top {DIVERGENCE_LIMIT} per tail)")
        lines.append("jev-hot, lexical-buried:")
        lines.extend(_divergence_lines(self.jev_hot))
        lines.append("lexical-hot, jev-cold:")
        lines.extend(_divergence_lines(self.lexical_hot))
        lines.append("")

        counts = self.receipts_counts
        lines.append("## The Week's Receipts")
        lines.append(
            f"- posted: {counts['posted']} · kept {counts['kept']} · "
            f"skipped {counts['skipped']} · labeled {counts['labeled']}"
        )
        calibration = self.calibration
        precision = calibration["precision_at_5"]
        brier = calibration["brier"]
        if counts["labeled"]:
            precision_value = precision["precision"] if precision["precision"] is not None else "n/a"
            lines.append(
                f"- calibration: precision@5 {precision_value} (n={precision['n']}) · "
                f"brier n: score {brier['score']['n']}, noul {brier['noul']['n']}"
            )
        else:
            lines.append(
                "- calibration: no labels yet — the receipts are blind this window; "
                "Jev is unmeasured, not vindicated (keep/skip the digest's picks)"
            )
        lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines) + "\n"

    def render_slack(self) -> str:
        """The channel rendering — Slack mrkdwn, written for the people in the
        channel: bold section titles, titles linked to arXiv, readable dates,
        plain labels. The divergences and internal notes stay in render()'s file
        report (found live 2026-10-25: raw Markdown read as noise in #papers)."""
        if self.window_runs:
            first, last = (_short_date(self.window_runs[i]["ts"]) for i in (0, -1))
            span = first if first == last else f"{first} – {last}"
            runs = len(self.window_runs)
            head = f"*arJev week in review* · {span} · {runs} digest{'s' if runs != 1 else ''}"
        else:
            head = f"*arJev week in review* · no digests ran in the last {self.days} days"
        lines = [head, ""]

        lines.append(f"*Worth a look — relevant papers that missed a daily top 5* "
                     f"({len(self.buried)} of {self.buried_total})")
        if self.buried:
            lines.extend(f"• {_slack_link(c)} — {_label(c)}" for c in self.buried)
        else:
            lines.append("_Nothing relevant was left out this week._")
        lines.append("")

        lines.append("*Your people* — papers by tracked authors")
        if self.people:
            for c in self.people:
                authors = ", ".join(c["authors"][:3]) + (" et al." if len(c["authors"]) > 3 else "")
                suffix = " · posted" if c.get("posted") else ""
                lines.append(f"• {_slack_link(c)} — {authors}{suffix}")
        else:
            lines.append("_No tracked authors this week._")
        lines.append("")

        counts = self.receipts_counts
        lines.append("*This week*")
        lines.append(f"• {counts['posted']} picks posted · {counts['kept']} kept · {counts['skipped']} skipped")
        if counts["labeled"]:
            precision = self.calibration["precision_at_5"]
            value = precision["precision"]
            shown = f"{value:.0%}" if isinstance(value, float) else "n/a"
            lines.append(f"• {shown} of top-5 picks were kept (n={precision['n']})")
        else:
            lines.append("• No reactions yet — 👍 or ❌ a pick to start calibrating the ranking.")
        return "\n".join(lines) + "\n"


def review(days: int = 7, now: date | None = None) -> Review:
    jp = journal_path()
    if not jp.is_file():
        raise FileNotFoundError("no digest journal — digest first")
    runs = [json.loads(line) for line in jp.read_text().splitlines() if line.strip()]
    cutoff = datetime.combine((now or date.today()) - timedelta(days=days), time.min, tzinfo=UTC)
    window = [run for run in runs if _run_ts(run) >= cutoff]

    report = Review(days=days, window_runs=window)

    candidates = [c for run in window for c in run.get("candidates", [])]
    report.buried_total = len({c["arxiv"] for c in candidates if not c.get("posted") and _is_relevant(c)})
    best_by_id: dict[str, dict] = {}
    for c in candidates:
        if c.get("posted") or _jev_relevance(c) is None or not _is_relevant(c):
            continue  # the buried are relevant papers the top-N cap dropped — nothing else
        incumbent = best_by_id.get(c["arxiv"])
        if incumbent is None or _jev_relevance(c) > _jev_relevance(incumbent):
            best_by_id[c["arxiv"]] = c
    report.buried = sorted(best_by_id.values(), key=lambda c: (-_jev_relevance(c), c["arxiv"]))[:BURIED_LIMIT]

    people_by_id: dict[str, dict] = {}
    for c in candidates:
        if not c.get("authors"):
            continue
        existing = people_by_id.setdefault(c["arxiv"], c)
        existing["posted"] = existing.get("posted") or c.get("posted")
    report.people = sorted(people_by_id.values(), key=lambda c: c["arxiv"])

    report.jev_hot, report.lexical_hot = _divergences(window)

    ledger = LabelLedger()
    labels_by_id: dict[str, list[Label]] = {}
    for label in ledger.rows():
        labels_by_id.setdefault(label.arxiv_id, []).append(label)
    posted_candidates = [c for c in candidates if c.get("posted")]
    posted_by_id = {c["arxiv"] for c in posted_candidates}
    kept = sum(
        1 for arxiv in posted_by_id if any(lbl.label_type in POSITIVE_TYPES for lbl in labels_by_id.get(arxiv, []))
    )
    skipped = sum(
        1 for arxiv in posted_by_id if any(lbl.label_type in NEGATIVE_TYPES for lbl in labels_by_id.get(arxiv, []))
    )
    report.receipts_counts = {
        "posted": len(posted_candidates),
        "kept": kept,
        "skipped": skipped,
        "labeled": kept + skipped,
    }

    window_run_ids = {run.get("run_id") for run in window}
    receipts = _latest_receipts([r for r in _load_receipts() if r.get("run_id") in window_run_ids])
    report.calibration = {
        "precision_at_5": _precision_at_5(window, labels_by_id),
        "brier": _brier(receipts, labels_by_id),
    }
    report.notes.append("read-only: the review proposes, never stages — the staged worklist stays human-gated")
    return report


def post_review(cfg: Config, report: Review, slack_client=None) -> str:
    """Post the rendered review to the configured channel — the digest/ingest
    client seam, so the posting path stays testable offline."""
    if not cfg.slack_channel:
        raise SystemExit("slack_channel not configured (docs/slack-setup.md)")
    if slack_client is None:
        from .digest import slack_token
        from .slack import SlackClient

        slack_client = SlackClient(token=slack_token())
    return slack_client.post_message(cfg.slack_channel, report.render_slack())


# ── helpers ─────────────────────────────────────────────────────────────────────

_ARXIV_SUFFIX = re.compile(r"\s*\(arXiv:[^)]*\)\s*$")


def _short_date(ts: str) -> str:
    d = datetime.fromisoformat(ts)
    return f"{d:%b} {d.day}"


def _slack_link(candidate: dict) -> str:
    """A Slack mrkdwn link to the paper, the title cleaned of LaTeX and of the
    '(arXiv:… [cat])' tail some feeds append, escaped for mrkdwn."""
    from .latex import latex_to_unicode

    title = _ARXIV_SUFFIX.sub("", latex_to_unicode(candidate.get("title") or candidate["arxiv"]))
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "/")
    return f"<https://arxiv.org/abs/{candidate['arxiv']}|{title}>"


def _label(candidate: dict) -> str:
    return ((candidate.get("jev") or {}).get("top") or "").replace("-", " ").replace("must read", "must-read")



_LEVELS = ["must-read", "worth-reading", "borderline", "unlikely", "irrelevant"]  # jev.RELEVANCE_LEVELS
_RELEVANT = ("must-read", "worth-reading")


def _jev_relevance(candidate: dict) -> float | None:
    """The Jev row's RELEVANCE as one sortable number — None for absent and
    fail-open rows (a lone fail_reason carries no judgment). The journal keeps
    only (top label, confidence in it), so the label orders first and the
    confidence orders within it: a confident must-read beats an unsure one, and
    any relevant label beats any borderline/unlikely/irrelevant one. Found live
    2026-10-25: ranking by bare confidence put papers Jev was 100% sure were
    *irrelevant* at the top of the week-in-review."""
    jev = candidate.get("jev") or {}
    confidence = jev.get("confidence")
    if confidence is None or jev.get("top") not in _LEVELS:
        return None
    rank = len(_LEVELS) - _LEVELS.index(jev["top"])  # must-read 5 … irrelevant 1
    signed = float(confidence) if jev["top"] in _RELEVANT else 1.0 - float(confidence)
    return rank + signed


def _is_relevant(candidate: dict) -> bool:
    return (candidate.get("jev") or {}).get("top") in _RELEVANT


def _divergence_lines(rows: list[dict]) -> list[str]:
    """One line per divergence, both tails identically shaped; empty tail says so."""
    if not rows:
        return ["- none"]
    return [
        f"- {c['arxiv']} — {c['title']} (jev {c['jev'].get('top')} {c['jev']['confidence']:.2f} rank #{c['jev_rank']} "
        f"· lexical {c['lexical_score']} rank #{c['lexical_rank']})"
        for c in rows
    ]


def _run_ts(run: dict) -> datetime:
    try:
        return datetime.fromisoformat(run["ts"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"journal run {run.get('run_id', '?')} has an unparseable ts: {exc}") from exc


def _divergences(window: list[dict]) -> tuple[list[dict], list[dict]]:
    """The two tails by within-run rank gap: positive = Jev ranked it better than
    the words did; negative = the reverse. Per paper, the window's largest gap
    in each direction; candidates with no Jev row have no divergence to report."""
    jev_gaps: dict[str, dict] = {}
    lexical_gaps: dict[str, dict] = {}
    for run in window:
        scored = [c for c in run.get("candidates", []) if _jev_relevance(c) is not None]
        by_jev = sorted(scored, key=lambda c: (-_jev_relevance(c), c["arxiv"]))
        by_lexical = sorted(scored, key=lambda c: (-c["lexical_score"], c["arxiv"]))
        ranks = {c["arxiv"]: (by_jev.index(c) + 1, by_lexical.index(c) + 1) for c in scored}
        for c in scored:
            jev_rank, lexical_rank = ranks[c["arxiv"]]
            gap = lexical_rank - jev_rank
            if gap > 0 and _beats(c, jev_gaps.get(c["arxiv"]), gap):
                jev_gaps[c["arxiv"]] = {**c, "jev_rank": jev_rank, "lexical_rank": lexical_rank}
            if gap < 0 and _beats(c, lexical_gaps.get(c["arxiv"]), -gap):
                lexical_gaps[c["arxiv"]] = {**c, "jev_rank": jev_rank, "lexical_rank": lexical_rank}
    # ascending by negated gap: the biggest divergence first, arxiv breaking ties
    jev_hot = sorted(jev_gaps.values(), key=lambda c: (c["jev_rank"] - c["lexical_rank"], c["arxiv"]))[
        :DIVERGENCE_LIMIT
    ]
    lexical_hot = sorted(lexical_gaps.values(), key=lambda c: (c["lexical_rank"] - c["jev_rank"], c["arxiv"]))[
        :DIVERGENCE_LIMIT
    ]
    return jev_hot, lexical_hot


def _beats(candidate: dict, incumbent: dict | None, gap: int) -> bool:
    if incumbent is None:
        return True
    incumbent_gap = incumbent["lexical_rank"] - incumbent["jev_rank"]
    return gap > abs(incumbent_gap)

"""`arjev review`: the week-in-review — a pure re-read of the digest journal,
Jev receipts, and label ledger (the same three sources calibrate joins), with
zero fetches and zero Jev calls. The daily digest is capped at top-5 and sees
one day of the firehose; the review looks across the window: the cap's
casualties, your people, the Jev-vs-lexical divergences, the week's receipts.
Read-only — it proposes, never stages; every count states its n (issue #83)."""

from __future__ import annotations

import json
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
            f"## The Buried — the cap's casualties (top {len(self.buried)} of {self.buried_total} never-posted)"
        )
        lines.append(buried_header)
        if self.buried:
            lines.extend(
                f"- {c['arxiv']} — {c['title']} (jev {c['jev']['confidence']}, pool {c['pool']})" for c in self.buried
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


def review(days: int = 7, now: date | None = None) -> Review:
    jp = journal_path()
    if not jp.is_file():
        raise FileNotFoundError("no digest journal — digest first")
    runs = [json.loads(line) for line in jp.read_text().splitlines() if line.strip()]
    cutoff = datetime.combine((now or date.today()) - timedelta(days=days), time.min, tzinfo=UTC)
    window = [run for run in runs if _run_ts(run) >= cutoff]

    report = Review(days=days, window_runs=window)

    candidates = [c for run in window for c in run.get("candidates", [])]
    report.buried_total = sum(1 for c in candidates if not c.get("posted"))
    best_by_id: dict[str, dict] = {}
    for c in candidates:
        if c.get("posted") or _jev_confidence(c) is None:
            continue
        incumbent = best_by_id.get(c["arxiv"])
        if incumbent is None or _jev_confidence(c) > _jev_confidence(incumbent):
            best_by_id[c["arxiv"]] = c
    report.buried = sorted(best_by_id.values(), key=lambda c: (-_jev_confidence(c), c["arxiv"]))[:BURIED_LIMIT]

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
    return slack_client.post_message(cfg.slack_channel, report.render())


# ── helpers ─────────────────────────────────────────────────────────────────────


def _jev_confidence(candidate: dict) -> float | None:
    """The Jev row's confidence — None for absent rows and fail-open rows (a
    lone fail_reason carries no judgment, so there is no mass to rank by)."""
    confidence = (candidate.get("jev") or {}).get("confidence")
    return float(confidence) if confidence is not None else None


def _divergence_lines(rows: list[dict]) -> list[str]:
    """One line per divergence, both tails identically shaped; empty tail says so."""
    if not rows:
        return ["- none"]
    return [
        f"- {c['arxiv']} — {c['title']} (jev {c['jev']['confidence']} rank #{c['jev_rank']} "
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
        scored = [c for c in run.get("candidates", []) if _jev_confidence(c) is not None]
        by_jev = sorted(scored, key=lambda c: (-c["jev"]["confidence"], c["arxiv"]))
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

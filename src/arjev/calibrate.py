"""`arjev calibrate`: join the three sources of record — label ledger (labels), digest
journal (candidates + scores + mode per run), Jev receipts (predicted distributions) —
and nothing else. The staged-gate audit is a fold self-audit, not a calibration join.

Four metrics, every one n-stated, honest about censoring (the label set grades only
papers the tool posted — the report says so). Thresholds are RECOMMENDED only; the
tool never writes config (obligation #14). Unsaved-weak-negatives are reported
separately and never drive a recommendation (obligation #24)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Config
from .fold import FoldResult
from .ledger import Label, LabelLedger
from .profile import staged_audit
from .rerank import journal_path, state_dir

RELIABILITY_BINS = 10
POSITIVE_TYPES = {"keep", "read-later"}
NEGATIVE_TYPES = {"skip"}


@dataclass
class Report:
    metrics: dict = field(default_factory=dict)
    staged_audit: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = ["# arjev calibration report", ""]
        for name, block in self.metrics.items():
            lines.append(f"## {name}")
            if isinstance(block, dict):
                for k, v in block.items():
                    lines.append(f"- {k}: {v}")
            else:
                lines.append(f"- {block}")
            lines.append("")
        if self.staged_audit:
            lines.append("## staged-gate audit — VIOLATIONS")
            lines.extend(f"- {v}" for v in self.staged_audit)
        else:
            lines.append("## staged-gate audit: clean (current fold)")
        lines.append("")
        if self.recommendations:
            lines.append("## recommendations (human applies; this tool never edits config)")
            lines.extend(f"- {r}" for r in self.recommendations)
        lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines) + "\n"


def calibrate(cfg: Config, fold: FoldResult, runs: int = 30) -> Report:
    report = Report()
    journal = _load_journal(runs)
    receipts = _load_receipts()
    ledger = LabelLedger()

    labels_by_id: dict[str, list[Label]] = {}
    for label in ledger.rows():
        labels_by_id.setdefault(label.arxiv_id, []).append(label)

    report.metrics["brier"] = _brier(receipts, labels_by_id)
    report.metrics["reliability"] = _reliability(receipts, labels_by_id)
    report.metrics["precision_at_5"] = _precision_at_5(journal, labels_by_id)
    report.metrics["probe_lift"] = _probe_lift(journal, labels_by_id)

    report.staged_audit = staged_audit(fold, cfg, _today())

    weak_negatives = sum(1 for rows in labels_by_id.values()
                         if any(row.label_type == "unsaved-weak-negative" for row in rows))
    explicit_skips = sum(1 for rows in labels_by_id.values() if any(r.label_type == "skip" for r in rows))
    report.notes.append(
        f"unsaved-weak-negatives: {weak_negatives} (reported separately from {explicit_skips} explicit "
        "skips — already-known is not irrelevant; neither drives a threshold alone)"
    )
    report.notes.append(
        "censoring: labels exist only for papers this tool posted — this report grades "
        "selection, not recall in general; the recall probe is the partial instrument."
    )
    explicit_positives = sum(1 for rows in labels_by_id.values()
                             if any(row.label_type in POSITIVE_TYPES for row in rows))
    if weak_negatives + explicit_skips + explicit_positives < 20:
        report.notes.append("n is small — treat every number above as a first reading, not a verdict.")
        report.recommendations.append("collect more labels before tuning any threshold (n < 20).")
    probe = report.metrics["probe_lift"]
    if probe.get("mode") != "jev-first" and probe.get("probe_rescue_n", 0) == 0:
        report.recommendations.append("no probe rescues yet — the probe is unmeasured, not refuted.")
    return report


# ── the four metrics ─────────────────────────────────────────────────────────────

def _positive(labels: list[Label]) -> int | None:
    """1 for keep ∪ read-later, 0 for skip, None otherwise (discussed is flavor;
    implicit labels never enter the Brier/reliability classes)."""
    types = {lbl.label_type for lbl in labels}
    if types & POSITIVE_TYPES:
        return 1
    if types & NEGATIVE_TYPES:
        return 0
    return None


def _p_positive(receipt: dict) -> float:
    dist = receipt.get("distribution", {})
    if receipt["primitive"] == "score":
        return float(dist.get("must-read", 0.0)) + float(dist.get("worth-reading", 0.0))
    return float(dist.get("true", 0.0))


def _brier(receipts: list[dict], labels_by_id: dict) -> dict:
    per_primitive: dict[str, list[tuple[float, int]]] = {"score": [], "noul": []}
    for r in receipts:
        outcome = _positive(labels_by_id.get(r["candidate_arxiv"], []))
        if outcome is None:
            continue
        per_primitive[r["primitive"]].append((_p_positive(r), outcome))
    return {
        primitive: {
            "brier": round(sum((p - o) ** 2 for p, o in pairs) / len(pairs), 4) if pairs else None,
            "n": len(pairs),
        }
        for primitive, pairs in per_primitive.items()
    }


def _reliability(receipts: list[dict], labels_by_id: dict) -> dict:
    per_primitive: dict[str, list] = {"score": [], "noul": []}
    for r in receipts:
        outcome = _positive(labels_by_id.get(r["candidate_arxiv"], []))
        if outcome is None:
            continue
        per_primitive[r["primitive"]].append((_p_positive(r), outcome))
    out: dict = {}
    for primitive, pairs in per_primitive.items():
        bins = [{"predicted": 0.0, "observed": 0.0, "n": 0} for _ in range(RELIABILITY_BINS)]
        for p, o in pairs:
            idx = min(RELIABILITY_BINS - 1, int(p * RELIABILITY_BINS))
            bins[idx]["predicted"] += p
            bins[idx]["observed"] += o
            bins[idx]["n"] += 1
        out[primitive] = [
            {
                "bin": f"[{i / RELIABILITY_BINS:.1f},{(i + 1) / RELIABILITY_BINS:.1f})",
                "predicted": round(b["predicted"] / b["n"], 3) if b["n"] else None,
                "observed": round(b["observed"] / b["n"], 3) if b["n"] else None,
                "n": b["n"],
            }
            for i, b in enumerate(bins) if b["n"]
        ]
    return out


def _precision_at_5(journal: list[dict], labels_by_id: dict) -> dict:
    posted: list[str] = []
    for line in journal:
        top5 = [c for c in line.get("candidates", []) if c.get("posted")][:5]
        posted.extend(c["arxiv"] for c in top5)
    positive = sum(
        1 for arxiv in posted
        if any(lbl.label_type in POSITIVE_TYPES | {"discussed"} for lbl in labels_by_id.get(arxiv, []))
    )
    return {"precision": round(positive / len(posted), 4) if posted else None, "n": len(posted)}


def _probe_lift(journal: list[dict], labels_by_id: dict) -> dict:
    def keep_rate(ids: list[str]) -> tuple[float | None, int]:
        kept = sum(
            1 for arxiv in ids
            if any(lbl.label_type in POSITIVE_TYPES for lbl in labels_by_id.get(arxiv, []))
        )
        return (round(kept / len(ids), 4) if ids else None), len(ids)

    if any(line.get("ranking") == "jev-first" for line in journal):
        return {
            "mode": "jev-first",
            "note": "n/a — no probe in jev-first: every eligible item is screened, "
            "so there is no zero-score band to lift from",
        }
    rescues, survivors = [], []
    for line in journal:
        for c in line.get("candidates", []):
            if not c.get("posted"):
                continue
            if c.get("rescued") == "probe":
                rescues.append(c["arxiv"])
            elif c.get("pool") == "survivor" and not c.get("rescued"):
                survivors.append(c["arxiv"])
    rescue_rate, rescue_n = keep_rate(rescues)
    survivor_rate, survivor_n = keep_rate(survivors[:5] or survivors)
    return {
        "rescue_keep_rate": rescue_rate,
        "probe_rescue_n": rescue_n,
        "survivor_top5_keep_rate": survivor_rate,
        "survivor_n": survivor_n,
        "lexical_zero_baseline": "zero rescues by construction (the probe pool scores 0)",
    }


# ── loaders ─────────────────────────────────────────────────────────────────────

def _load_journal(runs: int) -> list[dict]:
    jp = journal_path()
    if not jp.is_file():
        return []
    lines = [json.loads(line) for line in jp.read_text().splitlines() if line.strip()]
    return lines[-runs:]


def _load_receipts() -> list[dict]:
    path = state_dir() / "jev-receipts.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _today():
    from datetime import date

    return date.today()

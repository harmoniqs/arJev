"""`arjev rate` — the advisory rating loop (spec: rating-proposal amendment).
Jev proposes (core/useful/marginal) into a SIDE TABLE in the state dir — never
into the vault; machine opinion cannot masquerade as human judgment. The human
accepts (or sets a fresh rating), and only that explicit invocation writes
`rating:` into the note. The never-edit invariant holds; the accept IS the gate.

Human-set ratings then weight the profile (core 1.5×, useful 1.0×, marginal 0.5×
on that note's term bumps) — 'core' papers pull harder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .fold import FoldResult, PaperNote
from .jev import JevClient, JevReceipt
from .rerank import state_dir

RATING_LEVELS = ("core", "useful", "marginal")
RATING_RUBRICS = {
    "core": "central to the lab's current work — matches the taste directives strongly and immediately",
    "useful": "relevant background or method — clear overlap with the lab's interests",
    "marginal": "peripherally relevant — the lab might cite it but would not chase it",
}
RATING_WEIGHT = {"core": 1.5, "useful": 1.0, "marginal": 0.5}


def proposals_path() -> Path:
    return state_dir() / "rating-proposals.json"


@dataclass
class Proposal:
    arxiv: str
    rating: str
    confidence: float
    model_version: str
    ts: str


def load_proposals() -> dict[str, dict]:
    path = proposals_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_proposals(rows: dict[str, dict]) -> None:
    path = proposals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")


def propose_ratings(fold: FoldResult, client: JevClient, profile, run_id: str,
                    receipts: list[JevReceipt]) -> list[Proposal]:
    """Jev first pass over UNRATED notes. Advisory only: results land in the side
    table; the vault is untouched. A note with a human `rating` (or a pending
    proposal) is skipped. Notes without an arxiv id are skipped (no join key)."""
    import time

    from .ledger import now_ts

    existing = load_proposals()
    made: list[Proposal] = []
    for note in fold.papers:
        if not note.arxiv or note.rating or note.arxiv in existing:
            continue
        assembly_state = {
            "researcher_taste": {
                "directives": profile.directives_body[:800] or None,
                "terms": dict(sorted(profile.terms.items(), key=lambda kv: -kv[1])[:15]),
            },
            "candidate": {
                "title": note.title,
                "abstract": note.body[:750],
                "arxiv": note.arxiv,
                "note_tags": note.tags,
                "note_why": note.why or None,
            },
            "instructions_context": "Rate this PAPER NOTE for the researcher's library (not a digest pick).",
        }
        answer = client.choice_rating(assembly_state, note.arxiv, run_id, receipts)
        time.sleep(0.05)
        if not answer.ok or not answer.distribution:
            continue
        top = max(answer.distribution, key=answer.distribution.get)
        if top not in RATING_LEVELS:
            continue
        existing[note.arxiv] = {
            "rating": top, "confidence": answer.confidence,
            "distribution": answer.distribution, "model_version": answer.model_version, "ts": now_ts(),
        }
        made.append(Proposal(note.arxiv, top, answer.confidence, answer.model_version, now_ts()))
    save_proposals(existing)
    return made


def accept_rating(note: PaperNote, rating: str, papers_dir: Path | None) -> Path:
    """The human gate: write `rating:` into the note's frontmatter. This is the ONLY
    arJev path that edits an existing note, and it runs on explicit invocation."""
    if rating not in RATING_LEVELS:
        raise ValueError(f"rating must be one of {RATING_LEVELS}, got {rating!r}")
    if "rating:" in note.file.read_text().split("---")[1]:
        raise ValueError(f"{note.file.name} already carries a human rating")
    path = note.file
    text = path.read_text()
    text = text.replace("\n---\n", f'\nrating: {rating}\n---\n', 1)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
    rows = load_proposals()
    rows.pop(note.arxiv, None)
    save_proposals(rows)
    return path

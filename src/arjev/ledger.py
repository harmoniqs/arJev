"""The label ledger: every surface reduces to the same rows (obligation #1's core).
(arxiv_id, label_type, source, ts) — closed vocabularies, JSONL in the state dir,
append-only with idempotent dedupe."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LABEL_TYPES = {"keep", "read-later", "skip", "discussed", "saved-implicit", "unsaved-weak-negative"}
SOURCES = {"slack-reaction", "slack-reply", "cli-keep", "checkbox", "vault-arrival", "vault-unsaved"}

EXPLICIT_POSITIVE = {"keep", "read-later", "discussed"}


@dataclass
class Label:
    arxiv_id: str
    label_type: str
    source: str
    ts: str

    def __post_init__(self) -> None:
        if self.label_type not in LABEL_TYPES:
            raise ValueError(f"label_type {self.label_type!r} outside the closed vocabulary")
        if self.source not in SOURCES:
            raise ValueError(f"source {self.source!r} outside the closed vocabulary")

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> Label:
        return cls(**json.loads(line))


def ledger_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(base) / "arjev" / "label-ledger.jsonl"


class LabelLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ledger_path()

    def rows(self) -> list[Label]:
        if not self.path.is_file():
            return []
        return [Label.from_json(line) for line in self.path.read_text().splitlines() if line.strip()]

    def has(self, arxiv_id: str, label_type: str) -> bool:
        return any(r.arxiv_id == arxiv_id and r.label_type == label_type for r in self.rows())

    def has_positive(self, arxiv_id: str) -> bool:
        return any(r.arxiv_id == arxiv_id and r.label_type in EXPLICIT_POSITIVE for r in self.rows())

    def append(self, label: Label) -> bool:
        """Append one row; idempotent on (arxiv_id, label_type). Returns True if written."""
        if self.has(label.arxiv_id, label.label_type):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(label.to_json() + "\n")
        return True

    def append_many(self, labels: list[Label]) -> int:
        return sum(self.append(label) for label in labels)


def now_ts() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

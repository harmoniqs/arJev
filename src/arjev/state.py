"""The posted-state: the incumbent's schema, byte-compatible. Read + append only —
{posted: [ids…], updated: ISO}. Legacy ids (no journal line) take their posting
timestamp from the file's `updated` value at load, in memory, for the 30-day rule
only — nothing is stamped or written back (obligation #7)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class PostedState:
    ids: list[str]
    updated: str
    path: Path

    @classmethod
    def load(cls, path: Path) -> PostedState:
        if not path.is_file():
            return cls(ids=[], updated="", path=path)
        data = json.loads(path.read_text())
        return cls(ids=list(data.get("posted", [])), updated=str(data.get("updated", "")), path=path)

    def posting_time(self, arxiv_id: str, journal_ts: str | None) -> str | None:
        """Journal timestamps win; legacy ids inherit the file's `updated` — in memory."""
        return journal_ts or (self.updated if arxiv_id in self.ids else None)

    def append(self, new_ids: list[str], now: str | None = None) -> bool:
        """Preserve every existing id (acceptance: posted_ids_lost == 0), schema-identical.
        Never called for a legacy file until a digest posts — the file keeps its shape."""
        merged = list(dict.fromkeys([*self.ids, *new_ids]))
        if merged == self.ids:
            return False
        payload = {"posted": merged[-2000:], "updated": now or datetime.now(UTC).isoformat(timespec="seconds")}
        tmp = self.path.with_suffix(".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload) + "\n")
        tmp.replace(self.path)
        self.ids = merged[-2000:]
        self.updated = payload["updated"]
        return True

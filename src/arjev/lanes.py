"""Personal lanes (issue #121): the state scope.

A lane is a named ranking context — one recipient, its own roots and feeds (the
`[lanes.<name>]` tables, parsed in config.py). Its journal, posted ids, receipts
and label ledger live under `<state>/lanes/<name>/`, so a lane's picks, labels
and 30-day clock never mix with the shared channel's or another lane's.

The scope is a context variable every state path consults (`rerank.state_dir`,
`ledger.ledger_path`) — the persisted schemas themselves are unchanged; only the
directory they live in moves."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_ACTIVE: ContextVar[str | None] = ContextVar("arjev_lane", default=None)

LANE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")


def validate_lane_name(name: str) -> str:
    """Lane names become a directory under the state dir — no separators, no dots."""
    if not LANE_NAME.fullmatch(name):
        raise ValueError(f"lane name {name!r} must match {LANE_NAME.pattern} (lowercase, digits, - and _)")
    return name


def active_lane() -> str | None:
    return _ACTIVE.get()


@contextmanager
def lane_scope(name: str | None) -> Iterator[None]:
    """Route every state path into the lane's own directory for the duration.
    `None` is the shared scope — a no-op, so callers can wrap unconditionally."""
    if name is not None:
        validate_lane_name(name)
    token = _ACTIVE.set(name)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def scoped(base: Path) -> Path:
    """`<state>/arjev` → `<state>/arjev/lanes/<name>` inside a lane scope."""
    name = _ACTIVE.get()
    return base / "lanes" / name if name else base

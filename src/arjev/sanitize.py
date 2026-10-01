"""Fixture sanitization — no channel/user ids, tokens, or keys may land in committed
fixtures (spec invariant: recorded fixtures are sanitized before commit).

The sanitizer is pure and total: it walks any JSON-able structure, replaces
id-looking values with deterministic synthetic placeholders, and drops anything
that looks like a secret. `ensure_sanitized` is the gate `capture_fixtures.py`
runs before writing — if it raises, nothing lands.
"""

from __future__ import annotations

import re
from typing import Any

# Slack-style ids: C (channel), U/W (user), G (group), D (dm), T (team/workspace);
# bot tokens (xoxb-…), shared secrets, and anything literally named key/token/secret.
_SLACK_ID = re.compile(r"^[CUGDWT]0[0-9A-Z]{6,}$")
_SECRET_FIELD = re.compile(r"key|token|secret|password", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"xox[baprs]-|Bearer\s+|sk-[A-Za-z0-9]{8,}|AIza[0-9A-Za-z_-]{10,}")

SYNTHETIC_IDS = {
    "channel": "C0000000SYN",
    "user": "U0000000SYN",
    "other": "X0000000SYN",
}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        if _SECRET_VALUE.search(value):
            return "<sanitized-secret>"
        if _SLACK_ID.match(value):
            kind = "channel" if value.startswith("C") else "user" if value.startswith("U") else "other"
            return SYNTHETIC_IDS[kind]
        return value
    if isinstance(value, dict):
        return {k: ("<dropped-secret>" if _SECRET_FIELD.search(k) else _sanitize_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value


def sanitize(payload: Any) -> Any:
    """Return a sanitized deep copy of a recorded payload."""
    return _sanitize_value(payload)


def _find_violations(node: Any, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if _SECRET_FIELD.search(k):
                violations.append(f"{path}.{k}: secret-named field")
            violations.extend(_find_violations(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            violations.extend(_find_violations(v, f"{path}[{i}]"))
    elif isinstance(node, str):
        if _SLACK_ID.match(node) and not node.endswith("SYN"):
            violations.append(f"{path}: unsanitized Slack id {node!r}")
        if _SECRET_VALUE.search(node):
            violations.append(f"{path}: secret-looking value {node[:12]!r}…")
    return violations


def ensure_sanitized(payload: Any) -> None:
    """The gate: raise if anything id- or secret-shaped is present in THIS payload.
    Callers run it on the sanitized output before writing: clean = sanitize(raw);
    ensure_sanitized(clean); write(clean)."""
    violations = _find_violations(payload)
    if violations:
        raise ValueError(f"fixture not clean: {'; '.join(violations)}")

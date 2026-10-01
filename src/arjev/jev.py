"""The Jev middle layer: TypeSafe System One — typed Score/Noul with calibrated
confidence, on the pools the front line classified. Doctrine (spec-20260920-jev-
integration): advisory-only, fail-open, never load-bearing. No key, outage, or low
confidence → the lexical ranking, unchanged, and the journal says why.

Wire contract (the contract of record, live-verified 2026-09-20 against the vendor
API — amicode #1311's jev_client.ts; arJev's first live run failed open on a guessed
shape, issue #23): POST /v1/systemone, {"model": "jev-latest", "state": <object>,
"questions": {"<id>": Question}}; Question = {"type": "choice"|"noul", "instructions":
<str>, "criteria": <choice: option→rubric MAP | noul: {"true": …, "false": …}>};
response = {"model": "jev-1.13.0", "answers": {"<id>": Answer}, "usage": {…}};
choice answer = {"choice": <option>, "confidence": <float>, "probabilities": {…}};
noul answer = {"noul": <float>} (p(true)).

Receipts (canonical schema, normative): candidate arxiv id, run_id, ts, primitive,
state_bytes, distribution, confidence, latency_ms, model_version — JSONL in the XDG
state dir, never inside the repo (obligations #2, #11)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .profile import Profile

RELEVANCE_LEVELS = ["must-read", "worth-reading", "borderline", "unlikely", "irrelevant"]
DEFAULT_MIN_CONFIDENCE = 0.6
DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

Transport = Callable[[str, str, dict], dict]  # (url, key, payload) -> response json


@dataclass
class JevReceipt:
    candidate_arxiv: str
    run_id: str
    ts: str
    primitive: str  # "score" | "noul"
    state_bytes: int
    distribution: dict
    confidence: float  # top probability
    latency_ms: int
    model_version: str


@dataclass
class JevAnswer:
    candidate_arxiv: str
    primitive: str
    distribution: dict
    confidence: float
    state_bytes: int
    model_version: str
    ok: bool = True
    fail_reason: str | None = None  # "no-key" | "outage" | "low-confidence" | "state-overflow" | "error"


class JevClient:
    def __init__(self, key: str | None, min_confidence: float = DEFAULT_MIN_CONFIDENCE, url: str = DEFAULT_URL,
                 transport: Transport | None = None, timeout: float = 30.0, model: str = DEFAULT_MODEL) -> None:
        self.key = key or os.environ.get("ARJEV_JEV_KEY") or _key_file()
        self.min_confidence = min_confidence
        self.url = url
        self.model = model
        self.timeout = timeout
        self._transport = transport or self._http_transport

    @property
    def enabled(self) -> bool:
        return bool(self.key) and not _disabled()

    def _http_transport(self, url: str, key: str, payload: dict) -> dict:
        with httpx.Client(timeout=self.timeout, headers={"authorization": f"Bearer {key}"}) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
            return r.json()

    def _ask(self, state: dict, question: dict) -> dict:
        # the contract of record: questions is a MAP keyed by id, and the model rides the body
        return self._transport(self.url, self.key,
                               {"model": self.model, "state": state, "questions": {question["id"]: question}})

    def score_relevance(self, state: dict, candidate_arxiv: str, run_id: str,
                        receipts: list[JevReceipt]) -> JevAnswer:
        question = {
            "id": "relevance",
            "type": "choice",
            "instructions": "How relevant is this paper to the researcher's taste digest?",
            "criteria": {level: rubric for level, rubric in zip(
                RELEVANCE_LEVELS,
                [
                    "matches the taste digest strongly and immediately",
                    "clear overlap with the taste digest",
                    "partial overlap with the taste digest",
                    "tangential to the taste digest",
                    "no meaningful overlap with the taste digest",
                ],
                strict=True,
            )},
        }
        return self._call("score", state, candidate_arxiv, run_id, receipts, question)

    def choice_rating(self, state: dict, candidate_arxiv: str, run_id: str,
                      receipts: list[JevReceipt]) -> JevAnswer:
        """The library-rating question (arjev rate): one of core/useful/marginal for
        a PAPER NOTE — a different judgment from digest relevance."""
        from .rate import RATING_LEVELS, RATING_RUBRICS

        question = {
            "id": "library_rating",
            "type": "choice",
            "instructions": "Rate this paper note for the researcher's library.",
            "criteria": {level: RATING_RUBRICS[level] for level in RATING_LEVELS},
        }
        return self._call("score", state, candidate_arxiv, run_id, receipts, question)

    def noul_relevant(self, state: dict, candidate_arxiv: str, run_id: str,
                      receipts: list[JevReceipt]) -> JevAnswer:
        question = {
            "id": "relevant",
            "type": "noul",
            "instructions": "Is this paper relevant to the researcher's taste digest?",
            "criteria": {
                "true": "there is meaningful overlap with the taste digest",
                "false": "no meaningful overlap with the taste digest",
            },
        }
        return self._call("noul", state, candidate_arxiv, run_id, receipts, question)

    def _call(self, primitive: str, state: dict, candidate_arxiv: str, run_id: str,
              receipts: list[JevReceipt], question: dict) -> JevAnswer:
        payload_bytes = len(json.dumps({"state": state}, sort_keys=True).encode())
        if not self.enabled:
            return JevAnswer(candidate_arxiv, primitive, {}, 0.0, payload_bytes, "none",
                             ok=False, fail_reason="no-key")
        started = time.monotonic()
        try:
            response = self._ask(state, question)
        except Exception as exc:  # outage, HTTP, parse — every path fails open
            receipts.append(JevReceipt(
                candidate_arxiv=candidate_arxiv, run_id=run_id, ts=_now(), primitive=primitive,
                state_bytes=payload_bytes, distribution={"error": str(type(exc).__name__)},
                confidence=0.0, latency_ms=int((time.monotonic() - started) * 1000), model_version="none",
            ))
            return JevAnswer(candidate_arxiv, primitive, {}, 0.0, payload_bytes, "none",
                             ok=False, fail_reason="outage")
        latency_ms = int((time.monotonic() - started) * 1000)
        distribution = _answer_distribution(response, question["id"])
        confidence = max(distribution.values()) if distribution else 0.0
        model_version = str(response.get("model", "unknown"))
        receipts.append(JevReceipt(
            candidate_arxiv=candidate_arxiv, run_id=run_id, ts=_now(), primitive=primitive,
            state_bytes=payload_bytes, distribution=distribution, confidence=confidence,
            latency_ms=latency_ms, model_version=model_version,
        ))
        if confidence < self.min_confidence:
            return JevAnswer(candidate_arxiv, primitive, distribution, confidence, payload_bytes,
                             model_version, ok=False, fail_reason="low-confidence")
        return JevAnswer(candidate_arxiv, primitive, distribution, confidence, payload_bytes, model_version)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _answer_distribution(response: dict, question_id: str) -> dict:
    """Answers is a map keyed by id. A choice answer carries `probabilities`
    (+ its top choice + confidence); a noul answer carries a p(true) float."""
    answer = (response.get("answers") or {}).get(question_id)
    if not isinstance(answer, dict):
        return {}
    if answer.get("type") == "noul":
        p = float(answer.get("noul", 0.0))
        return {"true": p, "false": 1.0 - p}
    dist = answer.get("probabilities")
    if isinstance(dist, dict):
        return {str(k): float(v) for k, v in dist.items()}
    return {}


def _key_file() -> str | None:
    """ARJEV_JEV_KEY_FILE: an EXPLICIT opt-in key-file path, read at call time —
    our ops points it at the server-side key (the amicode posture); a public
    install without the env set never reads any file for a key."""
    override = os.environ.get("ARJEV_JEV_KEY_FILE")
    if not override:
        return None
    try:
        key = Path(override).expanduser().read_text().strip()
        return key or None
    except OSError:
        return None


def _disabled() -> bool:
    """ARJEV_JEV_DISABLED truthy disables the whole Jev path, zero behavioral delta
    (the ops env-flag convention)."""
    value = os.environ.get("ARJEV_JEV_DISABLED", "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


# ── state assembly (the 4096 budget; spec: Jev state assembly) ────────────────────

TASTE_BUDGET = 2500
ABSTRACT_BUDGET = 750
HARD_CAP = 4096
WHY_CAP = 200
TOP_TERMS = 15
TOP_TITLES = 3


@dataclass
class StateAssembly:
    state: dict | None  # None = skip the item (state-overflow), fail open
    state_bytes: int
    dropped_terms: int = 0
    dropped_why: int = 0


def assemble_state(profile: Profile, candidate, now=None) -> StateAssembly:
    """Budgeted, deterministic: top ~15 weighted terms, then why-lines (recency-first,
    capped 200 chars), then 3 recent titles, into a 2.5 KB soft budget; the candidate's
    title + 0.75 KB abstract follow. Overflow: drop lowest-weight terms first, then
    why-lines; still over 4096 → the item is skipped (fail-open, journaled)."""
    terms = sorted(profile.terms.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TERMS]
    whys = [(d, w[:WHY_CAP]) for d, w in profile.why_lines]
    titles = profile.recent_titles[:TOP_TITLES]

    def build(term_count: int, why_count: int, body_cap: int = 800) -> dict:
        return {
            "researcher_taste": {
                "directives": (profile.directives_body[:body_cap] if profile.directives_body else None),
                "terms": {t: round(w, 2) for t, w in terms[:term_count]},
                "why_lines": [w for _, w in whys[:why_count]],
                "recent_titles": titles,
            },
            "candidate": {
                "title": candidate.item.title,
                "abstract": candidate.item.abstract[:ABSTRACT_BUDGET],
                "arxiv": candidate.item.arxiv,
            },
        }

    state = build(len(terms), len(whys))
    size = _size(state)
    dropped_terms = 0
    while size > TASTE_BUDGET + ABSTRACT_BUDGET + 128 and len(terms) - dropped_terms > 3:
        dropped_terms += 5
        state = build(len(terms) - dropped_terms, len(whys))
        size = _size(state)
    dropped_why = 0
    while size > HARD_CAP and len(whys) - dropped_why > 0:
        dropped_why += 1
        state = build(len(terms) - dropped_terms, len(whys) - dropped_why)
        size = _size(state)
    if size > HARD_CAP:
        return StateAssembly(None, size, dropped_terms, dropped_why)
    return StateAssembly(state, size, dropped_terms, dropped_why)


def _size(state: dict) -> int:
    return len(json.dumps(state, sort_keys=True).encode())


def write_receipts(state_dir: Path, receipts: list[JevReceipt]) -> Path:
    """JSONL append; the canonical schema is enforced — a receipt missing a field or a
    candidate id raises (acceptance: calls_without_receipt and receipts_without_
    candidate_id are both 0 by construction)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "jev-receipts.jsonl"
    required = ("candidate_arxiv", "run_id", "ts", "primitive", "state_bytes",
                "distribution", "confidence", "latency_ms", "model_version")
    with path.open("a") as f:
        for r in receipts:
            row = {k: getattr(r, k) for k in required}
            missing = [k for k in required if row[k] is None or (isinstance(row[k], (dict, str)) and not row[k])]
            if missing:
                raise ValueError(f"receipt missing required fields: {missing}")
            if not r.candidate_arxiv:
                raise ValueError("receipt without candidate arxiv id — would break the calibration join")
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return path

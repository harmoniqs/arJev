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


# ── state assembly (budgeted, deterministic; spec: Jev state assembly) ────────────

# the incumbent fixed-15 policy's canonical values (the spec's "4096 budget");
# StatePolicy defaults reference them, so the knob surface and the spec stay in lockstep
TASTE_BUDGET = 2500
ABSTRACT_BUDGET = 750
HARD_CAP = 4096
WHY_CAP = 200
TOP_TERMS = 15
TOP_TITLES = 3
DIRECTIVES_CAP = 800


@dataclass
class StatePolicy:
    """The assembly knobs. The defaults ARE the incumbent fixed-15 policy —
    budget-greedy and candidate conclusions are opt-in arms until calibrate replays
    say otherwise (the vendor documents context rot: accuracy falls as irrelevant
    state grows, so bigger states must measurably beat the incumbent, not ship)."""

    policy: str = "fixed-15"  # "fixed-15" | "budget-greedy"
    taste_budget: int = TASTE_BUDGET
    abstract_budget: int = ABSTRACT_BUDGET
    hard_cap: int = HARD_CAP
    why_cap: int = WHY_CAP
    top_terms: int = TOP_TERMS
    top_titles: int = TOP_TITLES
    directives_cap: int = DIRECTIVES_CAP  # fixed-15 truncation of authored taste (greedy: whole)
    candidate_conclusions: bool = False
    candidate_conclusions_chars: int = 600
    enrich_k: int = 10  # finalists re-scored with candidate conclusions (jev-first)


def policy_from_config(cfg) -> StatePolicy:
    from .config import Config

    if not isinstance(cfg, Config):
        raise TypeError("policy_from_config takes a Config")
    return StatePolicy(
        policy=cfg.state_policy,
        taste_budget=cfg.taste_budget_bytes,
        candidate_conclusions=cfg.candidate_content,
    )


@dataclass
class StateAssembly:
    state: dict | None  # None = skip the item (state-overflow), fail open
    state_bytes: int
    dropped_terms: int = 0
    dropped_why: int = 0


def assemble_state(profile: Profile, candidate, policy: StatePolicy | None = None,
                   conclusions: str | None = None) -> StateAssembly:
    """Budgeted, deterministic. Fixed-15 (the incumbent): top ~15 weighted terms,
    why-lines recency-first (capped), 3 recent titles, into the taste budget.
    Budget-greedy (the context engine): directives whole, then terms and per-paper
    taste cards compete on normalized priority (weight / category max — the decay
    already rides the weights), filling the budget greedily; a small corpus fits
    everything, a growing one gives recent work proportionally more of the window.
    Candidate conclusions ride only when the arm is on. Overflow beyond the hard cap
    still drops lowest-weight content first, then skips the item (fail-open,
    journaled) — never silent truncation."""
    policy = policy or StatePolicy()
    candidate_block = {
        "title": candidate.item.title,
        "authors": candidate.item.authors,  # authorship rides the state (issue #66)
        "abstract": candidate.item.abstract[: policy.abstract_budget],
        "arxiv": candidate.item.arxiv,
    }
    if policy.candidate_conclusions and conclusions:
        candidate_block["conclusions"] = conclusions[: policy.candidate_conclusions_chars]
    if policy.policy == "budget-greedy":
        return _assemble_greedy(profile, candidate_block, policy)
    return _assemble_fixed(profile, candidate_block, policy)


def _assemble_fixed(profile: Profile, candidate_block: dict, policy: StatePolicy) -> StateAssembly:
    terms = sorted(profile.terms.items(), key=lambda kv: (-kv[1], kv[0]))[: policy.top_terms]
    whys = [(d, w[: policy.why_cap]) for d, w in profile.why_lines]

    def build(term_count: int, why_count: int) -> dict:
        return {
            "researcher_taste": {
                "directives": (profile.directives_body[: policy.directives_cap]
                               if profile.directives_body else None),
                "terms": {t: round(w, 2) for t, w in terms[:term_count]},
                "why_lines": [w for _, w in whys[:why_count]],
                "recent_titles": profile.recent_titles[: policy.top_titles],
            },
            "candidate": candidate_block,
        }

    state = build(len(terms), len(whys))
    size = _size(state)
    dropped_terms = 0
    while size > policy.taste_budget + policy.abstract_budget + 128 and len(terms) - dropped_terms > 3:
        dropped_terms += 5
        state = build(len(terms) - dropped_terms, len(whys))
        size = _size(state)
    dropped_why = 0
    while size > policy.hard_cap and len(whys) - dropped_why > 0:
        dropped_why += 1
        state = build(len(terms) - dropped_terms, len(whys) - dropped_why)
        size = _size(state)
    if size > policy.hard_cap:
        return StateAssembly(None, size, dropped_terms, dropped_why)
    return StateAssembly(state, size, dropped_terms, dropped_why)


def _assemble_greedy(profile: Profile, candidate_block: dict, policy: StatePolicy) -> StateAssembly:
    # directives ride WHOLE (the authored taste outranks every derived signal, and
    # the fixed-15 800-char truncation was throwing most of it away)
    items: list[tuple[float, str, str, dict]] = []
    max_term = max(profile.terms.values(), default=0.0) or 1.0
    for term, weight in profile.terms.items():
        items.append((weight / max_term, f"t:{term}", "term", {term: round(weight, 2)}))
    max_card = max((card.weight for card in profile.cards), default=0.0) or 1.0
    for card in profile.cards:
        payload = {"title": card.title}
        if card.read:
            payload["read"] = card.read.isoformat()
        if card.why:
            payload["why"] = card.why[: policy.why_cap]
        if card.abstract:
            payload["abstract"] = card.abstract
        if card.conclusions:
            payload["conclusions"] = card.conclusions
        items.append((card.weight / max_card, f"c:{card.title}", "card", payload))
    # strict (priority, name) order — the fill is deterministic; a skipped big item
    # never blocks a fitting smaller one (true greedy, not first-fit)
    items.sort(key=lambda it: (-it[0], it[1]))
    terms: dict[str, float] = {}
    cards: list[dict] = []
    used = 0
    for _, _, kind, payload in items:
        size = len(json.dumps(payload, sort_keys=True).encode())
        if used + size > policy.taste_budget:
            continue
        used += size
        if kind == "term":
            terms.update(payload)
        else:
            cards.append(payload)
    state = {
        "researcher_taste": {
            "directives": profile.directives_body or None,
            "terms": terms or None,
            "cards": cards or None,
            "recent_titles": profile.recent_titles[: policy.top_titles],
        },
        "candidate": candidate_block,
    }
    size = _size(state)
    # hard-cap backstop: drop lowest-priority content (last-in) until it fits
    while size > policy.hard_cap and (cards or terms):
        if cards:
            cards.pop()
        elif terms:
            terms.popitem()
        state["researcher_taste"]["cards"] = cards or None
        state["researcher_taste"]["terms"] = terms or None
        size = _size(state)
    if size > policy.hard_cap:
        return StateAssembly(None, size)
    return StateAssembly(state, size)


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

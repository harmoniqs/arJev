"""Digest orchestration: fold → profile → feed → score → rank → Jev middle layer →
post (stdout | any of vault, slack — one ranking, many sinks) + journal. Deterministic on identical inputs (acceptance:
fingerprint mismatches == 0). Fail-open: no key / outage / low confidence → the lexical
ranking, with the mode flag and per-candidate journal saying exactly what ran."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from .config import Config
from .feed import arxiv_namespace, load_feed
from .fold import fold_roots
from .jev import JevClient, JevReceipt, policy_from_config
from .paper_content import corpus_content, paced_conclusions, sections_cache_dir
from .profile import build_profile, profile_flag
from .rank import rank
from .render import canonical_picks, mode_line, render_mrkdwn, render_vault_note, write_vault_note
from .rerank import (
    Pick,
    RunRecord,
    apply_jev,
    apply_jev_first,
    run_id_for,
    state_dir,
    write_journal,
    write_run_receipts,
)
from .state import PostedState


@dataclass
class DigestResult:
    markdown: str
    fingerprint: str
    mode: str
    picks: list[Pick] = field(default_factory=list)
    run_id: str = ""
    journal_rows: int = 0


ENRICH_CAP = 4096

SINKS = ("stdout", "vault", "slack")
# durable sinks run in this fixed order whatever order the caller lists them:
# the vault note is the durable record, so it lands before the Slack post can fail
DURABLE_ORDER = ("vault", "slack")


def parse_post(value) -> tuple[str, ...]:
    """`--post` value → the run's sinks: a single sink or a comma list of durable
    ones (issue #106). Unknown or empty tokens are rejected; stdout is the
    no-durable-sink preview, so combining it with vault/slack is a contradiction
    (and redundant — the CLI always prints the digest) and is rejected too."""
    tokens = [t.strip() for t in value.split(",")] if isinstance(value, str) else [str(t).strip() for t in value]
    if not tokens or any(not t for t in tokens):
        raise ValueError(f"--post {value!r}: empty sink token (choose from {', '.join(SINKS)})")
    unknown = [t for t in tokens if t not in SINKS]
    if unknown:
        raise ValueError(f"--post: unknown sink {', '.join(map(repr, unknown))} (choose from {', '.join(SINKS)})")
    chosen = set(tokens)
    if "stdout" in chosen:
        if len(chosen) > 1:
            raise ValueError("--post: stdout is the preview sink and cannot combine with vault/slack "
                             "(the digest always prints; list only the durable sinks)")
        return ("stdout",)
    return tuple(s for s in DURABLE_ORDER if s in chosen)


class PostFailure(RuntimeError):
    """A multi-sink run where at least one sink failed. The run itself happened:
    the sinks that landed consumed the posted ids and the journal is written
    (when anything landed); `result` carries the digest, `failed` maps each
    failed sink to its error. A single-sink failure raises the sink's own error."""

    def __init__(self, failed: dict[str, BaseException], result: DigestResult):
        self.failed = failed
        self.result = result
        detail = "; ".join(f"{sink}: {exc}" for sink, exc in failed.items())
        super().__init__(f"digest post failed for {', '.join(failed)} — {detail}")


def _enrich(markdown: str, picks: list[Pick], mode: str, command: str) -> str:
    """The enrichment seam (docs/amicode-integration.md): the command receives the
    canonical picks JSON on stdin and its stdout (capped) is appended to the digest.
    The deterministic core stays text-free; prose is separable and fail-open — a
    broken or missing command NEVER breaks the digest."""
    import subprocess

    payload = json.dumps(
        {"mode": mode, "picks": canonical_picks(picks), "titles": {p.identity.id: p.title for p in picks}},
        sort_keys=True,
    )
    try:
        out = subprocess.run(command, shell=True, input=payload, capture_output=True, text=True, timeout=120)
        if out.returncode == 0 and out.stdout.strip():
            return markdown + "\n\n" + out.stdout.strip()[:ENRICH_CAP]
    except (subprocess.SubprocessError, OSError):
        pass
    return markdown


def fingerprint_picks(picks: list[Pick]) -> str:
    return hashlib.sha256(json.dumps(canonical_picks(picks), sort_keys=True).encode()).hexdigest()[:16]


def slack_token() -> str:
    """ARJEV_SLACK_TOKEN, else the contents of ARJEV_SLACK_TOKEN_FILE — the same
    file form the Jev key takes, so the token can stay in a mode-600 file."""
    token = os.environ.get("ARJEV_SLACK_TOKEN")
    if not token and (path := os.environ.get("ARJEV_SLACK_TOKEN_FILE")):
        try:
            token = Path(path).expanduser().read_text().strip()
        except OSError:
            token = None
    if not token:
        raise SystemExit("no Slack token: set ARJEV_SLACK_TOKEN_FILE to a mode-600 token file, "
                         "or ARJEV_SLACK_TOKEN (docs/slack-setup.md)")
    return token


def run_digest(
    cfg: Config,
    feed: str | None = None,
    feed_file: str | None = None,
    post: str | tuple[str, ...] = "stdout",
    today: date | None = None,
    seed: str | None = None,
    jev_client: JevClient | None = None,
    slack_client=None,
    enrich: bool = False,
    pdf_fetcher=None,
) -> DigestResult:
    today = today or date.today()
    sinks = parse_post(post)
    # a missing feed list is a config error, never a silent default-category digest
    # (fail-open is for Jev seams only — issue #53)
    if not (feed or feed_file or cfg.feeds):
        raise SystemExit(
            'feeds not configured — set feeds = ["<arXiv category>", …] in arjev.toml; '
            "arJev ranks only what you configure and never defaults to a category"
        )
    # slack config is checked BEFORE ranking: a config error must not burn a
    # full Jev pass, and must never leave a half-posted multi-sink run
    sc = None
    if "slack" in sinks:
        if not cfg.slack_channel:
            raise SystemExit("slack_channel not configured (docs/slack-setup.md)")
        from .slack import SlackClient

        sc = slack_client or SlackClient(token=slack_token())
    # the seed fallback names the config slot, never a category — the configured
    # feeds live in the journal's feed field, not in the seed (issue #53)
    seed = seed or f"{feed or feed_file or 'feeds'}:{today.isoformat()}"
    fold = fold_roots(cfg.expanded_roots, cfg)
    policy = policy_from_config(cfg)
    # corpus-side content resolves LOCAL sources only — the fold stays deterministic;
    # cards ride without content when the library holds nothing. The candidate-content
    # arm is the one network surface a digest can touch (fail-open, cached, paced).
    content = corpus_content(cfg) if policy.policy == "budget-greedy" else None
    profile = build_profile(fold, cfg, today, content=content)
    if feed or feed_file:
        items = load_feed(feed, feed_file)
        run_warnings = []
    else:
        from .feed import load_feeds_with_health

        items, dead_feeds = load_feeds_with_health(cfg.feeds)
        if dead_feeds and items:
            run_warnings = [f"feed returned 0 items (possible outage): {', '.join(dead_feeds)}"]
        elif dead_feeds:
            raise SystemExit(
                "feed failure — every configured feed returned 0 items; this is an outage "
                "or an endpoint change, NOT a quiet day. Check the arXiv RSS status; no digest."
            )
        else:
            run_warnings = []
    ranked = rank(
        items,
        profile,
        corpus_ids=fold.arxiv_ids(),
        posted_ids=set(PostedState.load(state_dir() / "papers-digest-state.json").ids),
        top=cfg.top,
        screen=cfg.screen,
        probe_k=cfg.probe_k,
        seed=seed,
    )
    client = jev_client or JevClient(key=None, min_confidence=cfg.jev_min_confidence)
    run_id = run_id_for(seed, today)
    receipts: list[JevReceipt] = []
    # the content arm's enrich callable: one paced, fail-open seam (paper_content's
    # paced_conclusions — cache hits free, sleeps only after real fetch attempts)
    content_enrich = None
    if cfg.candidate_content:
        def content_enrich(ids):
            return paced_conclusions(ids, sections_cache_dir(), pace_s=cfg.candidate_pace_s)

    # the ranking amendment: jev-first is the default when the layer can run at all
    # (no key → lexical-first automatically, the mode flag reports what ran)
    use_jev_first = cfg.ranking == "jev-first" and client.enabled
    if use_jev_first:
        from .score import score_item

        # the skip set is the vault's arxiv namespace (fold corpus + posted-state,
        # both frozen bare-id schemas), lifted into identity pairs — the join namespace
        skip = arxiv_namespace(fold.arxiv_ids()
                               | set(PostedState.load(state_dir() / "papers-digest-state.json").ids))
        scored_by_id = {}
        for item in items:
            if item.identity not in skip:
                scored_by_id[item.identity] = score_item(item, profile)
        picks, mode_primary, candidates = apply_jev_first(
            items, scored_by_id, skip, client, profile, run_id, receipts,
            top=cfg.top, pace_s=cfg.jev_pace_s, policy=policy, enrich=content_enrich,
        )
    else:
        picks, mode_primary, candidates = apply_jev(ranked, client, profile, run_id, receipts,
                                                    top=cfg.top, policy=policy, enrich=content_enrich)
    if receipts:
        write_run_receipts(receipts)
    mode = mode_line(mode_primary, profile_flag(profile))
    if content_enrich is not None and mode_primary == "jev":
        # jev-first enriches the top finalists; lexical-first enriches the pools
        mode = f"{mode} · content: {'finalists' if use_jev_first else 'candidates'}"
    if run_warnings:
        mode = f"{mode} · fetch-warning: {'; '.join(run_warnings)}"
    feed_name = feed or (Path(feed_file).stem if feed_file else "+".join(cfg.feeds))

    record = RunRecord(
        run_id=run_id,
        ts=datetime.now(UTC).isoformat(timespec="seconds"),
        feed=feed_name,
        mode=mode,
        seed=seed,
        candidates=candidates,
        ranking="jev-first" if use_jev_first else "lexical-first",
    )

    # the who-line data (issue #87): authors always, affiliations only in
    # full mode, never fetched under "authors", never rendered under "none"
    who_by_id = {}
    if cfg.who_style != "none":
        from .affil import build_who
        from .directives import load_directives

        roster = load_directives(cfg).authors
        items_by_id = {i.identity.id: i for i in items}
        who_by_id = {
            p.identity.id: build_who(items_by_id[p.identity.id].authors, roster,
                                      p.identity.id, Path(cfg.library_dir).expanduser()
                                      if cfg.library_dir else None,
                                      full=cfg.who_style == "full", fetcher=pdf_fetcher)
            for p in picks if p.identity.id in items_by_id
        }

    def post_vault():
        digest_dir = Path(cfg.digest_dir).expanduser() if cfg.digest_dir else cfg.expanded_roots[0] / "digests"
        note = render_vault_note(picks, feed_name, total=len(items), today=today, mode=mode,
                                  skipped_corpus=len(ranked.skipped_corpus), who_by_id=who_by_id)
        write_vault_note(note, digest_dir, today)

    def post_slack():
        from .slack import render_pick_message

        record.slack_channel = cfg.slack_channel
        roster_hits = sum(1 for p in picks if who_by_id.get(p.identity.id) and who_by_id[p.identity.id].hits)
        roster_note = f" · {roster_hits} roster hits" if roster_hits else ""
        # the digest header: one message that reads AS the digest (the channel
        # showed five bare picks could be mistaken for bot noise)
        sc.post_message(
            cfg.slack_channel,
            f"*arJev daily digest — {today.isoformat()}* — {len(picks)} picks · {mode} · "
            f"{len(items)} new items ranked against your vault{roster_note}",
        )
        for i, p in enumerate(picks):
            msg = render_pick_message(p, i + 1, len(picks), today, mode, cfg.why_style,
                                      who=who_by_id.get(p.identity.id))
            ts = sc.post_message(cfg.slack_channel, msg.text)
            for c in record.candidates:
                # the journal row carries the identity's id half only (frozen schema)
                if c.arxiv == p.identity.id:
                    c.slack_ts = ts
                    break

    # one ranking, many sinks (issue #106): each durable sink is isolated — a
    # Slack failure never costs the vault note, a vault failure never blocks Slack.
    # A single sink keeps its historical contract: its own error propagates.
    failed: dict[str, BaseException] = {}
    durable = [sink for sink in sinks if sink != "stdout"]
    for sink in durable:
        try:
            (post_vault if sink == "vault" else post_slack)()
        except Exception as exc:
            if len(durable) == 1:
                raise
            failed[sink] = exc

    # posted ids are consumed only by DURABLE posts — a stdout preview must not
    # mark picks as seen (the live integration run caught the opposite: a preview
    # burned the day's picks and the real post would have shipped empty). ONE
    # append per run however many sinks landed; nothing landed → nothing consumed.
    landed = [sink for sink in durable if sink not in failed]
    if landed:
        state_file = state_dir() / "papers-digest-state.json"
        # posted ids persist the identity's id half (frozen state schema)
        PostedState.load(state_file).append([p.identity.id for p in picks])
    if landed or not durable:
        write_journal(record)

    markdown = render_mrkdwn(picks, feed_name, total=len(items), today=today, mode=mode,
                              skipped_corpus=len(ranked.skipped_corpus))
    if enrich and cfg.enrich_command:
        markdown = _enrich(markdown, picks, mode, cfg.enrich_command)
    result = DigestResult(
        markdown=markdown,
        fingerprint=fingerprint_picks(picks),
        mode=mode,
        picks=picks,
        run_id=run_id,
        journal_rows=len(candidates),
    )
    if failed:
        raise PostFailure(failed, result) from next(iter(failed.values()))
    return result

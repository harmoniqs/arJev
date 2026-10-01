"""arjev CLI: init + digest (the verb surface grows per slice)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arjev", description="arXiv digest ranked against your Obsidian vault")
    parser.add_argument("--version", action="version", version=f"arjev {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="scaffold ~/.config/arjev/arjev.toml")
    p_init.add_argument("--vault", required=True, help="vault root path (scanned recursively)")
    p_init.add_argument("--config", default=None, help="config path (default: ~/.config/arjev/arjev.toml)")
    p_init.add_argument("--smoke-feed-file", default=None, help="RSS fixture; init then digests through it")
    p_init.add_argument("--smoke-post", default="stdout", choices=["stdout", "vault"])

    p_digest = sub.add_parser("digest", help="run the daily digest")
    p_digest.add_argument("--feed", default=None, help="arXiv RSS feed name (default: config feeds[0])")
    p_digest.add_argument("--feed-file", default=None, help="RSS fixture path (overrides --feed)")
    p_digest.add_argument("--post", default="stdout", choices=["stdout", "vault", "slack"], help="output sink")
    p_digest.add_argument("--config", default=None, help="config path")
    p_digest.add_argument("--top", type=int, default=None)
    p_digest.add_argument("--screen", type=int, default=None)
    p_digest.add_argument("--probe-k", type=int, default=None)

    p_keep = sub.add_parser("keep", help="record a keep: label row + staged vault stub")
    p_keep.add_argument("arxiv", help="arXiv id (normalization handles vN suffixes)")
    p_keep.add_argument("--config", default=None)

    p_fetch = sub.add_parser("fetch", help="download the arXiv PDF into the library dir")
    p_fetch.add_argument("arxiv")
    p_fetch.add_argument("--config", default=None)

    p_labels = sub.add_parser("labels", help="label ledger operations")
    p_labels_sub = p_labels.add_subparsers(dest="labels_cmd", required=True)
    p_labels_sync = p_labels_sub.add_parser("sync", help="vault-arrival join + checkbox harvest")
    p_labels_sync.add_argument("--config", default=None)

    p_slack = sub.add_parser("slack", help="Slack surface operations")
    p_slack_sub = p_slack.add_subparsers(dest="slack_cmd", required=True)
    p_slack_sync = p_slack_sub.add_parser("sync", help="harvest reactions/replies → labels; auto-scaffold keeps")
    p_slack_sync.add_argument("--config", default=None)

    p_ingest = sub.add_parser("ingest", help="seed the taste profile: BibTeX, a PDF folder, or a Slack channel")
    p_ingest.add_argument("--bibtex", default=None, help="path to a .bib export (Google Scholar / Zotero)")
    p_ingest.add_argument("--pdf-dir", default=None, help="folder of papers (ids from filenames/stamps)")
    p_ingest.add_argument("--slack-channel", default=None, help="channel name — harvest human-shared arXiv links")
    p_ingest.add_argument("--slack-channel-id", default=None, help="channel id (when the name is not in the config)")
    p_ingest.add_argument("--limit", type=int, default=200, help="Slack history window")
    p_ingest.add_argument("--papers-dir", default=None, help="where seeded notes land (default: config papers dir)")
    p_ingest.add_argument("--config", default=None)

    p_cal = sub.add_parser("calibrate", help="replay joins → Brier, reliability, precision@5, probe lift")
    p_cal.add_argument("--config", default=None)
    p_cal.add_argument("--runs", type=int, default=30, help="journal window (last N runs)")
    p_cal.add_argument("--json", action="store_true", help="machine-readable report")

    args = parser.parse_args(argv)
    if args.cmd == "init":
        from .init import init_config

        smoke = (args.smoke_feed_file, args.smoke_post) if args.smoke_feed_file else None
        path = init_config(args.vault, Path(args.config).expanduser() if args.config else None, smoke)
        print(f"config written: {path}")
        return 0
    if args.cmd == "digest":
        from .config import load_config
        from .digest import run_digest

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        for attr in ("top", "screen", "probe_k"):
            value = getattr(args, attr)
            if value is not None:
                setattr(cfg, attr, value)
        result = run_digest(cfg, feed=args.feed, feed_file=args.feed_file, post=args.post)
        print(result.markdown)
        print(f"\n[fingerprint {result.fingerprint} · {result.mode} · {result.picks} picks]")
        return 0
    if args.cmd == "keep":
        from datetime import date

        from arjev.config import load_config
        from arjev.keep import keep
        from arjev.ledger import LabelLedger
        from arjev.rerank import journal_path

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        candidate = _candidate_from_journal(args.arxiv, journal_path())
        if candidate is None:
            print(f"no journaled candidate for {args.arxiv} — digest first", file=sys.stderr)
            return 1
        path = keep(candidate, LabelLedger(), cfg, date.today())
        print(f"kept {args.arxiv}: stub at {path} (staged — fill rating/why to give it taste)")
        return 0
    if args.cmd == "fetch":
        from arjev.config import load_config
        from arjev.keep import fetch_pdf

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        if not cfg.library_dir:
            print("library_dir not configured", file=sys.stderr)
            return 1
        path = fetch_pdf(args.arxiv, Path(cfg.library_dir).expanduser())
        print(f"fetched: {path}")
        return 0
    if args.cmd == "labels" and args.labels_cmd == "sync":
        from datetime import datetime

        from arjev.config import load_config
        from arjev.fold import fold_roots
        from arjev.labels import labels_sync
        from arjev.ledger import LabelLedger

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        ledger = LabelLedger()
        new = labels_sync(cfg, fold_roots(cfg.expanded_roots, cfg), ledger, now=datetime.now())
        print(f"{len(new)} new label rows; ledger holds {len(ledger.rows())}")
        return 0
    if args.cmd == "ingest":
        from datetime import date

        from arjev.config import load_config
        from arjev.ingest import ingest_bibtex, ingest_pdf_dir, ingest_slack_channel

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        papers_dir = Path(args.papers_dir).expanduser() if args.papers_dir else None
        today = date.today()
        total = 0
        if args.bibtex:
            hits = ingest_bibtex(Path(args.bibtex).expanduser(), cfg, today, papers_dir)
            print(f"bibtex: {len(hits)} papers seeded from {args.bibtex}")
            total += len(hits)
        if args.pdf_dir:
            hits = ingest_pdf_dir(Path(args.pdf_dir).expanduser(), cfg, today, papers_dir)
            print(f"pdf-dir: {len(hits)} papers seeded from {args.pdf_dir}")
            total += len(hits)
        if args.slack_channel or args.slack_channel_id:
            from arjev.digest import slack_token
            from arjev.slack import SlackClient

            name = args.slack_channel or args.slack_channel_id
            channel_id = args.slack_channel_id or _resolve_channel(cfg, args.slack_channel)
            users = _slack_users()
            hits = ingest_slack_channel(
                SlackClient(token=slack_token()), channel_id, name, users,
                cfg, today, papers_dir, limit=args.limit,
            )
            print(f"slack: {len(hits)} human-shared papers seeded from #{name}")
            total += len(hits)
        print(f"{total} seeded notes total (existing ids skipped, never edited)")
        return 0
    if args.cmd == "calibrate":
        from arjev.calibrate import calibrate
        from arjev.config import load_config
        from arjev.fold import fold_roots

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        report = calibrate(cfg, fold_roots(cfg.expanded_roots, cfg), runs=args.runs)
        import dataclasses

        print(json.dumps(dataclasses.asdict(report), indent=2, sort_keys=True) if args.json else report.render())
        return 0
    if args.cmd == "slack" and args.slack_cmd == "sync":
        from datetime import date

        from arjev.config import load_config
        from arjev.digest import slack_token
        from arjev.keep import scaffold_note
        from arjev.ledger import LabelLedger, now_ts
        from arjev.rerank import journal_path
        from arjev.slack import SlackClient, harvest_labels

        cfg = load_config(Path(args.config).expanduser() if args.config else None)
        if not cfg.slack_channel:
            print("slack_channel not configured (docs/slack-setup.md)", file=sys.stderr)
            return 1
        journal = [json.loads(line) for line in journal_path().read_text().splitlines() if line.strip()]
        posted = [
            {"arxiv": c["arxiv"], "slack_ts": c["slack_ts"]}
            for line in journal if line.get("slack_channel") == cfg.slack_channel
            for c in line.get("candidates", []) if c.get("slack_ts")
        ]
        labels, _, _ = harvest_labels(
            SlackClient(token=slack_token()), cfg.slack_channel, posted,
            set(cfg.slack_keepers), cfg.emoji_map, now_ts(),
        )
        ledger = LabelLedger()
        written = [label for label in labels if ledger.append(label)]
        scaffolded = 0
        for label in written:
            if label.label_type != "keep":
                continue
            candidate = _candidate_from_journal(label.arxiv_id, journal_path())
            if candidate is None:
                continue
            scaffold_note(candidate, cfg, date.today())
            scaffolded += 1
        print(f"{len(written)} labels written; {scaffolded} keep stubs scaffolded")
        return 0
    parser.error(f"unknown command {args.cmd!r}")
    return 2


def _resolve_channel(cfg, name: str) -> str:
    """Channel name → id via the config's slack section, or accept a raw id."""
    from arjev.slack import resolve_channel

    return resolve_channel(cfg, name)


def _slack_users() -> dict[str, str]:
    """user id → display name, from the amico users cache when present."""
    path = Path.home() / ".amico" / "slack" / "users.json"
    if not path.is_file():
        return {}
    try:
        return {u.get("id"): u.get("name") or u.get("real_name") or u.get("id") for u in json.loads(path.read_text())}
    except (json.JSONDecodeError, OSError):
        return {}


def _candidate_from_journal(arxiv: str, journal_file: Path):
    """The durable record feeds the scaffold — title + authors come from the journal."""
    from arjev.fold import normalize_arxiv
    from arjev.keep import KeepCandidate

    target = normalize_arxiv(arxiv)
    if not journal_file.is_file():
        return None
    for line in reversed(journal_file.read_text().splitlines()):
        if not line.strip():
            continue
        for c in json.loads(line).get("candidates", []):
            if c["arxiv"] == target and c.get("title"):
                return KeepCandidate(arxiv=target, title=c["title"], authors=c.get("authors", []))
    return None


if __name__ == "__main__":
    sys.exit(main())

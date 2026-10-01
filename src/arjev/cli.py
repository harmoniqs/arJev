"""arjev CLI: init + digest (the verb surface grows per slice)."""

from __future__ import annotations

import argparse
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
    p_digest.add_argument("--post", default="stdout", choices=["stdout", "vault"], help="output sink")
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
    parser.error(f"unknown command {args.cmd!r}")
    return 2


def _candidate_from_journal(arxiv: str, journal_file: Path):
    """The durable record feeds the scaffold — title + authors come from the journal."""
    import json

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

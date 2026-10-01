"""arjev CLI: init + digest (the verb surface grows per slice)."""

from __future__ import annotations

import argparse
import sys

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

    args = parser.parse_args(argv)
    if args.cmd == "init":
        from pathlib import Path

        from .init import init_config

        smoke = (args.smoke_feed_file, args.smoke_post) if args.smoke_feed_file else None
        path = init_config(args.vault, Path(args.config).expanduser() if args.config else None, smoke)
        print(f"config written: {path}")
        return 0
    if args.cmd == "digest":
        from pathlib import Path

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
    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

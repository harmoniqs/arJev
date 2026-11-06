"""`arjev daily`: the whole day in one command, so a timer is one line.

The order and the operational lessons are encoded here rather than in each
deployment's shell glue:

1. digest — retried with backoff, because arXiv RSS sometimes returns zero items
   mid-day and the announced batch stays in the window all day. On Saturdays and
   Sundays (UTC) arXiv publishes no new listings, so an empty feed is a quiet
   day: one attempt, no retries, no failure.
2. ingest — papers people shared in the digest channel become vault notes.
3. slack sync — reactions and thread replies become labels; keeps become notes.
   Then each personal lane: its digest by DM (retried the same way) and its sync.
4. Sundays — the calibration report (to the state dir) and the week-in-review.

Steps 2–4 run only when a Slack token is available. A failed step is logged
and the rest still run; the exit code is 1 if any step failed.
"""

from __future__ import annotations

import io
import sys
import time
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import UTC, datetime

Runner = Callable[[list[str]], int]


def run_daily(
    runner: Runner,
    cfg,
    *,
    config_arg: list[str],
    now: datetime | None = None,
    retries: int = 5,
    backoff_s: float = 600,
    sleep: Callable[[float], None] = time.sleep,
    has_slack: bool | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    now = now or datetime.now(UTC)
    log = log or (lambda line: print(f"[{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}] {line}", flush=True))
    slack = _slack_available() if has_slack is None else has_slack
    slack_posting = slack and bool(cfg.slack_channel)
    failed: list[str] = []

    weekend = now.isoweekday() in (6, 7)
    attempts = 1 if weekend else max(1, retries)

    def digest(argv: list[str], label: str) -> None:
        for attempt in range(1, attempts + 1):
            log(f"{label} (attempt {attempt}/{attempts}, post {argv[argv.index('--post') + 1]})")
            if _ok(runner, [*argv, *config_arg], log):
                return
            if attempt < attempts:
                log(f"{label} attempt {attempt} failed — retrying in {backoff_s / 60:g} min")
                sleep(backoff_s)
            elif weekend:
                log(f"quiet weekend — arXiv publishes no new listings on Saturday or Sunday; no {label} "
                    "(not an outage)")
            else:
                log(f"{label} FAILED after {attempts} attempts")
                failed.append(label)

    digest(["digest", "--post", "slack,vault" if slack_posting else "vault"], "digest")

    if slack_posting:
        log("ingest — papers shared in the digest channel")
        if not _ok(runner, ["ingest", "--slack-channel-id", cfg.slack_channel, *config_arg], log):
            failed.append("ingest")
        log("slack sync — reactions and replies → labels")
        if not _ok(runner, ["slack", "sync", *config_arg], log):
            failed.append("slack sync")
    else:
        log("slack steps skipped — no Slack token or no channel configured")

    # personal lanes (issue #121): each lane's picks go to its recipient's DM,
    # then its reactions sync — after the shared day, one lane never stops another
    if cfg.lanes and slack:
        for name in cfg.lanes:
            digest(["digest", "--lane", name, "--post", "slack"], f"lane {name} digest")
            log(f"lane {name} slack sync — DM reactions → the lane's labels")
            if not _ok(runner, ["slack", "sync", "--lane", name, *config_arg], log):
                failed.append(f"lane {name} slack sync")
    elif cfg.lanes:
        log("lanes skipped — personal lanes deliver by Slack DM and no Slack token is available")

    if now.isoweekday() == 7:
        log("calibrate — the weekly report")
        if not _ok(runner, ["calibrate", *config_arg], log, save_as=f"calibration-{now:%Y%m%d}.md"):
            failed.append("calibrate")
        log("review — the week in review")
        review = ["review", "--days", "7", *(["--post", "slack"] if slack_posting else []), *config_arg]
        if not _ok(runner, review, log, save_as=f"review-{now:%Y%m%d}.md"):
            failed.append("review")

    log("done" if not failed else f"done with failures: {', '.join(failed)}")
    return 1 if failed else 0


def _ok(runner: Runner, argv: list[str], log, save_as: str | None = None) -> bool:
    """Run one verb; a SystemExit or exception is a logged failure, never a crash.
    With `save_as`, the verb's stdout is also written to the state dir."""
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            code = runner(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if exc.code and not isinstance(exc.code, int):
            log(f"  {exc.code}")
    except Exception as exc:  # one step's crash must not cost the others
        log(f"  {type(exc).__name__}: {exc}")
        code = 1
    out = buffer.getvalue()
    if out:
        sys.stdout.write(out)
    if save_as and out:
        from .rerank import state_dir

        state_dir().mkdir(parents=True, exist_ok=True)
        (state_dir() / save_as).write_text(out)
    return code == 0


def _slack_available() -> bool:
    from .digest import slack_token

    try:
        slack_token()
        return True
    except SystemExit:
        return False

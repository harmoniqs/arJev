"""`arjev daily`: the orchestration and its operational rules, tested offline
through an injected runner, clock, and sleep."""

from datetime import UTC, datetime

from arjev.config import Config
from arjev.daily import run_daily

WEDNESDAY = datetime(2026, 10, 21, 13, 0, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 24, 13, 0, tzinfo=UTC)
SUNDAY = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)


class Runner:
    """Records every verb; `digest_failures` makes the first N digests fail."""

    def __init__(self, digest_failures=0, fail=()):
        self.calls, self.digest_failures, self.fail = [], digest_failures, set(fail)

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[0] == "digest" and self.digest_failures:
            self.digest_failures -= 1
            raise SystemExit("feed failure — every configured feed returned 0 items")
        if " ".join(argv[:2]) in self.fail or argv[0] in self.fail:
            return 1
        print(f"ran {' '.join(argv)}")
        return 0

    def verbs(self):
        return [" ".join(a[:2]) if a[0] == "slack" else a[0] for a in self.calls]


def _cfg(channel="C0000000SYN"):
    cfg = Config()
    cfg.slack_channel = channel
    return cfg


def _run(runner, now, **kw):
    lines, sleeps = [], []
    code = run_daily(runner, _cfg(kw.pop("channel", "C0000000SYN")), config_arg=[], now=now,
                     sleep=sleeps.append, log=lines.append, has_slack=kw.pop("has_slack", True), **kw)
    return code, lines, sleeps


def test_weekday_runs_digest_then_ingest_then_sync():
    runner = Runner()
    code, _, _ = _run(runner, WEDNESDAY)
    assert code == 0
    assert runner.verbs() == ["digest", "ingest", "slack sync"]
    assert runner.calls[0] == ["digest", "--post", "slack,vault"]
    assert runner.calls[1] == ["ingest", "--slack-channel-id", "C0000000SYN"]


def test_weekday_retries_a_flaky_feed_then_succeeds():
    runner = Runner(digest_failures=2)
    code, lines, sleeps = _run(runner, WEDNESDAY, retries=5, backoff_s=600)
    assert code == 0
    assert runner.verbs().count("digest") == 3
    assert sleeps == [600, 600]


def test_weekday_digest_that_never_recovers_fails_the_run_but_not_the_other_steps():
    runner = Runner(digest_failures=99)
    code, lines, _ = _run(runner, WEDNESDAY, retries=3, backoff_s=1)
    assert code == 1
    assert runner.verbs() == ["digest", "digest", "digest", "ingest", "slack sync"]
    assert any("digest FAILED after 3 attempts" in line for line in lines)


def test_weekend_empty_feed_is_a_quiet_day_not_an_outage():
    runner = Runner(digest_failures=99)
    code, lines, sleeps = _run(runner, SATURDAY, retries=5)
    assert code == 0
    assert runner.verbs().count("digest") == 1 and sleeps == []
    assert any("quiet weekend" in line for line in lines)


def test_without_slack_the_digest_goes_to_the_vault_and_slack_steps_skip():
    runner = Runner()
    code, lines, _ = _run(runner, WEDNESDAY, has_slack=False)
    assert code == 0
    assert runner.calls == [["digest", "--post", "vault"]]
    assert any("slack steps skipped" in line for line in lines)


def test_sunday_adds_calibrate_and_the_review(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    runner = Runner(digest_failures=99)  # Sunday's feed is empty too
    code, _, _ = _run(runner, SUNDAY)
    assert code == 0
    assert runner.verbs() == ["digest", "ingest", "slack sync", "calibrate", "review"]
    assert runner.calls[-1] == ["review", "--days", "7", "--post", "slack"]
    assert (tmp_path / "arjev" / "calibration-20261025.md").read_text().startswith("ran calibrate")
    assert (tmp_path / "arjev" / "review-20261025.md").exists()


def test_a_failing_step_is_logged_and_the_rest_still_run():
    runner = Runner(fail={"ingest"})
    code, lines, _ = _run(runner, WEDNESDAY)
    assert code == 1
    assert runner.verbs() == ["digest", "ingest", "slack sync"]
    assert lines[-1] == "done with failures: ingest"


def test_a_crashing_step_never_takes_the_run_down():
    def runner(argv):
        if argv[0] == "ingest":
            raise RuntimeError("slack conversations.history failed: ratelimited")
        return 0

    code, lines, _ = _run(runner, WEDNESDAY)
    assert code == 1 and any("RuntimeError" in line for line in lines)

"""Multi-sink digest (issue #106, rd-system v2.1 A8a): one run, one ranking, many
sinks — `--post slack,vault`. The vault note is the durable record: it is written
first, and a Slack failure never costs it; a vault failure never blocks Slack.
Posted ids are consumed once and the journal is written once, per run."""

import json

import pytest

from arjev.cli import main
from arjev.digest import PostFailure, parse_post, run_digest
from conftest import RSS, TODAY, digest_cfg, isolate_state
from test_slack import FakeSlack


class FailingSlack:
    """A Slack client whose every post fails the way SlackClient._call fails."""

    def __init__(self):
        self.calls = 0

    def post_message(self, channel, text):
        self.calls += 1
        raise RuntimeError("slack chat.postMessage failed: channel_not_found")


def _cfg(tmp_path):
    cfg = digest_cfg()
    cfg.slack_channel = "C0000000SYN"
    cfg.digest_dir = str(tmp_path / "digests")
    return cfg


def _journal(tmp_path):
    path = tmp_path / "state" / "arjev" / "digest-journal.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def _posted(tmp_path):
    path = tmp_path / "state" / "arjev" / "papers-digest-state.json"
    return json.loads(path.read_text())["posted"] if path.is_file() else []


def _count_appends(monkeypatch):
    from arjev.state import PostedState

    calls = []
    real = PostedState.append

    def spy(self, new_ids, now=None):
        calls.append(list(new_ids))
        return real(self, new_ids, now)

    monkeypatch.setattr(PostedState, "append", spy)
    return calls


# ── parsing ─────────────────────────────────────────────────────────────────────

def test_parse_post_single_values_unchanged():
    assert parse_post("stdout") == ("stdout",)
    assert parse_post("vault") == ("vault",)
    assert parse_post("slack") == ("slack",)


def test_parse_post_comma_list_is_order_free_and_deduped():
    assert parse_post("slack,vault") == ("vault", "slack")
    assert parse_post("vault, slack") == ("vault", "slack")
    assert parse_post("slack,slack") == ("slack",)
    assert parse_post(("slack", "vault")) == ("vault", "slack")


@pytest.mark.parametrize("bad", ["email", "slack,email", "", "slack,", ",vault", "stdout,vault", "slack,stdout"])
def test_parse_post_rejects_unknown_empty_and_stdout_combinations(bad):
    with pytest.raises(ValueError):
        parse_post(bad)


def test_cli_rejects_invalid_post_token(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["digest", "--feed-file", str(RSS), "--post", "slack,email"])
    assert exc.value.code == 2
    assert "email" in capsys.readouterr().err


def test_cli_rejects_stdout_combined_with_durable_sink(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["digest", "--feed-file", str(RSS), "--post", "stdout,slack"])
    assert exc.value.code == 2
    assert "stdout" in capsys.readouterr().err


# ── the multi-sink run ──────────────────────────────────────────────────────────

def test_multi_sink_writes_both_and_consumes_ids_once(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    appends = _count_appends(monkeypatch)
    fake = FakeSlack()
    result = run_digest(_cfg(tmp_path), feed_file=str(RSS), today=TODAY, seed="s",
                        post="slack,vault", slack_client=fake.client())
    note = tmp_path / "digests" / "2026-10-01.md"
    assert note.is_file() and "type: digest" in note.read_text()
    posts = [p for m, p in fake.calls if m == "chat.postMessage"]
    assert len(posts) == 1 + len(result.picks)  # header + one per pick
    assert len(appends) == 1, "posted ids appended once per run, not once per sink"
    assert sorted(_posted(tmp_path)) == sorted(p.identity.id for p in result.picks)
    journal = _journal(tmp_path)
    assert len(journal) == 1, "journal written once per run"
    assert journal[0]["slack_channel"] == "C0000000SYN"
    assert all(c.get("slack_ts") for c in journal[0]["candidates"] if c["arxiv"] in
               {p.identity.id for p in result.picks})


def test_multi_sink_ranks_once(monkeypatch, tmp_path):
    import arjev.digest as digest_mod

    isolate_state(monkeypatch, tmp_path)
    calls = []
    real_rank = digest_mod.rank
    monkeypatch.setattr(digest_mod, "rank", lambda *a, **k: calls.append(1) or real_rank(*a, **k))
    run_digest(_cfg(tmp_path), feed_file=str(RSS), today=TODAY, seed="s",
               post="slack,vault", slack_client=FakeSlack().client())
    assert len(calls) == 1


def test_multi_sink_matches_single_sink_picks(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path / "a")
    single = run_digest(_cfg(tmp_path / "a"), feed_file=str(RSS), today=TODAY, seed="s", post="vault")
    isolate_state(monkeypatch, tmp_path / "b")
    multi = run_digest(_cfg(tmp_path / "b"), feed_file=str(RSS), today=TODAY, seed="s",
                       post="slack,vault", slack_client=FakeSlack().client())
    assert single.fingerprint == multi.fingerprint
    assert (tmp_path / "a" / "digests" / "2026-10-01.md").read_text() == \
        (tmp_path / "b" / "digests" / "2026-10-01.md").read_text()


def test_slack_failure_still_writes_vault_note_and_signals(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    appends = _count_appends(monkeypatch)
    failing = FailingSlack()
    with pytest.raises(PostFailure) as exc:
        run_digest(_cfg(tmp_path), feed_file=str(RSS), today=TODAY, seed="s",
                   post="slack,vault", slack_client=failing)
    assert failing.calls == 1
    assert (tmp_path / "digests" / "2026-10-01.md").is_file(), "the vault note is the durable record"
    assert set(exc.value.failed) == {"slack"}
    assert "channel_not_found" in str(exc.value)
    # the vault post was durable: its picks are consumed, and the run is journaled
    assert len(appends) == 1
    assert sorted(_posted(tmp_path)) == sorted(p.identity.id for p in exc.value.result.picks)
    assert len(_journal(tmp_path)) == 1


def test_vault_failure_does_not_block_slack(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    cfg = _cfg(tmp_path)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("a file where the digest dir should be")
    cfg.digest_dir = str(blocker / "digests")
    fake = FakeSlack()
    with pytest.raises(PostFailure) as exc:
        run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack,vault", slack_client=fake.client())
    assert set(exc.value.failed) == {"vault"}
    posts = [p for m, p in fake.calls if m == "chat.postMessage"]
    assert len(posts) == 1 + len(exc.value.result.picks), "slack posted in full despite the vault failure"
    assert sorted(_posted(tmp_path)) == sorted(p.identity.id for p in exc.value.result.picks)
    assert len(_journal(tmp_path)) == 1


def test_all_sinks_failing_consumes_nothing(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    cfg = _cfg(tmp_path)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    cfg.digest_dir = str(blocker / "digests")
    with pytest.raises(PostFailure) as exc:
        run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack,vault", slack_client=FailingSlack())
    assert set(exc.value.failed) == {"vault", "slack"}
    assert _posted(tmp_path) == [], "nothing durable landed — no ids consumed"


def test_single_slack_failure_unchanged_raises_raw(monkeypatch, tmp_path):
    """Single-sink behavior is unchanged: a lone slack failure propagates the
    client's own error, consumes nothing, journals nothing."""
    isolate_state(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="channel_not_found") as exc:
        run_digest(_cfg(tmp_path), feed_file=str(RSS), today=TODAY, seed="s", post="slack",
                   slack_client=FailingSlack())
    assert not isinstance(exc.value, PostFailure)
    assert _posted(tmp_path) == []
    assert _journal(tmp_path) == []


def test_slack_config_missing_fails_before_any_sink(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    cfg = _cfg(tmp_path)
    cfg.slack_channel = None
    with pytest.raises(SystemExit, match="slack_channel"):
        run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack,vault")
    assert not (tmp_path / "digests").exists(), "a config error writes nothing"
    assert _journal(tmp_path) == []


def test_single_vault_sink_unchanged(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    appends = _count_appends(monkeypatch)
    cfg = _cfg(tmp_path)
    cfg.slack_channel = None  # vault alone never needs slack config
    run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="vault")
    assert (tmp_path / "digests" / "2026-10-01.md").is_file()
    assert len(appends) == 1
    assert "slack_channel" not in _journal(tmp_path)[0] or _journal(tmp_path)[0]["slack_channel"] in (None, "")


def test_digest_dir_defaults_to_first_root_digests(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    root = tmp_path / "vault"
    (root / "papers").mkdir(parents=True)
    cfg = _cfg(tmp_path)
    cfg.roots = [str(root), str(tmp_path / "other")]
    cfg.digest_dir = None
    run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack,vault", slack_client=FakeSlack().client())
    assert (root / "digests" / "2026-10-01.md").is_file()


# ── the CLI signal ──────────────────────────────────────────────────────────────

def test_cli_partial_failure_prints_digest_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    import arjev.config as config_mod
    import arjev.digest as digest_mod

    isolate_state(monkeypatch, tmp_path)
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(config_mod, "load_config", lambda path=None: cfg)
    real = digest_mod.run_digest
    monkeypatch.setattr(digest_mod, "run_digest",
                        lambda c, **kw: real(c, today=TODAY, seed="s", slack_client=FailingSlack(), **kw))
    code = main(["digest", "--feed-file", str(RSS), "--post", "slack,vault"])
    out, err = capsys.readouterr()
    assert code == 1
    assert "fingerprint" in out, "the digest still prints — the run happened"
    assert "slack" in err and "channel_not_found" in err
    assert (tmp_path / "digests" / "2026-10-01.md").is_file()


def test_cli_multi_sink_success_exits_zero(monkeypatch, tmp_path, capsys):
    import arjev.config as config_mod
    import arjev.digest as digest_mod

    isolate_state(monkeypatch, tmp_path)
    cfg = _cfg(tmp_path)
    fake = FakeSlack()
    monkeypatch.setattr(config_mod, "load_config", lambda path=None: cfg)
    real = digest_mod.run_digest
    monkeypatch.setattr(digest_mod, "run_digest",
                        lambda c, **kw: real(c, today=TODAY, seed="s", slack_client=fake.client(), **kw))
    assert main(["digest", "--feed-file", str(RSS), "--post", "slack,vault"]) == 0
    assert (tmp_path / "digests" / "2026-10-01.md").is_file()
    assert any(m == "chat.postMessage" for m, _ in fake.calls)

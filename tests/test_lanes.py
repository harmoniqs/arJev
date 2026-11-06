"""Personal lanes (issue #121): a lane is a named ranking context — one recipient,
its own roots and feeds — whose picks arrive as Slack DMs, whose reactions label
only that lane, and whose journal / posted ids / label ledger live apart from the
shared channel's. A config with no lanes behaves exactly as before."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from arjev.cli import main
from arjev.config import Config, lane_config, load_config
from arjev.digest import run_digest
from arjev.inspect import run_inspect
from arjev.lanes import lane_scope
from arjev.ledger import LabelLedger, ledger_path
from arjev.rerank import journal_path, state_dir
from arjev.slack import SlackClient
from conftest import RSS, TODAY, VAULT, digest_cfg

FIXTURES = Path(__file__).parent / "fixtures"
RECIPIENT = "U0000000LNE"
OTHER = "U0000000OTH"
DM = "D0000000LNE"


class FakeSlack:
    """The Slack Web API, recorded: DMs open to a fixed channel id; every post
    gets a fresh ts; reactions are scripted per (channel, ts)."""

    def __init__(self, reactions=None, open_error=None):
        self.calls: list[tuple[str, dict]] = []
        self.reactions = reactions or {}
        self.open_error = open_error
        self._n = 0

    def __call__(self, method, payload, token):
        self.calls.append((method, payload))
        if method == "conversations.open":
            if self.open_error:
                return {"ok": False, "error": self.open_error}
            return {"ok": True, "channel": {"id": DM}}
        if method == "chat.postMessage":
            self._n += 1
            return {"ok": True, "ts": f"1789990002.{self._n:06d}", "channel": payload["channel"]}
        if method == "reactions.get":
            key = (payload["channel"], payload["timestamp"])
            return {"ok": True, "message": {"reactions": self.reactions.get(key, [])}}
        if method == "conversations.replies":
            return {"ok": True, "messages": [{"ts": payload["ts"]}]}
        raise AssertionError(method)

    def client(self):
        return SlackClient(token="xoxb-test", transport=self, sleep=lambda s: None)

    def posts(self):
        return [p for m, p in self.calls if m == "chat.postMessage"]


def _lane_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "lane-vault"
    shutil.copytree(VAULT, vault)
    return vault


def _config_file(tmp_path: Path, lane_vault: Path, *, feeds='["quant-ph"]', recipient=RECIPIENT,
                 extra_lane="") -> Path:
    path = tmp_path / "arjev.toml"
    path.write_text(
        "[vault]\n"
        f'roots = ["{VAULT}"]\n'
        'feeds = ["quant-ph"]\n'
        f'papers_dir = "{tmp_path / "shared-papers"}"\n'
        "\n[slack]\n"
        'channel = "C0000000SYN"\n'
        f'keepers = ["{OTHER}"]\n'
        "\n[lanes.jackson]\n"
        + (f'recipient = "{recipient}"\n' if recipient else "")
        + f'roots = ["{lane_vault}"]\n'
        + f"feeds = {feeds}\n"
        + f'papers_dir = "{tmp_path / "lane-papers"}"\n'
        + "top = 3\n"
        + extra_lane
    )
    return path


# ── config ───────────────────────────────────────────────────────────────────────

def test_a_lane_is_parsed_and_derives_its_own_config(tmp_path):
    lane_vault = _lane_vault(tmp_path)
    cfg = load_config(_config_file(tmp_path, lane_vault))
    assert list(cfg.lanes) == ["jackson"]
    lane = lane_config(cfg, "jackson")
    assert lane.lane == "jackson"
    assert lane.roots == [str(lane_vault)]
    assert lane.feeds == ["quant-ph"]
    assert lane.top == 3
    assert lane.slack_recipient == RECIPIENT
    assert lane.slack_channel is None, "a lane never posts to the shared channel"
    assert lane.slack_keepers == [RECIPIENT], "only the recipient's reactions label a lane"
    assert lane.lanes == {}
    # the base config is untouched
    assert cfg.roots == [str(VAULT)] and cfg.slack_channel == "C0000000SYN" and cfg.lane is None


def test_a_lane_never_inherits_the_shared_roots_or_feeds(tmp_path):
    """A personal lane never folds another researcher's vault, and a category is
    never defaulted — an unset lane slot stays empty, it does not fall through."""
    path = tmp_path / "arjev.toml"
    path.write_text(
        '[vault]\nroots = ["/team/vault"]\nfeeds = ["quant-ph"]\n'
        f'\n[lanes.solo]\nrecipient = "{RECIPIENT}"\n'
    )
    lane = lane_config(load_config(path), "solo")
    assert lane.roots == [] and lane.feeds == []


def test_unknown_lane_is_a_loud_error(tmp_path):
    cfg = load_config(_config_file(tmp_path, _lane_vault(tmp_path)))
    with pytest.raises(SystemExit, match="no lane 'nobody'"):
        lane_config(cfg, "nobody")


def test_no_lanes_config_has_no_lanes(tmp_path):
    path = tmp_path / "arjev.toml"
    path.write_text('[vault]\nroots = ["/v"]\nfeeds = ["quant-ph"]\n')
    assert load_config(path).lanes == {}


# ── state isolation ──────────────────────────────────────────────────────────────

def test_lane_scope_namespaces_every_state_file():
    shared_state, shared_ledger = state_dir(), ledger_path()
    with lane_scope("jackson"):
        assert state_dir() == shared_state / "lanes" / "jackson"
        assert journal_path().parent == shared_state / "lanes" / "jackson"
        assert ledger_path() == shared_state / "lanes" / "jackson" / "label-ledger.jsonl"
    assert state_dir() == shared_state and ledger_path() == shared_ledger
    with lane_scope(None):
        assert state_dir() == shared_state


def test_lane_names_cannot_escape_the_state_dir():
    with pytest.raises(ValueError):
        with lane_scope("../etc"):
            pass


# ── delivery ─────────────────────────────────────────────────────────────────────

def test_a_lane_digest_arrives_by_dm_one_message_per_pick(tmp_path):
    lane_vault = _lane_vault(tmp_path)
    cfg = lane_config(load_config(_config_file(tmp_path, lane_vault)), "jackson")
    fake = FakeSlack()
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=fake.client())
    assert ("conversations.open", {"users": RECIPIENT}) in fake.calls
    posts = fake.posts()
    assert posts and all(p["channel"] == DM for p in posts), "every lane post goes to the recipient's DM"
    assert len(posts) == len(result.picks) + 1  # the header + one per pick
    assert "arJev picks for you" in posts[0]["text"]
    for post in posts[1:]:
        assert "arxiv.org/abs/" in post["text"] and "_why:_" in post["text"]
    # the lane's journal records the DM channel and every pick's ts
    with lane_scope("jackson"):
        rows = [json.loads(line) for line in journal_path().read_text().splitlines()]
        posted_ids = json.loads((state_dir() / "papers-digest-state.json").read_text())["posted"]
    assert rows[-1]["slack_channel"] == DM
    assert sum(1 for c in rows[-1]["candidates"] if c.get("slack_ts")) == len(result.picks)
    assert sorted(posted_ids) == sorted(p.identity.id for p in result.picks)
    # …and none of it touched the shared state
    assert not journal_path().exists()
    assert not (state_dir() / "papers-digest-state.json").exists()


def test_a_lane_whose_dm_cannot_open_fails_before_ranking(tmp_path):
    cfg = lane_config(load_config(_config_file(tmp_path, _lane_vault(tmp_path))), "jackson")
    fake = FakeSlack(open_error="user_not_found")
    with pytest.raises(RuntimeError, match="user_not_found"):
        run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=fake.client())
    assert not fake.posts()
    with lane_scope("jackson"):
        assert not journal_path().exists(), "a lane that never posted journals nothing"


def test_lane_posted_ids_are_independent_of_the_shared_channel(tmp_path):
    """A paper the shared channel already posted can still be picked in a lane."""
    lane_vault = _lane_vault(tmp_path)
    file_cfg = load_config(_config_file(tmp_path, lane_vault))
    shared = digest_cfg()
    shared.slack_channel = "C0000000SYN"
    shared_fake = FakeSlack()
    shared_result = run_digest(shared, feed_file=str(RSS), today=TODAY, seed="s", post="slack",
                               slack_client=shared_fake.client())
    lane = lane_config(file_cfg, "jackson")
    lane.top = shared.top
    lane_result = run_digest(lane, feed_file=str(RSS), today=TODAY, seed="s", post="slack",
                             slack_client=FakeSlack().client())
    assert shared_result.picks
    assert [p.identity for p in lane_result.picks] == [p.identity for p in shared_result.picks]


def test_no_lane_configs_rank_exactly_as_before(tmp_path):
    """Back-compat parity: a config that merely declares lanes leaves the shared
    digest's ranking byte-identical (machine gate: score_delta_no_lane_configs == 0)."""
    plain = digest_cfg()
    baseline = run_digest(plain, feed_file=str(RSS), today=TODAY, seed="s", post="stdout")
    with_lanes = load_config(_config_file(tmp_path, _lane_vault(tmp_path)))
    with_lanes.roots = [str(VAULT)]
    again = run_digest(with_lanes, feed_file=str(RSS), today=TODAY, seed="s", post="stdout")
    assert again.fingerprint == baseline.fingerprint
    assert [p.lexical_score for p in again.picks] == [p.lexical_score for p in baseline.picks]


# ── the harvest: reactions label only their own lane ─────────────────────────────

def _post_both(tmp_path):
    """Post the shared digest and the lane digest; return (config path, shared ts, lane ts)."""
    lane_vault = _lane_vault(tmp_path)
    path = _config_file(tmp_path, lane_vault)
    file_cfg = load_config(path)
    shared_fake, lane_fake = FakeSlack(), FakeSlack()
    shared = load_config(path)
    run_digest(shared, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=shared_fake.client())
    run_digest(lane_config(file_cfg, "jackson"), feed_file=str(RSS), today=TODAY, seed="s", post="slack",
               slack_client=lane_fake.client())
    return path, shared_fake.posts()[1:], lane_fake.posts()[1:]


def _sync(monkeypatch, path, fake, *lane):
    import arjev.slack as slack_mod

    monkeypatch.setenv("ARJEV_SLACK_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_mod, "SlackClient", lambda **kw: fake.client())
    return main(["slack", "sync", "--config", str(path), *lane])


def test_reactions_in_a_lane_dm_label_only_that_lane(monkeypatch, tmp_path, capsys):
    path, _, lane_posts = _post_both(tmp_path)
    lane_ts = [f"1789990002.{i + 2:06d}" for i in range(len(lane_posts))]
    reactions = {
        (DM, lane_ts[0]): [{"name": "thumbsup", "users": [RECIPIENT]}],
        (DM, lane_ts[1]): [{"name": "thumbsup", "users": [OTHER]}],  # not the recipient
    }
    fake = FakeSlack(reactions=reactions)
    assert _sync(monkeypatch, path, fake, "--lane", "jackson") == 0
    assert all(p["channel"] == DM for m, p in fake.calls if m == "reactions.get")
    with lane_scope("jackson"):
        keeps = [r for r in LabelLedger().rows() if r.label_type == "keep"]
    assert len(keeps) == 1, "only the recipient's reaction labels the lane"
    assert not [r for r in LabelLedger().rows() if r.label_type == "keep"], "cross_lane_labels == 0"
    # the keep scaffolds into the lane's own papers dir, never the shared one
    assert list((tmp_path / "lane-papers").glob("*.md"))
    assert not (tmp_path / "shared-papers").exists()


def test_shared_channel_reactions_never_label_a_lane(monkeypatch, tmp_path):
    path, _, _ = _post_both(tmp_path)
    reactions = {("C0000000SYN", f"1789990002.{i:06d}"): [{"name": "thumbsup", "users": [OTHER, RECIPIENT]}]
                 for i in range(2, 12)}
    fake = FakeSlack(reactions=reactions)
    assert _sync(monkeypatch, path, fake) == 0
    assert all(p["channel"] == "C0000000SYN" for m, p in fake.calls if m == "reactions.get")
    assert [r for r in LabelLedger().rows() if r.label_type == "keep"]
    with lane_scope("jackson"):
        assert not LabelLedger().rows(), "cross_lane_labels == 0"


def test_lane_sync_before_any_digest_is_a_quiet_no_op(monkeypatch, tmp_path, capsys):
    path = _config_file(tmp_path, _lane_vault(tmp_path))
    assert _sync(monkeypatch, path, FakeSlack(), "--lane", "jackson") == 0
    assert "0 labels written" in capsys.readouterr().out


# ── the CLI ──────────────────────────────────────────────────────────────────────

def test_cli_digest_lane_flag_posts_to_the_dm(monkeypatch, tmp_path, capsys):
    import arjev.slack as slack_mod

    path = _config_file(tmp_path, _lane_vault(tmp_path))
    fake = FakeSlack()
    monkeypatch.setenv("ARJEV_SLACK_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_mod, "SlackClient", lambda **kw: fake.client())
    assert main(["digest", "--lane", "jackson", "--feed-file", str(RSS), "--post", "slack",
                 "--config", str(path)]) == 0
    assert fake.posts() and all(p["channel"] == DM for p in fake.posts())


# ── inspect ──────────────────────────────────────────────────────────────────────

LANE_LINE = re.compile(r"lane [a-z0-9_-]+ [a-z-]+: .+")


def test_inspect_reports_each_lane(tmp_path):
    lane_vault = _lane_vault(tmp_path)
    report = run_inspect(load_config(_config_file(tmp_path, lane_vault)), today=TODAY)
    lane_lines = [ln for ln in report.lines if ln.startswith("lane ")]
    assert f"lane jackson recipient: {RECIPIENT}" in lane_lines
    assert f"lane jackson roots: {lane_vault}" in lane_lines
    assert "lane jackson feeds: quant-ph" in lane_lines
    assert any(ln.startswith("lane jackson identity-bearing: ") for ln in lane_lines)
    assert any(ln.startswith("lane jackson directives: ") for ln in lane_lines)
    assert all(LANE_LINE.fullmatch(ln) for ln in lane_lines)
    assert not report.blocked


def test_inspect_blocks_a_lane_with_empty_feeds_naming_it(tmp_path):
    report = run_inspect(load_config(_config_file(tmp_path, _lane_vault(tmp_path), feeds="[]")), today=TODAY)
    assert "lane jackson feeds: empty" in report.lines
    assert "blocked: lane jackson: no feeds configured" in report.blocked


def test_inspect_blocks_a_lane_without_a_recipient(tmp_path):
    report = run_inspect(load_config(_config_file(tmp_path, _lane_vault(tmp_path), recipient=None)), today=TODAY)
    assert "blocked: lane jackson: no recipient configured" in report.blocked


def test_inspect_without_lanes_prints_no_lane_lines():
    cfg = Config()
    cfg.roots, cfg.feeds = [str(VAULT)], ["quant-ph"]
    report = run_inspect(cfg, today=TODAY)
    assert not [ln for ln in report.lines if ln.startswith("lane ")]


# ── daily ────────────────────────────────────────────────────────────────────────

def test_daily_runs_each_lane_after_the_shared_day():
    from datetime import UTC, datetime

    from arjev.config import Lane
    from arjev.daily import run_daily

    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:3] == ["digest", "--lane", "broken"]:
            raise SystemExit("slack conversations.open failed: user_not_found")
        return 0

    cfg = Config()
    cfg.slack_channel = "C0000000SYN"
    cfg.lanes = {"jackson": Lane(name="jackson", recipient=RECIPIENT),
                 "broken": Lane(name="broken", recipient=OTHER)}
    code = run_daily(runner, cfg, config_arg=[], now=datetime(2026, 10, 21, 13, tzinfo=UTC),
                     sleep=lambda s: None, log=lambda line: None, has_slack=True, retries=1)
    assert calls[:3] == [["digest", "--post", "slack,vault"],
                         ["ingest", "--slack-channel-id", "C0000000SYN"], ["slack", "sync"]]
    assert ["digest", "--lane", "jackson", "--post", "slack"] in calls
    assert ["slack", "sync", "--lane", "jackson"] in calls
    assert ["slack", "sync", "--lane", "broken"] in calls, "a failed lane digest never stops the others"
    assert code == 1, "a failed lane is reported"


def test_daily_skips_lanes_without_a_slack_token():
    from datetime import UTC, datetime

    from arjev.config import Lane
    from arjev.daily import run_daily

    calls = []
    cfg = Config()
    cfg.lanes = {"jackson": Lane(name="jackson", recipient=RECIPIENT)}
    lines = []
    run_daily(lambda argv: calls.append(argv) or 0, cfg, config_arg=[],
              now=datetime(2026, 10, 21, 13, tzinfo=UTC), sleep=lambda s: None, log=lines.append,
              has_slack=False, retries=1)
    assert not [c for c in calls if "--lane" in c]
    assert any("lanes skipped" in line for line in lines)


# ── the rest of the loop, per lane: review, calibrate, seeding ──────────────────

def test_a_lane_review_reads_the_lane_journal_and_goes_to_the_dm(monkeypatch, tmp_path, capsys):
    """The week-in-review is a lane's too: it re-reads only that lane's journal
    and posts to the recipient's DM, never the shared channel."""
    import arjev.slack as slack_mod

    path = _config_file(tmp_path, _lane_vault(tmp_path))
    lane = lane_config(load_config(path), "jackson")
    run_digest(lane, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=FakeSlack().client())
    fake = FakeSlack()
    monkeypatch.setenv("ARJEV_SLACK_TOKEN", "xoxb-test")
    monkeypatch.setattr(slack_mod, "SlackClient", lambda **kw: fake.client())
    assert main(["review", "--lane", "jackson", "--days", "36500", "--post", "slack", "--config", str(path)]) == 0
    posts = fake.posts()
    assert len(posts) == 1 and posts[0]["channel"] == DM
    # the shared scope has no journal at all — the review read the lane's
    assert not journal_path().exists()


def test_post_review_opens_the_recipients_dm():
    from arjev.review import Review, post_review

    cfg = Config()
    cfg.slack_recipient = RECIPIENT
    fake = FakeSlack()
    report = Review(days=7)
    report.render_slack = lambda: "the week"  # the rendering is test_review's; this is the routing
    post_review(cfg, report, slack_client=fake.client())
    assert ("conversations.open", {"users": RECIPIENT}) in fake.calls
    assert [p["channel"] for p in fake.posts()] == [DM]


def test_calibrate_runs_in_the_lane_scope(tmp_path, capsys):
    path = _config_file(tmp_path, _lane_vault(tmp_path))
    lane = lane_config(load_config(path), "jackson")
    run_digest(lane, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=FakeSlack().client())
    assert main(["calibrate", "--lane", "jackson", "--json", "--config", str(path)]) == 0
    lane_report = json.loads(capsys.readouterr().out)
    assert main(["calibrate", "--json", "--config", str(path)]) == 0
    shared_report = json.loads(capsys.readouterr().out)
    assert lane_report != shared_report, "the lane calibrates against its own journal"


def test_ingest_lane_seeds_the_lane_vault_not_the_shared_one(tmp_path, capsys):
    lane_vault = _lane_vault(tmp_path)
    path = _config_file(tmp_path, lane_vault)
    bib = tmp_path / "mine.bib"
    bib.write_text("@article{a,\n  title = {A seeded lane paper},\n  eprint = {2601.07777},\n  year = {2026}\n}\n")
    assert main(["ingest", "--lane", "jackson", "--bibtex", str(bib), "--config", str(path)]) == 0
    assert list((tmp_path / "lane-papers").glob("*.md")), "the lane's papers_dir"
    assert not (tmp_path / "shared-papers").exists()


def test_daily_sunday_sends_each_lane_its_review():
    from datetime import UTC, datetime

    from arjev.config import Lane
    from arjev.daily import run_daily

    calls = []
    cfg = Config()
    cfg.slack_channel = "C0000000SYN"
    cfg.lanes = {"jackson": Lane(name="jackson", recipient=RECIPIENT)}
    run_daily(lambda argv: calls.append(argv) or 0, cfg, config_arg=[],
              now=datetime(2026, 10, 25, 13, tzinfo=UTC), sleep=lambda s: None, log=lambda line: None,
              has_slack=True, retries=1)
    assert ["calibrate", "--lane", "jackson"] in calls
    assert ["review", "--days", "7", "--lane", "jackson", "--post", "slack"] in calls

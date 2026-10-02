"""Slack surface tests: LaTeX cleanup, keepers enforcement, the reaction→keep→scaffold
roundtrip, discussed replies, the content boundary, rate discipline, per-pick posting
(obligations #10 #12 #18)."""

import json
from pathlib import Path

from arjev.cli import main
from arjev.digest import run_digest
from arjev.latex import latex_to_unicode
from arjev.slack import DEFAULT_EMOJI_MAP, SlackClient, harvest_labels, render_pick_message
from conftest import RSS, TODAY, VAULT, digest_cfg, isolate_state

FIXTURES = Path(__file__).parent / "fixtures"
KEEPERS = {"U0000000SYN"}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeSlack:
    def __init__(self, reactions=None, replies=None, posts=None):
        self.calls = []
        self.sleeps = []
        self._reactions = reactions if reactions is not None else _fixture("slack-reactions.json")
        self._replies = replies if replies is not None else _fixture("slack-thread.json")
        self._posts = posts or _fixture("slack-post.json")
        self._clock = 100.0

    def __call__(self, method, payload, token):
        self.calls.append((method, payload))
        if method == "chat.postMessage":
            return self._posts
        if method == "reactions.get":
            return self._reactions
        if method == "conversations.replies":
            return self._replies
        raise AssertionError(method)

    def fake_sleep(self, seconds):
        self.sleeps.append(seconds)
        self._clock += seconds

    def client(self):
        import arjev.slack as slack

        real_monotonic = slack.time.monotonic
        slack.time.monotonic = lambda: self._clock
        try:
            c = SlackClient(token="xoxb-test", transport=self, sleep=self.fake_sleep)
            return c
        finally:
            slack.time.monotonic = real_monotonic


# ── LaTeX cleanup ────────────────────────────────────────────────────────────────

def test_latex_sqrt_text_x():
    assert latex_to_unicode("Synthetic: $\\sqrt{\\text{X}}$-gate calibration") == \
        "Synthetic: √(X)-gate calibration"


def test_latex_greek_and_operators():
    out = latex_to_unicode("$\\pi$ pulses with $\\alpha \\leq 0.1$")
    assert "π" in out and "α" in out and "≤" in out and "$" not in out


# ── keepers enforcement ───────────────────────────────────────────────────────────

def test_unauthorized_reactions_label_nothing():
    fake = FakeSlack()
    labels, keeps, discussed = harvest_labels(
        fake.client(), "C0000000SYN", [{"arxiv": "2601.01011", "slack_ts": "1789990001.000100"}],
        KEEPERS, DEFAULT_EMOJI_MAP, "2026-10-01T00:00:00Z",
    )
    kinds = {(lbl.arxiv_id, lbl.label_type) for lbl in labels}
    assert ("2601.01011", "keep") in kinds         # the keeper's thumbsup counts
    assert ("2601.01011", "read-later") in kinds    # keeper's eyes count
    assert "fire" not in {lbl.label_type for lbl in labels}  # unmapped emoji: not a label
    reaction_labels = [lbl for lbl in labels if lbl.label_type != "discussed"]
    assert reaction_labels and all(lbl.source == "slack-reaction" for lbl in reaction_labels)


def test_reply_harvest_is_discussed_flavor():
    fake = FakeSlack()
    labels, _, discussed = harvest_labels(
        fake.client(), "C0000000SYN", [{"arxiv": "2601.01011", "slack_ts": "1789990001.000100"}],
        KEEPERS, DEFAULT_EMOJI_MAP, "2026-10-01T00:00:00Z",
    )
    assert discussed == ["2601.01011"]
    assert any(lbl.label_type == "discussed" and lbl.source == "slack-reply" for lbl in labels)


# ── content boundary + why_style gating ──────────────────────────────────────────

class _Pick:
    arxiv = "2601.01011"
    title = "Synthetic: $\\sqrt{\\text{X}}$-gate calibration"
    lexical_score = 68.5
    terms = ["randomized", "compiling"]
    jev_primary = 0.95
    rescued = None


def test_content_boundary_terms_mode():
    msg = render_pick_message(_Pick(), 1, 5, TODAY, "mode: jev, ok", "terms")
    assert "randomized" in msg.text and "arxiv.org/abs/2601.01011" in msg.text
    assert "/" not in str(VAULT) or str(VAULT) not in msg.text  # no vault paths
    assert ".md" not in msg.text  # no note filenames
    assert "√(X)" in msg.text  # LaTeX cleaned


def test_content_boundary_opaque_mode():
    msg = render_pick_message(_Pick(), 1, 5, TODAY, "mode: jev, ok", "opaque")
    assert "randomized" not in msg.text and "profile match" in msg.text


def test_content_boundary_none_mode():
    msg = render_pick_message(_Pick(), 1, 5, TODAY, "mode: jev, ok", "none")
    assert "randomized" not in msg.text and "profile match" not in msg.text


def test_probe_rescue_why_line_in_slack():
    pick = _Pick()
    pick.rescued = "probe"
    pick.terms = []
    msg = render_pick_message(pick, 1, 5, TODAY, "mode: jev, ok", "none")
    assert "rescued by probe" in msg.text and f"p={pick.jev_primary:.2f}" in msg.text


# ── rate discipline ──────────────────────────────────────────────────────────────

def test_rate_limit_never_faster_than_one_per_second():
    fake = FakeSlack()
    client = fake.client()
    posted = [{"arxiv": f"2601.0101{i}", "slack_ts": "t"} for i in range(4)]
    harvest_labels(client, "C0000000SYN", posted, KEEPERS, DEFAULT_EMOJI_MAP, "t")
    # 4 pick messages × (reactions.get + conversations.replies) = 8 transport calls,
    # each preceded by the min-interval wait
    assert len(fake.sleeps) >= 7 and all(s >= 0.99 for s in fake.sleeps)


def test_429_backoff_retries_then_succeeds():
    calls = {"n": 0}

    def transport(method, payload, token):
        calls["n"] += 1
        if calls["n"] <= 2:
            return {"ok": True, "error": "ratelimited"}
        return json.loads((FIXTURES / "slack-post.json").read_text())


    client = SlackClient(token="xoxb-test", transport=transport, sleep=lambda s: None)
    ts = client.post_message("C0000000SYN", "hello")
    assert ts == "1789990002.000100" and calls["n"] == 3


# ── the per-pick posting + auto-scaffold roundtrip ───────────────────────────────

def test_digest_posts_each_pick_and_journals_ts(monkeypatch, tmp_path):
    isolate_state(monkeypatch, tmp_path)
    fake = FakeSlack()
    cfg = digest_cfg()
    cfg.slack_channel = "C0000000SYN"
    cfg.papers_dir = str(tmp_path / "papers")
    cfg.roots = [str(tmp_path / "vault")]  # isolated copy
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "papers").mkdir()
    cfg2 = digest_cfg()
    cfg2.slack_channel = "C0000000SYN"
    cfg2.papers_dir = str(tmp_path / "papers")
    result = run_digest(cfg2, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=fake.client())
    assert len(fake.calls) == len(result.picks) + 1  # the header + one per pick
    texts = [p["text"] for _, p in fake.calls]
    assert all("arxiv.org/abs/" in t for t in texts[1:])  # the header carries no link
    # the journal carries (arxiv, slack_ts) pairs — the sync's join key
    from arjev.rerank import journal_path

    journal = [json.loads(line) for line in journal_path().read_text().splitlines()]
    posted_rows = [(c["arxiv"], c["slack_ts"]) for line in journal for c in line["candidates"] if c.get("slack_ts")]
    assert len(posted_rows) == len(result.picks)


def test_slack_sync_auto_scaffolds_keeps(monkeypatch, tmp_path, capsys):
    isolate_state(monkeypatch, tmp_path)
    monkeypatch.setenv("ARJEV_SLACK_TOKEN", "xoxb-test")
    # run a digest that posts (fake transport) so the journal has slack_ts entries
    fake = FakeSlack()
    cfg = digest_cfg()
    cfg.slack_channel = "C0000000SYN"
    cfg.papers_dir = str(tmp_path / "papers")  # stubs scaffold here, not into the fixture vault
    cfg.slack_keepers = ["U0000000SYN"]
    cfg.roots = [str(VAULT)]
    run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=fake.client())
    # swap the client transport to the reaction/reply fixtures for the sync

    fake_sync = FakeSlack()
    import arjev.slack as slack_mod

    original = slack_mod.SlackClient
    slack_mod.SlackClient = lambda **kw: fake_sync.client()
    try:
        rc = main(["slack", "sync", "--config", _write_config(tmp_path, cfg)])
    finally:
        slack_mod.SlackClient = original
    assert rc == 0
    out = capsys.readouterr().out
    assert "labels written" in out and "stubs scaffolded" in out
    stubs = list((tmp_path / "papers").glob("*.md"))
    assert stubs, "the keeper's thumbsup must have scaffolded the staged stub"
    assert len(list((VAULT / "papers").glob("*.md"))) == 7, "the fixture vault must never be written to"


def _write_config(tmp_path, cfg):

    path = tmp_path / "arjev.toml"
    path.write_text(
        "[vault]\n"
        f'roots = ["{cfg.roots[0]}"]\n'
        f'\npapers_dir = "{cfg.papers_dir}"\n'
        "\n[slack]\n"
        'channel = "C0000000SYN"\n'
        'keepers = ["U0000000SYN"]\n'
    )
    return str(path)


def test_slack_post_opens_with_a_digest_header(monkeypatch, tmp_path):
    """The channel showed five bare picks read as bot noise, not a digest — the
    first message must announce the digest itself."""
    isolate_state(monkeypatch, tmp_path)
    fake = FakeSlack()
    cfg = digest_cfg()
    cfg.slack_channel = "C0000000SYN"
    cfg.roots = [str(VAULT)]
    result = run_digest(cfg, feed_file=str(RSS), today=TODAY, seed="s", post="slack", slack_client=fake.client())
    first = fake.calls[0][1]["text"]
    assert "arJev daily digest" in first and str(TODAY) in first
    assert f"{len(result.picks)} picks" in first and "mode: lexical-only, ok" in first
    assert len(fake.calls) == len(result.picks) + 1  # header + one per pick

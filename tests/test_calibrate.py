"""Calibrate tests: the four metrics on known fixture data (exact values, n-stated),
the planted staged-gate audit failure, the no-config-write assertion, weak-negatives
kept separate, censoring named (obligations #14 #19 #20 #21 #24)."""

import json

from arjev.calibrate import calibrate
from arjev.ledger import Label, LabelLedger
from arjev.rerank import journal_path, state_dir
from conftest import TODAY, VAULT, isolate_state

TODAY_S = TODAY.isoformat() + "T00:00:00Z"


def _write_state(tmp_path, receipts: list[dict], journal: list[dict]) -> None:
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "jev-receipts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in receipts))
    journal_path().write_text("".join(json.dumps(j) + "\n" for j in journal))


def _receipt(arxiv: str, primitive: str, distribution: dict) -> dict:
    return {"candidate_arxiv": arxiv, "run_id": "r1", "ts": TODAY_S, "primitive": primitive,
            "state_bytes": 500, "distribution": distribution, "confidence": max(distribution.values()),
            "latency_ms": 300, "model_version": "test-1"}


def _journal(candidates: list[dict], ts: str = TODAY_S) -> dict:
    return {"run_id": "r1", "ts": ts, "feed": "quant-ph", "mode": "mode: jev, ok", "seed": "s",
            "slack_channel": None, "candidates": candidates}


def _cand(arxiv: str, pool: str = "survivor", posted: bool = True, rescued=None) -> dict:
    return {"arxiv": arxiv, "pool": pool, "lexical_score": 1.0, "terms": [], "jev": None,
            "posted": posted, "rescued": rescued, "title": f"t-{arxiv}", "authors": [], "slack_ts": ""}


def _label_ledger(rows: list[tuple[str, str, str]]) -> None:
    ledger = LabelLedger()
    for arxiv, label_type, source in rows:
        ledger.append(Label(arxiv, label_type, source, TODAY_S))


def test_brier_exact_values_on_known_data(tmp_path):
    isolate_state_monkey = _monkey(tmp_path)
    # score: p(positive)=0.8 kept → (0.2)^2 = 0.04; noul: p=0.9 kept → 0.01; noul skip p=0.9 → 0.81
    _write_state(tmp_path, [
        _receipt("2601.01011", "score", {"must-read": 0.6, "worth-reading": 0.2, "irrelevant": 0.2}),
        _receipt("2601.01012", "noul", {"true": 0.9, "false": 0.1}),
        _receipt("2601.01013", "noul", {"true": 0.9, "false": 0.1}),
    ], [])
    _label_ledger([
        ("2601.01011", "keep", "cli-keep"),
        ("2601.01012", "keep", "cli-keep"),
        ("2601.01013", "skip", "checkbox"),
    ])
    report = _calibrate(tmp_path)
    assert report.metrics["brier"]["score"]["brier"] == 0.04
    assert report.metrics["brier"]["score"]["n"] == 1
    assert report.metrics["brier"]["noul"]["brier"] == round((0.01 + 0.81) / 2, 4)
    assert report.metrics["brier"]["noul"]["n"] == 2


def test_reliability_bins_are_ten_equal_width(tmp_path):
    isolate_state_monkey = _monkey(tmp_path)
    _write_state(tmp_path, [
        _receipt("2601.01011", "noul", {"true": 0.05, "false": 0.95}),  # bin 0, observed 0
        _receipt("2601.01012", "noul", {"true": 0.15, "false": 0.85}),   # bin 1, observed 1
        _receipt("2601.01013", "noul", {"true": 0.55, "false": 0.45}),    # bin 5, observed 1
    ], [])
    _label_ledger([
        ("2601.01011", "skip", "checkbox"),
        ("2601.01012", "keep", "cli-keep"),
        ("2601.01013", "read-later", "slack-reaction"),
    ])
    report = _calibrate(tmp_path)
    bins = report.metrics["reliability"]["noul"]
    assert [b["bin"] for b in bins] == ["[0.0,0.1)", "[0.1,0.2)", "[0.5,0.6)"]
    assert bins[0]["observed"] == 0.0 and bins[1]["observed"] == 1.0 and bins[2]["observed"] == 1.0


def test_precision_at_5_and_probe_lift(tmp_path):
    _monkey(tmp_path)
    # a real run posts at most `top` (5) picks — survivors and probe rescues share the slots
    journal = [
        _journal([_cand("2601.01011"), _cand("2601.01012"), _cand("2601.01013"),
                  _cad_probe("2601.01015"), _cad_probe("2601.01016"),
                  _cand("2601.01017", posted=False)]),
    ]
    _write_state(tmp_path, [], journal)
    _label_ledger([
        ("2601.01011", "keep", "cli-keep"),
        ("2601.01012", "discussed", "slack-reply"),
        ("2601.01015", "keep", "slack-reaction"),   # probe rescue kept
    ])
    report = _calibrate(tmp_path)
    p = report.metrics["precision_at_5"]
    assert p["n"] == 5  # a run posts at most 5
    assert p["precision"] == round(3 / 5, 4)  # kept ∪ discussed among them
    lift = report.metrics["probe_lift"]
    assert lift["probe_rescue_n"] == 2
    assert lift["rescue_keep_rate"] == 0.5
    assert lift["survivor_n"] == 3
    assert lift["survivor_top5_keep_rate"] == round(1 / 3, 4)  # one keep of three survivors
    assert "zero rescues" in lift["lexical_zero_baseline"]


def _cad_probe(arxiv: str) -> dict:
    return _cand(arxiv, pool="probe", rescued="probe")


def test_planted_staged_audit_failure_surfaces(tmp_path):
    _monkey(tmp_path)
    vault = tmp_path / "vault" / "papers"
    vault.mkdir(parents=True)
    (vault / "s.md").write_text(
        '---\ntype: paper\narxiv: "2601.01007"\nstatus: staged\ntags: [poisonedterm]\n---\n'
        "body mentioning poisonedterm only"
    )
    (vault / "p.md").write_text('---\ntype: paper\narxiv: "2601.01001"\ntags: [leakedterm]\nwhy: "x"\n---\n')
    # plant the gate bug itself: contributes_taste returns True for everything
    from arjev.config import Config as C
    from arjev.fold import PaperNote, fold_roots

    original = PaperNote.contributes_taste
    PaperNote.contributes_taste = property(lambda self: True)
    try:
        cfg = C()
        cfg.roots = [str(tmp_path / "vault")]
        report = calibrate(cfg, fold_roots(cfg.expanded_roots, cfg))
        assert any("staged gate leak" in v and "poisonedterm" in v for v in report.staged_audit)
    finally:
        PaperNote.contributes_taste = original


def test_calibrate_never_writes_config(tmp_path):
    _monkey(tmp_path)
    config = tmp_path / "arjev.toml"
    config.write_text(f'[vault]\nroots = ["{VAULT}"]\n')
    from arjev.config import load_config
    from arjev.fold import fold_roots

    cfg = load_config(config)
    before = config.read_bytes()
    calibrate(cfg, fold_roots(cfg.expanded_roots, cfg))
    assert config.read_bytes() == before, "calibrate recommends; it never edits config"


def test_weak_negatives_reported_separately_and_censoring_named(tmp_path):
    _monkey(tmp_path)
    _write_state(tmp_path, [], [])
    _label_ledger([
        ("2601.09999", "unsaved-weak-negative", "vault-unsaved"),
        ("2601.09998", "skip", "checkbox"),
    ])
    from arjev.config import Config as C
    from arjev.fold import fold_roots

    cfg = C()
    cfg.roots = [str(VAULT)]
    report = calibrate(cfg, fold_roots(cfg.expanded_roots, cfg))
    notes = " ".join(report.notes)
    assert "unsaved-weak-negatives: 1" in notes and "explicit skips" in notes
    assert "censoring" in notes
    # the weak negative did NOT enter the Brier classes (no receipts/labels overlap here anyway)
    assert report.metrics["brier"]["noul"]["n"] == 0


def test_metrics_emitted_at_least_four(tmp_path):
    _monkey(tmp_path)
    report = _calibrate(tmp_path)
    assert set(report.metrics) == {"brier", "reliability", "precision_at_5", "probe_lift"}
    assert len(report.metrics) >= 4


def _calibrate(tmp_path):
    from arjev.config import Config as C
    from arjev.fold import fold_roots

    cfg = C()
    cfg.roots = [str(VAULT)]
    return calibrate(cfg, fold_roots(cfg.expanded_roots, cfg))


def _monkey(tmp_path):

    class _M:
        def setenv(self, key, value):
            import os

            os.environ[key] = value

    isolate_state(_M(), tmp_path)
    return None




def test_cli_calibrate_json_smoke(tmp_path, capsys, monkeypatch):
    isolate_state(monkeypatch, tmp_path)
    config = tmp_path / "arjev.toml"
    config.write_text(f'[vault]\nroots = ["{VAULT}"]\n')
    from arjev.cli import main

    rc = main(["calibrate", "--config", str(config), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert set(parsed["metrics"]) >= {"brier", "reliability", "precision_at_5", "probe_lift"}

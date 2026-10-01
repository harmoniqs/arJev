"""Profile tests: decay, tag/token weights, staged gate, degraded flag, the audit."""

from datetime import date
from pathlib import Path

from arjev.config import Config
from arjev.fold import fold_roots
from arjev.profile import DEGRADED_MIN_NOTES, build_profile, profile_flag, staged_audit

VAULT = Path(__file__).parent / "fixtures" / "vault"
TODAY = date(2026, 10, 1)


def build():
    return build_profile(fold_roots([VAULT], Config()), Config(), TODAY)


def test_staged_untouched_note_contributes_no_terms():
    profile = build()
    # the staged stub's distinctive term must be absent (the gate is real)
    assert profile.weight("seeded") == 0.0
    assert profile.weight("stub") == 0.0


def test_decay_half_life():
    from arjev.profile import _decay

    assert _decay(date(2026, 9, 25), TODAY, 180) == 0.5 ** (6 / 180)
    assert _decay(None, TODAY, 180) == 1.0  # ladder exhausted → weight 1
    profile = build()
    assert profile.weight("control-noise") > 0


def test_discriminator_tag_is_not_taste():
    profile = build()
    assert profile.weight("paper") == 0.0


def test_tags_outweigh_body_tokens():
    profile = build()
    # 'blockade' is a deliberate tag on 2601.01002; body tokens weigh less per occurrence
    assert profile.weight("blockade") >= profile.weight("radius")


def test_degraded_flag_rules():
    fold = fold_roots([VAULT], Config())
    assert len(fold.papers) >= DEGRADED_MIN_NOTES
    profile = build()
    assert profile.degraded is False, "fixture vault has >=5 notes and why-lines — must be ok"
    assert profile_flag(profile) == "ok"


def test_thin_fold_is_degraded(tmp_path):
    for i in range(3):
        (tmp_path / f"n{i}.md").write_text(
            f'---\ntype: paper\narxiv: "2601.0100{i}"\ntitle: "t{i}"\ntags: [qec]\n---\nbody'
        )
    profile = build_profile(fold_roots([tmp_path], Config()), Config(), TODAY)
    assert profile.degraded is True
    assert profile_flag(profile) == "profile-degraded"


def test_staged_audit_catches_a_real_leak(tmp_path):
    # a good note legitimately carries leakytag; the untouched staged stub is distinctive
    (tmp_path / "s.md").write_text(
        '---\ntype: paper\narxiv: "2601.01007"\nstatus: staged\ntags: [seededstub]\n---\n'
        "body about the seededstub only"
    )
    (tmp_path / "p.md").write_text('---\ntype: paper\narxiv: "2601.01001"\ntags: [leakytag]\nwhy: "x"\n---\nbody')
    cfg = Config()
    fold = fold_roots([tmp_path], cfg)
    # simulate the gate bug the audit exists to catch: a profile built WITH the stub
    poisoned = fold_roots([tmp_path], cfg)
    for n in poisoned.papers:
        if n.status == "staged":
            n.touched = True
    profile = build_profile(poisoned, cfg, TODAY)
    violations = staged_audit(fold, profile)
    assert any("leaked" in v and "seededstub" in v for v in violations)


def test_staged_audit_clean_on_fixture():
    fold = fold_roots([VAULT], Config())
    profile = build_profile(fold, Config(), TODAY)
    assert staged_audit(fold, profile) == [], "shared generic words must not false-positive"

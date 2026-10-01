"""Fixture sanity (spec: the failopen fixture vault has >= 5 notes including >= 1
why-bearing note; the posted-state fixture matches the incumbent schema exactly)."""

import json
from pathlib import Path

import yaml

FIXTURES = Path(__file__).parent / "fixtures"
VAULT_PAPERS = FIXTURES / "vault" / "papers"


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_fixture_vault_meets_fold_requirements():
    notes = sorted(VAULT_PAPERS.glob("*.md"))
    assert len(notes) >= 5
    fms = [frontmatter(p) for p in notes]
    assert any(fm.get("why") for fm in fms), "fixture vault needs a why-bearing note"
    assert any(fm.get("rating") in {"core", "useful", "marginal"} for fm in fms)
    assert all(fm.get("type") == "paper" for fm in fms)
    assert all(fm.get("arxiv") for fm in fms)


def test_fixture_vault_covers_backcompat_and_fallback_cases():
    fms = {frontmatter(p)["arxiv"]: frontmatter(p) for p in VAULT_PAPERS.glob("*.md")}
    assert "2601.01002" in fms and fms["2601.01002"].get("relevance") == "marginal"
    assert isinstance(fms["2601.01003"].get("relevance"), str) and len(fms["2601.01003"]["relevance"]) > 20
    assert not any(k in fms["2601.01006"] for k in ("date_read", "date"))


def test_posted_state_fixture_matches_incumbent_schema():
    state = json.loads((FIXTURES / "posted-state.json").read_text())
    assert set(state) == {"posted", "updated"}
    assert all(isinstance(i, str) for i in state["posted"])

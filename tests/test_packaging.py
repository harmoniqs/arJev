"""Packaging invariants: the version has exactly one source, pyproject.toml."""

import tomllib
from pathlib import Path

import arjev

REPO = Path(__file__).resolve().parents[1]


def test_version_is_single_sourced_from_pyproject():
    # two hand-synced copies (pyproject + __init__) drifted twice in v0.5.x;
    # __init__ now reads the installed metadata, so a release bumps one line
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert arjev.__version__ == pyproject["project"]["version"]
    init = (REPO / "src" / "arjev" / "__init__.py").read_text()
    assert pyproject["project"]["version"] not in init  # no literal copy to drift

"""arJev — a daily arXiv digest engine that ranks against a living Obsidian vault.

The brand is arJev (capitalized J, mirroring arXiv); identifiers (package, CLI,
config paths) are lowercase arjev — the same convention arXiv itself uses."""

from importlib.metadata import PackageNotFoundError, version

# the version lives in exactly one place — pyproject.toml — and is read from the
# installed package's metadata; two hand-synced copies drifted twice in v0.5.x
try:
    __version__ = version("arjev")
except PackageNotFoundError:  # a bare source tree with no install
    __version__ = "0+unknown"

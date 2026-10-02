"""Doc-command lint (issue #58): every `arjev …` command in the docs — fenced
code-block lines and inline code spans — must exist verbatim in the shipped CLI
surface: subcommand and flags both. The argparse tree arjev.cli.main builds IS
what `arjev --help` prints, so validating against it is validating against the
help output. Docs may lag code only by this slice's merge, never the reverse —
this lint is the enforcement."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from arjev.cli import main

REPO = Path(__file__).resolve().parents[1]
DOCS = [REPO / "README.md", REPO / "CONTEXT.md", *sorted((REPO / "docs").rglob("*.md"))]

# a documented command: a fence line leading with arjev (shell prompts allowed),
# or an inline code span opening with it — `arjev.toml`/`arjev-digest.timer`
# have no space after the word and correctly never match
_FENCED = re.compile(r"^\s*(?:\$\s+)?arjev\s+(.+?)\s*$")
_INLINE = re.compile(r"`arjev\s+([^`]+?)`")


def _commands(text: str) -> list[str]:
    """Every arjev command a doc documents: fence lines inside ``` blocks + inline spans."""
    inside = False
    found = []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside and (match := _FENCED.match(line)):
            found.append(match.group(1))
    return found + _INLINE.findall(text)


def _shipped_surface(monkeypatch) -> argparse.ArgumentParser:
    """The parser main builds, captured at its single parse_args call — by then
    every subparser is registered, so the tree equals the help output's source."""
    captured = {}

    def spy(self, *args, **kwargs):
        captured["parser"] = self
        raise SystemExit(0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    with pytest.raises(SystemExit):
        main(["--version"])
    return captured["parser"]


def _subcommands(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _flags(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings}


def _drift(command: str, root: argparse.ArgumentParser) -> str | None:
    """The first way a documented command has drifted from the shipped surface,
    as a human-readable complaint; None when the command is verbatim-shipped.
    Walks the tree exactly as argparse would: a non-flag token under a parser
    with subparsers must name one (else unknown subcommand); under a leaf
    parser it is a positional value and none of the linter's business."""
    parser = root
    for token in command.split():
        if token.startswith("-") and len(token) > 1:
            if token.split("=", 1)[0] not in _flags(parser):
                return f"unknown flag {token.split('=', 1)[0]!r}"
        elif _subcommands(parser):
            if token not in _subcommands(parser):
                return f"unknown subcommand {token!r}"
            parser = _subcommands(parser)[token]
    return None


def test_the_lint_bites(monkeypatch):
    """Guard the guard: a doc that ships an unshipped verb or flag is reported —
    a lint that cannot fail is not a lint."""
    root = _shipped_surface(monkeypatch)
    assert _drift("telepath", root) is not None
    assert _drift("digest --not-a-flag", root) is not None
    assert _drift("keep 2610.01234", root) is None
    assert _drift("rate accept 2610.01234 core", root) is None
    assert _drift("--version", root) is None


def test_extraction_finds_fenced_and_inline_commands_not_names():
    """The extractor sees fence lines and inline spans — and never command-shaped
    noise (comments inside fences, `arjev.toml`-style identifiers)."""
    text = (
        "# title\n"
        "\n"
        "```bash\n"
        "arjev digest --feed econ.TH\n"
        "# a comment mentioning arjev retired-verb is not a command line\n"
        "```\n"
        "\n"
        "prose with `arjev staged` inline, plus `arjev.toml` and `arjev-digest.timer`.\n"
    )
    assert _commands(text) == ["digest --feed econ.TH", "staged"]


def test_every_documented_command_is_shipped_verbatim(monkeypatch):
    """The invariant itself: nothing in the docs names an arjev verb or flag the
    CLI does not ship. Failure output lists every drift, doc by doc."""
    root = _shipped_surface(monkeypatch)
    documented = [(doc, command) for doc in DOCS for command in _commands(doc.read_text())]
    assert documented, "the lint must find commands to lint — extractor or doc drift"
    drift = [
        f"{doc.name}: arjev {command} → {_drift(command, root)}"
        for doc, command in documented
        if _drift(command, root)
    ]
    assert not drift, "documented commands the CLI does not ship:\n" + "\n".join(drift)

# AGENTS.md

Instructions for AI agents working on the arJev codebase. If you are here to
**install arJev for a person**, stop and follow
[docs/agent-setup.md](docs/agent-setup.md) instead.

arJev is a Python 3.11+ CLI: a daily arXiv digest ranked against an Obsidian
vault, with an optional Slack surface. Runtime dependencies are PyYAML, httpx,
and pypdf; nothing else.

## Commands

```bash
uv sync --extra dev                           # set up the environment
uv run --extra dev pytest                     # the full suite (~10 s, no network)
uv run --extra dev pytest tests/test_slack.py -k who_line   # one area
uv run --extra dev ruff check .               # lint (CI runs exactly this)
uv run arjev --help                           # the CLI from the working tree
```

CI (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` on Python 3.11.
Both must pass before a merge.

## Layout

| Path | What lives there |
|---|---|
| `src/arjev/cli.py` | every verb: argparse tree + dispatch; nothing else |
| `src/arjev/config.py` · `init.py` | the TOML config and the commented starter config `arjev init` writes |
| `src/arjev/feed.py` | arXiv RSS fetch and parse (author names are split here) |
| `src/arjev/fold.py` · `profile.py` · `directives.py` | the vault scan, the taste profile, and taste directives |
| `src/arjev/score.py` · `rank.py` · `rerank.py` · `jev.py` | lexical scoring, ranking, the Jev layer, and the digest journal |
| `src/arjev/digest.py` · `render.py` | one digest run and its sinks (stdout, vault note, Slack) |
| `src/arjev/affil.py` | the who-line: affiliations parsed from a paper's own PDF |
| `src/arjev/slack.py` · `ingest.py` | the Slack client, pick rendering, reaction harvest; seeding from BibTeX/PDFs/Slack |
| `src/arjev/keep.py` · `labels.py` · `ledger.py` · `state.py` | keeps, the label ledger, posted ids |
| `src/arjev/paper_content.py` | PDF text extraction and the library |
| `src/arjev/calibrate.py` · `review.py` · `rate.py` | calibration, the week-in-review, rating proposals |
| `src/arjev/daily.py` | `arjev daily`: the scheduled run and its retry/weekend rules |
| `src/arjev/inspect.py` · `sanitize.py` · `latex.py` | config verification, fixture sanitizing, LaTeX → Unicode |
| `tests/` · `tests/fixtures/` | the suite; recorded, sanitized fixtures (never live data) |
| `contrib/` | systemd and launchd units that run `arjev daily` |
| `scripts/` | `brand.py` regenerates `docs/brand/`; `capture_fixtures.py` records fixtures (networked, maintainer-only) |
| `docs/` | user docs, [ADRs](docs/adr/), [history](docs/history/) |

## Invariants — do not break these

1. **The tool never writes prose.** Note bodies and why-lines come from an
   agent or a person; arJev renders deterministically and Jev only makes typed
   decisions ([ADR 0001](docs/adr/0001-vault-generation-is-the-agents-contract.md)).
2. **Never edit an existing note.** arJev writes new files only. The single
   exception is `arjev rate accept`, which a human invokes.
3. **Never default a category.** Empty `feeds` blocks the digest with an error
   naming the slot.
4. **Attribution is printed or curated, never inferred.** Affiliations come
   from the paper's own PDF and are never bound to an author; groups come only
   from the roster ([ADR 0002](docs/adr/0002-at-digest-time-affiliations-ride-from-the-papers-own-pdf.md)).
5. **External seams fail open.** A Jev, PDF, or enrichment failure degrades
   that feature and the run continues; the `mode:` line says what ran.
6. **State lives under XDG state** (`~/.local/state/arjev/`), never in the
   vault or a repo. Tests isolate it automatically (`tests/conftest.py`).
7. **Secrets never touch config or the repo.** Keys and tokens come from env
   vars or mode-600 files (`ARJEV_JEV_KEY_FILE`, `ARJEV_SLACK_TOKEN_FILE`).
8. **Persisted schemas are frozen.** Journal rows, the label ledger, and posted
   state keep bare arXiv ids; extend with new fields, never change existing ones.
9. **The Slack content boundary.** Posts carry feed-derived text, printed
   affiliations, curated roster labels, and matched terms only — never vault
   paths, note filenames, or a note's `why` text.

## How to change things

- **Test first.** Write the failing test, then the code. Tests exercise public
  behavior; network calls go through injectable seams (`SlackClient(transport=…)`,
  `http_transport=`, `pdf_fetcher=`, `JevClient` stubs), never real services.
- **The docs lint is real.** `tests/test_docs_commands.py` checks that every
  arjev command shown in `README.md`, `CONTEXT.md`, `AGENTS.md`, and `docs/`
  exists in the CLI, verb and flags. Add the flag before you document it, and
  never put a placeholder verb inside a code span.
- **Docs have one job each.** `README.md` is for a human deciding whether to use
  arJev; setup steps go in `docs/setup.md` (human) and `docs/agent-setup.md`
  (agent); how it works goes in `docs/architecture.md`. New domain terms go in
  `CONTEXT.md`; hard-to-reverse decisions get an ADR in `docs/adr/`.
- **Record user-visible changes** in `CHANGELOG.md` with the release that ships them.

## Releasing

1. Bump `version` in `pyproject.toml` — the only place it lives (`arjev.__version__`
   reads the installed metadata; `tests/test_packaging.py` enforces this).
2. Add the `CHANGELOG.md` entry.
3. Open the PR, wait for CI to pass, merge.
4. Tag the **merge commit on `main`** and push the tag:
   `git tag vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`. Never tag before the
   merge lands — a tag on an unmerged branch ships an install without the fix.

## External behavior worth knowing

Lessons from live runs that the tests now pin:

- arXiv RSS puts **all authors in one comma-joined field**; `feed.py` splits it.
- arXiv publishes **no new listings on Saturday or Sunday**; empty weekend
  feeds are expected (`daily.py`).
- arXiv RSS is **occasionally empty mid-day on weekdays**; retry, don't alarm.
- Slack's read methods (`reactions.get`, `conversations.replies`) **ignore JSON
  bodies**; every call is form-encoded (`slack.py`).
- Slack needs a channel **ID**, not a name, for history and ingest.
- No external index (arXiv API, Semantic Scholar, INSPIRE, OpenAlex) carries
  affiliations on publication day; the paper's PDF is the only source.

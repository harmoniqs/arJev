# ADR 0002: At-digest-time affiliations ride from the paper's own PDF

## Status

Accepted — 2026-10-21.

## Context

The who-line (the pick message's author-and-attribution line) needs
affiliations at digest time — within hours of the arXiv announcement. An
empirical probe on 2026-10-21 found no external source that carries them
there: the arXiv RSS, abs page, and export API carry none at all (0 of 25
probed papers), Semantic Scholar and INSPIRE-HEP index same-week papers but
with empty affiliation fields until curators process them (days later), and
OpenAlex has not indexed a two-day-old paper yet. The only same-day source
of affiliations is the paper's own PDF, where the authors printed them.

## Decision

The who-line resolves each pick's PDF (library cache first, else a paced
fetch stored in the library) and parses the printed affiliations as a
deduped, paper-level set — never bound to individual authors, and dropped
entirely for that pick when the author block parses ambiguously (fail-open
to authors-only). Author→group binding exists only for tracked people, from
curated roster labels, never from parsing or inference. This carries a
standing constraint from the 2026-10-02 roster audit: attribution in arJev
is either the paper's own printed claim or human curation — never graph or
model inference, after coauthor-graph-derived lab attributions turned out
to be real people with wrong labs.

## Alternatives considered

### Scholarly-graph APIs (Semantic Scholar, OpenAlex, INSPIRE-HEP)

Rejected on measured coverage — empty or unindexed at digest time — and on
doctrine: their author-institution links are disambiguation inferences, the
exact attribution-failure class the 2026-10-02 audit cut. Revisit only for
retrospective surfaces (a paper indexed weeks later), never the digest.

### Roster-only (no affiliations for non-tracked papers)

Rejected as too thin: it answers "is this my people" but leaves the common
case — a strong paper from a group Aaron doesn't track — with no
institution context at the moment he reacts to the pick.

## Consequences

- The digest gains one paced network seam per pick (≤ 5 fetches/day),
  fail-open by construction; `who_style = "authors"` keeps it opt-in for
  pip-installers.
- The parse must stay conservative: ambiguity degrades to authors-only,
  never to a guess. A parser that starts binding names to institutions
  would reintroduce the failure this decision exists to prevent.

# arJev v0.5.0

**The one-line version:** the who-line — every pick now carries who wrote the
paper: authors, affiliations, and tracked-people hits, so the reaction moment
(👍/❌) finally shows *whose* work is being judged.

## What's new

**The who-line (issue #87).** Each Slack pick message gains a `_who:_` line
between the title and the why-line:

- authors as the feed reports them — first three plus `+N`
- tracked-people hits always pulled in, even beyond the first three, each
  rendered `⭐ Name (Group)` from the roster's curated group label
- affiliations as the paper's own PDF prints them — a deduped paper-level set,
  never bound to individual authors, capped at four with `+k`

Attribution doctrine (ADR 0002): at digest time no external source carries
affiliations — the arXiv API returned 0/25 in our probe, Semantic Scholar and
INSPIRE index same-week but with empty fields, OpenAlex lags by days — so the
only same-day source is the paper's own PDF. The parse is conservative by
construction: ambiguity degrades to authors-only, never to a guess, and a
degraded who-line never blocks the post. The 2026-10-02 roster-audit constraint
stands: attribution is the paper's printed claim or human curation, never
graph or model inference.

**Roster group labels (issue #87).** Directives `authors:` entries may carry a
group — `authors: ["M. Lukin — Harvard-Lukin"]` — display-only; the matching
rule (surname + first-initial) ignores the suffix, and scoring is unchanged.

**New config slot.** `[slack] who_style = "full" | "authors" | "none"` —
default `authors` (the PDF fetch stays opt-in for pip-installers); `full`
resolves each pick's PDF through the library-cached fetch, so a later
`arjev fetch` on a kept pick is a no-op. The vault digest note carries the same
attribution block per pick; the digest header gains a nonzero-only roster-hit
count; journal/state schemas are untouched.

## Prior art and doctrine

- ADR 0002 — *At-digest-time affiliations ride from the paper's own PDF* (with
  the empirical source probe and the no-binding rule)
- `CONTEXT.md` — the who-line glossary entry

# CONTEXT

arJev's domain language. This file is a glossary and nothing else: each term
below is settled, and terms resolve here as they land in the product — not
before. No implementation detail lives here.

## Glossary

- **adoption** — Mapping an existing Obsidian vault to arJev's config so its
  paper notes feed the taste profile; the agent does the mapping, and
  `inspect` proves it landed.
- **vault generation** — The writing of note prose into the vault (paper-note
  bodies, why-lines); it is the agent's contract because the decision model is
  text-free by design, and the tool never writes prose.
- **checklist-file** — The init-written config template: the single authoring
  surface where every decision slot carries its own explanation — the file is
  the setup checklist.
- **staged** — The status of a kept paper's scaffold note: metadata only,
  awaiting prose.
- **written** — The status of a staged note after the agent (or a human hand)
  writes its body; a written note's body feeds taste.
- **inspect** — The read-only verification verb: it prints the checklist state
  and what the config actually sees, and exits nonzero when blocked.
- **taste card** — One kept paper as the Jev state rides it under the
  budget-greedy policy: the note's why plus the paper's own abstract and
  conclusions excerpts, weighted by the note's decay and rating.
- **budget-greedy** — The state-assembly policy where directives ride whole
  and taste items fill the byte budget by recency-weighted priority; the
  incumbent fixed-count policy is `fixed-15`.
- **backfill** — The explicit, paced fetch of every corpus paper's PDF (plus
  extracted text) into the library; the digest itself never fetches corpus
  content, so the fold stays local and deterministic.
- **finalist enrichment** — The candidate-half content arm: after the first
  scoring pass, the top finalists are re-scored with their fetched
  conclusions/outlook in the state; fail-open, cached, never in the library.

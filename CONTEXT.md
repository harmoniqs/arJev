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

# The Amicode integration — the two-way seam, and who generates what

arJev's core is deliberately **text-free**: digest rendering is deterministic, the
label ledger and journal are mechanical records, and Jev — the decision model —
can only pick from pre-declared options with calibrated confidence. **It cannot
generate strings.** That is a safety property (nothing in the ranking loop can
fabricate), and it draws a clean division of labor:

**The decision model judges, your agent writes, the vault stays yours.**

Prose is valuable but optional, and it rides **two seams, both filled by the
agent** (or a human hand — same contract, slower traversal):

- **Enrich (digest out)** — prose appended *to* the digest.
- **Write (vault in)** — prose written *into* the vault's staged notes.

## What arJev does alone (every public user)

- Folds the vault into a taste profile; ranks the multi-feed union; explains every
  pick with matched terms; scaffolds keeps into staged notes; harvests labels;
  calibrates honestly. All deterministic + one decision model. No LLM required.

## Seam 1: `enrich_command` — prose on the digest (out)

Configure a command and arJev pipes one JSON document to its stdin:

```toml
enrich_command = "your-command"
```

- the stdin payload:

```json
{
  "mode": "mode: jev, ok",
  "picks": [{"arxiv": "2609.26880", "score": 883.8, "terms": ["control", "bosonic"], "rescued": null}],
  "titles": {"2609.26880": "Bosonic Error Correction with Fluxonium"}
}
```

- The command's stdout (capped at 4 KB) is appended to the digest.
- A missing, failing, or slow command **never breaks the digest** — it just ships
  without prose. Run it with `arjev digest --enrich`.

**Any LLM CLI can fill the seam.** A one-line wrapper around any API works. The
contract is stdin JSON in, markdown out.

## Seam 2: writing the vault — the staged → written contract (in)

The richer path is not the digest at all. Every kept paper is scaffolded into the
vault as a note with `status: staged` — metadata only, contributing zero taste
until prose exists. **Writing that prose is the agent's contract** (the model
can't, the tool won't):

1. **Pull the worklist** — `arjev staged` lists exactly the staged notes, one
   stable line each: `id | title | kept-when | kept-by`.
2. **Fetch the paper** — `arjev fetch <id>` downloads the arXiv PDF into the
   configured `library_dir`.
3. **Write the note** — a summary body in the agent's own words, plus the
   one-line `why:` in the frontmatter (the taste signal). This is an ordinary
   vault edit, subject to the normal human review — not digest decoration.
4. **Flip the status** — `status: staged` → `status: written` in the frontmatter.
   There is no tool verb for the flip, by design: it is an ordinary edit the
   human reviews in git, and arJev holds only the worklist and the verification.

**Check:** the note leaves the `arjev staged` worklist; `arjev inspect` shows
`fold staged:` counting down; the written body feeds taste exactly like a
hand-authored note's — the learning loop closes through this seam.

The full loop, agent-operated: seeding (`arjev ingest` from Slack, BibTeX, PDF
folders), schema adoption (`arjev inspect` proving the mapping), rating
proposals review (`arjev rate`), the weekly calibration read-through and
threshold application, feed curation — the runbook in
[agent-setup.md](agent-setup.md) is written for exactly that agent.

## The design lines that make this safe

- **Jev never generates** — ranking, rescue, rating proposals: all typed decisions
  with calibrated confidence, all logged as receipts. Prose comes only through
  the two seams, where the source is explicit and the output is capped (enrich)
  or human-reviewed (write).
- **The vault is never silently edited** — staged stubs are new files; ratings land
  only through the human `accept` gate; agent-written bodies and status flips are
  ordinary vault edits a human reviews in git.
- **The pen stays with the agent** — `arjev staged` is a pull-shaped worklist, not
  a write path. The tool never writes note bodies; it holds the worklist and the
  verification (`arjev inspect`), never the pen. The doctrine is recorded in
  [ADR 0001](adr/0001-vault-generation-is-the-agents-contract.md).
- **Fail-open everywhere** — no Jev key, no Slack token, no enrich command: the
  digest still ships, and the mode line says exactly what ran.

# The Amicode integration — prose, the enrichment seam, and who generates what

arJev's core is deliberately **text-free**: digest rendering is deterministic, the
label ledger and journal are mechanical records, and Jev — the decision model —
can only pick from pre-declared options with calibrated confidence. **It cannot
generate strings.** That is a safety property (nothing in the ranking loop can
fabricate), and it draws a clean line for the Amicode relationship:

## What arJev does alone (every public user)

- Folds the vault into a taste profile; ranks the multi-feed union; explains every
  pick with matched terms; scaffolds keeps into staged notes; harvests labels;
  calibrates honestly. All deterministic + one decision model. No LLM required.

## The seam: `enrich_command`

Prose — a take on today's picks, a one-paragraph summary per paper — is valuable
but optional. It is a **separable seam**, fail-open by construction:

```toml
enrich_command = "your-command"
```

- arJev pipes one JSON document to the command's stdin:

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

## What Amicode adds (first-party)

Amicode users should not wrap an API — their agent *is* the prose engine:

1. **Digest takes.** Point `enrich_command` at an amico invocation that writes the
   take (the agent reads the pick JSON, produces 3–5 sentences, done).
2. **Paper summaries.** The richer path is not the digest at all — the Amicode
   agent writes `## Summary` sections into the staged stubs it just scaffolded,
   with the paper's abstract already in hand. The vault note becomes complete
   before the human even opens it. That is vault-native generation, subject to the
   normal human review, not digest decoration.
3. **The whole loop, agent-operated.** Seeding (`arjev ingest` from Slack, BibTeX,
   PDF folders), rating proposals review (`arjev rate`), the weekly calibration
   read-through and threshold application, feed curation — the runbook in
   [agent-setup.md](agent-setup.md) is written for exactly that agent.

## The design lines that make this safe

- **Jev never generates** — ranking, rescue, rating proposals: all typed decisions
  with calibrated confidence, all logged as receipts. Prose comes only through the
  enrichment seam, where the source is explicit and the output is capped.
- **The vault is never silently edited** — staged stubs are new files; ratings land
  only through the human `accept` gate; summaries written by the Amicode agent are
  ordinary vault edits a human reviews in git.
- **Fail-open everywhere** — no Jev key, no Slack token, no enrich command: the
  digest still ships, and the mode line says exactly what ran.

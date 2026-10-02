# ADR 0001: Vault prose generation is the agent's contract

## Status

Accepted — 2026-10-02.

## Context

arJev's decision model (Jev) never generates strings. That is the
anti-fabrication invariant from the v1 spec of record ([issue
#1](https://github.com/harmoniqs/arJev/issues/1)): every call the model makes
is a typed decision — rank, rescue, rate — and every string a user reads is
either vault content or deterministic rendering by code. Nothing in the
pipeline can fabricate prose, because nothing in the pipeline can write prose.

That leaves the vault's prose — paper-note bodies, why-lines, takes — without
an author inside the tool. Someone must write it: an LLM agent, or a human
hand. The question is whether the tool should *force* that someone to be an
agent (a gate), *be* that someone itself (a wizard), or *route* to that
someone (a contract the agent fulfills). Getting this wrong cuts both ways: a
tool that writes its users' notes silently edits their vault, and a tool that
refuses to run without an agent is unusable by the person who just pip
installed it.

## Decision

Vault prose generation is the agent's contract — not a gate the tool enforces,
and not a surface the tool owns. The CLI keeps deterministic, headless
primitives and stays scriptable; the agent runbook is the only documented path
for vault prose bootstrap. A human hand following the same runbook is the same
contract, traversed slower. The *why* is capability, not policy: the decision
model is text-free by design, so prose must come from an LLM agent or a human
hand — and the tool never writes note bodies.

## Alternatives considered

### Hard technical gate — refuse agentless generation

Rejected. A gate the tool cannot verify is unfalsifiable for a public Apache
tool: there is no way to check, from inside the tool, that the thing on the
other end is an agent. Worse, the constraint it would police is a capability
fact — the decision model cannot write prose — not an access policy, and a
gate would promise enforcement the code cannot deliver.

### CLI interview wizard

Rejected. A wizard is always the worse interview: the agent runbook is the
blessed path, and a wizard would compete with it — two interviewers, two
authoring flows, drifting apart. The no-wizard invariant (judgment lives in
the runbook; the CLI stays headless and cron-able) predates this decision, and
the doctrine inherits it.

### Typed init flags

Rejected. Flags can only carry simple values, and the remapping knobs cannot
fit in flags, so authoring would split across two surfaces — flags for the
simple settings, file edits for the rest — duplicating the config schema into
CLI code. The config file is the single authoring surface (the
checklist-file), and this doctrine keeps it that way.

## Consequences

- The agent runbook carries the prose loop explicitly; the tool never writes
  note bodies, and the write-safety invariants are untouched.
- Agentless users lose nothing: a human hand can do everything an agent can,
  slower, and everything cron-able stays cron-able.
- Any future text-shaped surface must route the same way — hand the prose to
  an agent or a human, never to the decision model — so this decision governs
  more than the surfaces that exist today.

## The three tests

- **Hard to reverse.** The contract shapes every downstream surface — the
  runbook, the checklist-file, the staged/written status vocabulary, the
  enrichment seam. Reversing it means either teaching the decision model to
  generate strings (breaking anti-fabrication) or building the wizard this
  decision forgoes.
- **Surprising without context.** "The tool never writes prose" reads as a
  missing feature until the capability fact is known: the decision model is
  text-free *by design*, as a safety property. Without this ADR, the doctrine
  looks like an omission; with it, the omission is the point.
- **Real trade-off.** The doctrine forgoes a wizard (a friendlier first-run
  experience for the hand user) and forgoes a gate (a hard boundary for
  operators who want one). What it buys is one authoring surface, one
  interview path, and a vault nobody's tool edits silently.

# arJev v0.3.0

**The one-line version:** arJev now serves any arXiv-served field by default instead of
presuming one lab's physics vault, the generation loop (keep → write → learn) is a
first-class verb surface, and the config file became a self-explaining checklist.

## Behavior changes — read before upgrading

**1. Neutral defaults: the feeds list is now empty.**
In v0.2.x, a config that never set `feeds` silently digested `quant-ph` — a hardcoded
category fallback. v0.3.0 defaults `feeds` to `[]`, and unconfigured feeds block plainly:

- `arjev digest` exits with an error that names the fix: `feeds not configured — set
  feeds = ["<arXiv category>", …] in arjev.toml` — arJev ranks only what you configure
  and never defaults to a category.
- `arjev inspect` prints `blocked: no feeds configured` and exits nonzero.

**If you relied on the v0.2.x default, add `feeds = ["quant-ph"]` (or your own
categories) to `[vault]` in your `arjev.toml`.** arJev never silently ranks a category
you didn't choose.

**2. `arjev init` refuses to rewrite an existing config.**
v0.2.x init overwrote `arjev.toml` unconditionally. v0.3.0 writes only where no config
exists and exits nonzero when one is already there.

**3. The init template is now the checklist-file.**
The config init writes is fully commented — every decision slot (feeds, note type,
identity fields, taste knobs) carries its own one-line explanation — and field-neutral:
zero lab names, `feeds` starts empty with a pointer to the arXiv category taxonomy, and
the note-schema mapping ships with three complete remap examples (a physics vault, a
Zotero-style vault, an econ vault). A successful init is provably runnable: the
`--smoke-feed-file` pass digests through the written config itself.

## New verbs

**`arjev inspect`** — the read-only verification verb. It prints the checklist state
and exactly what the config sees in the vault — notes scanned, identity-bearing count,
fold warnings, directives, the staged count — and exits nonzero precisely when a
blocking condition holds: a closed set of no feeds, no roots, or zero identity-bearing
notes. It is the agent's acceptance check and the self-server's edit-verify loop, and it
never writes anything.

**`arjev staged`** — the prose worklist. It lists, read-only, the kept notes awaiting a
body (`status: staged`) — which closes the generation loop: keep scaffolds, the
worklist names what awaits prose, your agent (or your own hand) writes each note's body
and why-line, and flipping the status to `written` feeds taste exactly like a
hand-authored note.

## Internal, zero behavior change

**Feed items carry a normalized `(source, id)` identity**, populated once at parse, and
every join routes on the pair. Persisted records (journal rows, posted-state, label
ledger) keep the bare id — those schemas are frozen — and re-join through the arxiv
namespace. This is the seam a future source adapter implements; nothing user-visible
changes in v0.3.0.

## Docs

- **README restructured user-path-first** — "you already have a vault" / "you're
  starting fresh" / "no agent" as the three ways in, with the honest bound stated up
  front: arJev serves any field that posts to arXiv and sources nothing beyond arXiv.
- **`docs/agent-setup.md`** — the agent install runbook, now field-agnostic.
- **`docs/amicode-integration.md`** — the two-way agent integration contract (enrich:
  prose appended to the digest; write: prose written into staged notes) and who
  generates what: the decision model judges, the agent writes, the vault stays yours.
- **`CONTEXT.md`** — the repo's first domain glossary (adoption, vault generation,
  checklist-file, staged/written, inspect).
- **`docs/adr/0001-vault-generation-is-the-agents-contract.md`** — the doctrine on
  record: vault prose generation is the agent's contract, because the decision model is
  text-free by design — the tool never writes prose and never edits an existing note.

## Upgrade

```bash
uv tool install --reinstall git+https://github.com/harmoniqs/arJev@v0.3.0
arjev --version
# prints: arjev 0.3.0
```

Config format and CLI vocabulary are otherwise unchanged from v0.2.x; Python 3.11+.
The full verb surface: `arjev init`, `arjev digest`, `arjev keep`, `arjev fetch`,
`arjev staged`, `arjev inspect`, `arjev labels sync`, `arjev slack sync`,
`arjev ingest`, `arjev rate propose`, `arjev rate accept`, `arjev calibrate`.

# ADR 0003: arJev is the lab's paper engine — per-root schemas, write-through keeps

## Status

Proposed — 2026-10-25.

## Context

arJev was built to rank one researcher's feeds against one vault. A lab wants one engine informed by its shared knowledge: at Harmoniqs that is the company vault, which holds 109 paper notes (89 with arXiv ids, only 15 shared with the founder's personal vault) and 51 curated people cards. It cannot be read as-is: it was written before arJev existed and records `relevance:` (an enum, or a sentence) where arJev expects `rating:` and `why:`. Keeps scaffolded staged stubs that waited weeks for prose, and the host platform kept a second literature fold over the same corpus.

## Decision

arJev becomes the lab's paper engine and the source of truth for its literature. Each vault root may carry its own field mapping, so existing vaults fold without migration. Keeps write through to a configured target vault as complete notes: a configured writer command (an agent) authors the body in the same run, and the engine commits and pushes with keeper, run, and pick in the message — git history is the audit trail and the undo. Hosts consume a versioned corpus view; arJev never imports a host.

## Alternatives considered

### Migrate the company vault to arJev's schema

Rejected. It rewrites 109 notes to fit one tool, and every other lab adopting arJev would face the same migration. Per-root mapping is the general fix.

### Keep staged stubs for human completion

Rejected. The staged queue is where keeps went to wait; the host's companion decision (Amicode ADR 0036) retires the human promotion gate for the same reason.

### Let the host keep its own literature fold

Rejected. Two folds of one corpus, in two languages, drift into two answers.

## Consequences

- ADR 0001 stands: the tool never writes prose; the writer command is the agent seam, exactly like the enrichment hook.
- The "arJev writes new files only" invariant gains a git step: new files are committed and pushed, never silently left on disk.
- Single-root configs are unchanged, so existing users upgrade without touching their config.

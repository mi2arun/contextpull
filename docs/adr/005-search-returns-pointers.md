# ADR 005 — Search returns pointers and snippets, never bodies

**Status:** accepted · 2026-09-13

## Context
The central claim is that the model chooses what it reads. If `search` returned full sections, the tool would be push RAG with an extra step: top-k bodies land in context whether or not the model wanted them, tokens scale with k, and the trace no longer shows what the model actually consulted.

## Decision
`search` returns id, document, heading path, a short snippet and a score. `read` returns text. `grep` returns matching lines with ids. `neighbours` returns sections because its purpose is context around a section already chosen.

## Consequences
- One extra round trip for the common case of one hit. Accepted; `read(id, context=n)` recovers most of it.
- Token cost is proportional to sections read, not to k.
- The tool trace is a faithful record of what informed the answer; citations are exact.
- The model must be told the discipline; every tool description carries it.

## Alternatives
- **Return bodies for the top 1–3 hits.** Fewer round trips, but it reintroduces unrequested content and blurs the measurement of what the model chose.

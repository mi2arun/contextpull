# ADR 007 — Lexical retrieval first, embeddings optional

**Status:** accepted · 2026-09-13

## Context
In an agentic loop the model rewrites and narrows queries itself, which recovers much of what embeddings add to one-shot retrieval. The shapes that push RAG fails on hardest, exact lookup and table cells, are lexical problems. On the `uv` documentation ragbisect measured bm25 at recall@5 0.918 against dense at 0.903, and hybrid at 0.952. Embeddings require a provider, credentials and cost at ingest.

## Decision
FTS5 bm25 with an identifier-preserving tokenizer is the default and only required search mode. Embeddings are an opt-in ingest flag that enables `search(mode="hybrid")` through reciprocal rank fusion. Missing embeddings fall back to lexical with a note in the result.

## Consequences
- Ingest works offline and costs nothing by default.
- Conceptual questions phrased far from the document's vocabulary may need a second search; the loop is designed for that.
- Hybrid remains available where the corpus shows a gap, and ragbisect tells us where that is.

## Alternatives
- **Dense first.** Best one-shot conceptual recall, worst identifier recall, mandatory provider dependency.
- **Dense only.** Rejected for the same reasons, more strongly.

# ADR 002 — SQLite with FTS5 as store and lexical index

**Status:** accepted · 2026-09-13

## Context
We need durable storage for documents and sections, a lexical index good enough that `search` finds identifiers and headings reliably, and a deployment story that is one file. Python's `sqlite3` ships FTS5 with built-in bm25 ranking on the platforms we care about; verified on macOS with SQLite 3.53.

## Decision
One SQLite file in WAL mode holds documents, sections, an FTS5 virtual table with an identifier-preserving tokenizer, cached summaries, the index text, and optional embeddings as blobs. Read-only at query time.

## Consequences
- Zero dependencies, one file to copy, back up or build in CI.
- Search scales to hundreds of thousands of sections without an in-memory index.
- Heading-path weighting is one parameter of `bm25()`.
- FTS5 availability must be checked at startup with a clear error on exotic Python builds.
- Vector search past a few tens of thousands of sections needs sqlite-vec or a brute-force pass; acceptable because embeddings are optional.

## Alternatives
- **Pure-Python BM25 in memory** (what ragbisect uses). Fine for a benchmark, not for a server over a large corpus; slow startup, no persistence.
- **A vector database.** Dependency, process, and the wrong primary index: identifiers need lexical matching.
- **Postgres.** Right for the shared deployment at scale, wrong as the default; the default must be a file.

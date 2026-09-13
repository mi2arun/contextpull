# ADR 006 — Section ids are path plus ordinal, with a content hash

**Status:** accepted · 2026-09-13

## Context
Ids appear in citations, in tool arguments the model types, in stagewise gold labels, and in logs. They must be readable, stable for an unchanged document, and safe to resolve.

## Decision
`id = "<relative path>#<ordinal>"`, ordinal zero-based in document order. Each section also stores a sha256 of its text. Ids resolve only through the database.

## Consequences
- Readable in an answer: `[policy-2025.md#3]` tells a human where to look.
- Stable across re-ingest for unchanged documents; changed documents renumber and the hash exposes drift.
- No path traversal surface: the id is a key, not a path to open.
- Renaming a file changes every id in it. Acceptable; a rename is a corpus change.

## Alternatives
- **Content-hash ids.** Stable under reordering, but unreadable and they change on any edit, so citations rot faster, not slower.
- **UUIDs.** Unreadable and unstable across re-ingest.
- **Byte offsets.** Meaningless after any edit and unreadable.

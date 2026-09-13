# ADR 009 — The store file is the cross-language contract

**Status:** accepted · 2026-09-13

## Context
Custom clients will be written in TypeScript, Go, Java and others. Options were: force every language through the Python server as a sidecar; expose a C library over FFI; or make the SQLite store itself the interface and reimplement the small read side per language. The read operations are a few hundred lines; ingest is where the complexity lives.

## Decision
The versioned SQLite store format plus precisely specified operation semantics, `tools.json`, and an executable conformance suite form the contract. Readers may be implemented natively in any language with an FTS5-capable SQLite binding. Ingest stays in the Python reference implementation. The Python server remains available as a sidecar for languages without a native reader.

## Consequences
- `npx contextpull serve` and a Go single binary become possible without Python at query time.
- Search semantics must be pinned to the level of tie-breaking, which also makes the Python implementation more rigorous.
- Every tool change is a coordinated release across SDKs, by design.
- Regex grep and hybrid search are outside conformance because they depend on the host engine or an external model; the docs say so.
- Contributors can add a language by passing a suite instead of reading Python.

## Alternatives
- **Python sidecar only.** Zero duplication, but a second runtime in every deployment and no `npx` story.
- **Shared C core over FFI.** Maximum consistency, maximum build pain; SQLite already is the shared native layer.
- **gRPC or HTTP service as the only interface.** Fine for hosted use, wrong for embedded clients and offline tools.

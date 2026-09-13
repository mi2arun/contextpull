# Multi-language SDK plan

Custom clients are not all Python. Web backends are TypeScript, infrastructure teams write Go, enterprises run Java and C#. This plan says how ContextPull reaches them without forking the logic into five slowly diverging copies.

## The idea: the store file is the contract

ContextPull's core state is one SQLite file with FTS5. Every mainstream language has a mature SQLite binding with FTS5 compiled in: `better-sqlite3` for Node, `modernc.org/sqlite` or `mattn/go-sqlite3` for Go, `sqlite-jdbc` for Java and Kotlin, `Microsoft.Data.Sqlite` for .NET, `rusqlite` for Rust. The five read operations are a few hundred lines of SQL and glue each. Ingest, which carries the parsers and the summariser, stays in Python.

So the contract between languages is not a Python API. It is:

1. **The store format**, versioned, in [store-format.md](store-format.md).
2. **The operation semantics**, exact enough that two implementations return the same ids in the same order for the same call.
3. **The tool schemas**, `tools.json`, generated from Python and embedded verbatim by every SDK.
4. **A conformance suite**: a fixture corpus, its built store, and a list of calls with expected results. An SDK is done when it passes.

Anything that passes the suite can call itself a ContextPull reader. Benchmark numbers measured through one SDK then hold for all of them, because the ids and rankings are identical.

## Three ways to wrap, and when each applies

| Approach | What it is | Needs Python at query time | Fidelity | Use when |
|---|---|---|---|---|
| **Protocol client** | Talk to the Python server over MCP stdio or streamable HTTP | Yes, as a sidecar | Exact by construction | Any language, day one; hosted deployments |
| **Store-native reader** | Open the SQLite file directly and implement the five operations | No | Exact if the conformance suite passes | Embedded custom clients; `npx` distribution; single-binary servers |
| **CLI subprocess** | Spawn `contextpull search --json …` | Yes | Exact | Scripts and glue; never for interactive latency |

The protocol client is available to every language the moment M2 ships and needs no per-language work beyond an example. Store-native readers are the real SDK investment and are staged by demand.

## Tiers

### Tier 0 — every language, at M2

- The MCP server and streamable HTTP transport.
- Examples under `examples/clients/` for TypeScript, Go and Java showing a protocol client asking one comparison question. Each is under a hundred lines and uses that language's MCP client library or plain HTTP.
- `tools.json` published in the repo and in the Python wheel.

### Tier 1 — TypeScript, at M3

The most requested, because web clients and most MCP tooling are TypeScript, and because `npx contextpull` is the distribution people expect.

npm package `contextpull`:

- **Reader SDK.** `openStore(path)`, then `index`, `search`, `read`, `grep`, `neighbours` with the same names, arguments and return shapes as Python. Built on `better-sqlite3`, synchronous, no network.
- **Native MCP server.** `npx contextpull serve <store>` runs the five tools over the store with the official TypeScript MCP SDK. No Python at query time. Same instructions text, same index delivery rules as the Python server.
- **`npx contextpull ingest`** shells out to `uvx contextpull ingest` and says so, until a native ingest exists. Ingest is where the parsers live; duplicating them is the last thing we port, not the first.
- Framework adapters as separate small packages when asked: a LangChain.js retriever, a Vercel AI SDK tool set. Thin, and they call the reader SDK.

### Tier 2 — Go, at M4

For the shared, read-only deployment: one static binary serving the store over streamable HTTP, built in CI next to the store file.

Go module `github.com/<org>/contextpull-go`:

- Reader package with the five operations over `modernc.org/sqlite` (pure Go, FTS5 included, no cgo).
- `cmd/contextpull-server` speaking MCP streamable HTTP. Same instructions, same delivery rules.
- Read-only by design; ingest remains Python.

### Tier 3 — Java and Kotlin, C#, Rust, on demand

Each is a reader plus, optionally, a server. The conformance suite makes them tractable for outside contributors: the spec is executable. We publish the suite and a contributor guide, and accept an SDK into the org when it passes.

Framework adapters for Python itself, a LangChain `BaseRetriever` and a LlamaIndex `BaseRetriever`, are Tier 1 work in the Python package, gated on someone asking.

## What has to be nailed down for this to work

These are the places two implementations would drift. Each gets a precise definition in the system design and a conformance case.

| Concern | Definition |
|---|---|
| Query sanitisation for FTS5 | Tokenise the query with the same identifier-preserving regex used at ingest; each token becomes a quoted FTS5 string; join with `OR`. If two or more tokens, first run the exact phrase query and take its results in bm25 order, then append the `OR` query's results not already present. Both use `bm25(sections_fts, 2.0, 1.0)`. |
| Snippet | FTS5 `snippet()` over `text`, 20 tokens, `…` ellipsis, `**` markers. |
| Path filter | Each entry in `in` is matched with SQLite `GLOB` against `documents.path`; a filter without wildcard also matches as a prefix ending in `/`. |
| Grep | Case-insensitive substring via lower-case `instr`; regex per language's engine on the same candidate set, so regex results may legitimately differ by engine and the conformance suite only covers literal mode. |
| Index | Readers return `meta.index_text` verbatim; `index(prefix)` is computed from `documents` with the documented line format. |
| Table header recovery | Continuations of a split table are found by `kind = 'table'` and a shared heading path; the header is the first section of that run. |
| Ids and ordering | Ties broken by `id` ascending after rank. |
| Limits | The same defaults and caps in every SDK; caps live in `tools.json`. |

## Versioning across languages

- The store format has its own version, `schema_version` in `meta`, semver-like: major bumps mean old readers must refuse; minor bumps add columns or keys and old readers keep working.
- Each SDK declares the store major it supports and refuses others with a message naming both versions.
- `tools.json` carries a version; SDKs embed the file at build time, so a tool change is a release in every language, on purpose.
- The Python package is the reference implementation. When Python and an SDK disagree and both pass the suite, the suite is wrong and gets a new case.

## Conformance suite

Under `conformance/`:

- `corpus/` a small fixture: versioned policies, a spec sheet with tables, an errors reference with codes, a guide with deep headings.
- `store.sqlite` built from it by the reference implementation, checked in.
- `cases.json`: a list of `{op, args, expect}` where `expect` is ids in order, plus for `read` the text hash and for `index` the exact text.
- A runner per language that loads the store, executes each case, and diffs. The Python runner is the oracle and runs in CI on every change to `ops`.

## What we are not doing

- No native ingest outside Python before there is a user who cannot run Python at build time.
- No language-specific tool semantics. If TypeScript wants a sixth tool, Python gets it first and `tools.json` changes.
- No shared C library or FFI core. SQLite is already the shared native layer; a second one adds build pain for no gain.

## Sequence

1. M1: publish `store-format.md`, `tools.json`, and the first conformance cases with the Python oracle.
2. M2: protocol client examples in TypeScript, Go, Java.
3. M3: TypeScript reader and native server; the conformance runner in TypeScript.
4. M4: Go reader and single-binary server.
5. After: accept community SDKs that pass the suite.

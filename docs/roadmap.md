# Roadmap

Four milestones, each with an acceptance test that a cold reader can run. Order matters: the store must be right before the server, the server before the measurement.

## M1 — Core store and ingest · built 2026-09-13

- SQLite schema with migration table.
- Markdown and text parsing to blocks; heading-aware sectioning; tables and code kept whole.
- Stable IDs, content hashes, prev and next pointers.
- FTS5 index with identifier-preserving tokenizer.
- `ops.search`, `ops.read`, `ops.grep`, `ops.neighbours` as functions.
- Flat index with offline summaries; token budget enforced.
- CLI: `ingest`, `index`, `search`, `read`, `grep`, `export-chunks`.
- `tools.json` generated from the Python schemas; `store-format.md` published; first conformance cases with the Python oracle.

**Acceptance.** Ingest the `uv` docs (81 files). `search "UV_CACHE_DIR"` returns the cache section first. `read` of a table section returns the header row. Re-running ingest with no changes writes nothing and produces byte-identical index text. Unit tests for sectioning invariants.

**Result, 2026-09-13.** 81 documents, 604 sections, 0.3 s. No-change re-ingest: 0 writes, identical index. Table parts carry their header (tested on the fixture; the `uv` docs have no table over the size limit). Sectioning invariants: unit tests pass; 23 conformance cases pass. A broader campaign (adversarial inputs, 60 randomised seeds, CLI, concurrent reads during ingest, a 98k-section scale run, and a ragbisect quality measurement) is written up in [testing.md](testing.md); it found seven further bugs, all fixed. **One criterion not met as written:** `search "UV_CACHE_DIR"` ranks the concepts page third, behind two CI caching sections that also use the variable; bm25 prefers the shorter sections. The heading paths (`Caching > Cache directory` vs `Using uv in GitLab CI/CD > Caching`) let a model pick the right one from the pointers, which is the pull argument, but ranking a definition above a usage is open work: a summary or title column in the FTS table is the likely fix and is tracked for M2. Two bugs found and fixed by this run: fence info strings with attributes broke code-block detection, and `-` `.` as token characters made `--no-cache` and sentence-final words unsearchable until the indexed columns were normalised. The index went compact rather than flat at 81 documents with offline summaries, which led to the compact mode being added.

## M2 — MCP server and Claude Code · built 2026-09-13

- `contextpull[mcp]` extra with the official SDK. Five tools registered from shared schemas.
- Index delivered in server instructions when within budget; `index` tool and `contextpull://index` resource always.
- stdio transport. `claude mcp add contextpull -- uvx contextpull serve <corpus>` works.
- LLM summaries through the provider-agnostic wrapper, cached by document hash.
- Protocol client examples in TypeScript, Go and Java under `examples/clients/`.

**Acceptance.** In Claude Code, ask a comparison question over a two-version policy corpus. The trace shows `search` then two `read` calls and the answer cites both IDs. Ask about an identifier that appears in one section; `grep` finds it. In-memory MCP client tests for all five tools.

**Result, 2026-09-13.** Both acceptance runs passed through Claude Code headless (`claude -p … --mcp-config`) over the conformance corpus:

- Comparison question: two `search` calls scoped with `in=` to each year, three `read` calls, answer cites `[policies/policy-2024.md#2]` and `[policies/policy-2025.md#2]`. 7 turns, $0.33.
- Identifier question (TX-4419): `grep`, `read` with context, a second `grep`; answer cites `[errors.md#1]`. 5 turns, $0.23.

Nine MCP tests pass over in-memory streams and a real stdio subprocess, including tool errors that do not crash the server and `serve <directory>` ingesting first. LLM summaries: 81 of 81 `uv` docs summarised by gpt-5.4-mini for about 42k tokens; a re-run costs nothing; the flat index with summaries is ≈2,100 tokens. Protocol client examples run in TypeScript (official SDK), Go (official SDK) and Java (raw JSON-RPC); the direct API loop example answers the comparison question with two reads and two citations. Two bugs found and fixed: reasoning tokens consumed the summary completion budget and returned empty summaries (reasoning is now off for summaries and empty output falls back with the error recorded), and the default index budget of 2,000 tokens was 5% too small for 81 summarised documents (now 3,000). Open from M1: ranking a definition above a usage for identifier searches.

## M3 — Measurement · built 2026-09-14

- `contextpull.eval.ApiLoopRetriever`: direct API tool loop, returns section IDs read in order.
- `contextpull.eval.ClaudeCodeRetriever`: drives `claude -p` headless with the server attached, parses the trace.
- Cost and latency per query recorded alongside recall.
- `export-chunks` so the ragbisect eval set is built over ContextPull sections.
- TypeScript package: store-native reader, `npx contextpull serve`, conformance runner. **Built**: `sdk/typescript/`, 23/23 conformance, identical to Python over MCP.

**Acceptance.** ragbisect prints a table with bm25, dense, hybrid and agentic rows on the `uv` docs. Numbers are reproducible from the cache. The agentic row includes tokens and tool calls per query.

**Result, 2026-09-14.** Met, with two rows pending. The table in [testing.md](testing.md#m3-measurement) has bm25, dense, hybrid, and two agentic rows with tokens, tool calls and wall time per query, all reproducible from the adapter cache. **Corrected 2026-09-14** (the first agentic rows were invalid, see testing.md): pull with a no-reasoning small model reaches recall 0.615 over ids read with NDCG 0.964 given a hit and 2.7 tool calls a question; pull through Claude Code reads the right section on 10 of 10 sampled questions (recall 1.0) at about $0.30 a question; hybrid push is 0.964 at 61 ms and no model tokens. The strict-reads and surfaced-ids rows are pending on API credits. Also built in M3: ragbisect cost columns and `--sample`; the TypeScript store-native reader and server (23/23 conformance, identical to Python over MCP).

## M4 — Breadth and publication · in progress, 2026-09-14

- PDF ingest through the `pdf` extra; table detection in PDFs where the extractor exposes it. **Built** (headings from font size; no table detection or page numbers yet).
- Office files (docx, xlsx, pptx) with the standard library. **Built** 2026-09-14, prompted by an integrator's air-gapped document-intelligence PoC; with an [embedding guide](embedding.md) and an access-control example.
- Hierarchical index for corpora past the budget; `index(prefix)` drill-down. **Built in M1/M2** (flat, compact, hierarchical, budget always honoured).
- Optional embeddings and `search(mode="hybrid")`. **Built**, tested with a fake embedder; a real-provider run is pending on API credits.
- Streamable HTTP transport for the shared, read-only deployment. **Built** (`serve --transport http`), tested end to end with the SDK client.
- Go reader and single-binary server for the shared deployment. **Built** 2026-09-14: `sdk/go/`, 23/23 conformance, identical to Python over MCP, stdio and HTTP.
- Published benchmark across two or more corpora and all five question shapes, including cases where pull loses. **Partly**: ragbisect now generates all five shapes (comparison needs a model call per pair; aggregation and table are computed). The `uv` docs support only 5 structured questions (all table); the pydantic docs were added as the second corpus (10 unambiguous table questions, search 1.000 vs bm25 0.900; migration guide available for comparison once credits exist). Model-dependent shapes and the agentic rows on the second corpus need API credits.

**Acceptance.** A second corpus with tables and versioned documents supports all five shapes in ragbisect. The write-up names at least one shape or corpus where hybrid push is the better choice and says why.

## Later, only if M1–M4 land and people use it

- Reranking inside `search`.
- Watch mode: re-ingest on file change.
- Per-section access rules for the shared deployment.
- Java/Kotlin, C# and Rust readers as community SDKs that pass the conformance suite.

# Design document

## Problem

Teams put documents behind an LLM and get fluent answers that are sometimes wrong, with no error and no way to tell which part failed. The dominant pattern, retrieval-augmented generation, embeds the raw question, takes the k nearest chunks, and places them in the prompt before the model has reasoned about what it needs. It handles conceptual questions and little else. Exact identifiers blur in embedding space. Comparison questions produce a blend of both sources. Aggregations have no chunk that contains the answer. Table rows lose their headers to the chunker.

Claude Code demonstrates a different pattern on codebases. A small, always-present index tells the model what exists. The model decides what to look at, reads exact content through tools, refines, and only then writes. Nothing is pushed at it. Iteration replaces guessing.

ContextPull applies that pattern to arbitrary document corpora and packages it so that any host, or any custom client, can use it without a rewrite.

## Goals

1. **The model pulls, nothing pushes.** Content reaches the model only in response to a call the model made.
2. **Exact and citable.** Every piece of text returned carries a stable section ID. Answers cite IDs.
3. **Host-agnostic.** Works in Claude Code, in any MCP host, and inside a custom client through the same core.
4. **Install alongside anything.** Zero runtime dependencies in the core. One SQLite file as the store.
5. **Measured, not asserted.** The agentic configuration is scored with ragbisect on the same self-built eval set as bm25, dense and hybrid, and the results are published whether or not they flatter us.

## Non-goals

- Not a general RAG framework. No chains, no agents of our own, no prompt templates beyond the embedding recipe.
- Not a vector database. Embeddings are optional and stored in the same SQLite file only to support a hybrid `search` mode.
- Not a chat UI or a hosted service. The shared-store deployment is a flag on the same server, not a product.
- Not a document editor or a writer. Read-only over the corpus.
- No plugin system, no configuration DSL in v1.

## Principles

**Small surface.** Five tools. Their schemas are defined once and reused by the MCP server, the embedding recipe and the evaluation adapters. Adding a sixth tool needs a documented failure the five cannot cover.

**Search returns pointers, read returns text.** `search` never returns bodies. This keeps the model choosing, keeps token use proportional to what was actually needed, and makes the trace legible: you can see what the model looked at.

**Structure survives ingest.** Sections follow headings. Tables and code blocks are never split. Neighbours are one call away. A table row can always recover its header.

**Deterministic where possible.** Same corpus, same settings, same section IDs and same index text. Sectioning has no randomness. Summaries are cached by document hash so re-ingest is stable.

**Degrade honestly.** No LLM available: summaries fall back to first heading plus first sentence and the index says so. Corpus too big for the token budget: the index becomes hierarchical and says so. `search` finds nothing: the tool says so, and the model can say so.

**The measurement is the moat.** Everyone can build a tool server. Nobody publishes the comparison against the pipeline it replaces, across question shapes, with cost. We will.

## Key decisions

Each is expanded in a decision record under `adr/`.

| # | Decision | Chosen | Rejected |
|---|---|---|---|
| 001 | Language and dependency policy | Python, stdlib-only core, extras for MCP and PDF | TypeScript-first for npx convenience; a framework dependency for speed of build |
| 002 | Store and lexical index | SQLite with FTS5, one file | Pure-Python BM25 in memory; a vector DB; Postgres |
| 003 | Packaging of the pattern | Layered: core library, MCP server, embedding recipe | MCP server only; library only |
| 004 | Index delivery | Server instructions when it fits, `index` tool and resource always, hierarchical past budget | A `CONTEXTPULL.md` written into the project; index tool only |
| 005 | Search contract | IDs, heading paths, snippets, scores; no bodies | Return top-k bodies for fewer round trips |
| 006 | Section identity | `path#ordinal` plus content hash | Content-hash IDs; UUIDs; byte offsets |
| 007 | Retrieval modes | Lexical first via FTS5 bm25; embeddings optional for hybrid | Dense-first; dense-only |
| 008 | Evaluation | ragbisect as the harness, agentic row in the same table, losses published | Custom benchmark; anecdotal demos |
| 009 | Other languages | The SQLite store is the contract; native readers per language, ingest stays Python | Python sidecar only; C core over FFI; service-only interface |

## Alternatives considered at the product level

**Just write a Claude Code skill or CLAUDE.md instructions.** Tempting and cheap, but it only works in Claude Code, gives the model grep over raw files with no section structure and no citations, and cannot be measured against a push pipeline in a controlled way. ContextPull can produce a CLAUDE.md snippet as a convenience; it is not the product.

**Improve the push pipeline instead.** Hybrid retrieval and reranking do help; ragbisect showed hybrid beating dense on our test corpus. But the failure modes that matter most, comparison and aggregation, are about who controls retrieval, not about ranking quality. A better ranker still returns one list for a question that needs two.

**Build on an existing agentic RAG framework.** LlamaIndex and LangGraph have agentic retrieval. They bring a dependency tree that conflicts with whatever the user already runs, and they do not expose the corpus to an external host over MCP. The point of ContextPull is to install next to anything.

## Risks

| Risk | Mitigation |
|---|---|
| Large corpora overflow the index budget | Hierarchical index by directory; search-first guidance in instructions; measured in the scale tiers |
| Latency of several tool round trips | Acceptable for agent hosts; published as a cost column; `read` with `context` reduces calls |
| A weak `search` makes the loop weak | FTS5 bm25 with identifier-preserving tokenizer; optional hybrid; ragbisect measures `search` alone as a config |
| Hosts differ in whether instructions reach the system prompt | Index also exposed as tool and resource; instructions tell the model to call `index` first if it sees none |
| Prior art overlap | Differentiate on structure-preserving sections, citations, and published measurements |
| Single gold chunk in evaluation undercounts recall | Documented; identifier dedupe and rarity filter in ragbisect; misses dumped for inspection |

## What measurement has taught so far

- **Snippets leak.** With 20-token snippets, a small model answers from the search result on about a quarter of factoid questions instead of reading; prompt rules do not change this. Snippet size is a design lever, not a prompt lever (roadmap).
- **Reading is precise, recall is the problem.** When the small model reads, it reads the right section (NDCG 0.96 given a hit); Claude Code reads the right section every time. The pull pattern's quality is set by the model's decision to read, and the tool must make reading the cheapest good option.
- **Complex questions are where pull earns its cost.** Both models passed all six multi-section scenarios; on single-fact questions hybrid push is as good and a hundred times cheaper.
- **Duplicate content is the eval set's main distortion**, in both corpora: the same table or the same fact in several places makes any single gold arbitrary. ragbisect now skips repeated table keys and repeated identifiers; recall remains a lower bound.

## Success criteria for v1

- Ingest the `uv` documentation and one PDF-heavy corpus with no manual steps.
- Claude Code answers a comparison question with two correct citations, visible in the trace.
- The ragbisect table has an agentic row with recall, MRR, NDCG, tokens per query and tool calls per query, next to bm25, dense and hybrid, on at least two corpora and all five question shapes where the corpus supports them.
- At least one published case where pull does not beat hybrid, with the reason.

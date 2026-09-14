# ContextPull

**Website:** https://mi2arun.github.io/contextpull/ · [demo](https://mi2arun.github.io/contextpull/demo.html) · [docs](https://mi2arun.github.io/contextpull/docs/index.html)

Pull, don't push. ContextPull turns a folder of documents into something an LLM agent can pull from the way Claude Code pulls from a codebase: a small index that is always in context, and five tools that return exact sections on demand. The model never receives content it did not ask for.

Zero runtime dependencies. One SQLite file. Works offline.

ContextPull ships with a companion, [ragbisect](https://github.com/mi2arun/ragbisect) (formerly stagewise): a neutral benchmark harness that builds an eval set from your corpus and scores ContextPull next to bm25, dense and hybrid pipelines. Two names, one project, kept apart so the measurement stays independent of the thing it measures.

## Status

M1 to M3 are built: store, ingest, the five operations, CLI, conformance suite, MCP server, Claude Code integration, LLM summaries, protocol client examples, ragbisect adapters, and a TypeScript reader and server. See the [roadmap](docs/roadmap.md).

## Measured

uv documentation, 603 sections, 221 self-generated questions, recall@5, from [docs/testing.md](docs/testing.md#m3-measurement):

| config | recall@5 | ms/q | model tokens/q |
|---|---|---|---|
| hybrid push (dense + bm25) | 0.964 | 69 | 0 |
| bm25 push | 0.923 | 5 | 0 |
| **pull, Claude Code** (10-question sample) | **1.000** | 26,565 | 86,656 |
| pull, gpt-5.4-mini with reasoning off | 0.615 | 16,023 | 10,891 |

A strong agent reads the right section every time; a small no-reasoning model reads the right section when it reads (NDCG 0.96 given a hit) but misses the gold section on 38% of questions. Push retrieval is nearly free per query; pull costs tens of thousands of tokens. Both facts are in the table on purpose. The model's own searches surfaced the gold section on 88% of a sample, so most of the gap is snippets being answered from rather than read; a stricter prompt did not change that. An earlier version of this table showed 0.045 for the small model; that number came from a threading bug in the benchmark adapter and is retracted in `docs/testing.md`.

## Try it

Fastest: `./scripts/demo.sh` ingests the bundled fixture corpus and walks through index, search, read and grep, then prints the exact `claude mcp add` line. `./scripts/demo.sh ./your-docs` does the same on your own folder.

```sh
uv tool install contextpull            # or: pip install contextpull   (PyPI: contextpull 0.1.0)
contextpull ingest ./docs              # writes .contextpull/store.sqlite
contextpull index                      # the always-in-context table of contents
contextpull search "refund window" --in policy-2025.md
contextpull read policy-2025.md#3 --context 1
contextpull grep TX-4419
contextpull neighbours specs.md#1
contextpull export-chunks > chunks.jsonl   # ragbisect-compatible sections
```

## In Claude Code

```sh
claude mcp add contextpull -- uvx --from "contextpull[mcp]" contextpull serve ./docs
```

The server ingests `./docs` into `./docs/.contextpull/store.sqlite`, puts the index into its instructions so it is always in context, and exposes the five tools. Ask a question; the trace shows `search`, then `read`, then an answer with `[path.md#3]` citations. `contextpull claude-md` prints a CLAUDE.md snippet if you want to tell the model about it explicitly. Add `--summarizer openai:gpt-5.4-mini` for model-written one-line summaries in the index (cached by document hash).

Any other MCP host works the same way; see `examples/clients/` for TypeScript, Go and Java protocol clients and `examples/direct_api_loop.py` for using the tools straight from a model API with no server.

## More

```sh
uv sync --extra pdf                                             # PDFs: headings inferred from font size
uv run contextpull ingest ./docs --embed-model openai:text-embedding-3-small   # enables: search --mode hybrid
uv run contextpull serve ./docs --transport http --port 8765    # streamable HTTP at /mcp for a shared read-only server
```

## As a library

Embedding it in your own product, with access control and air-gap notes: [docs/embedding.md](docs/embedding.md) and `examples/embed_with_acl.py`.

```python
from contextpull import Store, Ops

with Store.open(".contextpull/store.sqlite") as store:
    ops = Ops(store)
    print(ops.index())
    hits = ops.search("refund window", in_=["policy-2024.md", "policy-2025.md"]).hits
    for h in hits:
        print(h.id, h.heading_path, h.snippet)
    section = ops.read(hits[0].id).section
```

Tool definitions for any model API are in `contextpull.tools.TOOLS` (Anthropic shape) and `openai_tools()`; `tools.json` at the repo root is the same thing for other languages.

## How it works

1. **Ingest** parses Markdown, text, docx, xlsx, pptx and (with the `pdf` extra) PDF into headings, paragraphs, tables and code, and cuts heading-aware sections with stable ids like `policy-2025.md#3`. Tables and code are never split mid-block; long tables are split by rows and every part carries the header. Unchanged files are skipped on re-ingest.
2. **Store** is one SQLite file with an FTS5 index whose tokenizer keeps identifiers whole (`--no-cache`, `UV_CACHE_DIR`, `TX-4419`, `3.12`).
3. **Index** is a token-budgeted table of contents, one line per document, delivered into the model's context. It goes hierarchical when a corpus is too large for the budget.
4. **Tools**: `index`, `search` (ids and snippets, never bodies), `read` (verbatim), `grep` (exact matches), `neighbours` (the header row, the next clause).

## Node

`sdk/typescript/` is a store-native reader and MCP server in TypeScript over `better-sqlite3`: open the same store file, no Python at query time. Published to npm as `contextpull`.

```sh
npx contextpull serve /path/store.sqlite                   # npm: contextpull 0.1.0
claude mcp add contextpull -- npx -y contextpull serve /path/store.sqlite
```

It passes the same conformance suite as the Python reference and returns identical results over MCP. Ingest stays in Python (`npx contextpull ingest` delegates to `uvx contextpull ingest`).

## Go

`sdk/go/` is a store-native reader and a single static binary server, pure Go, no cgo: the shape for a shared read-only deployment.

```sh
cd sdk/go && go build -o contextpull-server ./cmd/contextpull-server
./contextpull-server serve /data/store.sqlite --http 0.0.0.0:8765    # or without --http for stdio
```

Same conformance suite, identical results to Python over MCP.

## Other languages

The store file is the contract. `docs/store-format.md` says what a reader must do; `conformance/` holds a fixture corpus, its store and expected results. An SDK in any language is done when `check` passes. See the [SDK plan](docs/sdk-plan.md).

## Docs

Start at [docs/README.md](docs/README.md): architecture, design, system design, tool reference, evaluation, roadmap, decision records.

Measured with [ragbisect](https://github.com/mi2arun/ragbisect), which lives next door.

# ContextPull

Pull, don't push. ContextPull turns a folder of documents into something an LLM agent can pull from the way Claude Code pulls from a codebase: a small index that is always in context, and five tools that return exact sections on demand. The model never receives content it did not ask for.

Zero runtime dependencies. One SQLite file. Works offline.

## Status

M1 and M2 are built: store, ingest, the five operations, CLI, conformance suite, MCP server, Claude Code integration, LLM summaries, protocol client examples. Measurement (M3) is next. See the [roadmap](docs/roadmap.md).

## Try it

```sh
uv tool install contextpull            # or: pip install contextpull  (not yet published; use `uv run` from this repo)
contextpull ingest ./docs              # writes .contextpull/store.sqlite
contextpull index                      # the always-in-context table of contents
contextpull search "refund window" --in policy-2025.md
contextpull read policy-2025.md#3 --context 1
contextpull grep TX-4419
contextpull neighbours specs.md#1
contextpull export-chunks > chunks.jsonl   # stagewise-compatible sections
```

## In Claude Code

```sh
uv sync --extra mcp                                   # from this checkout, until it is on PyPI
claude mcp add contextpull -- uv run --project $(pwd) contextpull serve ./docs
```

The server ingests `./docs` into `./docs/.contextpull/store.sqlite`, puts the index into its instructions so it is always in context, and exposes the five tools. Ask a question; the trace shows `search`, then `read`, then an answer with `[path.md#3]` citations. `contextpull claude-md` prints a CLAUDE.md snippet if you want to tell the model about it explicitly. Add `--summarizer openai:gpt-5.4-mini` for model-written one-line summaries in the index (cached by document hash).

Any other MCP host works the same way; see `examples/clients/` for TypeScript, Go and Java protocol clients and `examples/direct_api_loop.py` for using the tools straight from a model API with no server.

## As a library

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

1. **Ingest** parses Markdown and text into headings, paragraphs, tables and code, and cuts heading-aware sections with stable ids like `policy-2025.md#3`. Tables and code are never split mid-block; long tables are split by rows and every part carries the header. Unchanged files are skipped on re-ingest.
2. **Store** is one SQLite file with an FTS5 index whose tokenizer keeps identifiers whole (`--no-cache`, `UV_CACHE_DIR`, `TX-4419`, `3.12`).
3. **Index** is a token-budgeted table of contents, one line per document, delivered into the model's context. It goes hierarchical when a corpus is too large for the budget.
4. **Tools**: `index`, `search` (ids and snippets, never bodies), `read` (verbatim), `grep` (exact matches), `neighbours` (the header row, the next clause).

## Other languages

The store file is the contract. `docs/store-format.md` says what a reader must do; `conformance/` holds a fixture corpus, its store and expected results. An SDK in any language is done when `check` passes. See the [SDK plan](docs/sdk-plan.md).

## Docs

Start at [docs/README.md](docs/README.md): architecture, design, system design, tool reference, evaluation, roadmap, decision records.

Measured with [stagewise](https://github.com/mi2arun/stagewise), which lives next door.

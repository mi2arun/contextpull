# Changelog

## 0.2.1 — 2026-09-14

- MCP Registry manifest (`server.json`) and package ownership markers (`mcp-name` in the README, `mcpName` in the npm package). No code changes.

## 0.2.0 — 2026-09-14

### Added
- Office ingest: docx, xlsx, pptx with the standard library (Word heading styles, lists and tables; Excel sheets as pipe tables; PowerPoint slides as sections).
- PDF ingest through the `pdf` extra, headings inferred from font size.
- Hybrid search: `ingest --embed-model` stores per-section vectors; `search(mode="hybrid")` fuses lexical and dense by reciprocal rank.
- Streamable HTTP transport: `serve --transport http`.
- Go SDK (`sdk/go`): store-native reader and single static server binary, stdio and HTTP, 100% conformance.
- TypeScript SDK on npm as `contextpull`: store-native reader and server.
- `contextpull.eval`: ragbisect adapters for the direct-API tool loop and Claude Code headless, with strict and surfaced-ids variants.
- Scenario test layer: a six-format corpus, ten complex use-case tests, a 27-case scenario conformance suite run by Python, Node and Go, and a live agent scenario runner.
- Embedding guide with an access-control example; `claude-md` command; `CONTEXTPULL_EVAL_DEBUG` tracing.
- Benchmarks on two corpora under `benchmarks/`, including the retraction of the first agentic rows.

### Fixed
- Eval adapter used one SQLite connection across threads; every tool call failed and the failure was fed to the model as tool output. Runs whose tool calls all fail are now marked as errors and never cached.
- Fence info strings with attributes broke code-block detection.
- `-` and `.` as token characters made `--no-cache` and sentence-final words unsearchable; indexed columns are normalised.
- Grep pre-filtered with the word index and could not find substrings inside tokens.
- Index budget enforced in every mode; compact mode added between flat and hierarchical.
- Sectioner: word-boundary splitting, headings always followed by content, merges re-pack and cannot loop.

### Changed
- Default index budget 3,000 tokens. `search` runs three passes: phrase, all words, any word.

## 0.1.0 — 2026-09-14
First release: core store, ingest, five operations, MCP server over stdio, LLM summaries, conformance suite, protocol client examples.

# ContextPull documentation

ContextPull turns a folder of documents into something an LLM agent can pull from the way Claude Code pulls from a codebase: a small index that is always in context, and tools that return exact sections on demand. The model never receives content it did not ask for.

This set is the source of truth for what we are building. Read in order the first time.

| Document | What it answers |
|---|---|
| [Architecture](architecture.md) | What the parts are, how data flows, where the boundaries sit |
| [Design document](design.md) | Why it exists, goals and non-goals, principles, the decisions and the alternatives we rejected |
| [System design](system-design.md) | Data model, section IDs, ingest pipeline, index construction, tool contracts, delivery into hosts, scale tiers, failure modes, security |
| [Tool reference](tool-reference.md) | The five tools, argument by argument, with examples |
| [Evaluation](evaluation.md) | How we measure it with ragbisect, and what we publish, including losses |
| [Roadmap](roadmap.md) | Four milestones with acceptance criteria |
| [Multi-language SDK plan](sdk-plan.md) | How TypeScript, Go, Java and others get ContextPull without forking the logic |
| [Store format contract](store-format.md) | The rules a reader in any language must follow |
| [Testing](testing.md) | Test layers, scale and quality results, bugs the campaign found |
| [Decision records](adr/) | One page per irreversible-ish decision |

## One-paragraph summary

A corpus is ingested once into a single SQLite file: documents, heading-aware sections with stable IDs, an FTS5 full-text index, and a cached one-line summary per document. A compact table of contents built from those summaries is delivered into the model's context. The model then calls `search`, `read`, `grep` and `neighbours` to fetch exactly the sections it decides it needs, verbatim, with IDs it can cite. The same core is exposed three ways: as a Python library for teams building their own client, as an MCP server for any open host, and as an embedding recipe for direct API use. Claude Code is the development client. ragbisect is the measuring instrument, and the agentic configuration goes in the same table as bm25, dense and hybrid.

## Status

M1 (core, CLI, conformance) and M2 (MCP server, Claude Code integration, LLM summaries, protocol client examples) built; M3 (measurement) next. Name checked free on PyPI, npm and GitHub on 13 September 2026.

## Vocabulary

- **Document**: one source file, identified by its path relative to the corpus root.
- **Section**: a heading-delimited, size-bounded piece of a document. The unit of retrieval and citation.
- **Section ID**: `path#ordinal`, e.g. `policy-2025.md#3`.
- **Index**: the always-in-context table of contents, budgeted in tokens.
- **Host**: the program running the model and holding the MCP connection. Claude Code, Claude Desktop, Cursor, or a custom client.
- **Push / pull**: push is classic RAG, top-k chunks placed in the prompt before the model thinks. Pull is the model requesting content after it thinks.

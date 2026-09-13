# ADR 003 — Layered surfaces: library, MCP server, embedding recipe

**Status:** accepted · 2026-09-13

## Context
Prospective users split three ways: teams that want their own client and will embed the capability; teams that use an open host such as Claude Code, Claude Desktop or Cursor and want a server to attach; and teams that call model APIs directly and want the tools in their own loop. We develop with Claude Code.

## Decision
The core library owns the store, the operations and the tool schemas. The MCP server is a thin wrapper over the operations. The embedding recipe is documentation plus one runnable example using the same schemas. All three surfaces share one definition of each tool.

## Consequences
- A custom client is a `pip install` and five function calls, no server process.
- Any MCP host works without host-specific code beyond index delivery (ADR 004).
- The evaluation adapters use the same tool definitions as production, so the benchmark measures what ships.
- The core cannot import the MCP SDK; it is an extra.

## Alternatives
- **MCP server only.** Simplest, but excludes the custom-client segment and forces a process boundary onto embedders.
- **Library only.** Excludes open hosts, where most early adoption will come from.

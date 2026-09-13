# ADR 001 — Python with a stdlib-only core

**Status:** accepted · 2026-09-13

## Context
The core will be imported into other people's applications and run next to whatever retrieval stack they already have. The evaluation harness, stagewise, and its chunker, tokenizer and LLM wrapper are Python. MCP hosts commonly launch servers with `npx`, which favours TypeScript for distribution.

## Decision
Python 3.10+. The core package has zero runtime dependencies. The MCP SDK and pypdf are optional extras (`contextpull[mcp]`, `contextpull[pdf]`). Distribution through `uvx contextpull`, which Claude Code and other hosts launch as readily as `npx`.

## Consequences
- Reuse of stagewise code and one language across tool and benchmark.
- Every dependency conflict in a host application is avoided for library users.
- HTTP is done with `urllib`; JSON with `json`; storage with `sqlite3`. Slightly more code, no supply chain.
- An npm wrapper can be added later without touching the core.

## Alternatives
- **TypeScript first.** Better `npx` story, but splits the codebase from the benchmark and loses the existing corpus code.
- **Allow a small framework dependency.** Faster to build, but the tool is supposed to install alongside anything; a pinned pydantic or httpx is exactly the conflict we want to avoid for library users.

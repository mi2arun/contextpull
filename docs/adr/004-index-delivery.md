# ADR 004 — Index delivered through server instructions, with tool and resource fallback

**Status:** accepted · 2026-09-13

## Context
The pattern depends on the model knowing what exists before it decides what to read. In Claude Code that role is played by files loaded into the system prompt. MCP servers can return `instructions` at initialize, which Claude Code and Claude Desktop inject into the system prompt. Not every host does, and a large corpus cannot fit any budget.

## Decision
The index is delivered three ways from one cached text: in server `instructions` when it fits the token budget (default 3,000); as an `index` tool always; as resource `contextpull://index` always. Past the budget, instructions carry a hierarchical directory listing and tell the model to call `index(prefix)` to expand. Custom clients call `ops.index()`.

## Consequences
- In Claude Code the index is genuinely always in context with no user-visible file.
- Hosts that ignore instructions still work; the tool descriptions tell the model to call `index` first if it sees no index.
- Budget is a first-class setting and the index header states its mode, so behaviour is never mysterious.
- Hierarchical mode adds a round trip for large corpora; measured in the scale tiers.

## Alternatives
- **Write a `CONTEXTPULL.md` into the project and reference it from `CLAUDE.md`.** Works only in Claude Code, leaves generated files in the user's repo, drifts from the store. Offered as an optional convenience snippet, not the mechanism.
- **Tool only.** Costs a round trip on every conversation and depends on the model remembering to call it.

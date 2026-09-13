# ADR 008 — Measure with stagewise and publish the losses

**Status:** accepted · 2026-09-13

## Context
Agentic retrieval is easy to demo and hard to prove. Prior art shows demos. Buyers and contributors will ask how it compares to a tuned hybrid pipeline, on what question shapes, at what cost. We already own an instrument that answers exactly that.

## Decision
Every performance claim about ContextPull is a stagewise row next to bm25, dense and hybrid, on the same sections (via `export-chunks`), the same eval set and the same k, with tokens, tool calls and wall time as columns. Results and caches are committed under `benchmarks/`. Write-ups name where pull loses.

## Consequences
- Development has a number to move from week three.
- Two adapters to maintain, one through the API and one through Claude Code headless.
- The positioning is honesty; a flattering-only benchmark would undercut it.
- stagewise's own limits, single gold chunk in particular, are inherited and stated.

## Alternatives
- **A custom benchmark.** Duplicates work and invites the suspicion that it was designed to be won.
- **Demos and anecdotes.** What everyone else does.

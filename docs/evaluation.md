# Evaluation

The claim is that pulling beats pushing on the question shapes that matter, at a cost we can state. A claim like that needs the same eval set, the same metrics and the same table for both. ragbisect already does that for push configurations. This document says how the pull configuration joins the table.

## What ragbisect provides

- An eval set built from the corpus with no hand labelling, in all five shapes: conceptual and exact-lookup from one chunk each via a model; comparison from cross-document near-duplicate pairs, phrased by a model, gold is both chunks; aggregation over identifier families and table cells, computed with no model at all. `--shapes` selects; shapes a corpus cannot support are skipped with a reason.
- Stage metrics: recall@k, MRR@k, NDCG@k conditioned on a hit, faithfulness by LLM judge.
- Built-in push configurations: bm25, dense, hybrid with reciprocal rank fusion.
- A one-method adapter protocol: `retrieve(query, k) -> list[str]` of chunk ids.
- Cached LLM calls, seeded sampling, printed spend.

## Aligning the units

ragbisect scores chunk ids. ContextPull returns section ids. They must be the same ids or the comparison is meaningless.

`contextpull export-chunks` writes `{"id", "text", "source"}` lines for every section in the store. ragbisect takes that file as its corpus, so the eval set's gold ids are ContextPull section ids, and the built-in push configurations are indexed over exactly the same sections. Sectioning quality is then held constant across all rows; only the controller differs.

## Two agentic adapters

### `contextpull.eval.ApiLoopRetriever`

Runs a tool loop through the Anthropic or OpenAI API using `contextpull.tools.TOOLS` and `ops` directly, no server process.

- System prompt: the pull discipline and the index, exactly as the MCP server would deliver them.
- Loop: model call, execute tool calls against the store, append results, repeat until the model answers or `max_turns` (default 8).
- `retrieve(query, k)` returns the section ids the model **read**, in the order it read them, truncated to k. Ids that only appeared in `search` results do not count; the model did not look at them.
- Records per question: tool calls by name, input and output tokens, wall time, and the final answer text for faithfulness judging.

### `contextpull.eval.ClaudeCodeRetriever`

Drives Claude Code headless with the MCP server attached, the faithful measurement of the development client.

- Invocation: `claude -p "<question>" --mcp-config <generated json> --output-format stream-json` with a system prompt appendix asking for ids in the answer.
- Parses the stream for `tools/call` events to the ContextPull server and collects `read` ids in order.
- Slower and costlier than the API loop; run on a sample, report both.

## What counts as retrieved for a pull configuration

The first agentic run over the `uv` docs exposed a choice that the design had left implicit. With the default prompt, gpt-5.4-mini averaged 3.6 `search` calls and 0.46 `read` calls per question and answered more than half the questions from search snippets alone, never reading a section. The answers were often right; the snippet of a section whose heading matches the question frequently contains the fact. So "ids the model read" understates what the model was shown, and "ids surfaced by search" overstates what it chose.

We report both, as separate rows, and name them:

| row | `retrieve` returns | measures |
|---|---|---|
| **pull, ids read** | sections the model called `read` on, in order | the discipline the design asks for: verbatim evidence before answering |
| **pull, ids surfaced** | ids read, then ids seen in `search` and `grep` results, in order | what the model was shown; comparable to a push top-k list |
| **pull, strict reads** | ids read, under a prompt that forbids answering from snippets and citing unread ids | whether the discipline can be enforced by prompt alone, and what it costs in turns and tokens |

The gap between the first two rows is a measurement of snippet leakage. If it stays large, the remedy is in the tool, not the prompt: shorter snippets, or snippets that show heading path only. That is a design change to `search` and would be recorded in a decision record and a store-format bump.

`stats()` also reports `reads_per_query` and `answered_without_reading` so the write-up can state the behaviour, not just the recall.

## What goes in the table

| column | push rows | pull rows |
|---|---|---|
| recall@k, mrr@k, ndcg@k given hit | as today | over ids read |
| faithfulness | if the adapter has `generate` | the loop's final answer |
| tokens per query | embedding tokens | input + output across the loop |
| tool calls per query | 0 | count |
| wall time per query | ms | ms |

Reported overall and per question shape. The per-shape breakdown is where the argument lives: pull should win on comparison and aggregation and be close on conceptual; if it does not, that is the finding.

## Fairness rules

1. Same sections, same eval set, same k, same corpus fingerprint in every row.
2. The pull model gets no information the push pipeline could not have: the index is built from the same documents.
3. Push rows may use hybrid retrieval and a reranker if we add one. We compare against the best push configuration, not the weakest.
4. Costs are measured, not estimated, and printed by the same code path for all rows.
5. Every published number comes with the cache so it can be re-run.

## Known distortions, stated up front

- **Single gold chunk.** A question generated from one section may be answerable from another that says the same thing. ragbisect dedupes repeated identifiers and rejects very common ones; residual ambiguity makes recall a lower bound for all rows alike.
- **Reading is not answering.** A model can read the right section and still answer wrongly. Faithfulness covers part of this; answer correctness against the eval set's reference answers is a later addition.
- **Model dependence.** The pull row is a property of the model and the tools together. We name the model in every table.

## Publishing

Results live in `benchmarks/` as the ragbisect output, the eval set, the cache fingerprint and a short write-up per corpus. The write-up names the shapes and corpora where pull loses or costs more than it returns. That is the positioning, not a caveat.

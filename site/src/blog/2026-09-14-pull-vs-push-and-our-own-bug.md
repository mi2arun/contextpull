# We built a pull-based retrieval server, benchmarked it against hybrid RAG, and found our own bug

*ContextPull is an MCP server that lets a model pull exact document sections instead of being handed top-k chunks. ragbisect is the harness we built to measure it. This is what the numbers say, including the one we had to retract.*

## The idea

Classic RAG pushes: embed the question, take the k nearest chunks, stuff them into the prompt before the model has thought about anything. It works for conceptual questions and fails quietly on the rest. Exact identifiers blur in embedding space. Comparison questions return a blend of both documents. Aggregations have no chunk that contains the answer. Table rows lose their headers to the chunker.

Claude Code works the other way on codebases. A small index is always in context; the model decides what to look at, reads exact content through tools, refines, and only then writes. Nothing is pushed at it.

ContextPull applies that to any folder of documents. Ingest once into a SQLite file with FTS5: heading-aware sections with stable ids like `policy-2025.md#3`, tables and code never split, Word, Excel, PowerPoint and PDF included. A token-budgeted table of contents rides in the MCP server's instructions. Five tools: `index`, `search` (ids and snippets, never bodies), `read` (one section verbatim), `grep` (exact substrings, for the codes embeddings blur), `neighbours` (the table header, the next step). The model cites ids.

```sh
claude mcp add contextpull -- uvx --from "contextpull[mcp]" contextpull serve ./docs
```

Zero dependencies in the core. Readers in TypeScript (npm) and Go (one static binary) open the same file and pass the same conformance suite.

## Measuring it honestly

A claim like "pull beats push" needs the same eval set, the same metrics and the same table for both. ragbisect builds an eval set from the corpus itself, in five question shapes (conceptual, exact lookup, comparison, aggregation, table), scores retrieval and ranking separately, and compares any adapter with bm25, dense and hybrid pipelines on the same questions, with cost columns. ContextPull's agentic loop is just another row.

uv documentation, 603 sections, 221 questions, recall@5:

| config | recall@5 | ndcg given hit | model tokens / question | tool calls |
|---|---|---|---|---|
| hybrid push (dense + bm25) | 0.964 | 0.889 | 0 | 0 |
| ContextPull search, lexical | 0.927 | 0.879 | 0 | 0 |
| pull, Claude Code (10-question sample) | 1.000 | 0.913 | 86,656 | 4.8 |
| pull, gpt-5.4-mini, reasoning off | 0.615 | 0.964 | 10,891 | 2.7 |

Three things worth knowing:

1. **Hybrid push wins on recall and is a hundred times cheaper** for single-fact questions. We built the pull tool and we are telling you that.
2. **A strong agent reads the right section every time.** Claude Code searched, read the gold section and cited it on every sampled question, at about $0.30 each.
3. **A small model reads the right section when it reads.** Its NDCG given a hit is the best in the table. Its recall is 0.62 because on a quarter of questions it saw the right pointer in its own search results (surfaced-ids recall: 0.883) and answered from the 20-token snippet instead of reading. A stricter prompt changed nothing. The fix is in the tool, not the prompt: snippet size is now our top design item.

On complex questions the picture shifts. We built a scenario corpus in six formats with versioned policies, error-code references split across files, spec tables and a numbered procedure, and asked six multi-section questions: what changed between two policy versions, list every error code across two files, a table cell, the next step of a procedure, a spreadsheet lookup, a multi-hop reasoning question. Both models passed all six, reading two to six sections each and citing them. That is where pull earns its cost.

## The bug

Our first agentic rows said the small model reached recall 0.045: it read a section on one question in twenty. We published that. It was wrong.

The eval adapter opened its SQLite connection on the main thread while the harness called it from six worker threads. Python's `sqlite3` raised on every tool call, and our loop passed the error text back to the model as if it were tool output. The model never saw a search result. It was guessing section ids from the index.

We found it because the complex-scenario runs, which ran single-threaded, worked perfectly while the benchmark did not, and a per-call trace showed every tool returning an error. The fix is small. The lesson is not: a benchmark harness that silently turns infrastructure failures into model behaviour will produce a confident, wrong, publishable number. Ours now counts tool failures per record, refuses to cache a run whose tools all failed, and has a test that calls the adapter from a thread pool.

The retraction is in the repository next to the corrected numbers.

## What we would tell you to do

Use hybrid push for a chat product answering simple lookups; it is as good and far cheaper. Use pull where the question needs several sections or a verifiable citation, and where the agent is strong enough to read. Measure your own corpus and your own model before deciding: ragbisect does it in an afternoon, and it works against any OpenAI-compatible endpoint, including a local one.

- ContextPull: https://github.com/mi2arun/contextpull · https://mi2arun.github.io/contextpull/
- ragbisect: https://github.com/mi2arun/ragbisect
- Benchmarks, eval sets and the retraction: `benchmarks/` and `docs/testing.md`

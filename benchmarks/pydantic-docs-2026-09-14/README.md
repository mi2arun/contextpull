# pydantic docs benchmark, 2026-09-14

Corpus: `pydantic/pydantic` `docs/` (91 Markdown files, 802 ContextPull sections, offline summaries). Chosen as the second corpus because it has tables and a v1-to-v2 migration guide. All five shapes: 231 questions (126 conceptual, 92 exact-lookup, 10 table, 3 comparison; no digit-bearing identifier families for aggregation).

| file | what |
|---|---|
| `table-structured-shapes-search-vs-bm25.txt` | 10 table-cell questions; ContextPull `search` 1.000 recall@5, bm25 0.900 |
| `questions-table.jsonl` | the 10 table questions from the first, computed-only run |
| `questions-all-shapes.jsonl` | all 231 questions with gold section ids |
| `table-five-shapes-search-vs-builtins.txt` | ContextPull `search` 0.870 vs bm25 0.853, dense 0.844, hybrid 0.900; per shape |

What the run taught: the first attempt produced 24 questions with recall 0.50 for both configs, and every miss was a cell from the constraints table (gt, ge, lt, max_length …) that the docs repeat once per type. Those questions were answerable from ten sections, so the single gold was arbitrary. ragbisect now asks only about row keys that head rows in exactly one table; the honest count for this corpus is 10, and both lexical configs find them. No identifier families were detected: pydantic's error types (`string_type`, `missing`) carry no digits, and the family detector keys on digit patterns. That is a gap in the detector, noted in ragbisect's roadmap.

| `table-apiloop-sample60.txt` | pull, ids read, gpt-5.4-mini reasoning off, 60-question sample with the fixed adapter: 0.600 |

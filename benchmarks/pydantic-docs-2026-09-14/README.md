# pydantic docs benchmark, 2026-09-14 (partial: computed shapes only)

Corpus: `pydantic/pydantic` `docs/` (91 Markdown files, 802 ContextPull sections, offline summaries). Chosen as the second corpus because it has tables and a v1-to-v2 migration guide. Only the shapes that need no model were run; conceptual, exact-lookup and comparison wait on API credits.

| file | what |
|---|---|
| `table-structured-shapes-search-vs-bm25.txt` | 10 table-cell questions; ContextPull `search` 1.000 recall@5, bm25 0.900 |
| `questions-table.jsonl` | the questions, with gold section ids |

What the run taught: the first attempt produced 24 questions with recall 0.50 for both configs, and every miss was a cell from the constraints table (gt, ge, lt, max_length …) that the docs repeat once per type. Those questions were answerable from ten sections, so the single gold was arbitrary. ragbisect now asks only about row keys that head rows in exactly one table; the honest count for this corpus is 10, and both lexical configs find them. No identifier families were detected: pydantic's error types (`string_type`, `missing`) carry no digits, and the family detector keys on digit patterns. That is a gap in the detector, noted in ragbisect's roadmap.

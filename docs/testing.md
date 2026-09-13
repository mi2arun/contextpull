# Testing

What is tested, how, and what the M1 campaign found. Numbers are from 13 September 2026 on a 2019-era x86 MacBook with Python 3.12 and SQLite 3.53.

## Layers

| Layer | Where | What it guards |
|---|---|---|
| Unit | `tests/test_parse.py`, `test_section.py`, `test_store_ingest.py`, `test_ops.py` | Parser blocks, sectioning rules, store versioning, incremental ingest, every operation, tool dispatch |
| Adversarial | `tests/test_robustness.py::test_adversarial_corpus_ingests_without_crashing` | Empty, whitespace-only, binary, latin-1, CRLF, unclosed fence, table at EOF, table without body, six-level headings, 50k-char line, 2,000-section file, unicode filenames, hidden dirs, symlinks, duplicate basenames, shebangs and hashtags |
| Randomised invariants | `tests/test_robustness.py::test_sectionizer_invariants_on_random_markdown` (60 seeds) | Ordinals contiguous, heading paths non-empty, no partial fence, every table part carries its header, size limit respected except whole code blocks, table rows and single words, lossless modulo whitespace, deterministic |
| CLI and concurrency | `tests/test_cli_concurrency.py` | Every subcommand and its JSON output, exit codes, env var precedence, a reader running while ingest rewrites the store five times |
| Conformance | `conformance/run.py check` | 23 cases over a fixture store: the executable cross-language contract |
| Scale | `scripts/scale_test.py [n]` | Synthetic corpus, ingest throughput, store size, per-operation latency, identifier precision |
| Quality | `examples/ragbisect_adapter.py` with ragbisect | `search` as a one-shot retriever against ragbisect's bm25, dense and hybrid over the same sections |

## Scale results

Synthetic corpus, 20-word vocabulary so every common-word query matches nearly every section. This is the worst case for ranking; real corpora match far fewer rows.

| documents | sections | ingest | sections/s | no-op re-ingest | store size | index mode |
|---|---|---|---|---|---|---|
| 500 | 9,937 | 1.9 s | 5,200 | 0.13 s | 36 MB | hierarchical, 1,995 tokens |
| 5,000 | 98,366 | 20.6 s | 4,800 | 1.0 s | 354 MB | hierarchical, 1,998 tokens |

Latency at 98k sections, 300 calls each:

| operation | p50 | p95 |
|---|---|---|
| search, two common words | 184 ms | 212 ms |
| search, exact identifier | 0.3 ms | 0.5 ms |
| read | < 0.1 ms | 0.1 ms |
| grep, literal, whole corpus | 315 ms | see note |
| grep, literal, with `in=` filter | 8 ms | 21 ms |
| neighbours | 0.1 ms | 0.1 ms |
| index(prefix) | 2.0 ms | 2.4 ms |

Identifier search returned the exact section first in 200 of 200 tries.

**Grep is a full substring scan by design.** An earlier version pre-filtered candidates with the word index and ran in 0.1 ms, but it could not find `TX-45` inside `TX-4501`, which is the whole point of grep. The scan costs 315 ms (rare pattern) to 450 ms (common word) over 98k sections and 8 ms with a path filter; the tool description tells the model to pass `in=` on large corpora. A trigram FTS index would make substring grep fast at the cost of roughly 40% more store size and is the candidate optimisation if real corpora need it.

**The common-word search is over the 50 ms tier target.** The query matched 92,812 of 98,366 sections; FTS5 must score and sort all of them. Benchmarked variants on that store: the deterministic `ORDER BY rank, id` costs 230 ms against 95 ms for `ORDER BY rank` alone, and FTS5's rank-configuration optimisation did not beat it. Decision: keep the deterministic tie-break, because identical id lists across SDKs is the contract; document that latency scales with matched rows, not corpus size. Real corpora have vocabularies of thousands of words and matched sets in the hundreds. The three-pass query (phrase, AND, OR) was added during this campaign so the expensive `OR` pass runs only when stricter passes do not fill the limit.

Store size is about 3.6 KB per section, roughly twice the text: FTS5 keeps its own copy of the indexed columns for snippets plus the inverted index. Accepted for v1; a contentless FTS table would halve it at the cost of snippets.

## Quality results

ragbisect over the `uv` documentation, 604 ContextPull sections exported with `export-chunks`, 219 self-generated questions, k = 5, generation model gpt-5.4-mini.

| config | recall@5 | mrr@5 | ndcg@5 given hit | conceptual recall | exact-lookup recall |
|---|---|---|---|---|---|
| ContextPull `search` (lexical) | 0.927 | 0.777 | 0.879 | 0.906 | 0.956 |
| ragbisect bm25 | 0.922 | 0.785 | 0.889 | 0.914 | 0.934 |
| ragbisect dense | 0.918 | 0.791 | 0.897 | 0.938 | 0.890 |
| ragbisect hybrid RRF | 0.963 | 0.870 | 0.928 | 0.945 | 0.989 |

Reading: the identifier-preserving tokeniser and normalisation do what they were for, ContextPull's lexical search leads every single-mode config on exact lookups. It trails dense on conceptual questions by about three points, which is the case for the optional hybrid mode. Hybrid still wins overall, as it did on ragbisect's own chunks. This is a one-shot measurement of the `search` tool; the agentic loop that lets the model search twice is M3, and that is where the pull argument is actually tested.

## Bugs found by the campaign, all fixed

1. Fence info strings with attributes (`toml title="x"`) were not recognised as fence openers, so the closing fence opened a block that swallowed the next heading and table.
2. `-` and `.` as FTS token characters made `--no-cache` and every sentence-final word unsearchable. Indexed columns are now normalised; section text stays verbatim.
3. Offline summaries pushed an 81-document index past the budget straight to hierarchical mode. Compact mode was added.
4. The hierarchical index did not itself honour the budget at 5,000 documents. It now truncates the directory list and says how many were left out.
5. Oversized paragraphs were hard-cut mid-word. They now split at sentence and word boundaries.
6. A bare heading that did not fit with the following paragraph was flushed alone and merged forward, producing an over-limit prose section. The packer now splits prose to fit the room left after a heading.
7. `grep` pre-filtered candidates with the word index, so `TX-45` could not find `TX-4501`. It is now a plain substring scan; cost at 98k sections is recorded above.
8. Fragment merging ignored the size limit, so a trailing bare heading or a leading H1 could push a neighbour a few characters over. Merges now re-pack the combined blocks.

## M2: MCP server

- `tests/test_mcp.py`: nine tests. Initialize delivers the index in `instructions`; tools listed from the shared schemas; all five tools round-trip; tool errors (unknown id, bad regex, wrong argument type, unknown tool) come back as `is_error` results and the server keeps serving; the index resource equals the instructions body; a real stdio subprocess serves a store file and a directory; the summarizer wrapper with a mocked HTTP layer.
- Claude Code headless, conformance corpus: comparison question answered with two scoped searches, three reads, both ids cited ($0.33, 7 turns); identifier question answered via grep, read, grep, id cited ($0.23, 5 turns). Traces in the roadmap.
- Protocol clients: TypeScript and Go with the official SDKs, Java with raw JSON-RPC, all three against the Python server over stdio, all three read both refund-window sections.
- Direct API loop (OpenAI, no MCP): two searches, two reads, two citations.
- LLM summaries on the `uv` docs: 81 of 81 after the fix below; rerun uses the cache; retry path for documents that fell back to offline verified (17 recovered on the second run).

Bugs found: empty summaries from reasoning tokens eating a small completion budget; index budget too small for real summaries at 81 documents; Go example struct tag applied to two fields.

## Not yet tested

- PDF parsing (M4, no extra installed yet).
- Hybrid search with real embeddings (needs a provider; measured indirectly via ragbisect's dense config).
- Windows paths and case-insensitive filesystems.
- A second real corpus with large tables and versioned documents; the fixture corpus covers those shapes at small scale.

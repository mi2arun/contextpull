# System design

This document is the implementation contract. Where it disagrees with code, one of them is wrong and it is usually the code.

## 1. Data model

One SQLite file, `.contextpull/store.sqlite` by default. WAL mode. Opened read-only at query time.

```sql
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- keys: schema_version, corpus_root, corpus_fingerprint, index_text, index_tokens,
--       index_mode ('flat' | 'compact' | 'hierarchical'), summarizer ('llm:<provider:model>' | 'offline'),
--       section_max_chars, ingested_at

CREATE TABLE documents (
  doc_id      INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,      -- posix path relative to corpus root
  title       TEXT NOT NULL,             -- first H1, else file stem
  summary     TEXT,                      -- one line, ≤ 160 chars
  summary_src TEXT,                      -- 'llm' | 'offline'
  sha256      TEXT NOT NULL,
  bytes       INTEGER NOT NULL,
  kind        TEXT NOT NULL,             -- 'markdown' | 'text' | 'pdf'
  n_sections  INTEGER NOT NULL,
  ingested_at TEXT NOT NULL
);

CREATE TABLE sections (
  id           TEXT PRIMARY KEY,         -- '<path>#<ordinal>'
  doc_id       INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  ordinal      INTEGER NOT NULL,
  heading_path TEXT NOT NULL,            -- 'Configuration > Cache directory'
  level        INTEGER NOT NULL,         -- depth of the governing heading, 0 for preamble
  kind         TEXT NOT NULL,            -- 'prose' | 'table' | 'code' | 'mixed'
  text         TEXT NOT NULL,
  char_len     INTEGER NOT NULL,
  hash         TEXT NOT NULL,            -- sha256 of text
  prev_id      TEXT,
  next_id      TEXT,
  UNIQUE (doc_id, ordinal)
);

CREATE VIRTUAL TABLE sections_fts USING fts5(
  id UNINDEXED,
  heading_path,
  text,
  tokenize = "unicode61 remove_diacritics 2 tokenchars '-_.'"
);
-- tokenchars keeps identifiers whole: --no-cache, UV_CACHE_DIR, tx-4419, 3.12, tool.uv.sources

CREATE TABLE embeddings (                -- optional, populated only with --embed
  section_id TEXT PRIMARY KEY REFERENCES sections(id) ON DELETE CASCADE,
  model      TEXT NOT NULL,
  dim        INTEGER NOT NULL,
  vec        BLOB NOT NULL               -- float32 little-endian, L2-normalised
);

CREATE TABLE summary_cache (             -- survives document deletion so re-adding is free
  sha256  TEXT PRIMARY KEY,
  model   TEXT NOT NULL,
  summary TEXT NOT NULL
);
```

Schema changes bump `schema_version`; `Store.open` runs forward migrations or refuses with a clear message if the file is newer than the code.

## 2. Section identity

`id = f"{path}#{ordinal}"`, ordinal zero-based in document order.

- Stable across re-ingest when the document is unchanged (hash match skips the document entirely).
- When a document changes, its ordinals are reassigned. Sections after an inserted heading shift by one. The `hash` column lets a client detect that an ID it remembered now points at different text.
- IDs are looked up in the database, never mapped to the filesystem. There is no path traversal surface.

Rejected: content-hash IDs (unreadable in citations, change on any edit), UUIDs (unstable and unreadable), byte offsets (meaningless after re-ingest).

## 3. Ingest pipeline

```
discover → hash → parse → section → classify → write → fts → summarize → index
```

**Discover.** Walk the corpus root. Include `.md .markdown .txt .docx .xlsx .pptx`, and `.pdf` when the `pdf` extra is installed. Skip hidden directories and anything matching `.contextpullignore` (gitignore syntax subset: literal paths and `*` globs). Sorted order for determinism.

**Hash.** sha256 of file bytes. Unchanged documents are skipped whole. Deleted documents are removed with their sections and FTS rows.

**Parse** produces a block stream: `Heading(level, text)`, `Paragraph(text)`, `Table(header_row, rows, raw)`, `Code(lang, raw)`, `ListBlock(raw)`.

- Markdown: line-based parser for ATX headings, fenced code, pipe tables, paragraphs. Setext headings supported. Front matter (`---` block at top) parsed for `title` and otherwise dropped. No HTML rendering.
- Office Open XML, standard library only: docx heading styles become headings, numbered paragraphs list items, tables pipe tables; xlsx sheets become a level-2 heading plus one pipe table each, first row as header, cached values only; pptx slides become a level-2 heading ("Slide N: title") with their text. Images and embedded objects are ignored.
- Text: paragraphs split on blank lines; lines that are short, title-cased, and followed by a blank line are treated as level-2 headings.
- PDF (optional `pdf` extra, pypdf): text runs with their font size; the most common size by character count is the body size, runs at least 1.2× larger and under 120 characters become headings, levels assigned by descending size. Tables are not detected, and page numbers are not recorded in v1; sections carry heading paths only. A PDF whose text has one font size yields a single heading-less document, which is still searchable.

**Section.** Rules, in priority order:

1. A new section starts at every heading of level ≤ `section_heading_depth` (default 4).
2. A section longer than `section_max_chars` (default 2000) is split at block boundaries into parts that share the heading path. Prose is split to fit the room left in the current part, at sentence or word boundaries, so a heading is always followed by content in its own part and only a single word longer than the limit is ever cut. Parts get consecutive ordinals.
3. A code block is never split; if it exceeds the limit it becomes a section by itself. A table is never split mid-row; a table longer than the limit is split by rows into consecutive sections that share the heading path, and every part's text begins with the header row and separator, so a part is readable on its own. Such sections have `kind = 'table'`.
4. Fragments shorter than `section_min_chars` (default 40) are merged. A fragment that is only a heading merges forward into the next section, since the heading introduces what follows. Any other fragment merges backward into the previous section, or forward if it is the first. A merge re-packs the combined blocks under rule 2, so the size limit still holds; when nothing can absorb a fragment, for example a document that ends with a bare heading, it stays as its own small section.
5. Preamble before the first heading is a section with `level = 0` and `heading_path = title`.

Invariants tested: concatenating section texts in ordinal order reproduces the parsed document text modulo whitespace and repeated table headers; no section contains a partial fence or a partial table row; every table part begins with its header; every section has a non-empty heading path.

**Classify.** `kind` is `table` or `code` if the section is exactly one such block, `mixed` if it contains one alongside prose, else `prose`.

**Write.** One transaction per document: delete old sections, insert new, set `prev_id`/`next_id`. FTS rows inserted in the same transaction.

**Summarize.** Per changed document, one LLM call producing a one-line summary (≤ 160 chars) from the title, heading list and first 1,500 characters. Cached in `summary_cache` by document sha256. If no provider is configured, `summary_src = 'offline'` and the summary is the first heading plus the first sentence.

**Index.** See §4. Stored in `meta.index_text`.

Incremental cost is proportional to changed documents. A no-change re-ingest performs only the discover and hash steps and leaves `index_text` byte-identical.

## 4. Index construction

The index is plain text, budgeted in tokens (approximation: characters ÷ 4, configurable; exact tokenizer not required). Default budget 3,000 tokens: with model summaries a document line is about 25 tokens, so roughly 110 documents fit flat.

**Flat mode** (default when it fits the budget):

```
ContextPull index · 81 documents · 1,017 sections · corpus a3f1f1a6
Call search(query, in?) to find sections by words or identifiers, read(id) for exact text,
grep(pattern) for codes and flags, neighbours(id) for the header or next clause.
Search returns ids and snippets only; read what you need, then answer with [ids].

concepts/cache.md            Cache · how uv decides the cache dir, pruning, CI usage       (22 sections)
concepts/indexes.md          Indexes · defining, pinning packages to, explicit flag       (14)
guides/integration/aws.md    AWS CodeArtifact auth via keyring, env vars                 (9)
...
```

One line per document: path padded to column 30, summary (or title) truncated to 60 characters, section count. Paths are the `in` filter values for `search`, so the model learns them from the index.

**Compact mode** (when flat exceeds the budget): the same one line per document with the summary dropped, path and section count only, so every document is still addressable by name. The header says `compact; call index(prefix) for summaries`.

**Hierarchical mode** (when compact also exceeds the budget): one line per top-level directory with document and section counts and the first few titles. If even that exceeds the budget, directory lines are kept in path order until the budget is reached and a final line says how many were left out. `index(prefix)` returns the flat listing under a prefix. The header line says "hierarchical; call index(prefix) to expand". The budget is always honoured.

**Scale tiers** and expected behaviour:

| Corpus | Sections | Index mode | Search p50 target |
|---|---|---|---|
| ≤ ~110 docs | ≤ 5k | flat, with summaries | < 20 ms |
| ≤ ~300 docs | ≤ 10k | compact, paths and counts | < 20 ms |
| ≤ 5k docs | ≤ 100k | hierarchical, one level | < 50 ms |
| > 5k docs | > 100k | hierarchical, directory tree only, search-first | < 100 ms |

FTS5 handles the search side of all three tiers. The index budget is the constraint, not the store.

## 5. Operations

All in `contextpull.ops`, pure functions over an open `Store`, no I/O beyond SQLite. Full argument tables in [Tool reference](tool-reference.md).

| Operation | Implementation |
|---|---|
| `index(prefix?)` | Returns `meta.index_text`, or computes the sub-listing for `prefix` from `documents`. |
| `search(query, in?, limit=10, mode='lexical')` | FTS5 `MATCH` in three passes of descending precision: exact phrase, all terms (`AND`), any term (`OR`), stopping when `limit` is filled; rank by `bm25(sections_fts, 0.0, 2.0, 1.0)` (one weight per FTS column: id, heading path, text) weighting heading path over text; filter by `in` path globs via `documents.path GLOB`; snippet from `snippet()` at 20 tokens. `mode='hybrid'` fuses with cosine over `embeddings` by reciprocal rank when embeddings exist, else falls back to lexical and says so in the result. |
| `read(id, context=0)` | Section by primary key; with `context=n`, also the n previous and n next sections of the same document, in order, marked as context. For `kind='table'` parts of a split table, the header row is always included. |
| `grep(pattern, in?, regex=False, limit=20)` | Case-insensitive substring scan by default (`instr(lower(text), pattern)`), regex via Python `re` over all sections in the path filter; no FTS prefilter, because grep exists for substrings inside tokens; returns the matching line with the section id. Regex compile errors return a tool error. Pattern length capped at 200 chars; regex evaluation capped per section by a step budget. |
| `neighbours(id, before=1, after=1)` | Follows `prev_id`/`next_id`. Includes the table header section if `id` is a table continuation. |

Every result carries `id`, `heading_path` and `doc` so the model can cite without a second call.

## 6. Tool schemas

`contextpull.tools.TOOLS` is a list of five dicts with `name`, `description`, `input_schema` (JSON Schema draft 2020-12). The MCP server registers them verbatim; the embedding recipe passes them to the Anthropic or OpenAI tools parameter with a one-line adapter for OpenAI's `parameters` key; the evaluation adapters import them so the loop under test uses exactly the same definitions. Tool descriptions carry the pull discipline: search for pointers, read for text, cite ids.

## 7. Delivery into hosts

**Server instructions.** On MCP `initialize`, the server returns `instructions` containing the pull discipline paragraph and, when `index_tokens ≤ budget`, the full index. Claude Code and Claude Desktop inject server instructions into the system prompt, which makes the index always present without a user-visible file. When the index exceeds the budget, instructions contain the hierarchical header and the directory listing.

**Tool and resource.** `index` is also a tool, and the same text is served as resource `contextpull://index`, for hosts that ignore instructions or let users attach resources by hand.

**Custom clients** call `ops.index()` and put the text wherever their prompt assembly wants it.

**Attaching to Claude Code.**

```sh
claude mcp add contextpull -- uvx --from "contextpull[mcp]" contextpull serve ./docs   # from PyPI; the mcp extra is needed for serve
claude mcp add contextpull -- uv run --project /path/to/contextpull contextpull serve ./docs   # from a checkout
```

`serve <dir>` ingests incrementally into `<dir>/.contextpull/store.sqlite` and then speaks MCP over stdio; pass a `.sqlite` path to serve a prebuilt store, `--no-ingest` to skip the refresh, `--summarizer provider:model` for model summaries, `--log` for one line per tool call on stderr. Headless runs use `claude -p … --mcp-config cfg.json --strict-mcp-config --allowedTools "mcp__contextpull__*"`.

**Convenience for Claude Code.** `contextpull claude-md` prints a snippet for `CLAUDE.md` that tells the model the server exists and how to use it, for teams that prefer explicit project instructions. Optional, not the mechanism.

## 8. Configuration

Precedence: CLI flags, then environment variables prefixed `CONTEXTPULL_`, then `[tool.contextpull]` in `pyproject.toml` at the corpus root, then defaults.

| Setting | Default | Notes |
|---|---|---|
| `store` | `.contextpull/store.sqlite` | |
| `section_max_chars` | 2000 | |
| `section_min_chars` | 40 | |
| `section_heading_depth` | 4 | |
| `index_budget_tokens` | 3000 | |
| `summarizer` | `offline` | or `provider:model` |
| `embed_model` | none | `--embed-model provider:model` at ingest embeds every section (heading path + text, L2-normalised float32) and enables `search(mode="hybrid")`. Hybrid embeds the query at query time with the same model: the one network call ContextPull makes while answering, opt-in by construction. Fusion is reciprocal rank, k = 60, over the lexical hits and the top 4×limit dense neighbours, path filter applied to both. |
| `transport` | `stdio` | or `http`: streamable HTTP at `/mcp`, stateless sessions, `--host` (default 127.0.0.1) `--port` (default 8765) |
| `readonly` | true at serve time | |

## 9. Concurrency and consistency

- Ingest takes a write lock via SQLite; a running server in WAL mode keeps reading the last committed snapshot and sees the new index on its next `initialize` or `index` call.
- The server never writes.
- Multiple servers over one store file are fine (read-only, WAL).

## 10. Failure modes

| Failure | Behaviour |
|---|---|
| Corpus path missing or empty | `ingest` exits non-zero with the path and supported extensions |
| Unparseable file | Skipped, listed in the ingest summary with reason; never aborts the run |
| PDF without the extra | Listed as skipped with the install hint |
| No summarizer credentials | Offline summaries; index header says `summaries: offline` |
| `search` with no hits | Empty result with a `hint` field suggesting `grep` for identifiers or a broader query |
| `read` of unknown id | Tool error naming the id; suggests `search` |
| Regex too expensive | Tool error; suggests a substring match |
| Store newer than code | `Store.open` refuses with both versions |
| Index over budget | Hierarchical mode; instructions say how to expand |

Nothing here is silent. The push pipeline's central defect is that retrieval failure produces no signal; every failure above produces one the model can act on.

## 11. Security

- The server is read-only over one SQLite file. No filesystem access at query time; IDs resolve in the database.
- No network from the core at query time. The only outbound calls are during ingest, to the configured summarizer or embedding provider, and only over the text of documents the user chose to ingest.
- Regex `grep` bounded by pattern length and evaluation budget to prevent pathological patterns from stalling a host.
- Streamable HTTP transport binds to localhost by default; exposing it further is the operator's explicit choice, and per-section access rules are out of scope for v1.
- Credentials come only from environment variables and are never written to the store or logs.

## 12. Observability

- `ingest` prints documents seen, changed, skipped, sections written, summaries generated versus cached, tokens spent, index mode and size.
- `serve --log` writes one line per tool call: tool, arguments summary, result count, milliseconds. Never bodies.
- The evaluation adapters record tool calls, tokens and wall time per question for the cost columns.

## 13. Testing strategy

- Sectioning invariants as property-style tests over synthetic documents.
- Golden tests: ingest a fixture corpus, compare `index_text` and the id list against checked-in expected output.
- FTS behaviour: identifiers survive tokenisation; heading weighting ranks a heading match above a body match.
- MCP layer: in-memory client through the SDK, all five tools, error paths.
- Determinism: two ingests of the same fixture produce identical stores modulo timestamps.

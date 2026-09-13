# Store format contract

This is the cross-language contract. A reader in any language that honours this document and passes the conformance suite is a ContextPull reader. The schema itself is in [system-design.md §1](system-design.md); this page states the rules a reader must follow.

**Format version:** `1.0` (in `meta.schema_version`). Readers supporting major `1` must open any `1.x` store.

## Opening

1. Open read-only. Never write.
2. Read `meta.schema_version`. If missing, the file is not a store. If the major differs from what the reader supports, refuse with both versions in the message.
3. Check that FTS5 is available: `SELECT count(*) FROM sections_fts LIMIT 1` must succeed. If not, refuse with a message naming the binding.
4. Read `meta.index_text`, `meta.index_mode`, `meta.index_tokens`, `meta.corpus_fingerprint` once; they are immutable for the life of the file.

## Identifiers

- Section id is `documents.path || '#' || sections.ordinal`. Readers must not construct ids from the filesystem or accept ids that are not present in `sections`.
- Document paths are POSIX-style, relative, without a leading `./`.

## Tokenisation

Ingest writes `sections_fts` with `tokenize = "unicode61 remove_diacritics 2 tokenchars '-_.'"`. Because those characters are token characters everywhere, ingest first **normalises** the indexed columns (`heading_path`, `text` in the FTS table only): every run of `-`, `_`, `.` at the start or end of a token is removed, so `--no-cache` indexes as `no-cache`, `cache.` as `cache`, while `tx-4419`, `3.12` and `tool.uv.sources` stay whole. Readers apply the same normalisation to query text before tokenising. `sections.text` is verbatim; snippets come from the normalised column and may lack a leading dash or trailing full stop. Readers must build FTS queries so that the same tokeniser applies, which SQLite does automatically for `MATCH`. When a reader tokenises query text itself, for sanitisation or for grep candidates, it uses the regex `[^\W_][\w.\-]*` (a letter or digit, then letters, digits, `.`, `_`, `-`) on the lower-cased text and strips leading and trailing `._-` from each token.

## Search

Given `query`, `in`, `limit`, `mode`:

1. Tokenise `query`. If no tokens, return empty hits with the hint `no searchable words`.
2. Build `orq = '"t1" OR "t2" …'` with each token as an FTS5 string (double quotes doubled inside).
3. If two or more tokens, also build `phrase = '"t1 t2 …"'` and `andq = '"t1" AND "t2" …'`.
4. Path filter: `documents.path GLOB ?` for each entry in `in`, joined with `OR`; an entry with no `*`, `?` or `[` also matches `path GLOB entry || '/*'`.
5. Run, in order, the phrase query, the `AND` query, then `orq`, each ordered by `bm25(sections_fts, 0.0, 2.0, 1.0)` (weights per FTS column: id, heading_path, text), then `id`, each limited to `limit`. Concatenate, dropping ids already seen, and take `limit`. Precision descends and the candidate set for the expensive `OR` pass is only consulted when the stricter passes did not fill the limit.
6. Snippet: `snippet(sections_fts, 2, '**', '**', '…', 20)`, then all runs of whitespace collapsed to one space.
7. `score` is the negated bm25 value, rounded to two decimals, so higher is better.
8. `mode = 'hybrid'`: if `embeddings` has rows for this store, embed the query with the model named in `embeddings.model`, compute cosine over all rows, and fuse the two rankings by reciprocal rank with k = 60. If `embeddings` is empty, run lexical and set `mode` in the result to `lexical` with `hint = 'no embeddings in store'`. The conformance suite does not cover hybrid because it depends on an external model.

## Read

- Select by primary key. Unknown id is a tool error.
- `context = n`: also return the `n` sections with `ordinal` immediately below and above within the same `doc_id`, in ordinal order, each flagged `context: true`.
- Table parts already begin with the header row and separator as written by ingest, so a reader returns `text` verbatim. If a store from an older writer lacks the header on a continuation (`kind = 'table'`, previous section with the same `heading_path` and `kind`), the reader walks back to the first section of the run and prepends its header and separator lines. Readers must not duplicate a header the text already starts with.

## Grep

- Literal mode is a case-insensitive substring scan over `sections.text` (`instr(lower(text), lower(pattern)) > 0`), restricted by the path filter. Do **not** pre-filter with the word index: `TX-45` must match inside `TX-4501`, and FTS tokens cannot do that. A reader may add its own trigram index as an optimisation only if results stay identical.
- Return the first matching line of each section, one match per section, up to `limit`, ordered by `id`; set `truncated` when more sections matched.
- Regex mode uses the host language's engine over the same candidate set. Bound pattern length to 200 characters and bound evaluation per section; on overrun return a tool error. Regex results are not conformance-tested.

## Neighbours

- Follow `prev_id` and `next_id` up to `before` and `after` steps, stopping at document boundaries.
- If `id` is a table continuation as defined under Read, also return `header` as the first section of the run.

## Index

- `index()` with no prefix returns `meta.index_text` verbatim.
- `index(prefix)` returns one line per document whose path starts with `prefix`, in path order, formatted as `path` padded to column 30, two spaces, then `summary` if present else `title` truncated to 60 characters, two spaces, then `(n_sections)`. The first line is `ContextPull index · <prefix> · <n> documents · <m> sections`.

## Ordering and ties

Wherever this document says "ordered by rank", the full order is rank, then `id` ascending. Two conforming readers return identical id lists.

## Things readers must not do

- Write to the store, including creating temp tables in it. Use in-memory temp storage.
- Resolve ids to files.
- Return section bodies from `search`.
- Invent tools. The tool set is `tools.json`.

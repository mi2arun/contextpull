# Tool reference

Five tools. Definitions live in `contextpull.tools.TOOLS` and are shared by the MCP server, the embedding recipe and the evaluation adapters. All results include `id`, `heading_path` and `doc` so the model can cite immediately.

The discipline, as stated in every tool description: **search for pointers, read for text, cite ids.**

---

## `index`

Return the table of contents. Usually already present in context through server instructions; call it when it is not, or to expand a directory in hierarchical mode.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `prefix` | string | none | Path prefix to expand, e.g. `guides/` |

**Returns** plain text.

```
ContextPull index · 81 documents · 1,017 sections · corpus a3f1f1a6 · summaries: llm
...
concepts/cache.md            Cache · how uv decides the cache dir, pruning, CI usage       (22)
```

---

## `search`

Find sections by words or identifiers. Returns pointers and snippets, never full text.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `query` | string | required | Words, phrases in quotes, or identifiers |
| `in` | string[] | all | Path globs to restrict to, e.g. `["policy-2024.md", "guides/*"]` |
| `limit` | integer | 10 | 1–50 |
| `mode` | `"lexical"` \| `"hybrid"` | `"lexical"` | Hybrid requires embeddings; falls back with a note |

**Returns**

```json
{
  "hits": [
    {"id": "policy-2025.md#3", "doc": "policy-2025.md", "heading_path": "Refunds > Refund window",
     "snippet": "…full refund within **14 days** of delivery; store credit …", "score": 8.42, "kind": "prose"}
  ],
  "mode": "lexical",
  "hint": null
}
```

Empty `hits` come with a `hint`: try `grep` for exact codes, drop the `in` filter, or use fewer words.

**Example.** Comparison question, two years named:

```
search("refund window", in=["policy-2024.md", "policy-2025.md"])
```

---

## `read`

Return one section verbatim, optionally with neighbours for context.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `id` | string | required | Section id from `search`, `grep` or the index |
| `context` | integer | 0 | Also return this many sections before and after, marked `context: true` |

**Returns**

```json
{
  "id": "policy-2025.md#3", "doc": "policy-2025.md", "heading_path": "Refunds > Refund window",
  "kind": "prose", "text": "Customers may request a full refund within 14 days of delivery. …",
  "prev_id": "policy-2025.md#2", "next_id": "policy-2025.md#4",
  "context": []
}
```

For a table continuation section, `text` begins with the header row even though the header lives in an earlier section.

---

## `grep`

Exact substring or regex match across sections. For error codes, flags, environment variables, part numbers, anything an embedding would blur.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `pattern` | string | required | ≤ 200 chars |
| `in` | string[] | all | Path globs |
| `regex` | boolean | false | Python `re` syntax when true |
| `limit` | integer | 20 | 1–100 |

**Returns**

```json
{
  "matches": [
    {"id": "errors.md#12", "doc": "errors.md", "heading_path": "Transaction errors > TX-44xx",
     "line": "TX-4419  Declined by issuer; retry is not permitted."}
  ],
  "truncated": false
}
```

Case-insensitive. A regex that fails to compile, or exceeds the evaluation budget, returns a tool error with the reason.

---

## `neighbours`

Sections adjacent to a given one, in document order. For recovering a table's header, the clause before a definition, or the next step in a procedure.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `id` | string | required | |
| `before` | integer | 1 | 0–5 |
| `after` | integer | 1 | 0–5 |

**Returns** a list of section objects in the same shape as `read`, plus `header` when `id` is part of a split table:

```json
{"sections": [...], "header": {"id": "specs.md#7", "text": "| Model | Storage temp | Voltage |"}}
```

---

## Errors

All tools return MCP tool errors, not exceptions, with a one-line `message` and where useful a `suggestion`:

| Condition | message | suggestion |
|---|---|---|
| unknown id | `no section 'x'` | `search for it first` |
| bad glob in `in` | `invalid path filter 'x'` | listing of valid top-level paths |
| regex error | `pattern does not compile: …` | `set regex=false for a literal match` |
| regex budget exceeded | `pattern too expensive` | `narrow with in= or use a literal` |

## Using the schemas directly

```python
from contextpull.tools import TOOLS            # list[dict]: name, description, input_schema
anthropic_tools = TOOLS                        # already in Anthropic shape
openai_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                 "parameters": t["input_schema"]}} for t in TOOLS]
```

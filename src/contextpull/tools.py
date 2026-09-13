"""Tool definitions. One source of truth for the MCP server, the embedding
recipe, the evaluation adapters and every other-language SDK (via tools.json).
"""

from __future__ import annotations

import json

TOOLS_VERSION = "1.0"

_DISCIPLINE = "Search for pointers, read for text, cite ids like [path.md#3]."

TOOLS: list[dict] = [
    {
        "name": "index",
        "description": "Table of contents of the corpus: one line per document with its path, summary and section count. "
        "Usually already in your context; call it if you see no index, or with a prefix to expand a directory. " + _DISCIPLINE,
        "input_schema": {
            "type": "object",
            "properties": {"prefix": {"type": "string", "description": "Path prefix to expand, e.g. 'guides/'"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": "Find sections by words or identifiers. Returns ids, heading paths and short snippets, never full text. "
        "Use in= with document paths from the index to target specific documents (for comparisons, search each). " + _DISCIPLINE,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words, quoted phrases, or identifiers"},
                "in": {"type": "array", "items": {"type": "string"}, "description": "Document paths or globs to restrict to"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "mode": {"type": "string", "enum": ["lexical", "hybrid"], "default": "lexical"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read",
        "description": "Return one section verbatim by id, with its heading path and neighbour ids. "
        "context=n also returns n sections before and after. Table parts always begin with the header row. " + _DISCIPLINE,
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Section id from search, grep or the index"},
                "context": {"type": "integer", "minimum": 0, "maximum": 5, "default": 0},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "grep",
        "description": "Exact substring (or regex) match across sections. For error codes, flags, environment variables, part numbers: "
        "anything search may blur. Returns the matching line and section id. On large corpora pass in= to keep it fast. " + _DISCIPLINE,
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "maxLength": 200},
                "in": {"type": "array", "items": {"type": "string"}},
                "regex": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "neighbours",
        "description": "Sections adjacent to a given one, in document order: the clause before a definition, the next step, "
        "or a table's header row (returned as 'header' when the id is part of a split table). " + _DISCIPLINE,
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "before": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1},
                "after": {"type": "integer", "minimum": 0, "maximum": 5, "default": 1},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def tools_json() -> str:
    return json.dumps({"version": TOOLS_VERSION, "tools": TOOLS}, indent=2, ensure_ascii=False) + "\n"


def openai_tools() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOLS]


def call(ops, name: str, args: dict) -> dict | str:
    """Dispatch a tool call by name onto an ``Ops``. Shared by every surface."""
    args = dict(args or {})
    if name == "index":
        return ops.index(args.get("prefix"))
    if name == "search":
        return ops.search(args["query"], args.get("in"), args.get("limit", 10), args.get("mode", "lexical")).to_dict()
    if name == "read":
        return ops.read(args["id"], args.get("context", 0)).to_dict()
    if name == "grep":
        return ops.grep(args["pattern"], args.get("in"), bool(args.get("regex", False)), args.get("limit", 20)).to_dict()
    if name == "neighbours":
        return ops.neighbours(args["id"], args.get("before", 1), args.get("after", 1)).to_dict()
    raise KeyError(f"unknown tool {name!r}")

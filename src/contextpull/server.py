"""MCP surface: a thin wrapper over ``Ops`` using the official SDK's low-level
server so the five tools are registered from ``tools.TOOLS`` verbatim.

Index delivery (ADR 004): the store's budgeted index text goes into the
server's ``instructions`` at initialize, is also a tool (``index``) and a
resource (``contextpull://index``). Requires the ``mcp`` extra.

Nothing here writes to stdout: in stdio mode stdout is the wire.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server
except ImportError as e:  # pragma: no cover
    raise ImportError('the MCP server needs the "mcp" extra: pip install "contextpull[mcp]"') from e

from . import __version__
from .index import PREAMBLE
from .ops import Ops, OpsError
from .store import Store
from .tools import TOOLS, call

INDEX_URI = "contextpull://index"

def instructions_text(store: Store) -> str:
    return PREAMBLE + (store.meta_get("index_text") or "(index empty: run contextpull ingest)")


def _text_result(payload: Any, is_error: bool = False) -> types.CallToolResult:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


def build_server(store: Store, *, log: bool = False, name: str = "contextpull") -> tuple[Server, InitializationOptions]:
    ops = Ops(store)
    n_docs, n_secs = store.counts()

    def _log(msg: str) -> None:
        if log:
            print(msg, file=sys.stderr, flush=True)

    async def on_list_tools(ctx, params):
        return types.ListToolsResult(
            tools=[types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"]) for t in TOOLS]
        )

    async def on_call_tool(ctx, params: types.CallToolRequestParams):
        t0 = time.perf_counter()
        args = dict(params.arguments or {})
        try:
            out = call(ops, params.name, args)
            n = len(out.get("hits", out.get("matches", out.get("sections", [])))) if isinstance(out, dict) else len(out)
            _log(f"{params.name} {json.dumps(args, ensure_ascii=False)[:120]} -> {n} in {(time.perf_counter() - t0) * 1000:.1f} ms")
            return _text_result(out)
        except OpsError as e:
            _log(f"{params.name} {json.dumps(args, ensure_ascii=False)[:120]} -> error: {e.message}")
            return _text_result(e.to_dict(), is_error=True)
        except KeyError:
            return _text_result({"error": f"unknown tool {params.name!r}", "suggestion": "tools: " + ", ".join(t["name"] for t in TOOLS)}, is_error=True)
        except Exception as e:  # never crash the server on a bad argument
            _log(f"{params.name} -> unexpected {type(e).__name__}: {e}")
            return _text_result({"error": f"{type(e).__name__}: {e}", "suggestion": "check the argument types against the tool schema"}, is_error=True)

    async def on_list_resources(ctx, params):
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    name="index",
                    uri=INDEX_URI,
                    title="ContextPull index",
                    description=f"Table of contents: {n_docs} documents, {n_secs} sections. Same text as the server instructions.",
                    mime_type="text/plain",
                )
            ]
        )

    async def on_read_resource(ctx, params: types.ReadResourceRequestParams):
        if str(params.uri) != INDEX_URI:
            raise ValueError(f"unknown resource {params.uri}; only {INDEX_URI} exists")
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=INDEX_URI, mime_type="text/plain", text=ops.index())])

    server = Server(
        name,
        version=__version__,
        instructions=instructions_text(store),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )
    return server, server.create_initialization_options()


async def serve_stdio(store_path: str | Path, *, log: bool = False) -> None:
    with Store.open(store_path, readonly=True) as store:
        server, init = build_server(store, log=log)
        if log:
            d, s = store.counts()
            print(f"contextpull serving {store_path}: {d} documents, {s} sections, index {store.meta_get('index_mode')} ≈{store.meta_get('index_tokens')} tokens", file=sys.stderr, flush=True)
        async with stdio_server() as (read, write):
            await server.run(read, write, init)


CLAUDE_MD_SNIPPET = """## Documents (ContextPull)

The `contextpull` MCP server exposes this project's documents. Its instructions already contain an index of every document.
- Use `search` to find sections (returns ids + snippets), then `read` the ids you need. Never guess from memory.
- For comparisons, search each document with `in=[...]` and read both sides.
- For error codes, flags, env vars and part numbers use `grep`.
- Cite section ids like `[policy-2025.md#3]` in answers.
"""

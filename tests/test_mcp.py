"""MCP surface over in-memory streams and over a real stdio subprocess."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("contextpull.server")

import mcp.types as types  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from mcp.shared.memory import create_client_server_memory_streams  # noqa: E402

from contextpull.server import INDEX_URI, build_server  # noqa: E402
from contextpull.store import Store  # noqa: E402


def _text(result) -> str:
    assert result.content and isinstance(result.content[0], types.TextContent)
    return result.content[0].text


async def _with_session(store_path: Path, fn):
    with Store.open(store_path) as store:
        server, init = build_server(store)
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async def run_server():
                await server.run(server_streams[0], server_streams[1], init, raise_exceptions=True)

            task = asyncio.create_task(run_server())
            try:
                async with ClientSession(*client_streams) as session:
                    init_result = await session.initialize()
                    return await fn(session, init_result)
            finally:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


def test_initialize_delivers_index_in_instructions(fixture_store):
    async def fn(session, init):
        assert "ContextPull index · 7 documents" in init.instructions
        assert "policies/policy-2025.md" in init.instructions
        assert init.server_info.name == "contextpull"
        return True

    assert asyncio.run(_with_session(fixture_store, fn))


def test_tools_listed_from_shared_schemas(fixture_store):
    async def fn(session, init):
        tools = (await session.list_tools()).tools
        assert [t.name for t in tools] == ["index", "search", "read", "grep", "neighbours"]
        search = next(t for t in tools if t.name == "search")
        assert search.input_schema["required"] == ["query"]
        return True

    assert asyncio.run(_with_session(fixture_store, fn))


def test_all_five_tools_round_trip(fixture_store):
    async def fn(session, init):
        idx = _text(await session.call_tool("index", {}))
        assert idx.startswith("ContextPull index")
        sub = _text(await session.call_tool("index", {"prefix": "policies/"}))
        assert "3 documents" in sub.splitlines()[0]

        found = json.loads(_text(await session.call_tool("search", {"query": "refund window", "in": ["policies/policy-2024.md", "policies/policy-2025.md"]})))
        ids = [h["id"] for h in found["hits"]]
        assert ids[:2] == ["policies/policy-2024.md#2", "policies/policy-2025.md#2"]

        read = json.loads(_text(await session.call_tool("read", {"id": ids[1], "context": 1})))
        assert "14 days" in read["text"] and len(read["context"]) == 2

        grep = json.loads(_text(await session.call_tool("grep", {"pattern": "TX-45"})))
        assert grep["matches"][0]["id"].startswith("errors.md#")

        nb = json.loads(_text(await session.call_tool("neighbours", {"id": ids[1], "before": 1, "after": 0})))
        assert [s["id"] for s in nb["sections"]] == ["policies/policy-2025.md#1", "policies/policy-2025.md#2"]
        return True

    assert asyncio.run(_with_session(fixture_store, fn))


def test_errors_are_tool_errors_not_crashes(fixture_store):
    async def fn(session, init):
        r = await session.call_tool("read", {"id": "nope.md#0"})
        assert r.is_error and "no section" in json.loads(_text(r))["error"]
        r = await session.call_tool("grep", {"pattern": "(", "regex": True})
        assert r.is_error and "does not compile" in json.loads(_text(r))["error"]
        r = await session.call_tool("search", {"query": 42})  # wrong type
        assert r.is_error
        r = await session.call_tool("nope", {})
        assert r.is_error
        # server still alive
        assert _text(await session.call_tool("index", {})).startswith("ContextPull index")
        return True

    assert asyncio.run(_with_session(fixture_store, fn))


def test_index_resource(fixture_store):
    async def fn(session, init):
        res = (await session.list_resources()).resources
        assert [str(r.uri) for r in res] == [INDEX_URI]
        got = await session.read_resource(INDEX_URI)
        assert got.contents[0].text == init.instructions.split("\n\n", 1)[1]
        return True

    assert asyncio.run(_with_session(fixture_store, fn))


def test_real_stdio_subprocess(fixture_store):
    async def fn():
        params = StdioServerParameters(command=sys.executable, args=["-m", "contextpull.cli", "serve", str(fixture_store), "--log"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert "ContextPull index" in init.instructions
                found = json.loads(_text(await session.call_tool("search", {"query": "TX-4419"})))
                assert found["hits"][0]["id"].startswith("errors.md#")
                return True

    assert asyncio.run(fn())


def test_summarizer_wrapper_offline_and_mocked(monkeypatch):
    from contextpull import llm as llm_mod

    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(llm_mod, "_post", lambda url, headers, body, timeout: {"choices": [{"message": {"content": "Refund windows, store credits and how to contact support.\nsecond line ignored"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    l = llm_mod.LLM("openai:gpt-test")
    assert l.summarize("Refund Policy 2025", "Eligibility\nRefund window", "Applies to purchases…") == "Refund windows, store credits and how to contact support"
    assert l.calls == 1 and "10 in / 5 out" in l.spend()
    assert llm_mod.parse_model("claude-haiku-4-5-20251001") == ("anthropic", "claude-haiku-4-5-20251001")


def test_serve_directory_ingests_then_serves(tmp_path):
    import shutil

    from tests.conftest import FIXTURE

    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus)

    async def fn():
        params = StdioServerParameters(command=sys.executable, args=["-m", "contextpull.cli", "serve", str(corpus)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert "7 documents" in init.instructions
                return True

    assert asyncio.run(fn())
    assert (corpus / ".contextpull" / "store.sqlite").exists()


def test_claude_md_snippet(capsys):
    from contextpull.cli import main

    assert main(["claude-md"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## Documents (ContextPull)") and "`grep`" in out



def test_node_server_matches_python_over_mcp(fixture_store):
    """Cross-implementation: the Node store-native server answers like the Python one."""
    import shutil
    from pathlib import Path as _P

    node = shutil.which("node")
    dist = _P(__file__).resolve().parent.parent / "sdk" / "typescript" / "dist" / "index.js"
    if not node or not dist.exists():
        pytest.skip("node or the built TypeScript package is not available")

    async def run(params):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                found = json.loads(_text(await session.call_tool("search", {"query": "refund window", "in": ["policies/policy-2024.md", "policies/policy-2025.md"]})))
                read_ = json.loads(_text(await session.call_tool("read", {"id": "specs.md#1"})))
                return init.instructions, [h["id"] for h in found["hits"]], read_["text"]

    py = asyncio.run(run(StdioServerParameters(command=sys.executable, args=["-m", "contextpull.cli", "serve", str(fixture_store)])))
    js = asyncio.run(run(StdioServerParameters(command=node, args=[str(dist.parent.parent / "bin" / "contextpull.mjs"), "serve", str(fixture_store)])))
    assert py[0] == js[0]  # identical instructions, including the index text
    assert py[1] == js[1]  # identical ranking
    assert py[2] == js[2]  # identical verbatim text

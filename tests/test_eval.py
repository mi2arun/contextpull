"""Eval adapters with a mocked model API and a fake `claude` binary."""

import json
import pytest
import os
import stat
import sys
from pathlib import Path

from contextpull.eval import ApiLoopRetriever, ClaudeCodeRetriever


def _openai_script(responses):
    """Return a fake _post that replays scripted assistant messages."""
    it = iter(responses)

    def fake_post(self, url, headers, body):
        msg = next(it)
        return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 1000, "completion_tokens": 50}}

    return fake_post


def test_api_loop_reads_ids_in_order_and_caches(fixture_store, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    scripted = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": json.dumps({"query": "refund window", "in": ["policies/policy-2024.md", "policies/policy-2025.md"]})}}]},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c2", "type": "function", "function": {"name": "read", "arguments": json.dumps({"id": "policies/policy-2024.md#2"})}},
            {"id": "c3", "type": "function", "function": {"name": "read", "arguments": json.dumps({"id": "policies/policy-2025.md#2"})}}]},
        {"role": "assistant", "content": "30 days became 14 days [policies/policy-2024.md#2] [policies/policy-2025.md#2]"},
    ]
    monkeypatch.setattr(ApiLoopRetriever, "_post", _openai_script(scripted))
    r = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", cache_path=str(tmp_path / "c.sqlite"))
    ids = r.retrieve("What changed in the refund window?", 5)
    assert ids == ["policies/policy-2024.md#2", "policies/policy-2025.md#2"]
    assert "14 days" in r.generate("What changed in the refund window?", ids)
    st = r.stats()
    assert st["queries"] == 1 and st["tool_calls"] == 3 and st["by_tool"] == {"search": 1, "read": 2}
    assert st["tokens_in"] == 3000 and st["tokens_out"] == 150 and st["turns"] == 3

    # a fresh instance replays from the cache without calling the model
    monkeypatch.setattr(ApiLoopRetriever, "_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    r2 = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", cache_path=str(tmp_path / "c.sqlite"))
    assert r2.retrieve("What changed in the refund window?", 5) == ids
    assert r2.stats()["tool_calls"] == 3


def test_api_loop_survives_bad_tool_args_and_max_turns(fixture_store, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    bad = {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "read", "arguments": "{not json"}}]}
    monkeypatch.setattr(ApiLoopRetriever, "_post", _openai_script([bad] * 3))
    r = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", max_turns=3, cache_path=str(tmp_path / "c.sqlite"))
    assert r.retrieve("q", 5) == []
    rec = r.records["q"]
    assert rec.error == "max_turns reached" and rec.turns == 3


def test_api_loop_anthropic_shape(fixture_store, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    scripted = iter([
        {"content": [{"type": "tool_use", "id": "t1", "name": "grep", "input": {"pattern": "TX-4419"}}], "stop_reason": "tool_use", "usage": {"input_tokens": 500, "output_tokens": 20}},
        {"content": [{"type": "tool_use", "id": "t2", "name": "read", "input": {"id": "errors.md#1"}}], "stop_reason": "tool_use", "usage": {"input_tokens": 600, "output_tokens": 20}},
        {"content": [{"type": "text", "text": "Declined by issuer [errors.md#1]"}], "stop_reason": "end_turn", "usage": {"input_tokens": 700, "output_tokens": 30}},
    ])
    seen_bodies = []

    def fake_post(self, url, headers, body):
        seen_bodies.append(json.loads(json.dumps(body)))  # snapshot: the loop mutates `messages` afterwards
        return next(scripted)

    monkeypatch.setattr(ApiLoopRetriever, "_post", fake_post)
    r = ApiLoopRetriever(str(fixture_store), model="anthropic:claude-test", cache_path=str(tmp_path / "c.sqlite"))
    assert r.retrieve("What does TX-4419 mean?", 5) == ["errors.md#1"]
    assert seen_bodies[0]["tools"][0]["name"] == "index" and "input_schema" in seen_bodies[0]["tools"][0]
    assert seen_bodies[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert r.stats()["tokens_in"] == 1800


def test_claude_code_adapter_parses_trace(fixture_store, tmp_path):
    pytest.importorskip("contextpull.server")  # the adapter verifies the server interpreter can import the MCP server
    fake = tmp_path / "claude"
    fake.write_text("""#!/bin/sh
cat <<'EOF2'
{"type":"system","subtype":"init"}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"mcp__contextpull__search","input":{"query":"refund window"}}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"mcp__contextpull__read","input":{"id":"policies/policy-2024.md#2"}},{"type":"tool_use","name":"mcp__contextpull__read","input":{"id":"policies/policy-2025.md#2"}}]}}
{"type":"result","result":"30 to 14 days [policies/policy-2024.md#2] [policies/policy-2025.md#2]","total_cost_usd":0.31,"num_turns":4,"usage":{"input_tokens":1200,"cache_read_input_tokens":8000,"output_tokens":300},"is_error":false}
EOF2
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = ClaudeCodeRetriever(str(fixture_store), cache_path=str(tmp_path / "c.sqlite"), claude_bin=str(fake))
    assert r.retrieve("What changed in the refund window?", 5) == ["policies/policy-2024.md#2", "policies/policy-2025.md#2"]
    st = r.stats()
    assert st["tool_calls"] == 3 and abs(st["usd"] - 0.31) < 1e-9 and st["tokens_in"] == 9200 and st["tokens_out"] == 300
    assert "14 days" in r.generate("What changed in the refund window?", [])
    cfg = json.loads(r.config.read_text())
    assert cfg["mcpServers"]["contextpull"]["args"][-1] == str(Path(fixture_store).resolve())


def test_eval_package_does_not_import_mcp():
    import subprocess

    code = "import sys, contextpull, contextpull.eval, contextpull.tools; assert 'mcp' not in sys.modules, 'core imported mcp'"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_api_loop_surfaced_ids_and_strict_prompt(fixture_store, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    scripted = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": json.dumps({"query": "TX-4419"})}}]},
        {"role": "assistant", "content": "Declined by issuer (from the snippet)."},
    ]
    seen = []

    def fake(self, url, headers, body):
        seen.append(json.loads(json.dumps(body)))
        return {"choices": [{"message": scripted[len(seen) - 1]}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr(ApiLoopRetriever, "_post", fake)
    strict_reads = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", cache_path=str(tmp_path / "a.sqlite"), strict=True)
    assert strict_reads.retrieve("What does TX-4419 mean?", 5) == []          # nothing read
    assert "NOT evidence" in seen[0]["messages"][-1]["content"]                # strict rules were sent
    assert strict_reads.stats()["answered_without_reading"] == 1

    seen.clear()
    surfaced = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", cache_path=str(tmp_path / "b.sqlite"), count_surfaced=True)
    assert surfaced.retrieve("What does TX-4419 mean?", 5) == ["errors.md#1"]  # the search hit counts
    assert surfaced.stats()["reads_per_query"] == 0


def test_claude_code_adapter_flags_runs_without_tool_calls(fixture_store, tmp_path):
    pytest.importorskip("contextpull.server")
    fake = tmp_path / "claude"
    fake.write_text("""#!/bin/sh
echo '{"type":"result","result":"I think it is 30 days.","total_cost_usd":0.3,"num_turns":1,"usage":{"input_tokens":100,"output_tokens":20},"is_error":false}'
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = ClaudeCodeRetriever(str(fixture_store), cache_path=str(tmp_path / "c.sqlite"), claude_bin=str(fake))
    assert r.retrieve("q", 5) == []
    rec = r.records["q"]
    assert rec.error and "no contextpull tool calls" in rec.error
    assert r.stats()["errors"] == 1
    # not cached: a second instance runs the fake again rather than replaying
    r2 = ClaudeCodeRetriever(str(fixture_store), cache_path=str(tmp_path / "c.sqlite"), claude_bin=str(fake))
    assert r2.retrieve("q", 5) == [] and r2.records["q"].error


def test_claude_code_adapter_refuses_interpreter_without_mcp(fixture_store, tmp_path):
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="cannot run the ContextPull MCP server"):
        ClaudeCodeRetriever(str(fixture_store), cache_path=str(tmp_path / "c.sqlite"), server_python="/usr/bin/false")


def test_api_loop_tools_work_from_worker_threads(fixture_store, tmp_path, monkeypatch):
    """ragbisect calls retrieve() from a thread pool; the store connection must survive that,
    and infrastructure failures inside tools must surface as record errors, never as data."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("OPENAI_API_KEY", "x")

    def fake_post(self, url, headers, body):
        last = body["messages"][-1]
        if last["role"] == "tool":
            assert "hits" in last["content"], f"tool returned an error: {last['content'][:120]}"
            return {"choices": [{"message": {"role": "assistant", "content": "done"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "search", "arguments": json.dumps({"query": "refund window"})}}]}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr(ApiLoopRetriever, "_post", fake_post)
    r = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", cache_path=str(tmp_path / "c.sqlite"), count_surfaced=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda q: r.retrieve(q, 5), [f"question {i}" for i in range(12)]))
    assert all(res and res[0].startswith("policies/") for res in results)
    assert r.stats()["tool_errors"] == 0 and r.stats()["errors"] == 0


def test_api_loop_marks_run_failed_when_every_tool_call_fails(fixture_store, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    scripted = iter([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "search", "arguments": json.dumps({"query": "x"})}}]},
        {"role": "assistant", "content": "guessing"},
    ])
    monkeypatch.setattr(ApiLoopRetriever, "_post", lambda self, u, h, b: {"choices": [{"message": next(scripted)}], "usage": {}})
    r = ApiLoopRetriever(str(fixture_store), model="openai:gpt-test", cache_path=str(tmp_path / "c.sqlite"))
    r.store.close()  # simulate broken infrastructure: every tool call now raises
    assert r.retrieve("q", 5) == []
    rec = r.records["q"]
    assert rec.tool_errors == 1 and rec.error and rec.error.startswith("every tool call failed")
    assert r.cache.get(r.cache.key("api_loop", 3, "openai", "gpt-test", 8, r.fingerprint, "q", False)) is None  # not cached

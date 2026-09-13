"""ClaudeCodeRetriever: the faithful measurement of the development client.

Runs ``claude -p`` headless with the ContextPull MCP server attached through a
generated ``--mcp-config``, parses the stream-json trace for ``read`` calls,
and records cost from the result event. Expensive (tens of cents a question):
use ragbisect's ``--sample``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..store import Store
from ._cache import RunCache

SUFFIX = " Use the contextpull tools to find the answer in the corpus and cite section ids like [path.md#3]."


@dataclass
class CCRecord:
    read_ids: list[str] = field(default_factory=list)
    tool_calls: dict[str, int] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    turns: int = 0
    ms: float = 0.0
    usd: float = 0.0
    answer: str = ""
    error: str | None = None


class ClaudeCodeRetriever:
    concurrency = 3

    def __init__(
        self,
        store_path: str | None = None,
        max_turns: int = 12,
        model: str | None = None,
        cache_path: str = ".contextpull-eval/cache.sqlite",
        claude_bin: str = "claude",
        timeout: float = 300.0,
        server_python: str | None = None,
    ):
        """``server_python`` is the interpreter that runs the MCP server; it must have
        the ``mcp`` extra installed. Defaults to ``CONTEXTPULL_SERVER_PYTHON`` or the
        current interpreter, and is verified up front: a server that cannot start
        would make Claude Code answer from memory at full cost."""
        self.store_path = str(Path(store_path or os.environ.get("CONTEXTPULL_STORE", ".contextpull/store.sqlite")).resolve())
        with Store.open(self.store_path) as s:
            self.fingerprint = s.meta_get("corpus_fingerprint")
        self.max_turns = max_turns
        self.model = model
        self.timeout = timeout
        self.claude = shutil.which(claude_bin) or claude_bin
        self.cache = RunCache(cache_path)
        self.records: dict[str, CCRecord] = {}
        self._lock = threading.Lock()
        self.server_python = server_python or os.environ.get("CONTEXTPULL_SERVER_PYTHON") or sys.executable
        check = subprocess.run([self.server_python, "-c", "import contextpull.server"], capture_output=True, text=True)
        if check.returncode != 0:
            raise RuntimeError(
                f"{self.server_python} cannot run the ContextPull MCP server ({check.stderr.strip().splitlines()[-1] if check.stderr.strip() else 'import failed'}). "
                "Point CONTEXTPULL_SERVER_PYTHON at an interpreter with `contextpull[mcp]` installed."
            )
        self._tmp = Path(tempfile.mkdtemp(prefix="contextpull-cc-"))
        self.config = self._tmp / "mcp.json"
        self.config.write_text(json.dumps({"mcpServers": {"contextpull": {"command": self.server_python, "args": ["-m", "contextpull.cli", "serve", self.store_path]}}}))

    def retrieve(self, query: str, k: int) -> list[str]:
        rec = self._run(query)
        seen: list[str] = []
        for i in rec.read_ids:
            if i not in seen:
                seen.append(i)
        return seen[:k]

    def generate(self, query: str, chunk_ids: list[str]) -> str:
        return self._run(query).answer

    def stats(self) -> dict:
        recs = list(self.records.values())
        return {
            "queries": len(recs),
            "tokens_in": sum(r.tokens_in for r in recs),
            "tokens_out": sum(r.tokens_out for r in recs),
            "tool_calls": sum(sum(r.tool_calls.values()) for r in recs),
            "turns": sum(r.turns for r in recs),
            "usd": sum(r.usd for r in recs),
            "errors": sum(1 for r in recs if r.error),
            "model": self.model or "claude-code-default",
        }

    def _run(self, query: str) -> CCRecord:
        with self._lock:
            if query in self.records:
                return self.records[query]
        key = self.cache.key("claude_code", self.model, self.max_turns, self.fingerprint, query)
        cached = self.cache.get(key)
        rec = CCRecord(**cached) if cached else self._invoke(query)
        if not cached and not rec.error:
            self.cache.put(key, rec.__dict__)
        with self._lock:
            self.records[query] = rec
        return rec

    def _invoke(self, query: str) -> CCRecord:
        rec = CCRecord()
        cmd = [
            self.claude, "-p", query + SUFFIX,
            "--mcp-config", str(self.config), "--strict-mcp-config",
            "--allowedTools", "mcp__contextpull__*",
            "--output-format", "stream-json", "--verbose",
            "--max-turns", str(self.max_turns),
        ]
        if self.model:
            cmd += ["--model", self.model]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, cwd=self._tmp)
        except subprocess.TimeoutExpired:
            rec.error = "timeout"
            rec.ms = (time.perf_counter() - t0) * 1000
            return rec
        rec.ms = (time.perf_counter() - t0) * 1000
        if proc.returncode != 0 and not proc.stdout.strip():
            rec.error = f"exit {proc.returncode}: {proc.stderr.strip()[:300]}"
            return rec
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                for b in ev.get("message", {}).get("content", []):
                    if b.get("type") == "tool_use" and b.get("name", "").startswith("mcp__contextpull__"):
                        name = b["name"].removeprefix("mcp__contextpull__")
                        rec.tool_calls[name] = rec.tool_calls.get(name, 0) + 1
                        if name == "read" and b.get("input", {}).get("id"):
                            rec.read_ids.append(str(b["input"]["id"]))
            elif ev.get("type") == "result":
                rec.answer = ev.get("result") or ""
                rec.usd = float(ev.get("total_cost_usd") or 0)
                rec.turns = int(ev.get("num_turns") or 0)
                usage = ev.get("usage") or {}
                rec.tokens_in = int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0))
                rec.tokens_out = int(usage.get("output_tokens", 0))
                if ev.get("is_error"):
                    rec.error = (ev.get("result") or "error")[:300]
        if not rec.error and not rec.tool_calls:
            # No ContextPull tool was called: the server did not come up or the tools were not allowed.
            # This is a broken measurement, not a data point; never cache it.
            rec.error = "no contextpull tool calls in trace (server unreachable or tools not allowed): " + (proc.stderr.strip()[-300:] or "no stderr")
        return rec

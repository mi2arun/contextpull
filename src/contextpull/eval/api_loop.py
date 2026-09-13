"""ApiLoopRetriever: the embedding recipe as a measured adapter.

System prompt = pull discipline + the store's index, exactly what the MCP
server delivers. Tools = ``contextpull.tools.TOOLS``. The loop runs until the
model answers or ``max_turns`` is hit. Everything is recorded per question:
tool calls by name, tokens, wall time, ids read, final answer.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..llm import parse_model
from ..ops import Ops
from ..index import PREAMBLE
from ..store import Store
from ..tools import TOOLS, call, openai_tools
from ._cache import RunCache

# USD per 1M tokens (input, output) for the models we are confident about; else usd is omitted.
PRICES = {"gpt-5-mini": (0.25, 2.0), "gpt-5-nano": (0.05, 0.40), "gpt-4.1-mini": (0.40, 1.60), "gpt-4o-mini": (0.15, 0.60)}

USER_SUFFIX = "\n\nUse the tools to find the answer in the corpus, read the relevant sections, and answer citing section ids like [path.md#3]."

STRICT_SUFFIX = (
    "\n\nRules: search returns only pointers and short snippets, which are NOT evidence. You must call read on a section "
    "before using anything from it, and you may cite only ids you have read. Answer citing section ids like [path.md#3]. "
    "If you have not read a section that answers the question, keep reading; do not answer from snippets."
)


@dataclass
class LoopRecord:
    read_ids: list[str] = field(default_factory=list)
    surfaced_ids: list[str] = field(default_factory=list)  # ids the model saw in search/grep results, in order
    tool_calls: dict[str, int] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    turns: int = 0
    ms: float = 0.0
    answer: str = ""
    error: str | None = None


class ApiLoopRetriever:
    concurrency = 6

    def __init__(
        self,
        store_path: str | None = None,
        model: str = "openai:gpt-5.4-mini",
        max_turns: int = 8,
        cache_path: str = ".contextpull-eval/cache.sqlite",
        timeout: float = 120.0,
        strict: bool = False,
        count_surfaced: bool = False,
    ):
        """``strict`` adds rules forbidding answers from snippets. ``count_surfaced``
        makes ``retrieve`` return ids read first, then ids merely seen in search or
        grep results, which measures what the model was shown rather than what it
        chose to read."""
        self.strict = strict
        self.count_surfaced = count_surfaced
        self.store = Store.open(store_path or os.environ.get("CONTEXTPULL_STORE", ".contextpull/store.sqlite"))
        self.ops = Ops(self.store)
        self.provider, self.model = parse_model(model)
        self.max_turns = max_turns
        self.timeout = timeout
        self.cache = RunCache(cache_path)
        self.fingerprint = self.store.meta_get("corpus_fingerprint")
        self.system = PREAMBLE + (self.store.meta_get("index_text") or "")
        self.records: dict[str, LoopRecord] = {}
        self._lock = threading.Lock()
        self._sql_lock = threading.Lock()  # one sqlite connection shared across worker threads

    # ------------------------------------------------------------ ragbisect protocol
    def retrieve(self, query: str, k: int) -> list[str]:
        rec = self._run(query)
        seen: list[str] = []
        for i in rec.read_ids + (rec.surfaced_ids if self.count_surfaced else []):
            if i not in seen:
                seen.append(i)
        return seen[:k]

    def generate(self, query: str, chunk_ids: list[str]) -> str:
        return self._run(query).answer

    def stats(self) -> dict:
        recs = list(self.records.values())
        out = {
            "queries": len(recs),
            "tokens_in": sum(r.tokens_in for r in recs),
            "tokens_out": sum(r.tokens_out for r in recs),
            "tool_calls": sum(sum(r.tool_calls.values()) for r in recs),
            "turns": sum(r.turns for r in recs),
            "errors": sum(1 for r in recs if r.error),
            "by_tool": _sum_dicts(r.tool_calls for r in recs),
            "reads_per_query": (sum(len(r.read_ids) for r in recs) / len(recs)) if recs else 0,
            "answered_without_reading": sum(1 for r in recs if not r.read_ids and not r.error),
            "model": f"{self.provider}:{self.model}",
            "strict": self.strict,
            "count_surfaced": self.count_surfaced,
        }
        price = PRICES.get(self.model)
        if price:
            out["usd"] = out["tokens_in"] * price[0] / 1e6 + out["tokens_out"] * price[1] / 1e6
        return out

    # ------------------------------------------------------------------- loop
    def _run(self, query: str) -> LoopRecord:
        with self._lock:
            if query in self.records:
                return self.records[query]
        key = self.cache.key("api_loop", self.provider, self.model, self.max_turns, self.fingerprint, query, self.strict)
        cached = self.cache.get(key)
        if cached:
            rec = LoopRecord(**cached)
        else:
            rec = self._loop(query)
            if not rec.error:  # never cache a failed run; the next run should retry it
                self.cache.put(key, rec.__dict__)
        with self._lock:
            self.records[query] = rec
        return rec

    def _tool(self, name: str, args: dict, rec: LoopRecord | None = None) -> str:
        with self._sql_lock:
            try:
                out = call(self.ops, name, args)
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
        if rec is not None and isinstance(out, dict):
            for item in out.get("hits", []) + out.get("matches", []):
                if item.get("id"):
                    rec.surfaced_ids.append(item["id"])
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

    def _suffix(self) -> str:
        return STRICT_SUFFIX if self.strict else USER_SUFFIX

    def _loop(self, query: str) -> LoopRecord:
        rec = LoopRecord()
        t0 = time.perf_counter()
        try:
            if self.provider == "openai":
                self._loop_openai(query, rec)
            elif self.provider == "anthropic":
                self._loop_anthropic(query, rec)
            else:
                raise ValueError(f"unknown provider {self.provider!r}")
        except Exception as e:
            rec.error = f"{type(e).__name__}: {str(e)[:300]}"
        rec.ms = (time.perf_counter() - t0) * 1000
        return rec

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        data = json.dumps(body).encode()
        delay = 1.0
        for attempt in range(5):
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(delay)
                    delay = min(delay * 2, 20)
                    continue
                raise RuntimeError(f"HTTP {e.code}: {text[:300]}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 4:
                    time.sleep(delay)
                    delay = min(delay * 2, 20)
                    continue
                raise
        raise RuntimeError("unreachable")

    def _loop_openai(self, query: str, rec: LoopRecord) -> None:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": query + self._suffix()}]
        tools = openai_tools()
        for _ in range(self.max_turns):
            body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto"}
            if self.model.startswith(("gpt-5", "o1", "o3", "o4")):
                # Chat completions only allows function tools with reasoning off for these models.
                body["reasoning_effort"] = "none"
            resp = self._post(f"{base}/chat/completions", headers, body)
            rec.turns += 1
            usage = resp.get("usage", {})
            rec.tokens_in += usage.get("prompt_tokens", 0)
            rec.tokens_out += usage.get("completion_tokens", 0)
            msg = resp["choices"][0]["message"]
            messages.append(msg)
            if not msg.get("tool_calls"):
                rec.answer = msg.get("content") or ""
                return
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                rec.tool_calls[name] = rec.tool_calls.get(name, 0) + 1
                if name == "read" and args.get("id"):
                    rec.read_ids.append(str(args["id"]))
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": self._tool(name, args, rec)})
        rec.error = "max_turns reached"

    def _loop_anthropic(self, query: str, rec: LoopRecord) -> None:
        headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        messages = [{"role": "user", "content": query + self._suffix()}]
        for _ in range(self.max_turns):
            body = {"model": self.model, "max_tokens": 2048, "system": self.system, "messages": messages, "tools": TOOLS}
            resp = self._post("https://api.anthropic.com/v1/messages", headers, body)
            rec.turns += 1
            usage = resp.get("usage", {})
            rec.tokens_in += usage.get("input_tokens", 0)
            rec.tokens_out += usage.get("output_tokens", 0)
            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})
            uses = [b for b in content if b.get("type") == "tool_use"]
            if resp.get("stop_reason") != "tool_use" or not uses:
                rec.answer = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                return
            results = []
            for u in uses:
                name, args = u["name"], u.get("input") or {}
                rec.tool_calls[name] = rec.tool_calls.get(name, 0) + 1
                if name == "read" and args.get("id"):
                    rec.read_ids.append(str(args["id"]))
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": self._tool(name, args, rec)})
            messages.append({"role": "user", "content": results})
        rec.error = "max_turns reached"


def _sum_dicts(dicts) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out

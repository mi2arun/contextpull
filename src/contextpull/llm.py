"""Provider-agnostic completion wrapper used only at ingest time, for one-line
document summaries. Plain urllib, no SDKs. Results are cached by the caller in
the store's ``summary_cache`` table, keyed by document hash, so this module has
no cache of its own.

Model spec: ``provider:model`` — ``openai:gpt-5.4-mini``, ``anthropic:claude-…``.
A bare name starting with ``claude`` means anthropic, anything else openai.
``OPENAI_BASE_URL`` redirects the OpenAI-compatible path to any compatible server.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_SUMMARIZER = "openai:gpt-5.4-mini"

SUMMARY_SYSTEM = (
    "You write one-line summaries for a table of contents that an AI assistant reads to decide which document to open. "
    "Given a document's title, its headings and the start of its text, write ONE line, at most 110 characters, "
    "that says what the document covers and what a reader would look it up for. No trailing period, no quotes, "
    "no restating the title. Prefer concrete nouns: settings, commands, error codes, policies."
)


class LLMError(Exception):
    pass


def parse_model(spec: str) -> tuple[str, str]:
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return provider.lower(), model
    return ("anthropic", spec) if spec.startswith("claude") else ("openai", spec)


def _post(url: str, headers: dict[str, str], body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode()
    delay = 1.0
    for attempt in range(5):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code in (408, 409, 429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(delay)
                delay = min(delay * 2, 20)
                continue
            raise LLMError(f"HTTP {e.code} from {url}: {text[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(delay)
                delay = min(delay * 2, 20)
                continue
            raise LLMError(f"network error calling {url}: {e}") from e
    raise LLMError("unreachable")


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise LLMError(f"{name} is not set")
    return v


class LLM:
    def __init__(self, spec: str = DEFAULT_SUMMARIZER, timeout: float = 60.0):
        self.provider, self.model = parse_model(spec)
        self.spec = f"{self.provider}:{self.model}"
        self.timeout = timeout
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(self, prompt: str, system: str | None = None, max_tokens: int = 200) -> str:
        if self.provider == "openai":
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
            body: dict = {"model": self.model, "messages": messages}
            if self.model.startswith(("gpt-5", "o1", "o3", "o4")):
                # Reasoning tokens count against the completion budget; keep reasoning off for a one-liner.
                body["reasoning_effort"] = "none"
                body["max_completion_tokens"] = max_tokens * 4
            else:
                body["temperature"] = 0
                body["max_tokens"] = max_tokens
            resp = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {_env('OPENAI_API_KEY')}"}, body, self.timeout)
            usage = resp.get("usage", {})
            self._count(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
            return resp["choices"][0]["message"]["content"]
        if self.provider == "anthropic":
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}
            if system:
                body["system"] = system
            resp = _post(
                "https://api.anthropic.com/v1/messages",
                {"x-api-key": _env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
                body,
                self.timeout,
            )
            usage = resp.get("usage", {})
            self._count(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            return "".join(b.get("text", "") for b in resp.get("content", []))
        raise LLMError(f"unknown provider {self.provider!r}; use openai:<model> or anthropic:<model>")

    def _count(self, p: int, c: int) -> None:
        self.calls += 1
        self.prompt_tokens += p
        self.completion_tokens += c

    def summarize(self, title: str, headings: str, head_text: str) -> str:
        prompt = f"Title: {title}\n\nHeadings:\n{headings[:1200]}\n\nStart of text:\n{head_text[:1500]}"
        lines = [l for l in self.complete(prompt, system=SUMMARY_SYSTEM, max_tokens=100).strip().splitlines() if l.strip()]
        out = (lines[0] if lines else "").strip().strip('"').rstrip(".")[:160]
        if not out:
            raise LLMError("model returned an empty summary")
        return out

    def spend(self) -> str:
        return f"{self.calls} calls, {self.prompt_tokens:,} in / {self.completion_tokens:,} out tokens"

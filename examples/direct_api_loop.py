"""Embedding recipe: ContextPull tools in your own model loop, no MCP, no server.

    export CONTEXTPULL_STORE=.contextpull/store.sqlite OPENAI_API_KEY=...
    python examples/direct_api_loop.py "What changed in the refund window between 2024 and 2025?"

Uses the OpenAI chat completions API with plain urllib so the example has no
dependencies beyond contextpull itself. Swap the request body for the Anthropic
Messages API and pass ``contextpull.tools.TOOLS`` directly; the shapes match.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from contextpull import Ops, Store
from contextpull.tools import call, openai_tools

MODEL = os.environ.get("CONTEXTPULL_LOOP_MODEL", "gpt-5.4-mini")
SYSTEM = (
    "You answer questions about a document corpus using tools. The index below lists every document. "
    "Search for pointers, read the sections you need verbatim, then answer citing section ids like [path.md#3]. "
    "Never answer from memory; if the corpus does not contain the answer, say so.\n\n"
)


def chat(messages: list[dict], tools: list[dict]) -> dict:
    body = {"model": MODEL, "messages": messages, "tools": tools, "tool_choice": "auto"}
    req = urllib.request.Request(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main(question: str, max_turns: int = 8) -> None:
    with Store.open(os.environ.get("CONTEXTPULL_STORE", ".contextpull/store.sqlite")) as store:
        ops = Ops(store)
        messages = [{"role": "system", "content": SYSTEM + ops.index()}, {"role": "user", "content": question}]
        read_ids: list[str] = []
        for turn in range(max_turns):
            resp = chat(messages, openai_tools())
            msg = resp["choices"][0]["message"]
            messages.append(msg)
            if not msg.get("tool_calls"):
                print(msg.get("content", ""))
                break
            for tc in msg["tool_calls"]:
                name, args = tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}")
                print(f"  → {name}({json.dumps(args)})", file=sys.stderr)
                try:
                    result = call(ops, name, args)
                except Exception as e:  # tool errors go back to the model as text
                    result = {"error": str(e)}
                if name == "read":
                    read_ids.append(args.get("id", ""))
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result if isinstance(result, str) else json.dumps(result)})
        print(f"\nsections read: {read_ids}", file=sys.stderr)


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "What changed in the refund window between the 2024 and 2025 policy?")

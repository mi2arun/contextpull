"""ragbisect adapter over ContextPull's lexical `search`.

    export CONTEXTPULL_STORE=.contextpull/store.sqlite
    contextpull export-chunks > chunks.jsonl
    ragbisect run --corpus chunks.jsonl --adapter examples/ragbisect_adapter.py:ContextPullSearch

This measures the search tool alone as a one-shot retriever, next to
ragbisect's built-in bm25 / dense / hybrid over the same sections. The full
agentic loop (M3) is a different adapter.
"""

from __future__ import annotations

import os

from contextpull import Ops, Store


class ContextPullSearch:
    def __init__(self) -> None:
        self.store = Store.open(os.environ.get("CONTEXTPULL_STORE", ".contextpull/store.sqlite"))
        self.ops = Ops(self.store)

    def retrieve(self, query: str, k: int) -> list[str]:
        return [h.id for h in self.ops.search(query, limit=k).hits]


class ContextPullHybrid(ContextPullSearch):
    """search(mode="hybrid"): lexical fused with stored embeddings by reciprocal rank.
    The store must have been ingested with --embed-model; the query is embedded at query time."""

    def retrieve(self, query: str, k: int) -> list[str]:
        return [h.id for h in self.ops.search(query, limit=k, mode="hybrid").hits]

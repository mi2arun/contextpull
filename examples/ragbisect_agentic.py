"""ragbisect adapters for the agentic configurations (M3).

    contextpull export-chunks --store STORE > chunks.jsonl
    export CONTEXTPULL_STORE=STORE
    ragbisect run --corpus chunks.jsonl --adapter examples/ragbisect_agentic.py:ApiLoop          # ids read, default prompt
    ragbisect run --corpus chunks.jsonl --adapter examples/ragbisect_agentic.py:ApiLoopStrict    # ids read, no answering from snippets
    ragbisect run --corpus chunks.jsonl --adapter examples/ragbisect_agentic.py:ApiLoopSurfaced  # ids read + ids seen in results
    ragbisect run --corpus chunks.jsonl --adapter examples/ragbisect_agentic.py:ClaudeCode --sample 20

Model for ApiLoop from CONTEXTPULL_LOOP_MODEL (default openai:gpt-5.4-mini).
"""

from __future__ import annotations

import os

from contextpull.eval import ApiLoopRetriever, ClaudeCodeRetriever


class ApiLoop(ApiLoopRetriever):
    def __init__(self) -> None:
        super().__init__(model=os.environ.get("CONTEXTPULL_LOOP_MODEL", "openai:gpt-5.4-mini"))


class ApiLoopStrict(ApiLoopRetriever):
    """Same loop, with rules forbidding answers from snippets; ids read only."""

    def __init__(self) -> None:
        super().__init__(model=os.environ.get("CONTEXTPULL_LOOP_MODEL", "openai:gpt-5.4-mini"), strict=True)


class ApiLoopSurfaced(ApiLoopRetriever):
    """Default prompt; credits ids the model saw in search/grep results after the ones it read."""

    def __init__(self) -> None:
        super().__init__(model=os.environ.get("CONTEXTPULL_LOOP_MODEL", "openai:gpt-5.4-mini"), count_surfaced=True)


class ClaudeCode(ClaudeCodeRetriever):
    def __init__(self) -> None:
        super().__init__(model=os.environ.get("CONTEXTPULL_CC_MODEL") or None)

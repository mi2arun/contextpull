"""ragbisect adapters that measure ContextPull's agentic loop (M3).

Both satisfy ragbisect's one-method protocol, ``retrieve(query, k) -> list[str]``,
by running a tool loop and returning the section ids the model **read**, in
the order it read them. Ids that only appeared in ``search`` results do not
count: the model did not look at them. They also expose ``generate`` (the
loop's final answer, for faithfulness judging), ``stats()`` (tokens, tool
calls, dollars) and ``concurrency`` so ragbisect runs them in parallel.

    ApiLoopRetriever   — direct model API (OpenAI-compatible or Anthropic), no server
    ClaudeCodeRetriever — drives `claude -p` headless with the MCP server attached
"""

from .api_loop import ApiLoopRetriever
from .claude_code import ClaudeCodeRetriever

__all__ = ["ApiLoopRetriever", "ClaudeCodeRetriever"]

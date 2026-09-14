"""Live agent scenarios: complex questions through the real pull loop, with
expectations on what gets read and what the answer must contain.

    CONTEXTPULL_STORE=/tmp/scenario.sqlite uv run python scripts/scenario_agent.py [api|claude] [model]

Costs a few cents per run with a mini model; about $0.30 a question with Claude Code.
"""

from __future__ import annotations

import os
import re
import sys

from contextpull.eval import ApiLoopRetriever, ClaudeCodeRetriever

SCENARIOS = [
    {
        "name": "comparison across versions",
        "q": "How did the warranty coverage period and the claim window change between the 2024 and 2025 policies?",
        "reads_any": [["policies/warranty-2024.md#1", "policies/warranty-2024.md#2"], ["policies/warranty-2025.md#1", "policies/warranty-2025.md#2"]],
        "answer_all": ["24", "36", "30", "14"],
    },
    {
        "name": "aggregation across files",
        "q": "List every WR- error code documented for the controller and the drive unit, and say how many there are in total.",
        "reads_any": [["reference/error-codes-controller.md#1", "reference/error-codes-controller.md#2"], ["reference/error-codes-drive.md#1", "reference/error-codes-drive.md#2"]],
        "answer_all": ["WR-2201", "WR-2302", "WR-3107", "WR-3202"],
        "answer_regex": r"\b10\b",
    },
    {
        "name": "table cell",
        "q": "What is the operating temperature range and the weight of the R-40?",
        "reads_any": [["products/spec-sheet.md#1"]],
        "answer_all": ["-5", "40", "21"],
    },
    {
        "name": "procedure next step",
        "q": "In procedure P-40, after reseating the sensor harness connector, what must be verified and within how long?",
        "reads_any": [["procedures/p40-sensor-harness.md#4", "procedures/p40-sensor-harness.md#5"]],
        "answer_all": ["WR-2205", "60"],
    },
    {
        "name": "cross-format lookup in a spreadsheet",
        "q": "What is the part number and unit price of the heavy-duty brake pad set, and which models does it fit?",
        "reads_any": [["products/parts-list.xlsx#0"]],
        "answer_all": ["PN-88121", "72.5", "R-70"],
    },
    {
        "name": "multi-hop across reference and policy",
        "q": "A unit shows WR-2201 then WR-3101 ten seconds later, shipped in 2025. Is the warranty claim valid, and are these one incident or two?",
        "reads_any": [["reference/error-codes-drive.md#3", "reference/error-codes-drive.md#0", "reference/error-codes-drive.md#1", "reference/error-codes-drive.md#2"], ["policies/warranty-2025.md#3", "reference/error-codes-controller.md#1"]],
        "answer_all": ["void"],
        "answer_regex": r"(same|one) incident|consequence",
    },
]


def main(kind: str, model: str | None) -> int:
    store = os.environ.get("CONTEXTPULL_STORE", "/tmp/scenario.sqlite")
    if kind == "claude":
        r = ClaudeCodeRetriever(store, model=model, cache_path="/tmp/scenario-eval-cache.sqlite")
    else:
        r = ApiLoopRetriever(store, model=model or "openai:gpt-5.4-mini", strict=True, cache_path="/tmp/scenario-eval-cache.sqlite")
    passed = 0
    print(f"{'scenario':<38} {'reads ok':<9} {'answer ok':<10} calls  reads  detail")
    for sc in SCENARIOS:
        ids = r.retrieve(sc["q"], 20)
        rec = r.records[sc["q"]]
        ans = rec.answer or ""
        reads_ok = all(any(i in ids for i in group) for group in sc["reads_any"])
        ans_ok = all(v in ans for v in sc["answer_all"]) and (re.search(sc.get("answer_regex", ""), ans, re.I) is not None if sc.get("answer_regex") else True)
        ok = reads_ok and ans_ok and not rec.error
        passed += ok
        calls = sum(rec.tool_calls.values())
        detail = rec.error or ("" if ok else f"missing={[v for v in sc['answer_all'] if v not in ans]} read={ids[:4]}")
        print(f"{sc['name']:<38} {str(reads_ok):<9} {str(ans_ok):<10} {calls:<6} {len(rec.read_ids):<6} {detail[:80]}")
    st = r.stats()
    print(f"\n{passed}/{len(SCENARIOS)} scenarios passed | {st.get('tool_calls')} tool calls, {st.get('tokens_in', 0):,} in / {st.get('tokens_out', 0):,} out tokens" + (f", ≈ ${st['usd']:.2f}" if st.get("usd") else "") + f" | model {st.get('model')}")
    return 0 if passed == len(SCENARIOS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "api", sys.argv[2] if len(sys.argv) > 2 else None))

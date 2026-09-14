"""Conformance runner and case generator (Python is the oracle).

  python conformance/run.py generate   # rebuild store.sqlite + cases.json from corpus/
  python conformance/run.py check      # run cases.json against this implementation

Other-language SDKs implement the same `check` over the same store.sqlite and
cases.json. Regex grep and hybrid search are deliberately absent (host engine /
external model dependent).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from contextpull.ingest import ingest  # noqa: E402
from contextpull.ops import Ops, OpsError  # noqa: E402
from contextpull.store import Store  # noqa: E402

SUITES = {
    "default": (HERE / "corpus", HERE / "store.sqlite", HERE / "cases.json"),
    "scenarios": (HERE / "scenarios" / "corpus", HERE / "scenarios" / "store.sqlite", HERE / "scenarios" / "cases.json"),
}
STORE = HERE / "store.sqlite"
CASES = HERE / "cases.json"

SCENARIO_CALLS: list[dict] = [
    {"op": "index", "args": {}},
    {"op": "index", "args": {"prefix": "reference/"}},
    {"op": "search", "args": {"query": "coverage period", "in": ["policies/warranty-2024.md"]}},
    {"op": "search", "args": {"query": "coverage period", "in": ["policies/warranty-2025.md"]}},
    {"op": "search", "args": {"query": "warranty coverage period months", "limit": 5}},
    {"op": "search", "args": {"query": "claim window"}},
    {"op": "search", "args": {"query": "R-40 operating temp"}},
    {"op": "search", "args": {"query": "R-120 storage temp"}},
    {"op": "search", "args": {"query": "reseat connector latch pull straight out"}},
    {"op": "search", "args": {"query": "main bearing bolt torque"}},
    {"op": "search", "args": {"query": "claim serial number fifteen days"}},
    {"op": "search", "args": {"query": "WR-2205"}},
    {"op": "search", "args": {"query": "WR-2201 surge event", "limit": 8}},
    {"op": "search", "args": {"query": "ATEX zone 2"}},
    {"op": "search", "args": {"query": "RCTL_WATCHDOG_MS default"}},
    {"op": "search", "args": {"query": "brake pad heavy duty price", "in": ["products"]}},
    {"op": "read", "args": {"id": "policies/warranty-2025.md#2", "context": 1}},
    {"op": "read", "args": {"id": "products/spec-sheet.md#1"}},
    {"op": "read", "args": {"id": "procedures/p40-sensor-harness.md#4"}},
    {"op": "read", "args": {"id": "products/parts-list.xlsx#0"}},
    {"op": "grep", "args": {"pattern": "WR-", "limit": 100}},
    {"op": "grep", "args": {"pattern": "WR-22", "in": ["reference/error-codes-controller.md"]}},
    {"op": "grep", "args": {"pattern": "WR-320"}},
    {"op": "grep", "args": {"pattern": "PN-88121"}},
    {"op": "grep", "args": {"pattern": "ALLOW_DOWNGRADE"}},
    {"op": "neighbours", "args": {"id": "procedures/p40-sensor-harness.md#4", "before": 0, "after": 1}},
    {"op": "neighbours", "args": {"id": "products/spec-sheet.md#1", "before": 1, "after": 1}},
]

CALLS: list[dict] = [
    {"op": "index", "args": {}},
    {"op": "index", "args": {"prefix": "policies/"}},
    {"op": "search", "args": {"query": "TX-4419"}},
    {"op": "search", "args": {"query": "refund window"}},
    {"op": "search", "args": {"query": "refund window", "in": ["policies/policy-2024.md", "policies/policy-2025.md"]}},
    {"op": "search", "args": {"query": "refund", "in": ["policies"]}},
    {"op": "search", "args": {"query": "store credit expire"}},
    {"op": "search", "args": {"query": "R-40 storage temp"}},
    {"op": "search", "args": {"query": "no-cache flag"}},
    {"op": "search", "args": {"query": "GATEWAY_TIMEOUT_MS"}},
    {"op": "search", "args": {"query": "installation requirements python", "limit": 3}},
    {"op": "search", "args": {"query": "zzzz-nothing-here"}},
    {"op": "read", "args": {"id": "policies/policy-2025.md#2"}},
    {"op": "read", "args": {"id": "policies/policy-2025.md#2", "context": 1}},
    {"op": "read", "args": {"id": "specs.md#1"}},
    {"op": "read", "args": {"id": "missing.md#0"}},
    {"op": "grep", "args": {"pattern": "TX-4419"}},
    {"op": "grep", "args": {"pattern": "refund", "limit": 3}},
    {"op": "grep", "args": {"pattern": "retry", "in": ["errors.md"]}},
    {"op": "grep", "args": {"pattern": "°C", "limit": 2}},
    {"op": "neighbours", "args": {"id": "policies/policy-2025.md#2"}},
    {"op": "neighbours", "args": {"id": "guides/getting-started.md#0", "before": 0, "after": 2}},
    {"op": "neighbours", "args": {"id": "specs.md#1", "before": 1, "after": 1}},
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def run_call(ops: Ops, op: str, args: dict) -> dict:
    """Reduce a result to the comparable projection: ids and order, plus text hashes."""
    try:
        if op == "index":
            return {"text_sha": _sha(ops.index(args.get("prefix")))}
        if op == "search":
            r = ops.search(args["query"], args.get("in"), args.get("limit", 10), args.get("mode", "lexical"))
            return {"ids": [h.id for h in r.hits], "mode": r.mode, "empty": not r.hits}
        if op == "read":
            r = ops.read(args["id"], args.get("context", 0))
            return {"id": r.section.id, "text_sha": _sha(r.section.text), "heading_path": r.section.heading_path,
                    "context_ids": [c.id for c in r.context], "prev": r.section.prev_id, "next": r.section.next_id}
        if op == "grep":
            r = ops.grep(args["pattern"], args.get("in"), False, args.get("limit", 20))
            return {"ids": [m.id for m in r.matches], "lines_sha": [_sha(m.line) for m in r.matches], "truncated": r.truncated}
        if op == "neighbours":
            r = ops.neighbours(args["id"], args.get("before", 1), args.get("after", 1))
            return {"ids": [s.id for s in r.sections], "header": r.header.id if r.header else None}
    except OpsError as e:
        return {"error": True}
    raise KeyError(op)


def generate(suite: str = "default") -> None:
    corpus, STORE, CASES = SUITES[suite]
    CALLS_ = CALLS if suite == "default" else SCENARIO_CALLS
    if STORE.exists():
        STORE.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(STORE) + suffix)
        if p.exists():
            p.unlink()
    rep = ingest(corpus, STORE)
    # checkpoint WAL so the file is self-contained for other readers
    with Store.open(STORE, readonly=False) as s:
        s.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        s.conn.execute("PRAGMA journal_mode=DELETE")
        s.conn.commit()
    with Store.open(STORE) as s:
        ops = Ops(s)
        cases = [{"op": c["op"], "args": c["args"], "expect": run_call(ops, c["op"], c["args"])} for c in CALLS_]
        meta = {"store_schema": s.meta_get("schema_version"), "corpus_fingerprint": s.meta_get("corpus_fingerprint"),
                "documents": s.counts()[0], "sections": s.counts()[1]}
    CASES.write_text(json.dumps({"meta": meta, "cases": cases}, indent=2, ensure_ascii=False) + "\n")
    print(f"generated {len(cases)} cases; store {rep.corpus_fingerprint}, {meta['documents']} docs, {meta['sections']} sections")


def check(suite: str = "default") -> int:
    _, STORE, CASES = SUITES[suite]
    data = json.loads(CASES.read_text())
    failures = 0
    with Store.open(STORE) as s:
        ops = Ops(s)
        for c in data["cases"]:
            got = run_call(ops, c["op"], c["args"])
            if got != c["expect"]:
                failures += 1
                print(f"FAIL {c['op']} {json.dumps(c['args'])}\n  expect {c['expect']}\n  got    {got}")
    print(f"{len(data['cases']) - failures}/{len(data['cases'])} conformance cases pass ({suite})")
    return 1 if failures else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    suites = sys.argv[2:] or ["default"]
    if suites == ["all"]:
        suites = list(SUITES)
    rc = 0
    for suite in suites:
        if cmd == "generate":
            generate(suite)
        else:
            rc |= check(suite)
    sys.exit(rc)

"""``contextpull`` command line.

    contextpull ingest ./docs                 build or update .contextpull/store.sqlite
    contextpull index [--prefix guides/]      print the index text
    contextpull search "refund window" --in policy-2025.md
    contextpull read policy-2025.md#3 --context 1
    contextpull grep TX-4419
    contextpull neighbours specs.md#7
    contextpull export-chunks > chunks.jsonl  stagewise-compatible sections
    contextpull tools-json > tools.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .ingest import export_chunks, ingest
from .ops import Ops, OpsError
from .store import Store, StoreError
from .tools import tools_json

DEFAULT_STORE = ".contextpull/store.sqlite"
STORE_IN_CORPUS = ".contextpull/store.sqlite"  # used by `serve <dir>`


def _eprint(*a: object) -> None:
    print(*a, file=sys.stderr, flush=True)


def _env(name: str, default: str) -> str:
    return os.environ.get(f"CONTEXTPULL_{name}", default)


def _store_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--store", default=_env("STORE", DEFAULT_STORE), help=f"store file (default: {DEFAULT_STORE})")


def _json_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print JSON instead of text")


def _summarizer(spec: str | None):
    if not spec or spec == "offline":
        return None, "offline"
    from .llm import LLM

    llm = LLM(spec)
    return llm, llm.spec


def _run_ingest(a: argparse.Namespace):
    llm, name = _summarizer(getattr(a, "summarizer", None))
    rep = ingest(
        a.corpus,
        a.store,
        max_chars=a.max_chars,
        min_chars=a.min_chars,
        heading_depth=a.heading_depth,
        index_budget_tokens=a.index_budget,
        summarizer=llm.summarize if llm else None,
        summarizer_name=name,
        progress=_eprint if getattr(a, "verbose", False) else None,
    )
    if llm and llm.calls:
        _eprint(f"summaries: {llm.spend()}")
    return rep


def cmd_ingest(a: argparse.Namespace) -> int:
    rep = _run_ingest(a)
    if a.json:
        print(json.dumps(rep.to_dict(), indent=2))
        return 0
    print(
        f"{rep.seen} documents seen: {rep.changed} changed, {rep.unchanged} unchanged, {rep.deleted} deleted, {len(rep.skipped)} skipped\n"
        f"{rep.sections_written} sections written; summaries: {rep.summaries_llm} llm, {rep.summaries_offline} offline"
        + (f" ({rep.summary_errors} model errors, first: {rep.first_summary_error})" if rep.summary_errors else "") + "\n"
        f"index: {rep.index_mode}, ≈{rep.index_tokens} tokens; corpus {rep.corpus_fingerprint}; store {a.store}"
    )
    for path, why in rep.skipped[:20]:
        print(f"  skipped {path}: {why}")
    return 0


def _with_ops(a: argparse.Namespace, fn) -> int:
    try:
        with Store.open(a.store, readonly=True) as store:
            return fn(Ops(store))
    except StoreError as e:
        _eprint(f"error: {e}")
        return 1
    except OpsError as e:
        if getattr(a, "json", False):
            print(json.dumps(e.to_dict()))
        else:
            _eprint(f"error: {e.message}" + (f" ({e.suggestion})" if e.suggestion else ""))
        return 2


def cmd_index(a: argparse.Namespace) -> int:
    return _with_ops(a, lambda ops: (print(ops.index(a.prefix)), 0)[1])


def cmd_search(a: argparse.Namespace) -> int:
    def run(ops: Ops) -> int:
        res = ops.search(a.query, a.in_, a.limit, a.mode)
        if a.json:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
            return 0
        for h in res.hits:
            print(f"{h.score:>6.2f}  {h.id:<40} {h.heading_path}\n        {h.snippet}")
        if res.hint:
            print(f"hint: {res.hint}")
        return 0

    return _with_ops(a, run)


def cmd_read(a: argparse.Namespace) -> int:
    def run(ops: Ops) -> int:
        res = ops.read(a.id, a.context)
        if a.json:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
            return 0
        for c in [x for x in res.context if x.id < res.section.id]:
            print(f"--- context {c.id} · {c.heading_path}\n{c.text}\n")
        print(f"=== {res.section.id} · {res.section.heading_path} · {res.section.kind}\n{res.section.text}")
        for c in [x for x in res.context if x.id > res.section.id]:
            print(f"\n--- context {c.id} · {c.heading_path}\n{c.text}")
        return 0

    return _with_ops(a, run)


def cmd_grep(a: argparse.Namespace) -> int:
    def run(ops: Ops) -> int:
        res = ops.grep(a.pattern, a.in_, a.regex, a.limit)
        if a.json:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
            return 0
        for m in res.matches:
            print(f"{m.id:<40} {m.line}")
        if res.truncated:
            print("… truncated; raise --limit or narrow with --in")
        return 0

    return _with_ops(a, run)


def cmd_neighbours(a: argparse.Namespace) -> int:
    def run(ops: Ops) -> int:
        res = ops.neighbours(a.id, a.before, a.after)
        if a.json:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if res.header:
            print(f"=== header {res.header.id}\n{res.header.text.splitlines()[0]}\n")
        for s in res.sections:
            mark = ">>" if s.id == a.id else "  "
            print(f"{mark} {s.id} · {s.heading_path}\n{s.text}\n")
        return 0

    return _with_ops(a, run)


def cmd_export(a: argparse.Namespace) -> int:
    def run(ops: Ops) -> int:
        for line in export_chunks(ops.store):
            print(line)
        return 0

    return _with_ops(a, run)


def cmd_serve(a: argparse.Namespace) -> int:
    try:
        from .server import serve_stdio
    except ImportError as e:
        _eprint(f"error: {e}")
        return 1
    import asyncio

    p = Path(a.path)
    if p.is_dir():
        store = Path(a.store) if a.store else p / STORE_IN_CORPUS
        if not a.no_ingest:
            a.corpus, a.store = str(p), str(store)
            rep = _run_ingest(a)
            _eprint(f"ingest: {rep.changed} changed, {rep.unchanged} unchanged, {rep.deleted} deleted; index {rep.index_mode} ≈{rep.index_tokens} tokens")
    elif p.is_file():
        store = p
    else:
        _eprint(f"error: {p} is neither a directory nor a store file")
        return 1
    try:
        asyncio.run(serve_stdio(store, log=a.log))
    except StoreError as e:
        _eprint(f"error: {e}")
        return 1
    return 0


def cmd_claude_md(a: argparse.Namespace) -> int:
    from .server import CLAUDE_MD_SNIPPET

    sys.stdout.write(CLAUDE_MD_SNIPPET)
    return 0


def cmd_tools_json(a: argparse.Namespace) -> int:
    sys.stdout.write(tools_json())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="contextpull", description="Pull, don't push: exact sections on demand for LLM agents.")
    p.add_argument("--version", action="version", version=f"contextpull {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("ingest", help="build or update the store from a corpus directory")
    g.add_argument("corpus")
    _store_arg(g)
    g.add_argument("--max-chars", type=int, default=int(_env("SECTION_MAX_CHARS", "2000")))
    g.add_argument("--min-chars", type=int, default=int(_env("SECTION_MIN_CHARS", "40")))
    g.add_argument("--heading-depth", type=int, default=int(_env("SECTION_HEADING_DEPTH", "4")))
    g.add_argument("--index-budget", type=int, default=int(_env("INDEX_BUDGET_TOKENS", "3000")), help="index token budget")
    g.add_argument("--summarizer", default=_env("SUMMARIZER", "offline"), help="provider:model for one-line document summaries, or 'offline' (default)")
    g.add_argument("-v", "--verbose", action="store_true")
    _json_arg(g)
    g.set_defaults(func=cmd_ingest)

    g = sub.add_parser("serve", help="run the MCP server over stdio (needs the 'mcp' extra)")
    g.add_argument("path", help="a corpus directory (ingested into <dir>/.contextpull/store.sqlite first) or a store .sqlite file")
    g.add_argument("--store", default=None, help="store file to use/create when PATH is a directory")
    g.add_argument("--no-ingest", action="store_true", help="do not ingest before serving a directory")
    g.add_argument("--max-chars", type=int, default=int(_env("SECTION_MAX_CHARS", "2000")))
    g.add_argument("--min-chars", type=int, default=int(_env("SECTION_MIN_CHARS", "40")))
    g.add_argument("--heading-depth", type=int, default=int(_env("SECTION_HEADING_DEPTH", "4")))
    g.add_argument("--index-budget", type=int, default=int(_env("INDEX_BUDGET_TOKENS", "3000")))
    g.add_argument("--summarizer", default=_env("SUMMARIZER", "offline"))
    g.add_argument("--log", action="store_true", help="log one line per tool call to stderr")
    g.set_defaults(func=cmd_serve)

    g = sub.add_parser("claude-md", help="print a CLAUDE.md snippet describing how to use the server")
    g.set_defaults(func=cmd_claude_md)

    g = sub.add_parser("index", help="print the index text")
    _store_arg(g)
    g.add_argument("--prefix", default=None)
    g.set_defaults(func=cmd_index)

    g = sub.add_parser("search", help="find sections; returns ids and snippets")
    g.add_argument("query")
    _store_arg(g)
    g.add_argument("--in", dest="in_", action="append", metavar="PATH_OR_GLOB")
    g.add_argument("--limit", type=int, default=10)
    g.add_argument("--mode", choices=["lexical", "hybrid"], default="lexical")
    _json_arg(g)
    g.set_defaults(func=cmd_search)

    g = sub.add_parser("read", help="print one section verbatim")
    g.add_argument("id")
    _store_arg(g)
    g.add_argument("--context", type=int, default=0)
    _json_arg(g)
    g.set_defaults(func=cmd_read)

    g = sub.add_parser("grep", help="exact substring or regex match")
    g.add_argument("pattern")
    _store_arg(g)
    g.add_argument("--in", dest="in_", action="append", metavar="PATH_OR_GLOB")
    g.add_argument("--regex", action="store_true")
    g.add_argument("--limit", type=int, default=20)
    _json_arg(g)
    g.set_defaults(func=cmd_grep)

    g = sub.add_parser("neighbours", help="adjacent sections")
    g.add_argument("id")
    _store_arg(g)
    g.add_argument("--before", type=int, default=1)
    g.add_argument("--after", type=int, default=1)
    _json_arg(g)
    g.set_defaults(func=cmd_neighbours)

    g = sub.add_parser("export-chunks", help="stagewise-compatible JSONL of all sections")
    _store_arg(g)
    g.set_defaults(func=cmd_export)

    g = sub.add_parser("tools-json", help="print the tool definitions")
    g.set_defaults(func=cmd_tools_json)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except FileNotFoundError as e:
        _eprint(f"error: {e}")
        return 1
    except (StoreError, OpsError) as e:
        _eprint(f"error: {e}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

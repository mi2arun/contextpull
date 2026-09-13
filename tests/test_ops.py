import pytest

from contextpull.ops import Ops, OpsError, tokenize
from contextpull.tools import TOOLS, call, openai_tools


def test_normalize_for_fts():
    from contextpull.ops import normalize_for_fts
    assert normalize_for_fts("Use `--no-cache` or -p. Version 3.12. See tool.uv.sources, e.g. TX-4419.") == \
        "Use `no-cache` or p Version 3.12 See tool.uv.sources, e.g TX-4419"


def test_flags_and_sentence_final_words_are_searchable(store):
    ops = Ops(store)
    assert ops.search("no-cache").hits[0].id == "guides/getting-started.md#2"
    assert ops.search("--no-cache").hits[0].id == "guides/getting-started.md#2"
    assert ops.grep("--no-cache").matches[0].id == "guides/getting-started.md#2"
    # "packaging." ends a sentence in the policy docs
    assert {h.doc for h in ops.search("packaging").hits} >= {"policies/policy-2024.md", "policies/policy-2025.md"}


def test_tokenize_keeps_identifiers():
    assert tokenize("Set GATEWAY_TIMEOUT_MS or pass --no-cache; error TX-4419 on 3.12.") == [
        "set", "gateway_timeout_ms", "or", "pass", "no-cache", "error", "tx-4419", "on", "3.12"]


def test_search_identifier_first(store):
    ops = Ops(store)
    res = ops.search("TX-4419")
    assert res.hits and res.hits[0].id.startswith("errors.md#")
    assert "TX-4419" in res.hits[0].snippet
    assert res.hits[0].kind in ("table", "mixed")


def test_search_phrase_first_then_or(store):
    ops = Ops(store)
    res = ops.search("refund window")
    ids = [h.id for h in res.hits]
    # the three policy "Refund window" sections outrank everything else
    assert all(i.startswith("policies/") for i in ids[:3])
    assert len(ids) == len(set(ids))
    assert "Refund window" in res.hits[0].heading_path


def test_search_in_filter_and_glob(store):
    ops = Ops(store)
    res = ops.search("refund window", in_=["policies/policy-2025.md"])
    assert {h.doc for h in res.hits} == {"policies/policy-2025.md"}
    res = ops.search("refund", in_=["policies"])
    assert {h.doc for h in res.hits} <= {"policies/policy-2023.md", "policies/policy-2024.md", "policies/policy-2025.md"}
    res = ops.search("refund", in_=["guides/*"])
    assert res.hits == [] and "no hits" in res.hint


def test_search_empty_and_hybrid_fallback(store):
    ops = Ops(store)
    assert ops.search("   ").hits == []
    res = ops.search("refund", mode="hybrid")
    assert res.mode == "lexical" and "no embeddings" in res.hint


def test_read_with_context_and_unknown(store):
    ops = Ops(store)
    hit = ops.search("store credits", in_=["policies/policy-2025.md"]).hits[0]
    res = ops.read(hit.id, context=1)
    assert "12 months" in res.section.text
    assert {c.context for c in res.context} == {True}
    assert len(res.context) == 2
    with pytest.raises(OpsError) as e:
        ops.read("nope.md#9")
    assert "no section" in e.value.message and e.value.suggestion


def test_grep_literal_and_regex_and_limits(store):
    ops = Ops(store)
    # substrings inside tokens must match: this is what grep exists for
    assert [m.line[:9] for m in ops.grep("TX-45").matches] == ["## TX-45x"]  # first matching line of the one section
    assert ops.grep("4419").matches[0].id.startswith("errors.md#")
    assert ops.grep("_TIMEOUT_").matches
    res = ops.grep("TX-4419")
    assert res.matches and res.matches[0].id.startswith("errors.md#") and "retry is not permitted" in res.matches[0].line
    res = ops.grep(r"TX-45\d\d", regex=True)
    assert len(res.matches) == 1 and res.matches[0].line.startswith("- TX-4501")  # first matching line per section
    res = ops.grep("refund", limit=1)
    assert len(res.matches) == 1 and res.truncated
    with pytest.raises(OpsError, match="does not compile"):
        ops.grep("(", regex=True)
    with pytest.raises(OpsError):
        ops.grep("")


def test_neighbours_and_table_header(store):
    ops = Ops(store)
    tbl = ops.search("R-40 storage temp").hits[0]
    res = ops.neighbours(tbl.id, before=1, after=1)
    assert any(s.id == tbl.id for s in res.sections)
    sec = ops.read(tbl.id)
    lines = [l for l in sec.section.text.splitlines() if l.startswith("|")]
    assert lines[0].startswith("| Model") and "R-40" in sec.section.text


def test_index_and_prefix(store):
    ops = Ops(store)
    assert ops.index().startswith("ContextPull index")
    sub = ops.index("policies/")
    assert sub.splitlines()[0].startswith("ContextPull index · policies/ · 3 documents")
    assert "errors.md" not in sub


def test_tools_dispatch_and_schemas(store):
    ops = Ops(store)
    names = [t["name"] for t in TOOLS]
    assert names == ["index", "search", "read", "grep", "neighbours"]
    out = call(ops, "search", {"query": "TX-4419", "limit": 3})
    assert out["hits"][0]["id"].startswith("errors.md#")
    out = call(ops, "read", {"id": out["hits"][0]["id"]})
    assert "TX-4419" in out["text"]
    assert isinstance(call(ops, "index", {}), str)
    assert openai_tools()[1]["function"]["parameters"]["required"] == ["query"]
    with pytest.raises(KeyError):
        call(ops, "nope", {})

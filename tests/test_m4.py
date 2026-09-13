"""M4: PDF ingest, hybrid search with stored embeddings, streamable HTTP transport."""

import asyncio
import hashlib
import json
import math
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from contextpull.ingest import ingest
from contextpull.ops import Ops, tokenize
from contextpull.store import Store

from .conftest import FIXTURE

PDF_CORPUS = FIXTURE.parent / "corpus-pdf"


def test_pdf_ingest_headings_and_identifiers(tmp_path):
    pytest.importorskip("pypdf")
    sp = tmp_path / "s.sqlite"
    rep = ingest(PDF_CORPUS, sp)
    assert rep.changed == 1 and not rep.skipped
    with Store.open(sp) as s:
        ops = Ops(s)
        paths = [r["heading_path"] for r in s.conn.execute("SELECT heading_path FROM sections ORDER BY ordinal")]
        assert any(p.endswith("> Coverage") for p in paths) and any(p.endswith("> Claims Procedure") for p in paths)
        assert s.conn.execute("SELECT title, kind FROM documents").fetchone()[0] == "Warranty Terms and Conditions"
        assert ops.grep("WR-2201").matches[0].heading_path.endswith("Exclusions")
        assert ops.search("surge").hits[0].heading_path.endswith("Exclusions")
        assert "REPLACEMENT_SHIPPING" in ops.read(ops.search("express dispatch").hits[0].id).section.text


def _fake_embed(model: str, texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-hashed-tokens embedding, good enough to test plumbing and fusion."""
    out = []
    for t in texts:
        v = [0.0] * 64
        for tok in tokenize(t):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 64] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_hybrid_search_with_stored_embeddings(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus)
    sp = tmp_path / "s.sqlite"
    rep = ingest(corpus, sp, embed_model="fake:bag64", embed_fn=_fake_embed)
    with Store.open(sp) as s:
        n_sections = s.counts()[1]
        assert rep.embedded == n_sections
        assert tuple(s.conn.execute("SELECT count(*), max(dim) FROM embeddings").fetchone()) == (n_sections, 64)
        assert s.meta_get("embed_model") == "fake:bag64"
        ops = Ops(s, embed_fn=_fake_embed)
        lex = ops.search("refund window", limit=5)
        hyb = ops.search("refund window", limit=5, mode="hybrid")
        assert hyb.mode == "hybrid" and hyb.hint is None
        assert hyb.hits[0].id in {h.id for h in lex.hits[:3]}          # fusion keeps the lexical leaders on top
        assert len(hyb.hits) == 5 and len({h.id for h in hyb.hits}) == 5
        scoped = ops.search("refund window", in_=["policies/policy-2025.md"], mode="hybrid")
        assert {h.doc for h in scoped.hits} == {"policies/policy-2025.md"}  # dense side honours in=
        # a store without vectors falls back and says so
    plain = tmp_path / "plain.sqlite"
    ingest(corpus, plain)
    with Store.open(plain) as s:
        r = Ops(s, embed_fn=_fake_embed).search("refund", mode="hybrid")
        assert r.mode == "lexical" and "no embeddings" in r.hint
    # re-ingest embeds nothing new; a deleted document loses its vectors
    rep2 = ingest(corpus, sp, embed_model="fake:bag64", embed_fn=_fake_embed)
    assert rep2.embedded == 0
    (corpus / "notes.txt").unlink()
    ingest(corpus, sp, embed_model="fake:bag64", embed_fn=_fake_embed)
    with Store.open(sp) as s:
        assert s.conn.execute("SELECT count(*) FROM embeddings WHERE section_id LIKE 'notes.txt#%'").fetchone()[0] == 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_streamable_http_transport(fixture_store):
    pytest.importorskip("mcp")
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "contextpull.cli", "serve", str(fixture_store), "--transport", "http", "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError(f"server did not start: {proc.stderr.read()[:500]}")

        async def run():
            async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    assert "ContextPull index · 7 documents" in init.instructions
                    res = await session.call_tool("grep", {"pattern": "TX-4419"})
                    return json.loads(res.content[0].text)["matches"][0]["id"]

        assert asyncio.run(run()).startswith("errors.md#")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

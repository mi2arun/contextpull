import shutil
from pathlib import Path

import pytest

from contextpull.ingest import ingest
from contextpull.store import SCHEMA_VERSION, Store, StoreError

from .conftest import FIXTURE


def test_store_versions(tmp_path: Path):
    sp = tmp_path / "s.sqlite"
    with Store.create(sp) as s:
        assert s.meta_get("schema_version") == SCHEMA_VERSION
    with Store.open(sp, readonly=False) as s:
        s.meta_set("schema_version", "2.0")
        s.conn.commit()
    with pytest.raises(StoreError, match="schema 2.0"):
        Store.open(sp)
    with pytest.raises(StoreError, match="no store"):
        Store.open(tmp_path / "missing.sqlite")
    (tmp_path / "not.sqlite").write_text("hello")
    with pytest.raises(StoreError):
        Store.open(tmp_path / "not.sqlite")


def test_readonly_refuses_writes(fixture_store: Path):
    with Store.open(fixture_store) as s:
        with pytest.raises(StoreError, match="read-only"):
            s.meta_set("x", "y")


def test_ingest_counts_ignore_and_ids(tmp_path: Path):
    sp = tmp_path / "s.sqlite"
    rep = ingest(FIXTURE, sp)
    assert rep.seen == 7 and rep.changed == 7 and rep.deleted == 0
    with Store.open(sp) as s:
        paths = [r[0] for r in s.conn.execute("SELECT path FROM documents ORDER BY path")]
        assert "drafts/draft.md" not in paths
        assert "policies/policy-2025.md" in paths and "notes.txt" in paths
        ids = [r[0] for r in s.conn.execute("SELECT id FROM sections WHERE doc_id = (SELECT doc_id FROM documents WHERE path='policies/policy-2025.md') ORDER BY ordinal")]
        assert ids[0] == "policies/policy-2025.md#0" and all(i.startswith("policies/policy-2025.md#") for i in ids)
        prev = [r[0] for r in s.conn.execute("SELECT prev_id FROM sections WHERE id = ?", (ids[1],))]
        assert prev == [ids[0]]
        title = s.conn.execute("SELECT title, summary FROM documents WHERE path='policies/policy-2025.md'").fetchone()
        assert title[0] == "Refund Policy 2025" and title[1].startswith("Refund Policy 2025")


def test_reingest_no_change_is_a_noop_and_index_identical(tmp_path: Path):
    sp = tmp_path / "s.sqlite"
    ingest(FIXTURE, sp)
    with Store.open(sp) as s:
        before = s.meta_get("index_text")
        ingested = {r[0]: r[1] for r in s.conn.execute("SELECT path, ingested_at FROM documents")}
    rep = ingest(FIXTURE, sp)
    assert rep.changed == 0 and rep.unchanged == 7 and rep.sections_written == 0
    with Store.open(sp) as s:
        assert s.meta_get("index_text") == before
        assert {r[0]: r[1] for r in s.conn.execute("SELECT path, ingested_at FROM documents")} == ingested


def test_changed_and_deleted_documents(tmp_path: Path):
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus)
    sp = tmp_path / "s.sqlite"
    ingest(corpus, sp)
    (corpus / "notes.txt").unlink()
    (corpus / "policies" / "policy-2025.md").write_text("# Refund Policy 2025\n\n## Refund window\n\nNow it is 7 days, a change large enough to matter.\n")
    rep = ingest(corpus, sp)
    assert rep.deleted == 1 and rep.changed == 1 and rep.unchanged == 5
    with Store.open(sp) as s:
        assert s.conn.execute("SELECT count(*) FROM documents WHERE path='notes.txt'").fetchone()[0] == 0
        assert s.conn.execute("SELECT count(*) FROM sections_fts WHERE id LIKE 'notes.txt#%'").fetchone()[0] == 0
        n = s.conn.execute("SELECT n_sections FROM documents WHERE path='policies/policy-2025.md'").fetchone()[0]
        assert n == 1
        assert s.conn.execute("SELECT count(*) FROM sections WHERE id LIKE 'policies/policy-2025.md#%'").fetchone()[0] == 1


def test_index_is_flat_and_within_budget(fixture_store: Path):
    with Store.open(fixture_store) as s:
        assert s.meta_get("index_mode") == "flat"
        text = s.meta_get("index_text")
        assert text.startswith("ContextPull index · 7 documents")
        assert "policies/policy-2025.md" in text and "errors.md" in text
        assert int(s.meta_get("index_tokens")) <= 2000


def test_hierarchical_index_when_budget_is_tiny(tmp_path: Path):
    sp = tmp_path / "s.sqlite"
    rep = ingest(FIXTURE, sp, index_budget_tokens=60)
    assert rep.index_mode == "hierarchical"
    with Store.open(sp) as s:
        text = s.meta_get("index_text")
        assert "index(prefix)" in text
        # budget smaller than the header: directories are dropped and the tail line says so
        assert "policies/" in text or "more directories" in text
    rep = ingest(FIXTURE, tmp_path / "s2.sqlite", index_budget_tokens=150)
    assert rep.index_mode == "hierarchical" and rep.index_tokens <= 150
    with Store.open(tmp_path / "s2.sqlite") as s:
        text = s.meta_get("index_text")
        assert "docs ·" in text or "more directories" in text


def test_compact_index_between_flat_and_hierarchical(tmp_path: Path):
    sp = tmp_path / "s.sqlite"
    rep = ingest(FIXTURE, sp, index_budget_tokens=170)
    assert rep.index_mode == "compact"
    with Store.open(sp) as s:
        text = s.meta_get("index_text")
        assert "policies/policy-2025.md" in text and "compact" in text.splitlines()[0]

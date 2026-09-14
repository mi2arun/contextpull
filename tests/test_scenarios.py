"""Complex, realistic scenarios over conformance/scenarios/corpus: an engineering
knowledge base in six formats with versioned policies, split references,
tables, a procedure, duplicated facts and near-miss identifiers. Each test is
the sequence of tool calls a competent agent would make, and asserts the store
gives it what it needs. Offline and deterministic."""

import re
import shutil
import sys
from pathlib import Path

import pytest

from contextpull.ingest import ingest
from contextpull.ops import Ops, OpsError
from contextpull.store import Store

CORPUS = Path(__file__).resolve().parent.parent / "conformance" / "scenarios" / "corpus"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))


@pytest.fixture(scope="module")
def scenario_store(tmp_path_factory):
    sp = tmp_path_factory.mktemp("scenario") / "store.sqlite"
    rep = ingest(CORPUS, sp)
    assert rep.changed == 12 and not rep.skipped
    return sp


@pytest.fixture()
def ops(scenario_store):
    with Store.open(scenario_store) as s:
        yield Ops(s)


# 1. comparison across versions: two scoped searches, two reads, differing values
def test_comparison_across_policy_versions(ops):
    a = ops.search("coverage period", in_=["policies/warranty-2024.md"]).hits[0]
    b = ops.search("coverage period", in_=["policies/warranty-2025.md"]).hits[0]
    assert a.heading_path.endswith("Coverage period") and b.heading_path.endswith("Coverage period")
    ta, tb = ops.read(a.id).section.text, ops.read(b.id).section.text
    assert "24 months" in ta and "36 months" in tb
    # one unscoped search must surface both years in the top hits, so a model can plan two reads
    both = ops.search("warranty coverage period months", limit=5).hits
    assert {h.doc for h in both} >= {"policies/warranty-2024.md", "policies/warranty-2025.md"}
    # claim window changed too, and the 2025 text has the new tiered rule
    w = ops.read(ops.search("claim window", in_=["policies/warranty-2025.md"]).hits[0].id).section.text
    assert "14 days" in w and "day 45" in w
    w24 = ops.read(ops.search("claim window", in_=["policies/warranty-2024.md"]).hits[0].id).section.text
    assert "30 days" in w24


# 2. aggregation across documents: grep gathers every member of a code family
def test_aggregation_of_error_codes_across_files(ops):
    matches = ops.grep("WR-", limit=100)
    codes = set()
    for m in matches.matches:
        codes.update(re.findall(r"WR-\d{4}", m.line))
    # grep returns one line per section; collect all codes by reading the matched sections
    for m in matches.matches:
        codes.update(re.findall(r"WR-\d{4}", ops.read(m.id).section.text))
    assert codes == {"WR-2201", "WR-2205", "WR-2210", "WR-2301", "WR-2302", "WR-3101", "WR-3104", "WR-3107", "WR-3201", "WR-3202"}
    controller_only = ops.grep("WR-22", in_=["reference/error-codes-controller.md"])
    assert {m.doc for m in controller_only.matches} == {"reference/error-codes-controller.md"}
    # the drive document mentions WR-22 codes only in prose; a scoped grep keeps the two families apart
    drive = ops.grep("WR-31", in_=["reference/error-codes-drive.md"])
    assert drive.matches and all(m.doc == "reference/error-codes-drive.md" for m in drive.matches)


# 3. table cell with header intact, and header recovery when the chunker splits the table
def test_table_cell_and_header_recovery(ops, tmp_path):
    hit = ops.search("R-40 operating temp").hits[0]
    text = ops.read(hit.id).section.text
    lines = [l for l in text.splitlines() if l.startswith("|")]
    assert lines[0].startswith("| Model") and any(l.startswith("| R-40") and "-5 to 40" in l for l in lines)
    # force the 12-row table to split, then read a continuation
    sp = tmp_path / "small.sqlite"
    ingest(CORPUS, sp, max_chars=450)
    with Store.open(sp) as s:
        o = Ops(s)
        parts = [r[0] for r in s.conn.execute("SELECT id FROM sections WHERE kind='table' AND id LIKE 'products/spec-sheet.md#%' ORDER BY ordinal")]
        assert len(parts) >= 2
        cont = o.read(parts[-1]).section.text
        assert cont.splitlines()[0].startswith("| Model")           # header row present on every part
        assert o.neighbours(parts[-1]).header is not None            # and recoverable explicitly
        r120 = o.search("R-120 storage temp").hits[0]
        assert "| R-120" in o.read(r120.id).section.text and o.read(r120.id).section.text.startswith("| Model")


# 4. procedure: find a step, then the next step via neighbours
def test_procedure_next_step_via_neighbours(ops):
    step3 = ops.search("reseat connector latch pull straight out").hits[0]
    assert step3.heading_path.endswith("Step 3: reseat")
    nb = ops.neighbours(step3.id, before=0, after=1)
    assert [s.heading_path.rsplit(" > ", 1)[1] for s in nb.sections] == ["Step 3: reseat", "Step 4: verify"]
    assert "60 seconds" in nb.sections[1].text
    ctx = ops.read(step3.id, context=1)
    assert {c.heading_path.rsplit(" > ", 1)[1] for c in ctx.context} == {"Step 2: locate the harness", "Step 4: verify"}


# 5. every format contributes: xlsx, docx, pptx, pdf, txt, md
def test_cross_format_lookups(ops):
    assert ops.grep("PN-88121").matches[0].doc == "products/parts-list.xlsx"
    row = ops.read(ops.grep("PN-88121").matches[0].id).section.text
    assert "| PN-88121 | Brake pad set, heavy duty | R-70 to R-120 | 72.5" in row
    assert ops.search("main bearing bolt torque").hits[0].doc == "procedures/maintenance-manual.docx"
    assert ops.search("claim serial number fifteen days").hits[0].doc == "training/warranty-overview.pptx"
    assert any(m.doc == "policies/warranty-terms-legacy.pdf" for m in ops.grep("WR-2201").matches)
    assert ops.search("magnetic tray torque driver").hits[0].doc in ("training/onboarding-notes.txt", "procedures/p40-sensor-harness.md")


# 6. near-miss identifiers stay apart
def test_near_miss_identifiers(ops):
    # grep returns one line per section; the agent reads the section to see every member
    m = ops.grep("WR-320").matches
    assert len(m) == 1 and m[0].doc == "reference/error-codes-drive.md"
    assert set(re.findall(r"WR-\d{4}", ops.read(m[0].id).section.text)) == {"WR-3201", "WR-3202"}
    assert all("WR-2201" in ops.read(m.id).section.text for m in ops.grep("WR-2201").matches)
    # Three documents genuinely mention WR-2205. bm25 ranks the short mentions above the reference
    # table (the known definition-vs-usage gap); the heading paths let an agent pick the reference.
    top = ops.search("WR-2205").hits
    assert all("WR-2205" in ops.read(h.id).section.text for h in top)
    assert "reference/error-codes-controller.md" in {h.doc for h in top[:5]}
    assert any("WR-22xx" in h.heading_path for h in top[:5])


# 7. a fact repeated across documents: the model sees all sources and the reference ranks high
def test_duplicated_fact_surfaces_all_sources(ops):
    hits = ops.search("WR-2201 surge event", limit=8).hits
    docs = {h.doc for h in hits}
    assert len(docs) >= 3 and "reference/error-codes-controller.md" in {h.doc for h in hits[:3]}


# 8. hierarchical index and prefix drill-down
def test_hierarchical_index_drilldown(tmp_path):
    sp = tmp_path / "h.sqlite"
    rep = ingest(CORPUS, sp, index_budget_tokens=150)
    assert rep.index_mode == "hierarchical"
    with Store.open(sp) as s:
        o = Ops(s)
        assert "index(prefix)" in o.index()
        sub = o.index("reference/")
        assert "2 documents" in sub.splitlines()[0] and "error-codes-drive.md" in sub and "faq.md" not in sub


# 9. access control wrapper from the embedding example scopes every operation
def test_access_control_wrapper(ops):
    from embed_with_acl import AccessControlledOps

    scoped = AccessControlledOps(ops, ["products/*"])
    assert scoped.search("coverage period").hits == []
    assert {h.doc.split("/")[0] for h in scoped.search("R-40").hits} == {"products"}
    with pytest.raises(OpsError):
        scoped.read("policies/warranty-2025.md#2")
    assert "policies/" not in scoped.index().split("\n", 3)[3]


# 10. corpus changes while a reader holds the old snapshot; ids of unchanged docs stay stable
def test_incremental_update_with_open_reader(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    sp = tmp_path / "s.sqlite"
    ingest(corpus, sp)
    with Store.open(sp) as old:
        o_old = Ops(old)
        before = o_old.read("policies/warranty-2025.md#2").section.text
        assert "14 days" in before
        p = corpus / "policies" / "warranty-2025.md"
        p.write_text(p.read_text().replace("within 14 days", "within 21 days"))
        rep = ingest(corpus, sp)
        assert rep.changed == 1 and rep.unchanged == 11
        with Store.open(sp) as new:
            assert "21 days" in Ops(new).read("policies/warranty-2025.md#2").section.text
            assert Ops(new).read("reference/error-codes-drive.md#1").section.id == "reference/error-codes-drive.md#1"
        assert o_old.index().startswith("ContextPull index")  # old reader still works

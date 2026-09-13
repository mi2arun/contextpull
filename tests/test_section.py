import re

from contextpull.parse import parse_markdown
from contextpull.section import sectionize


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_sections_start_at_headings_and_carry_paths():
    md = "# Doc\n\nPreamble here, long enough to keep as a section on its own.\n\n## A\n\nText for section a, long enough to survive the minimum size rule.\n\n### A1\n\nText for section a1, long enough to survive the minimum size rule.\n\n## B\n\nText for section b, long enough to survive the minimum size rule.\n"
    rows = sectionize(parse_markdown(md), max_chars=500)
    paths = [r.heading_path for r in rows]
    assert paths == ["Doc", "Doc > A", "Doc > A > A1", "Doc > B"]
    assert [r.ordinal for r in rows] == [0, 1, 2, 3]
    assert rows[0].level == 1 and rows[2].level == 3


def test_concatenation_is_lossless_modulo_whitespace():
    md = "# T\n\n" + "\n\n".join(f"## H{i}\n\nParagraph {i} " + "word " * 30 for i in range(12))
    parsed = parse_markdown(md)
    rows = sectionize(parsed, max_chars=400)
    assert _norm(" ".join(r.text for r in rows)) == _norm(" ".join(b.raw for b in parsed.blocks))


def test_oversized_section_splits_at_block_boundaries_sharing_path():
    md = "# T\n\n## Big\n\n" + "\n\n".join("Para %d " % i + "x " * 120 for i in range(6))
    rows = sectionize(parse_markdown(md), max_chars=600)
    big = [r for r in rows if r.heading_path == "T > Big"]
    assert len(big) >= 3
    assert all(len(r.text) <= 600 for r in big)


def test_code_block_never_split_and_kind_code():
    code = "```\n" + "\n".join("line %d" % i for i in range(200)) + "\n```"
    md = f"# T\n\n## Code\n\n{code}\n"
    rows = sectionize(parse_markdown(md), max_chars=300)
    code_rows = [r for r in rows if "```" in r.text]
    assert len(code_rows) == 1 and code_rows[0].kind in ("code", "mixed")
    assert code_rows[0].text.count("```") == 2


def test_large_table_splits_by_rows_and_every_part_has_header():
    rows_md = "\n".join(f"| R-{i:02d} | {i} °C | {i} V |" for i in range(80))
    md = f"# Specs\n\n## Table\n\n| Model | Temp | Volt |\n|---|---|---|\n{rows_md}\n"
    rows = sectionize(parse_markdown(md), max_chars=500)
    parts = [r for r in rows if r.kind == "table"]
    assert len(parts) >= 3
    for p in parts:
        body = [l for l in p.text.splitlines() if l.startswith("|")]
        assert body[0].startswith("| Model") and "---" in body[1]
    # rows are not duplicated across parts
    all_rows = [l for p in parts for l in p.text.splitlines() if l.startswith("| R-")]
    assert len(all_rows) == 80 and len(set(all_rows)) == 80


def test_bare_heading_merges_forward_and_tiny_fragment_merges_back():
    md = "# T\n\n## Empty\n\n## Real\n\nEnough text here to be kept as a real section of its own.\n\nok\n"
    rows = sectionize(parse_markdown(md), max_chars=500, min_chars=40)
    assert len(rows) == 1
    assert rows[0].text.startswith("# T") and "## Empty" in rows[0].text and rows[0].text.endswith("ok")


def test_deterministic():
    md = open(__file__.replace("test_section.py", "../conformance/corpus/guides/getting-started.md")).read()
    a = sectionize(parse_markdown(md))
    b = sectionize(parse_markdown(md))
    assert [(r.ordinal, r.heading_path, r.hash) for r in a] == [(r.ordinal, r.heading_path, r.hash) for r in b]

"""docx / xlsx / pptx parsing with fixtures built in-test as minimal OOXML zips."""

import io
import zipfile
from pathlib import Path

from contextpull.ingest import ingest
from contextpull.ops import Ops
from contextpull.parse import Heading, ListBlock, Paragraph, Table
from contextpull.parse_office import parse_docx, parse_pptx, parse_xlsx
from contextpull.store import Store

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def _p(text, style=None, numbered=False):
    ppr = ""
    if style or numbered:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr>" if numbered else "") + "</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _tbl(rows):
    trs = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>" for r in rows)
    return f"<w:tbl>{trs}</w:tbl>"


def docx_bytes() -> bytes:
    body = (
        _p("Maintenance Manual R-40", "Title")
        + _p("Applies to the R-40 series from serial 4400 onwards, long enough to be a paragraph.")
        + _p("Torque settings", "Heading1")
        + _p("Tighten the main bearing bolts to 45 Nm and the cover screws to 8 Nm.")
        + _tbl([["Fastener", "Torque"], ["Main bearing bolt", "45 Nm"], ["Cover screw", "8 Nm"], ["Drain plug", "25 Nm"]])
        + _p("Error codes", "Heading1")
        + _p("WR-2201 indicates a surge event", numbered=True)
        + _p("WR-2205 indicates a sensor fault", numbered=True)
    )
    return _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": f'<w:document {W}><w:body>{body}</w:body></w:document>'})


def xlsx_bytes() -> bytes:
    S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    shared = ["Model", "Storage temp", "Voltage", "R-10", "-10 to 40 C", "R-40", "-20 to 50 C"]
    sst = "<sst " + S + ">" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>"
    def c(ref, idx=None, num=None):
        return f'<c r="{ref}" t="s"><v>{idx}</v></c>' if idx is not None else f'<c r="{ref}"><v>{num}</v></c>'
    sheet = f'<worksheet {S}><sheetData><row r="1">{c("A1",0)}{c("B1",1)}{c("C1",2)}</row><row r="2">{c("A2",3)}{c("B2",4)}{c("C2",num=110)}</row><row r="3">{c("A3",5)}{c("B3",6)}{c("C3",num=100)}</row></sheetData></worksheet>'
    wb = f'<workbook {S}><sheets><sheet name="Specs" sheetId="1" r:id="rId1"/></sheets></workbook>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>'
    return _zip({"[Content_Types].xml": "<Types/>", "xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels, "xl/sharedStrings.xml": sst, "xl/worksheets/sheet1.xml": sheet})


def pptx_bytes() -> bytes:
    NS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    def sp(text, ph=None):
        nv = f'<p:nvSpPr><p:nvPr>{f"<p:ph type=\"{ph}\"/>" if ph else ""}</p:nvPr></p:nvSpPr>'
        return f'<p:sp>{nv}<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
    s1 = f'<p:sld {NS}><p:cSld><p:spTree>{sp("Warranty Overview", "ctrTitle")}{sp("Two-year limited warranty on all R-series models")}</p:spTree></p:cSld></p:sld>'
    s2 = f'<p:sld {NS}><p:cSld><p:spTree>{sp("Claims", "title")}{sp("Open a claim with the serial number")}{sp("Resolved within fifteen business days")}</p:spTree></p:cSld></p:sld>'
    return _zip({"[Content_Types].xml": "<Types/>", "ppt/slides/slide1.xml": s1, "ppt/slides/slide2.xml": s2})


def test_docx_blocks():
    p = parse_docx(docx_bytes(), "manual")
    assert p.title == "Maintenance Manual R-40"
    kinds = [type(b).__name__ for b in p.blocks]
    assert kinds == ["Heading", "Paragraph", "Heading", "Paragraph", "Table", "Heading", "ListBlock"]
    t = next(b for b in p.blocks if isinstance(b, Table))
    assert t.header.startswith("| Fastener") and len(t.rows) == 3
    assert p.blocks[-1].raw.count("- WR-") == 2


def test_xlsx_blocks():
    p = parse_xlsx(xlsx_bytes(), "specs")
    heads = [b.text for b in p.blocks if isinstance(b, Heading)]
    assert heads == ["specs", "Specs"]
    t = next(b for b in p.blocks if isinstance(b, Table))
    assert t.header == "| Model | Storage temp | Voltage |" and t.rows == ["| R-10 | -10 to 40 C | 110 |", "| R-40 | -20 to 50 C | 100 |"]


def test_pptx_blocks():
    p = parse_pptx(pptx_bytes(), "deck")
    assert p.title == "Warranty Overview"
    heads = [b.text for b in p.blocks if isinstance(b, Heading)]
    assert heads == ["Warranty Overview", "Slide 1: Warranty Overview", "Slide 2: Claims"]
    assert isinstance(p.blocks[-1], ListBlock) and "fifteen business days" in p.blocks[-1].raw


def test_office_ingest_end_to_end(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manual.docx").write_bytes(docx_bytes())
    (corpus / "specs.xlsx").write_bytes(xlsx_bytes())
    (corpus / "deck.pptx").write_bytes(pptx_bytes())
    (corpus / "broken.docx").write_bytes(b"not a zip")
    sp = tmp_path / "s.sqlite"
    rep = ingest(corpus, sp)
    assert rep.changed == 3 and [s[0] for s in rep.skipped] == ["broken.docx"]
    with Store.open(sp) as s:
        ops = Ops(s)
        assert {r[0] for r in s.conn.execute("SELECT kind FROM documents")} == {"docx", "xlsx", "pptx"}
        assert ops.grep("WR-2205").matches[0].doc == "manual.docx"
        hit = ops.search("torque main bearing").hits[0]
        assert hit.doc == "manual.docx" and "Torque settings" in hit.heading_path
        cell = ops.search("R-40 storage temp").hits[0]
        assert cell.doc == "specs.xlsx" and "| R-40 |" in ops.read(cell.id).section.text
        assert ops.search("claim serial number").hits[0].heading_path.endswith("Slide 2: Claims")

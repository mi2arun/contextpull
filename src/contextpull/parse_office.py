"""Office Open XML (docx, xlsx, pptx) to the block stream, with the standard
library only: the files are zip archives of XML.

* docx: Word heading styles become headings, paragraphs become paragraphs,
  numbered/bulleted paragraphs become list items, tables become pipe tables.
* xlsx: each sheet becomes a level-2 heading plus one pipe table, first row as
  header. Formulas are not evaluated; cached values are used.
* pptx: each slide becomes a level-2 heading ("Slide N: title") with its text.
Images, drawings and embedded objects are ignored.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from .parse import Block, Heading, ListBlock, Paragraph, Parsed, Table

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

OFFICE_KINDS = {".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}


class OfficeError(Exception):
    pass


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _pipe_table(rows: list[list[str]]) -> Table | None:
    rows = [[_cell(c) for c in r] for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "|" + "---|" * width
    return Table(header, sep, ["| " + " | ".join(r) + " |" for r in rows[1:]])


def _open(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise OfficeError("not a valid Office Open XML file") from e


# ------------------------------------------------------------------------ docx

_HEADING_STYLE = re.compile(r"^(?:heading|berschrift|titre|t[ií]tulo)?\s*(\d)$", re.I)


def parse_docx(data: bytes, fallback_title: str = "") -> Parsed:
    z = _open(data)
    try:
        root = ET.fromstring(z.read("word/document.xml"))
    except KeyError as e:
        raise OfficeError("docx without word/document.xml") from e
    body = root.find(f"{W}body")
    blocks: list[Block] = []
    if body is None:
        return Parsed(fallback_title, blocks)
    for el in body:
        if el.tag == f"{W}p":
            text = "".join(t.text or "" for t in el.iter(f"{W}t")).strip()
            if not text:
                continue
            style = el.find(f"{W}pPr/{W}pStyle")
            sval = (style.get(f"{W}val") if style is not None else "") or ""
            low = sval.lower()
            if low in ("title", "subtitle"):
                blocks.append(Heading(1 if low == "title" else 2, text))
                continue
            m = re.match(r"^(?:heading|h)\s*(\d)$", low) or (re.match(r"^(\d)$", low[-1:]) if low.startswith("heading") else None)
            if m:
                blocks.append(Heading(min(int(m.group(1)), 6), text))
                continue
            if el.find(f"{W}pPr/{W}numPr") is not None:
                if blocks and isinstance(blocks[-1], ListBlock):
                    blocks[-1].raw += "\n- " + text
                else:
                    blocks.append(ListBlock("- " + text))
                continue
            blocks.append(Paragraph(text))
        elif el.tag == f"{W}tbl":
            rows = []
            for tr in el.iter(f"{W}tr"):
                rows.append(["".join(t.text or "" for t in tc.iter(f"{W}t")) for tc in tr.findall(f"{W}tc")])
            t = _pipe_table(rows)
            if t:
                blocks.append(t)
    title = next((b.text for b in blocks if isinstance(b, Heading) and b.level == 1), "") or fallback_title
    return Parsed(title, blocks)


# ------------------------------------------------------------------------ xlsx


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def parse_xlsx(data: bytes, fallback_title: str = "", max_rows: int = 2000) -> Parsed:
    z = _open(data)
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            rels[rel.get("Id")] = rel.get("Target")
    blocks: list[Block] = [Heading(1, fallback_title)]
    for sheet in wb.iter(f"{S}sheet"):
        name = sheet.get("name") or "Sheet"
        target = rels.get(sheet.get(f"{R}id"), "")
        path = "xl/" + target.lstrip("/").removeprefix("xl/") if target else ""
        if path not in names:
            continue
        rows: list[list[str]] = []
        for row in ET.fromstring(z.read(path)).iter(f"{S}row"):
            cells: dict[int, str] = {}
            for c in row.findall(f"{S}c"):
                idx = _col_index(c.get("r", "A"))
                t = c.get("t")
                v = c.find(f"{S}v")
                if t == "s" and v is not None and v.text is not None and v.text.isdigit():
                    val = shared[int(v.text)] if int(v.text) < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{S}t"))
                else:
                    val = (v.text or "") if v is not None else ""
                cells[idx] = val
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(i, "") for i in range(width)])
            if len(rows) >= max_rows:
                break
        blocks.append(Heading(2, name))
        t = _pipe_table(rows)
        if t:
            blocks.append(t)
        elif rows:
            blocks.append(Paragraph(" ".join(" ".join(r) for r in rows)))
    return Parsed(fallback_title, blocks)


# ------------------------------------------------------------------------ pptx


def parse_pptx(data: bytes, fallback_title: str = "") -> Parsed:
    z = _open(data)
    slides = sorted(
        (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)),
    )
    blocks: list[Block] = []
    deck_title = ""
    for i, name in enumerate(slides, 1):
        root = ET.fromstring(z.read(name))
        title = ""
        paras: list[str] = []
        for sp in root.iter(f"{P}sp"):
            ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
            is_title = ph is not None and (ph.get("type") in ("title", "ctrTitle"))
            for para in sp.iter(f"{A}p"):
                text = "".join(t.text or "" for t in para.iter(f"{A}t")).strip()
                if not text:
                    continue
                if is_title and not title:
                    title = text
                else:
                    paras.append(text)
        if i == 1 and title:
            deck_title = title
        blocks.append(Heading(2, f"Slide {i}: {title}" if title else f"Slide {i}"))
        if paras:
            blocks.append(ListBlock("\n".join("- " + p for p in paras)) if len(paras) > 1 else Paragraph(paras[0]))
    if deck_title:
        blocks.insert(0, Heading(1, deck_title))
    return Parsed(deck_title or fallback_title, blocks)


def parse_office(data: bytes, kind: str, fallback_title: str = "") -> Parsed:
    if kind == "docx":
        return parse_docx(data, fallback_title)
    if kind == "xlsx":
        return parse_xlsx(data, fallback_title)
    if kind == "pptx":
        return parse_pptx(data, fallback_title)
    raise OfficeError(f"unknown office kind {kind!r}")

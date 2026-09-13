"""Parse Markdown and plain text into a block stream.

Blocks: Heading, Paragraph, Table, Code, ListBlock. The sectioner never sees
raw lines, so every structural rule (never split a table or a fence) is
enforced by construction here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Heading:
    level: int
    text: str

    @property
    def raw(self) -> str:
        return f"{'#' * self.level} {self.text}"


@dataclass
class Paragraph:
    raw: str


@dataclass
class ListBlock:
    raw: str


@dataclass
class Code:
    lang: str
    raw: str  # includes fences


@dataclass
class Table:
    header: str        # first row, raw line
    separator: str     # the |---|---| line
    rows: list[str] = field(default_factory=list)

    @property
    def raw(self) -> str:
        return "\n".join([self.header, self.separator, *self.rows])


Block = Heading | Paragraph | ListBlock | Code | Table


@dataclass
class Parsed:
    title: str
    blocks: list[Block]
    front_matter: dict[str, str] = field(default_factory=dict)


def _closes(line: str, fence: str) -> bool:
    t = line.strip()
    return len(t) >= len(fence) and t == fence[0] * len(t)


_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```+|~~~+)(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_SETEXT_H1 = re.compile(r"^={3,}\s*$")
_SETEXT_H2 = re.compile(r"^-{3,}\s*$")


def parse_markdown(text: str, fallback_title: str = "") -> Parsed:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fm: dict[str, str] = {}
    i = 0
    # front matter
    if lines and lines[0].strip() == "---":
        j = 1
        while j < len(lines) and lines[j].strip() != "---":
            if ":" in lines[j]:
                k, v = lines[j].split(":", 1)
                fm[k.strip().lower()] = v.strip().strip("'\"")
            j += 1
        if j < len(lines):
            i = j + 1

    blocks: list[Block] = []
    para: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            raw = "\n".join(para).strip()
            if raw:
                blocks.append(ListBlock(raw) if _LIST.match(para[0]) else Paragraph(raw))
        para = []

    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        m = _FENCE.match(line)
        if m:
            flush_para()
            fence = m.group(1)
            info = m.group(2).strip()
            lang = info.split()[0] if info else ""
            buf = [line]
            i += 1
            # closing fence: same character, at least as long, nothing else on the line
            while i < n and not _closes(lines[i], fence):
                buf.append(lines[i])
                i += 1
            if i < n:
                buf.append(lines[i])
                i += 1
            blocks.append(Code(lang, "\n".join(buf)))
            continue

        m = _ATX.match(line)
        if m:
            flush_para()
            blocks.append(Heading(len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        # setext heading: a single paragraph line followed by === or ---
        if para and len(para) == 1 and i < n and (_SETEXT_H1.match(line) or _SETEXT_H2.match(line)):
            level = 1 if _SETEXT_H1.match(line) else 2
            blocks.append(Heading(level, para[0].strip()))
            para = []
            i += 1
            continue

        # pipe table: header line containing | followed by a separator line
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "|" in lines[i + 1]:
            flush_para()
            tbl = Table(header=line.rstrip(), separator=lines[i + 1].rstrip())
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                tbl.rows.append(lines[i].rstrip())
                i += 1
            blocks.append(tbl)
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        para.append(line)
        i += 1
    flush_para()

    title = fm.get("title") or next((b.text for b in blocks if isinstance(b, Heading) and b.level == 1), "") or fallback_title
    return Parsed(title=title, blocks=blocks, front_matter=fm)


_TXT_HEADING = re.compile(r"^[A-Z0-9][^.!?]{0,58}$")


def parse_text(text: str, fallback_title: str = "") -> Parsed:
    """Plain text: paragraphs on blank lines; a short capitalised line on its
    own, surrounded by blank lines, is treated as a level-2 heading."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n\s*\n", text)
    blocks: list[Block] = []
    for c in chunks:
        c = c.strip("\n")
        if not c.strip():
            continue
        lines = c.split("\n")
        if len(lines) == 1 and _TXT_HEADING.match(lines[0].strip()) and not lines[0].strip().endswith(":"):
            blocks.append(Heading(2, lines[0].strip()))
        elif _LIST.match(lines[0]):
            blocks.append(ListBlock(c.strip()))
        else:
            blocks.append(Paragraph(c.strip()))
    title = next((b.text for b in blocks if isinstance(b, Heading)), "") or fallback_title
    return Parsed(title=title, blocks=blocks)


def parse(text: str, kind: str, fallback_title: str = "") -> Parsed:
    if kind == "markdown":
        return parse_markdown(text, fallback_title)
    return parse_text(text, fallback_title)

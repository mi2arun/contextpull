"""Turn a block stream into size-bounded sections with heading paths.

Rules (docs/system-design.md §3, "Section"):
1. A new section starts at every heading of level <= heading_depth.
2. A section over max_chars is split at block boundaries; parts share the heading path.
3. Tables and code are never split mid-block. A table longer than max_chars is
   split by rows and every part begins with the header row and separator.
4. A fragment under min_chars is merged: a bare heading merges forward into
   the next section, anything else merges backward into the previous.
5. Preamble before the first heading is a level-0 section under the title.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .parse import Block, Code, Heading, ListBlock, Paragraph, Parsed, Table


@dataclass
class Draft:
    heading_path: str
    level: int
    blocks: list[Block]

    @property
    def text(self) -> str:
        return "\n\n".join(b.raw for b in self.blocks).strip()

    @property
    def kind(self) -> str:
        content = [b for b in self.blocks if not isinstance(b, Heading)]
        if not content:
            return "prose"
        if all(isinstance(b, Table) for b in content):
            return "table"
        if all(isinstance(b, Code) for b in content):
            return "code"
        if any(isinstance(b, (Table, Code)) for b in content):
            return "mixed"
        return "prose"


@dataclass
class SectionRow:
    ordinal: int
    heading_path: str
    level: int
    kind: str
    text: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def _split_table(t: Table, max_chars: int) -> list[Table]:
    head_len = len(t.header) + len(t.separator) + 2
    parts: list[Table] = []
    cur = Table(t.header, t.separator)
    size = head_len
    for row in t.rows:
        if cur.rows and size + len(row) + 1 > max_chars:
            parts.append(cur)
            cur = Table(t.header, t.separator)
            size = head_len
        cur.rows.append(row)
        size += len(row) + 1
    parts.append(cur)
    return parts


def _take_words(raw: str, room: int) -> tuple[str, str]:
    """Split raw at a word boundary so the head is at most ``room`` chars."""
    if len(raw) <= room:
        return raw, ""
    cut = raw.rfind(" ", 0, room + 1)
    if cut <= 0:
        cut = room  # a single word longer than the room: hard cut
    return raw[:cut].rstrip(), raw[cut:].lstrip()


def _pack(blocks: list[Block], max_chars: int) -> list[list[Block]]:
    """Pack blocks into groups of at most ``max_chars`` where possible.

    Prose (paragraphs, lists) is split to fit the room left in the current
    group, so a heading is always followed by content in the same group.
    Tables are split by rows beforehand; code blocks are never split. Those two
    may exceed the limit on their own, by design.
    """
    min_room = max(80, max_chars // 5)
    groups: list[list[Block]] = []
    cur: list[Block] = []
    size = 0

    def flush() -> None:
        nonlocal cur, size
        if cur:
            groups.append(cur)
        cur, size = [], 0

    def add(b: Block) -> None:
        nonlocal size
        cur.append(b)
        size += len(b.raw) + 2

    for b in blocks:
        if isinstance(b, Table) and len(b.raw) > max_chars:
            for part in _split_table(b, max_chars):
                if cur and size + len(part.raw) + 2 > max_chars:
                    flush()
                add(part)
            continue
        if isinstance(b, (Paragraph, ListBlock)):
            rest = b.raw
            while rest:
                room = max_chars - size - 2
                if cur and room < min_room and len(rest) > room:
                    flush()
                    room = max_chars - 2
                head, rest = _take_words(rest, max(room, 1))
                if head:
                    add(Paragraph(head) if rest or head != b.raw else b)
                if rest:
                    flush()
            continue
        if cur and size + len(b.raw) + 2 > max_chars and not (cur and isinstance(cur[-1], Heading) and len(cur) == 1):
            flush()
        add(b)
    flush()
    return groups


def sectionize(parsed: Parsed, *, max_chars: int = 2000, min_chars: int = 40, heading_depth: int = 4) -> list[SectionRow]:
    title = parsed.title or "Untitled"
    stack: list[tuple[int, str]] = []
    drafts: list[Draft] = []
    cur_blocks: list[Block] = []
    cur_path, cur_level = title, 0

    def flush() -> None:
        nonlocal cur_blocks
        if cur_blocks:
            for group in _pack(cur_blocks, max_chars):
                drafts.append(Draft(cur_path, cur_level, group))
        cur_blocks = []

    for b in parsed.blocks:
        if isinstance(b, Heading) and b.level <= heading_depth:
            flush()
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            stack.append((b.level, b.text))
            cur_path = " > ".join(t for _, t in stack)
            cur_level = b.level
            cur_blocks = [b]
        else:
            cur_blocks.append(b)
    flush()

    # Rule 4: merge fragments, re-packing so the size limit still holds. A merge
    # only counts if the fragment actually shares a group with other content;
    # otherwise (e.g. a tiny paragraph before an oversized table part) the
    # fragment stays as its own small section rather than looping.
    def merge_forward(i: int) -> bool:
        d, nxt = drafts[i], drafts[i + 1]
        groups = _pack(d.blocks + nxt.blocks, max_chars)
        if len(groups[0]) == len(d.blocks):
            return False
        drafts[i + 1 : i + 2] = [Draft(nxt.heading_path, nxt.level, g) for g in groups]
        return True

    def merge_backward(d: Draft) -> bool:
        prev = merged[-1]
        groups = _pack(prev.blocks + d.blocks, max_chars)
        if len(groups[-1]) == len(d.blocks):
            return False
        merged[-1:] = [Draft(prev.heading_path, prev.level, g) for g in groups]
        return True

    merged: list[Draft] = []
    i = 0
    while i < len(drafts):
        d = drafts[i]
        if len(d.text) < min_chars:
            only_heading = all(isinstance(b, Heading) for b in d.blocks)
            if only_heading and i + 1 < len(drafts) and merge_forward(i):
                i += 1
                continue
            if merged and merge_backward(d):
                i += 1
                continue
            if i + 1 < len(drafts) and merge_forward(i):
                i += 1
                continue
        merged.append(d)
        i += 1

    rows: list[SectionRow] = []
    for n, d in enumerate(merged):
        text = d.text
        if not text:
            continue
        rows.append(SectionRow(len(rows), d.heading_path or title, d.level, d.kind, text))
    return rows

"""The five operations over an open store. Reference implementation of
docs/store-format.md. Pure functions of the store; no network, no writes.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field

from .index import prefix_listing
from .store import Store

TOKEN_RE = re.compile(r"[^\W_][\w.\-]*")
_LEAD = re.compile(r"(?<![\w.\-])[-_.]+(?=\w)")
_TRAIL = re.compile(r"(?<=\w)[-_.]+(?![\w.\-])")


def normalize_for_fts(text: str) -> str:
    """Strip leading/trailing '-', '_' and '.' from tokens so that '--no-cache'
    indexes as 'no-cache' and 'cache.' as 'cache', while 'tx-4419', '3.12'
    and 'tool.uv.sources' stay whole. Applied to the indexed FTS columns and
    to queries; ``sections.text`` stays verbatim."""
    return _TRAIL.sub("", _LEAD.sub("", text))
MAX_PATTERN = 200
REGEX_STEP_BUDGET_CHARS = 200_000  # total text a regex may scan per call


class OpsError(Exception):
    """A tool error: message plus a suggestion the model can act on."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {"error": self.message, "suggestion": self.suggestion}


def tokenize(text: str) -> list[str]:
    return [t.strip("._-") for t in TOKEN_RE.findall(normalize_for_fts(text.lower())) if t.strip("._-")]


def _fts_string(tok: str) -> str:
    return '"' + tok.replace('"', '""') + '"'


@dataclass
class Hit:
    id: str
    doc: str
    heading_path: str
    snippet: str
    score: float
    kind: str


@dataclass
class Section:
    id: str
    doc: str
    heading_path: str
    kind: str
    text: str
    prev_id: str | None
    next_id: str | None
    context: bool = False


@dataclass
class Match:
    id: str
    doc: str
    heading_path: str
    line: str


@dataclass
class SearchResult:
    hits: list[Hit]
    mode: str
    hint: str | None = None

    def to_dict(self) -> dict:
        return {"hits": [asdict(h) for h in self.hits], "mode": self.mode, "hint": self.hint}


@dataclass
class ReadResult:
    section: Section
    context: list[Section] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self.section)
        d.pop("context", None)
        d["context"] = [asdict(c) for c in self.context]
        return d


@dataclass
class GrepResult:
    matches: list[Match]
    truncated: bool

    def to_dict(self) -> dict:
        return {"matches": [asdict(m) for m in self.matches], "truncated": self.truncated}


@dataclass
class NeighboursResult:
    sections: list[Section]
    header: Section | None = None

    def to_dict(self) -> dict:
        return {"sections": [asdict(s) for s in self.sections], "header": asdict(self.header) if self.header else None}


def _glob_clause(paths: list[str] | None) -> tuple[str, list[str]]:
    if not paths:
        return "", []
    parts, args = [], []
    for p in paths:
        if not isinstance(p, str) or not p:
            raise OpsError(f"invalid path filter {p!r}", "pass document paths or globs as shown in the index")
        parts.append("d.path GLOB ?")
        args.append(p)
        if not any(ch in p for ch in "*?["):
            parts.append("d.path GLOB ?")
            args.append(p.rstrip("/") + "/*")
    return " AND (" + " OR ".join(parts) + ")", args


class Ops:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    # ---------------------------------------------------------------- index
    def index(self, prefix: str | None = None) -> str:
        if prefix:
            return prefix_listing(self.store, prefix)
        return self.store.meta_get("index_text") or ""

    # --------------------------------------------------------------- search
    def search(self, query: str, in_: list[str] | None = None, limit: int = 10, mode: str = "lexical") -> SearchResult:
        limit = max(1, min(int(limit), 50))
        toks = tokenize(query or "")
        if not toks:
            return SearchResult([], "lexical", "no searchable words in query")
        where, args = _glob_clause(in_)
        seen: set[str] = set()
        hits: list[Hit] = []
        queries = []
        if len(toks) >= 2:
            queries.append(_fts_string(" ".join(toks)))          # exact phrase
            queries.append(" AND ".join(_fts_string(t) for t in toks))  # all words
        queries.append(" OR ".join(_fts_string(t) for t in toks))       # any word
        for q in queries:
            if len(hits) >= limit:
                break
            rows = self.conn.execute(
                f"""SELECT f.id, d.path, s.heading_path, s.kind,
                           snippet(sections_fts, 2, '**', '**', '…', 20) AS snip,
                           bm25(sections_fts, 0.0, 2.0, 1.0) AS rank
                    FROM sections_fts f
                    JOIN sections s ON s.id = f.id
                    JOIN documents d ON d.doc_id = s.doc_id
                    WHERE sections_fts MATCH ?{where}
                    ORDER BY rank, f.id
                    LIMIT ?""",
                (q, *args, limit),
            ).fetchall()
            for r in rows:
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                hits.append(Hit(r["id"], r["path"], r["heading_path"], " ".join(r["snip"].split()), round(-r["rank"], 2), r["kind"]))
                if len(hits) >= limit:
                    break
        result_mode = "lexical"
        hint = None
        if mode == "hybrid":
            hint = "no embeddings in store; ran lexical"
        if not hits:
            hint = "no hits; try grep for exact codes, drop the in= filter, or use fewer words"
        return SearchResult(hits, result_mode, hint)

    # ----------------------------------------------------------------- read
    def _row_to_section(self, r: sqlite3.Row, context: bool = False) -> Section:
        return Section(r["id"], r["path"], r["heading_path"], r["kind"], r["text"], r["prev_id"], r["next_id"], context)

    def _get(self, sid: str) -> sqlite3.Row:
        r = self.conn.execute(
            "SELECT s.*, d.path FROM sections s JOIN documents d ON d.doc_id = s.doc_id WHERE s.id = ?", (sid,)
        ).fetchone()
        if r is None:
            raise OpsError(f"no section '{sid}'", "search for it first; ids look like path.md#3")
        return r

    def _table_header(self, r: sqlite3.Row) -> sqlite3.Row | None:
        """If r is a continuation of a split table, return the first section of the run."""
        if r["kind"] != "table":
            return None
        first = r
        while first["prev_id"]:
            prev = self._get(first["prev_id"])
            if prev["kind"] == "table" and prev["heading_path"] == r["heading_path"]:
                first = prev
            else:
                break
        return None if first["id"] == r["id"] else first

    @staticmethod
    def _header_lines(header_row: sqlite3.Row) -> str:
        lines = [l for l in header_row["text"].splitlines() if l.lstrip().startswith("|")]
        return "\n".join(lines[:2])

    def read(self, sid: str, context: int = 0) -> ReadResult:
        r = self._get(sid)
        sec = self._row_to_section(r)
        header = self._table_header(r)
        if header is not None:
            head = self._header_lines(header)
            if head and not sec.text.startswith(head):
                sec.text = head + "\n" + sec.text
        ctx: list[Section] = []
        n = max(0, min(int(context), 5))
        if n:
            rows = self.conn.execute(
                """SELECT s.*, d.path FROM sections s JOIN documents d ON d.doc_id = s.doc_id
                   WHERE s.doc_id = ? AND s.ordinal BETWEEN ? AND ? AND s.id != ? ORDER BY s.ordinal""",
                (r["doc_id"], r["ordinal"] - n, r["ordinal"] + n, sid),
            ).fetchall()
            ctx = [self._row_to_section(x, context=True) for x in rows]
        return ReadResult(sec, ctx)

    # ----------------------------------------------------------------- grep
    def grep(self, pattern: str, in_: list[str] | None = None, regex: bool = False, limit: int = 20) -> GrepResult:
        if not pattern or len(pattern) > MAX_PATTERN:
            raise OpsError(f"pattern must be 1–{MAX_PATTERN} characters", "narrow the pattern")
        limit = max(1, min(int(limit), 100))
        where, args = _glob_clause(in_)
        if regex:
            rows = self.conn.execute(
                f"""SELECT s.id, d.path, s.heading_path, s.text FROM sections s
                    JOIN documents d ON d.doc_id = s.doc_id WHERE 1=1{where} ORDER BY s.id""",
                args,
            ).fetchall()
        else:
            # Literal: a full substring scan. An FTS prefilter would require whole-token
            # matches and miss 'TX-45' inside 'TX-4501', which is exactly what grep is for.
            rows = self.conn.execute(
                f"""SELECT s.id, d.path, s.heading_path, s.text FROM sections s
                    JOIN documents d ON d.doc_id = s.doc_id
                    WHERE instr(lower(s.text), ?) > 0{where} ORDER BY s.id""",
                (pattern.lower(), *args),
            ).fetchall()
        matcher = None
        if regex:
            try:
                matcher = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                raise OpsError(f"pattern does not compile: {e}", "set regex=false for a literal match")
        needle = pattern.lower()
        matches: list[Match] = []
        scanned = 0
        truncated = False
        for r in rows:
            if regex:
                scanned += len(r["text"])
                if scanned > REGEX_STEP_BUDGET_CHARS:
                    raise OpsError("pattern too expensive", "narrow with in= or use a literal pattern")
            for line in r["text"].splitlines():
                ok = matcher.search(line) if matcher else needle in line.lower()
                if ok:
                    if len(matches) >= limit:
                        truncated = True
                        break
                    matches.append(Match(r["id"], r["path"], r["heading_path"], line.strip()))
                    break
            if truncated:
                break
        return GrepResult(matches, truncated)

    # ----------------------------------------------------------- neighbours
    def neighbours(self, sid: str, before: int = 1, after: int = 1) -> NeighboursResult:
        r = self._get(sid)
        before = max(0, min(int(before), 5))
        after = max(0, min(int(after), 5))
        rows = self.conn.execute(
            """SELECT s.*, d.path FROM sections s JOIN documents d ON d.doc_id = s.doc_id
               WHERE s.doc_id = ? AND s.ordinal BETWEEN ? AND ? ORDER BY s.ordinal""",
            (r["doc_id"], r["ordinal"] - before, r["ordinal"] + after),
        ).fetchall()
        header = self._table_header(r)
        return NeighboursResult([self._row_to_section(x) for x in rows], self._row_to_section(header) if header else None)

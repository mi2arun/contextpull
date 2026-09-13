"""Ingest a corpus directory into a store.

discover → hash → parse → section → classify → write → fts → summarize → index

Incremental by document sha256: unchanged documents are not touched, deleted
documents are removed, and a no-change run leaves ``index_text`` identical.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .index import build_index
from .ops import normalize_for_fts
from .parse import parse, parse_pdf, pdf_available
from .section import SectionRow, sectionize
from .store import Store

TEXT_KINDS = {".md": "markdown", ".markdown": "markdown", ".txt": "text"}
IGNORE_FILE = ".contextpullignore"

Summarizer = Callable[[str, str, str], str]  # (title, headings, head_text) -> one line


@dataclass
class IngestReport:
    corpus_root: str
    seen: int = 0
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    sections_written: int = 0
    summaries_llm: int = 0
    summaries_offline: int = 0
    summary_errors: int = 0
    first_summary_error: str | None = None
    index_mode: str = ""
    index_tokens: int = 0
    corpus_fingerprint: str = ""
    embedded: int = 0

    def to_dict(self) -> dict:
        return {**self.__dict__, "skipped": [list(s) for s in self.skipped]}


def _load_ignore(root: Path) -> list[str]:
    f = root / IGNORE_FILE
    if not f.exists():
        return []
    return [l.strip() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")]


def discover(root: Path, extra_kinds: dict[str, str] | None = None) -> Iterable[tuple[str, Path, str]]:
    kinds = {**TEXT_KINDS, **(extra_kinds or {})}
    ignore = _load_ignore(root)
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if p.suffix.lower() not in kinds:
            continue
        if any(fnmatch.fnmatch(rel, pat) or rel.startswith(pat.rstrip("/") + "/") for pat in ignore):
            continue
        files.append((rel, p, kinds[p.suffix.lower()]))
    return sorted(files)


_SENT_END = re.compile(r"(?<=[.!?])\s")


def offline_summary(title: str, sections: list[SectionRow]) -> str:
    """First heading plus first sentence of prose. No model needed."""
    first = ""
    for s in sections:
        body = "\n".join(l for l in s.text.splitlines() if not l.startswith("#") and l.strip())
        body = re.sub(r"\s+", " ", body).strip()
        if len(body) >= 20 and not body.startswith(("|", "```")):
            first = _SENT_END.split(body, 1)[0]
            break
    out = f"{title} · {first}" if first and first.lower() != title.lower() else title
    return out[:157] + "…" if len(out) > 160 else out


def _fingerprint(store: Store) -> str:
    h = hashlib.sha256()
    for r in store.conn.execute("SELECT path, sha256 FROM documents ORDER BY path"):
        h.update(r["path"].encode())
        h.update(b"\0")
        h.update(r["sha256"].encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def _write_document(store: Store, rel: str, kind: str, sha: str, nbytes: int, title: str, sections: list[SectionRow], summary: str, summary_src: str) -> None:
    conn = store.conn
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = conn.execute("SELECT doc_id FROM documents WHERE path = ?", (rel,)).fetchone()
    if old:
        conn.execute("DELETE FROM sections_fts WHERE id IN (SELECT id FROM sections WHERE doc_id = ?)", (old[0],))
        conn.execute("DELETE FROM sections WHERE doc_id = ?", (old[0],))
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (old[0],))
    cur = conn.execute(
        "INSERT INTO documents (path, title, summary, summary_src, sha256, bytes, kind, n_sections, ingested_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (rel, title, summary, summary_src, sha, nbytes, kind, len(sections), now),
    )
    doc_id = cur.lastrowid
    ids = [f"{rel}#{s.ordinal}" for s in sections]
    for i, s in enumerate(sections):
        conn.execute(
            "INSERT INTO sections (id, doc_id, ordinal, heading_path, level, kind, text, char_len, hash, prev_id, next_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ids[i], doc_id, s.ordinal, s.heading_path, s.level, s.kind, s.text, len(s.text), s.hash, ids[i - 1] if i else None, ids[i + 1] if i + 1 < len(ids) else None),
        )
        conn.execute("INSERT INTO sections_fts (id, heading_path, text) VALUES (?,?,?)", (ids[i], normalize_for_fts(s.heading_path), normalize_for_fts(s.text)))


def ingest(
    corpus: str | Path,
    store_path: str | Path,
    *,
    max_chars: int = 2000,
    min_chars: int = 40,
    heading_depth: int = 4,
    index_budget_tokens: int = 3000,
    summarizer: Summarizer | None = None,
    summarizer_name: str = "offline",
    progress: Callable[[str], None] | None = None,
    embed_model: str | None = None,
    embed_fn: Callable[[str, list[str]], list[list[float]]] | None = None,
) -> IngestReport:
    root = Path(corpus).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a directory (supported files: {', '.join(sorted(TEXT_KINDS))})")
    sp = Path(store_path)
    store = Store.create(sp) if not sp.exists() else Store.open(sp, readonly=False)
    report = IngestReport(corpus_root=str(root))
    try:
        known = {r["path"]: r["sha256"] for r in store.conn.execute("SELECT path, sha256 FROM documents")}
        offline_docs = {r["path"] for r in store.conn.execute("SELECT path FROM documents WHERE summary_src = 'offline'")}
        seen_paths: set[str] = set()
        extra = {".pdf": "pdf"} if pdf_available() else {}
        if not extra and any(p.suffix.lower() == ".pdf" for p in root.rglob("*.pdf")):
            report.skipped.append(("*.pdf", 'PDF files present but the "pdf" extra is not installed: pip install "contextpull[pdf]"'))
        for rel, path, kind in discover(root, extra):
            report.seen += 1
            seen_paths.add(rel)
            try:
                raw = path.read_bytes()
            except OSError as e:
                report.skipped.append((rel, str(e)))
                continue
            sha = hashlib.sha256(raw).hexdigest()
            if known.get(rel) == sha:
                report.unchanged += 1
                if summarizer is not None and rel in offline_docs:
                    _retry_summary(store, rel, sha, summarizer, summarizer_name, report)
                continue
            try:
                if kind == "pdf":
                    parsed = parse_pdf(raw, fallback_title=path.stem)
                else:
                    parsed = parse(raw.decode("utf-8", errors="replace"), kind, fallback_title=path.stem)
                sections = sectionize(parsed, max_chars=max_chars, min_chars=min_chars, heading_depth=heading_depth)
            except Exception as e:  # a bad file must never abort the run
                report.skipped.append((rel, f"parse error: {e}"))
                continue
            if not sections:
                report.skipped.append((rel, "no content"))
                continue
            title = parsed.title or path.stem
            summary, src = _summary_for(store, sha, title, sections, summarizer, summarizer_name, report)
            if src == "llm":
                report.summaries_llm += 1
            else:
                report.summaries_offline += 1
            with store.conn:
                _write_document(store, rel, kind, sha, len(raw), title, sections, summary, src)
            report.changed += 1
            report.sections_written += len(sections)
            if progress:
                progress(f"{rel}: {len(sections)} sections")

        gone = [p for p in known if p not in seen_paths]
        if gone:
            with store.conn:
                for p in gone:
                    doc = store.conn.execute("SELECT doc_id FROM documents WHERE path = ?", (p,)).fetchone()
                    store.conn.execute("DELETE FROM sections_fts WHERE id IN (SELECT id FROM sections WHERE doc_id = ?)", (doc[0],))
                    store.conn.execute("DELETE FROM sections WHERE doc_id = ?", (doc[0],))
                    store.conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc[0],))
            report.deleted = len(gone)

        if embed_model:
            report.embedded = _embed_missing(store, embed_model, embed_fn, progress)
            store.meta_set("embed_model", embed_model)
            store.conn.commit()

        with store.conn:
            fp = _fingerprint(store)
            store.meta_set("corpus_root", str(root))
            store.meta_set("corpus_fingerprint", fp)
            store.meta_set("summarizer", summarizer_name)
            store.meta_set("section_max_chars", str(max_chars))
            store.meta_set("index_budget_tokens", str(index_budget_tokens))
            text, mode, tokens = build_index(store, index_budget_tokens)
            store.meta_set("index_text", text)
            store.meta_set("index_mode", mode)
            store.meta_set("index_tokens", str(tokens))
            store.meta_set("ingested_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        report.corpus_fingerprint = fp
        report.index_mode = mode
        report.index_tokens = tokens
    finally:
        store.close()
    return report


def _embed_missing(store: Store, model: str, embed_fn, progress) -> int:
    """Embed every section that has no vector for this model yet (changed or new)."""
    from .embed import embed_texts, to_blob

    fn = embed_fn or embed_texts
    rows = store.conn.execute(
        "SELECT s.id, s.heading_path, s.text FROM sections s LEFT JOIN embeddings e ON e.section_id = s.id AND e.model = ? WHERE e.section_id IS NULL ORDER BY s.id",
        (model,),
    ).fetchall()
    store.conn.execute("DELETE FROM embeddings WHERE model != ?", (model,))
    done = 0
    for start in range(0, len(rows), 100):
        batch = rows[start : start + 100]
        vectors = fn(model, [f"{r['heading_path']}\n{r['text']}" for r in batch])
        with store.conn:
            for r, v in zip(batch, vectors):
                store.conn.execute("INSERT OR REPLACE INTO embeddings (section_id, model, dim, vec) VALUES (?,?,?,?)", (r["id"], model, len(v), to_blob(v)))
        done += len(batch)
        if progress:
            progress(f"embedded {done}/{len(rows)}")
    return done


def _summary_for(store: Store, sha: str, title: str, sections: list[SectionRow], summarizer: Summarizer | None, name: str, report: IngestReport | None = None) -> tuple[str, str]:
    if summarizer is None:
        return offline_summary(title, sections), "offline"
    cached = store.conn.execute("SELECT summary FROM summary_cache WHERE sha256 = ? AND model = ?", (sha, name)).fetchone()
    if cached:
        return cached[0], "llm"
    headings = "\n".join(dict.fromkeys(s.heading_path for s in sections))
    head = "\n\n".join(s.text for s in sections[:3])[:1500]
    try:
        summary = summarizer(title, headings, head).strip().splitlines()[0][:160]
        if not summary:
            raise ValueError("empty summary")
    except Exception as e:
        if report is not None:
            report.summary_errors += 1
            if report.first_summary_error is None:
                report.first_summary_error = f"{type(e).__name__}: {str(e)[:200]}"
        return offline_summary(title, sections), "offline"
    with store.conn:
        store.conn.execute("INSERT OR REPLACE INTO summary_cache (sha256, model, summary) VALUES (?,?,?)", (sha, name, summary))
    return summary, "llm"


def _retry_summary(store: Store, rel: str, sha: str, summarizer: Summarizer, name: str, report: IngestReport) -> None:
    """An unchanged document whose summary fell back to offline earlier: try the model again."""
    doc = store.conn.execute("SELECT doc_id, title FROM documents WHERE path = ?", (rel,)).fetchone()
    rows = store.conn.execute("SELECT ordinal, heading_path, level, kind, text FROM sections WHERE doc_id = ? ORDER BY ordinal", (doc["doc_id"],)).fetchall()
    sections = [SectionRow(r["ordinal"], r["heading_path"], r["level"], r["kind"], r["text"]) for r in rows]
    summary, src = _summary_for(store, sha, doc["title"], sections, summarizer, name, report)
    if src == "llm":
        with store.conn:
            store.conn.execute("UPDATE documents SET summary = ?, summary_src = 'llm' WHERE doc_id = ?", (summary, doc["doc_id"]))
        report.summaries_llm += 1


def export_chunks(store: Store) -> Iterable[str]:
    """ragbisect-compatible JSONL: {"id","text","source"} per section."""
    for r in store.conn.execute("SELECT s.id, s.text, d.path FROM sections s JOIN documents d USING(doc_id) ORDER BY d.path, s.ordinal"):
        yield json.dumps({"id": r["id"], "text": r["text"], "source": r["path"]}, ensure_ascii=False)

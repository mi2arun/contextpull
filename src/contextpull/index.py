"""Build the always-in-context index text from document summaries.

Flat when it fits the token budget; hierarchical (one line per top-level
directory) when it does not. Readers return ``meta.index_text`` verbatim and
compute ``index(prefix)`` with ``prefix_listing``.
"""

from __future__ import annotations

from .store import Store

PREAMBLE = (
    "ContextPull gives you exact sections from a document corpus. The index below lists every document. "
    "Search for pointers (ids + snippets), read the sections you need verbatim, then answer citing ids like [path.md#3]. "
    "For comparisons search each document with in=[...] and read both. For codes, flags and identifiers use grep.\n\n"
)

DISCIPLINE = (
    "Call search(query, in?) to find sections by words or identifiers, read(id) for exact text, "
    "grep(pattern) for codes and flags, neighbours(id) for the header or next clause.\n"
    "Search returns ids and snippets only; read what you need, then answer with [ids]."
)


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


LABEL_CHARS = 60


def _doc_line(path: str, title: str, summary: str | None, n: int, compact: bool = False) -> str:
    if compact:
        return f"{path:<30}  ({n})"
    label = (summary or title).strip()
    if len(label) > LABEL_CHARS:
        label = label[: LABEL_CHARS - 1].rstrip() + "…"
    return f"{path:<30}  {label}  ({n})"


def _header(store: Store, n_docs: int, n_secs: int, mode: str) -> str:
    fp = (store.meta_get("corpus_fingerprint") or "")[:8]
    summ = store.meta_get("summarizer") or "offline"
    mode_note = {
        "flat": "",
        "compact": " · compact; call index(prefix) for summaries",
        "hierarchical": " · hierarchical; call index(prefix) to expand a directory",
    }[mode]
    return f"ContextPull index · {n_docs} documents · {n_secs} sections · corpus {fp} · summaries: {summ}{mode_note}"


def flat_listing(store: Store, prefix: str = "", compact: bool = False) -> list[str]:
    rows = store.conn.execute(
        "SELECT path, title, summary, n_sections FROM documents WHERE path LIKE ? ESCAPE '\\' ORDER BY path",
        (_like_prefix(prefix),),
    ).fetchall()
    return [_doc_line(r["path"], r["title"], r["summary"], r["n_sections"], compact) for r in rows]


def _like_prefix(prefix: str) -> str:
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "%"


def directory_listing(store: Store) -> list[str]:
    rows = store.conn.execute("SELECT path, title, summary, n_sections FROM documents ORDER BY path").fetchall()
    groups: dict[str, list] = {}
    for r in rows:
        top = r["path"].split("/", 1)[0] + "/" if "/" in r["path"] else "(root)"
        groups.setdefault(top, []).append(r)
    lines = []
    for top, rs in groups.items():
        n_secs = sum(r["n_sections"] for r in rs)
        titles = ", ".join((r["summary"] or r["title"])[:40] for r in rs[:3])
        more = f", +{len(rs) - 3} more" if len(rs) > 3 else ""
        lines.append(f"{top:<30}{len(rs)} docs · {n_secs} sections · {titles}{more}")
    return lines


def build_index(store: Store, budget_tokens: int) -> tuple[str, str, int]:
    """Returns (text, mode, tokens)."""
    n_docs, n_secs = store.counts()
    for mode in ("flat", "compact"):
        body = flat_listing(store, compact=(mode == "compact"))
        text = "\n".join([_header(store, n_docs, n_secs, mode), DISCIPLINE, "", *body])
        if estimate_tokens(text) <= budget_tokens:
            return text, mode, estimate_tokens(text)
    body = directory_listing(store)
    head = [_header(store, n_docs, n_secs, "hierarchical"), DISCIPLINE, ""]
    text = "\n".join([*head, *body])
    if estimate_tokens(text) <= budget_tokens:
        return text, "hierarchical", estimate_tokens(text)
    # Still too big: keep as many directory lines as fit and say how many were left out.
    kept: list[str] = []
    for line in body:
        candidate = "\n".join([*head, *kept, line, f"… and {len(body) - len(kept) - 1} more directories; call index(prefix) or search first"])
        if estimate_tokens(candidate) > budget_tokens:
            break
        kept.append(line)
    text = "\n".join([*head, *kept, f"… and {len(body) - len(kept)} more directories; call index(prefix) or search first"])
    return text, "hierarchical", estimate_tokens(text)


def prefix_listing(store: Store, prefix: str) -> str:
    rows = store.conn.execute(
        "SELECT count(*), coalesce(sum(n_sections), 0) FROM documents WHERE path LIKE ? ESCAPE '\\'",
        (_like_prefix(prefix),),
    ).fetchone()
    header = f"ContextPull index · {prefix or '/'} · {rows[0]} documents · {rows[1]} sections"
    return "\n".join([header, *flat_listing(store, prefix)])

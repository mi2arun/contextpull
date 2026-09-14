"""SQLite store: create, open, migrate, and typed access to `meta`.

Schema is documented in docs/system-design.md §1 and governed by
docs/store-format.md. Readers in other languages open this same file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = "1.0"
FTS_TOKENIZE = "unicode61 remove_diacritics 2 tokenchars '-_.'"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
  doc_id      INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,
  title       TEXT NOT NULL,
  summary     TEXT,
  summary_src TEXT,
  sha256      TEXT NOT NULL,
  bytes       INTEGER NOT NULL,
  kind        TEXT NOT NULL,
  n_sections  INTEGER NOT NULL,
  ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sections (
  id           TEXT PRIMARY KEY,
  doc_id       INTEGER NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  ordinal      INTEGER NOT NULL,
  heading_path TEXT NOT NULL,
  level        INTEGER NOT NULL,
  kind         TEXT NOT NULL,
  text         TEXT NOT NULL,
  char_len     INTEGER NOT NULL,
  hash         TEXT NOT NULL,
  prev_id      TEXT,
  next_id      TEXT,
  UNIQUE (doc_id, ordinal)
);
CREATE INDEX IF NOT EXISTS sections_doc ON sections(doc_id, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
  id UNINDEXED,
  heading_path,
  text,
  tokenize = "{FTS_TOKENIZE}"
);
CREATE TABLE IF NOT EXISTS embeddings (
  section_id TEXT PRIMARY KEY REFERENCES sections(id) ON DELETE CASCADE,
  model      TEXT NOT NULL,
  dim        INTEGER NOT NULL,
  vec        BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS summary_cache (
  sha256  TEXT PRIMARY KEY,
  model   TEXT NOT NULL,
  summary TEXT NOT NULL
);
"""


class StoreError(Exception):
    pass


def _major(v: str) -> str:
    return v.split(".", 1)[0]


class Store:
    """Thin wrapper over one sqlite3 connection. Use ``Store.create`` to build
    and ``Store.open`` to read. ``readonly=True`` opens with ``mode=ro`` and
    is what servers and SDK readers should do."""

    def __init__(self, conn: sqlite3.Connection, path: Path, readonly: bool):
        self.conn = conn
        self.path = path
        self.readonly = readonly
        self.conn.row_factory = sqlite3.Row

    # ---------------------------------------------------------------- open
    @classmethod
    def create(cls, path: str | Path) -> "Store":
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.executescript(SCHEMA)
        except sqlite3.OperationalError as e:
            conn.close()
            if "fts5" in str(e).lower() or "no such module" in str(e).lower():
                raise StoreError("this Python's sqlite3 lacks FTS5; ContextPull needs an FTS5-enabled SQLite") from e
            raise
        store = cls(conn, p, readonly=False)
        if store.meta_get("schema_version") is None:
            store.meta_set("schema_version", SCHEMA_VERSION)
        conn.commit()
        return store

    @classmethod
    def open(cls, path: str | Path, readonly: bool = True, check_same_thread: bool = True) -> "Store":
        """``check_same_thread=False`` lets one connection be used from several threads;
        the caller must then serialise access (the eval adapters hold a lock)."""
        p = Path(path)
        if not p.exists():
            raise StoreError(f"no store at {p}; run `contextpull ingest <corpus>` first")
        if readonly:
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=check_same_thread)
        else:
            conn = sqlite3.connect(str(p), check_same_thread=check_same_thread)
            conn.execute("PRAGMA foreign_keys=ON")
        store = cls(conn, p, readonly)
        try:
            version = store.meta_get("schema_version")
        except sqlite3.DatabaseError as e:
            conn.close()
            raise StoreError(f"{p} is not a ContextPull store") from e
        if version is None:
            conn.close()
            raise StoreError(f"{p} is not a ContextPull store (no schema_version)")
        if _major(version) != _major(SCHEMA_VERSION):
            conn.close()
            raise StoreError(f"store {p} has schema {version}; this contextpull supports {SCHEMA_VERSION}")
        try:
            conn.execute("SELECT count(*) FROM sections_fts LIMIT 1").fetchone()
        except sqlite3.OperationalError as e:
            conn.close()
            raise StoreError("this Python's sqlite3 lacks FTS5; ContextPull needs an FTS5-enabled SQLite") from e
        return store

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- meta
    def meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def meta_set(self, key: str, value: str) -> None:
        if self.readonly:
            raise StoreError("store is read-only")
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def meta_all(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM meta")}

    # ---------------------------------------------------------------- counts
    def counts(self) -> tuple[int, int]:
        d = self.conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        s = self.conn.execute("SELECT count(*) FROM sections").fetchone()[0]
        return d, s

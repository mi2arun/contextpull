"""Per-question result cache so a benchmark re-run costs nothing and the
numbers are reproducible. Keyed by everything that could change the answer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path


class RunCache:
    def __init__(self, path: str | Path = ".contextpull-eval/cache.sqlite"):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p), check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS runs (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._conn.commit()
        self._lock = threading.Lock()

    @staticmethod
    def key(*parts: object) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM runs WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO runs (key, value) VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))
            self._conn.commit()

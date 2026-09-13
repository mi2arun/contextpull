"""Synthetic scale run: N documents, measure ingest time, store size, index
mode and per-operation latency. Usage: python scripts/scale_test.py [n_docs]"""

from __future__ import annotations

import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from contextpull.ingest import ingest  # noqa: E402
from contextpull.ops import Ops  # noqa: E402
from contextpull.store import Store  # noqa: E402

WORDS = ("refund policy cache index resolve install package version environment marker platform "
         "credential token timeout retry gateway shipping warranty storage voltage model release").split()


def make_corpus(root: Path, n_docs: int, rng: random.Random) -> None:
    for i in range(n_docs):
        d = root / f"area{i % 40:02d}" / f"topic{(i // 40) % 25:02d}"
        d.mkdir(parents=True, exist_ok=True)
        parts = [f"# Document {i}: {' '.join(rng.choices(WORDS, k=3))}", ""]
        for s in range(rng.randint(8, 30)):
            parts.append(f"## Section {s} {' '.join(rng.choices(WORDS, k=2))} CODE-{i:05d}-{s:02d}")
            parts.append("")
            parts.append(" ".join(rng.choices(WORDS, k=rng.randint(40, 220))) + f". Set VAR_{i}_{s} to tune it.")
            parts.append("")
            if s % 6 == 0:
                parts.append("| Model | Temp | Volt |\n|---|---|---|\n" + "\n".join(f"| R-{i}{r} | {r} °C | {r} V |" for r in range(rng.randint(2, 12))))
                parts.append("")
        (d / f"doc-{i:05d}.md").write_text("\n".join(parts))


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def main() -> None:
    n_docs = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    rng = random.Random(0)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "corpus"
        t0 = time.perf_counter()
        make_corpus(root, n_docs, rng)
        t_gen = time.perf_counter() - t0

        sp = Path(td) / "store.sqlite"
        t0 = time.perf_counter()
        rep = ingest(root, sp)
        t_ingest = time.perf_counter() - t0

        t0 = time.perf_counter()
        rep2 = ingest(root, sp)
        t_noop = time.perf_counter() - t0

        size_mb = sum(p.stat().st_size for p in Path(td).glob("store.sqlite*")) / 1e6
        with Store.open(sp) as s:
            ops = Ops(s)
            n_docs_db, n_secs = s.counts()
            ids = [r[0] for r in s.conn.execute("SELECT id FROM sections ORDER BY random() LIMIT 300")]
            lat = {"search_words": [], "search_identifier": [], "read": [], "grep_literal": [], "neighbours": [], "index_prefix": []}
            for k in range(300):
                q = " ".join(rng.choices(WORDS, k=2))
                t0 = time.perf_counter(); ops.search(q); lat["search_words"].append(time.perf_counter() - t0)
                code = f"CODE-{rng.randrange(n_docs):05d}-{rng.randrange(8):02d}"
                t0 = time.perf_counter(); hits = ops.search(code); lat["search_identifier"].append(time.perf_counter() - t0)
                t0 = time.perf_counter(); ops.read(ids[k]); lat["read"].append(time.perf_counter() - t0)
                t0 = time.perf_counter(); ops.grep(f"VAR_{rng.randrange(n_docs)}_"); lat["grep_literal"].append(time.perf_counter() - t0)
                t0 = time.perf_counter(); ops.neighbours(ids[k]); lat["neighbours"].append(time.perf_counter() - t0)
                t0 = time.perf_counter(); ops.index(f"area{rng.randrange(40):02d}/"); lat["index_prefix"].append(time.perf_counter() - t0)
            # identifier precision: does the exact code come back first?
            exact_first = 0
            for _ in range(200):
                i, sct = rng.randrange(n_docs), rng.randrange(8)
                hits = ops.search(f"CODE-{i:05d}-{sct:02d}").hits
                exact_first += bool(hits) and hits[0].id.startswith(f"area{i % 40:02d}/topic{(i // 40) % 25:02d}/doc-{i:05d}.md#")
            index_mode = s.meta_get("index_mode")
            index_tokens = s.meta_get("index_tokens")

        print(f"docs={n_docs_db} sections={n_secs} store={size_mb:.1f}MB")
        print(f"corpus gen {t_gen:.1f}s | ingest {t_ingest:.1f}s ({n_secs / t_ingest:.0f} sections/s) | no-op re-ingest {t_noop:.2f}s (changed={rep2.changed})")
        print(f"index mode={index_mode} tokens={index_tokens}")
        print("latency ms          p50     p95     max")
        for k, v in lat.items():
            ms = [x * 1000 for x in v]
            print(f"  {k:<18}{statistics.median(ms):7.1f} {pct(ms, 0.95):7.1f} {max(ms):7.1f}")
        print(f"identifier search exact-first: {exact_first}/200")


if __name__ == "__main__":
    main()

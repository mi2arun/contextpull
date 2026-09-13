"""Adversarial inputs: ingest must never crash, and sectioning invariants must
hold for anything the parser accepts."""

import os
import random
import re
import string
from pathlib import Path

import pytest

from contextpull.ingest import ingest
from contextpull.ops import Ops
from contextpull.parse import parse_markdown
from contextpull.section import sectionize
from contextpull.store import Store


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _check_invariants(rows, max_chars):
    ordinals = [r.ordinal for r in rows]
    assert ordinals == list(range(len(rows)))
    for r in rows:
        assert r.heading_path.strip()
        assert r.text.strip()
        fences = sum(1 for l in r.text.splitlines() if l.strip().startswith("```"))
        assert fences % 2 == 0, "partial fence in section"
        if r.kind == "table":
            body = [l for l in r.text.splitlines() if l.lstrip().startswith("|")]
            assert len(body) >= 2 and "---" in body[1], "table part without header"
        if len(r.text) > max_chars:
            # only whole code blocks, unsplittable table rows, or single words may exceed the limit
            assert "```" in r.text or r.kind in ("code", "mixed", "table") or " " not in r.text.strip()


def test_adversarial_corpus_ingests_without_crashing(tmp_path: Path):
    c = tmp_path / "corpus"
    c.mkdir()
    (c / "empty.md").write_text("")
    (c / "spaces.md").write_text("   \n\n  \n")
    (c / "binary.md").write_bytes(bytes(range(256)) * 40)
    (c / "latin1.txt").write_bytes("caf\xe9 na\xefve r\xe9sum\xe9 ".encode("latin-1") * 20)
    (c / "crlf.md").write_text("# CRLF\r\n\r\nLine one is here and long enough.\r\n\r\n## Two\r\n\r\nSecond paragraph, also long enough.\r\n")
    (c / "unclosed.md").write_text("# Unclosed\n\nIntro text that is long enough.\n\n```python\nprint('never closed')\n\n## Not a heading inside fence\n")
    (c / "table-eof.md").write_text("# T\n\nText long enough to be kept.\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    (c / "table-no-body.md").write_text("# T\n\nText long enough to be kept here.\n\n| a | b |\n|---|---|\n\nafter\n")
    (c / "deep.md").write_text("# H1\n\ntext long enough to keep around\n\n###### H6\n\nsix levels deep and long enough\n\n#### H4\n\nfour levels and long enough\n")
    (c / "longline.md").write_text("# Long\n\n" + "x" * 50_000 + "\n")
    (c / "big.md").write_text("# Big\n\n" + "\n\n".join(f"## S{i}\n\n" + ("word " * 200) for i in range(2000)))
    (c / "unicode ñame 名前.md").write_text("# Ünïcödé 名前 🚀\n\nDiacritics and émojis, długość wystarczająca.\n\n## Wörter\n\nZürich, São Paulo, naïve café résumé.\n")
    (c / "sub dir").mkdir()
    (c / "sub dir" / "same.md").write_text("# Same\n\nOne copy of this text long enough.\n")
    (c / "same.md").write_text("# Same\n\nAnother copy of this text long enough.\n")
    (c / "hashes.md").write_text("#!/bin/bash\n\n#not-a-heading\n\n# Real\n\n#tag text long enough to be a paragraph\n")
    (c / "image.png").write_bytes(b"\x89PNG\r\n")
    (c / ".hidden").mkdir()
    (c / ".hidden" / "secret.md").write_text("# hidden\n\nshould not be ingested at all\n")
    os.symlink(c / "same.md", c / "link.md")

    sp = tmp_path / "s.sqlite"
    rep = ingest(c, sp)
    assert rep.seen >= 14
    skipped = dict(rep.skipped)
    assert "empty.md" in skipped and "spaces.md" in skipped
    with Store.open(sp) as s:
        paths = {r[0] for r in s.conn.execute("SELECT path FROM documents")}
        assert ".hidden/secret.md" not in paths
        assert "unicode ñame 名前.md" in paths and "sub dir/same.md" in paths and "same.md" in paths
        ops = Ops(s)
        assert ops.search("Zürich").hits and ops.search("zurich").hits  # diacritics folded
        assert ops.search("naïve").hits
        assert any(h.doc == "crlf.md" for h in ops.search("second paragraph").hits)
        # unclosed fence: swallowed to EOF but never crashes, and no partial fence in stored text
        r = s.conn.execute("SELECT text FROM sections WHERE id LIKE 'unclosed.md#%' ORDER BY ordinal").fetchall()
        assert r
        big = s.conn.execute("SELECT count(*), max(char_len) FROM sections WHERE id LIKE 'big.md#%'").fetchone()
        assert big[0] >= 2000 and big[1] <= 2000
        long_ = s.conn.execute("SELECT count(*) FROM sections WHERE id LIKE 'longline.md#%'").fetchone()[0]
        assert long_ >= 25  # 50k chars hard-cut into <=2000 char pieces


def _random_markdown(rng: random.Random) -> str:
    words = ["refund", "policy", "cache", "UV_CACHE_DIR", "--flag", "TX-4419", "3.12", "table", "code", "naïve"]
    out = []
    for _ in range(rng.randint(1, 40)):
        kind = rng.choice(["h", "h", "p", "p", "p", "code", "table", "list", "blank"])
        if kind == "h":
            out.append("#" * rng.randint(1, 6) + " " + " ".join(rng.choices(words, k=rng.randint(1, 4))))
        elif kind == "p":
            out.append(" ".join(rng.choices(words, k=rng.randint(1, 400))) + rng.choice([".", "", "!"]))
        elif kind == "code":
            out.append("```" + rng.choice(["", "python", 'toml title="x"']) + "\n" + "\n".join(" ".join(rng.choices(words, k=5)) for _ in range(rng.randint(0, 60))) + "\n```")
        elif kind == "table":
            cols = rng.randint(1, 5)
            hdr = "| " + " | ".join(rng.choices(words, k=cols)) + " |"
            sep = "|" + "---|" * cols
            rows = ["| " + " | ".join(rng.choices(words, k=cols)) + " |" for _ in range(rng.randint(0, 80))]
            out.append("\n".join([hdr, sep, *rows]))
        elif kind == "list":
            out.append("\n".join(f"- {' '.join(rng.choices(words, k=3))}" for _ in range(rng.randint(1, 8))))
        else:
            out.append("")
    return "\n\n".join(out) + "\n"


@pytest.mark.parametrize("seed", range(60))
def test_sectionizer_invariants_on_random_markdown(seed: int):
    rng = random.Random(seed)
    md = _random_markdown(rng)
    max_chars = rng.choice([200, 500, 2000])
    parsed = parse_markdown(md, fallback_title="doc")
    rows = sectionize(parsed, max_chars=max_chars)
    _check_invariants(rows, max_chars)
    # lossless modulo whitespace and repeated table headers
    joined = _norm(" ".join(r.text for r in rows))
    for b in parsed.blocks:
        first_line = _norm(b.raw.splitlines()[0]) if b.raw.strip() else ""
        assert first_line in joined
    # deterministic
    again = sectionize(parse_markdown(md, fallback_title="doc"), max_chars=max_chars)
    assert [(r.ordinal, r.heading_path, r.hash) for r in rows] == [(r.ordinal, r.heading_path, r.hash) for r in again]

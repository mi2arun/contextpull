import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from contextpull.cli import main
from contextpull.ingest import ingest
from contextpull.store import Store

from .conftest import FIXTURE


def _run(args, capsys):
    code = main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_end_to_end(tmp_path: Path, capsys, monkeypatch):
    sp = str(tmp_path / "s.sqlite")
    code, out, _ = _run(["ingest", str(FIXTURE), "--store", sp], capsys)
    assert code == 0 and "7 documents seen" in out

    code, out, _ = _run(["index", "--store", sp], capsys)
    assert code == 0 and out.startswith("ContextPull index")

    code, out, _ = _run(["search", "TX-4419", "--store", sp, "--json"], capsys)
    assert code == 0
    hits = json.loads(out)["hits"]
    assert hits[0]["id"].startswith("errors.md#")

    code, out, _ = _run(["read", hits[0]["id"], "--store", sp, "--context", "1", "--json"], capsys)
    assert code == 0 and "TX-4419" in json.loads(out)["text"]

    code, out, _ = _run(["grep", "--store", sp, "--", "TX-45"], capsys)
    assert code == 0 and "TX-45xx" in out

    code, out, _ = _run(["neighbours", hits[0]["id"], "--store", sp, "--json"], capsys)
    assert code == 0 and json.loads(out)["sections"]

    code, out, _ = _run(["export-chunks", "--store", sp], capsys)
    lines = [json.loads(l) for l in out.splitlines()]
    assert len(lines) == 27 and set(lines[0]) == {"id", "text", "source"}

    code, out, _ = _run(["tools-json"], capsys)
    assert [t["name"] for t in json.loads(out)["tools"]] == ["index", "search", "read", "grep", "neighbours"]

    # errors: unknown id (exit 2 with json), missing store (exit 1), bad regex
    code, out, _ = _run(["read", "nope.md#1", "--store", sp, "--json"], capsys)
    assert code == 2 and "no section" in json.loads(out)["error"]
    code, _, err = _run(["search", "x", "--store", str(tmp_path / "missing.sqlite")], capsys)
    assert code == 1 and "no store" in err
    code, _, err = _run(["grep", "(", "--regex", "--store", sp], capsys)
    assert code == 2 and "does not compile" in err
    code, _, err = _run(["ingest", str(tmp_path / "nowhere"), "--store", sp], capsys)
    assert code == 1 and "not a directory" in err

    # env var precedence for the store path
    monkeypatch.setenv("CONTEXTPULL_STORE", sp)
    code, out, _ = _run(["index"], capsys)
    assert code == 0 and "7 documents" in out


def test_console_script_installed():
    r = subprocess.run([sys.executable, "-m", "contextpull.cli", "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("contextpull ")


def test_reader_keeps_working_while_ingest_rewrites(tmp_path: Path):
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURE, corpus)
    sp = tmp_path / "s.sqlite"
    ingest(corpus, sp)

    errors: list[str] = []
    stop = False

    def reader():
        with Store.open(sp) as s:
            from contextpull.ops import Ops
            ops = Ops(s)
            while not stop:
                try:
                    assert ops.index().startswith("ContextPull index")
                    ops.search("refund window")
                except Exception as e:  # pragma: no cover
                    errors.append(repr(e))
                time.sleep(0.002)

    t = threading.Thread(target=reader)
    t.start()
    for i in range(5):
        (corpus / "policies" / "policy-2025.md").write_text(f"# Refund Policy 2025\n\n## Refund window\n\nRevision {i}: the window is {14 + i} days, text long enough.\n")
        ingest(corpus, sp)
    stop = True
    t.join()
    assert errors == []
    with Store.open(sp) as s:
        assert "Revision 4" in s.conn.execute("SELECT text FROM sections WHERE id='policies/policy-2025.md#0'").fetchone()[0]

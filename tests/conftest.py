from pathlib import Path

import pytest

from contextpull.ingest import ingest
from contextpull.store import Store

FIXTURE = Path(__file__).resolve().parent.parent / "conformance" / "corpus"


@pytest.fixture(scope="session")
def fixture_store(tmp_path_factory) -> Path:
    sp = tmp_path_factory.mktemp("store") / "store.sqlite"
    ingest(FIXTURE, sp)
    return sp


@pytest.fixture()
def store(fixture_store: Path):
    with Store.open(fixture_store, readonly=True) as s:
        yield s

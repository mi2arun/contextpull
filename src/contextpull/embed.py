"""Optional embeddings for hybrid search. OpenAI-compatible /embeddings via
urllib; vectors stored as float32 little-endian blobs, L2-normalised.

Hybrid search needs the query embedded at query time, which is the one place
ContextPull talks to a network service while answering. It is opt-in
(``ingest --embed-model …``) and documented as such.
"""

from __future__ import annotations

import json
import math
import os
import struct
import urllib.error
import urllib.request
from array import array

from .llm import LLMError, _env, _post, parse_model

DEFAULT_EMBED_MODEL = "openai:text-embedding-3-small"


def embed_texts(model_spec: str, texts: list[str], timeout: float = 60.0, batch_size: int = 100) -> list[list[float]]:
    provider, model = parse_model(model_spec)
    if provider != "openai":
        raise LLMError(f"embeddings need an OpenAI-compatible endpoint; got provider {provider!r} (OPENAI_BASE_URL may point at any compatible server)")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = _post(f"{base}/embeddings", {"Authorization": f"Bearer {_env('OPENAI_API_KEY')}"}, {"model": model, "input": batch}, timeout)
        vectors = sorted(resp["data"], key=lambda d: d["index"])
        if len(vectors) != len(batch):
            raise LLMError("embedding response length mismatch")
        out.extend(normalize(v["embedding"]) for v in vectors)
    return out


def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(math.fsum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def to_blob(v: list[float]) -> bytes:
    return array("f", v).tobytes()


def from_blob(b: bytes) -> array:
    a = array("f")
    a.frombytes(b)
    return a


def dot(a, b) -> float:
    return math.fsum(x * y for x, y in zip(a, b))

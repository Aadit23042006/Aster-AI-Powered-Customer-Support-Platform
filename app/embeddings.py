"""Embedding backends.

`GeminiEmbedder` is what the app uses in production (calls the real Gemini
embedding API and caches results to disk keyed by content hash, so
re-indexing after a small doc edit doesn't re-embed the whole corpus).

`FakeEmbedder` is a small deterministic bag-of-words hashing embedder used
only by the offline unit tests and the `--mock` evaluation mode, where no
network access / API key is available. It is never used to produce the
numbers that belong in the README.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Protocol

import numpy as np

from app import config


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    def __init__(self, api_key: str | None = None, model: str = config.EMBEDDING_MODEL,
                 dim: int = config.EMBEDDING_DIM, cache_path: Path | None = None):
        from google import genai  # imported lazily so tests don't need the package

        self._client = genai.Client(api_key=api_key or config.GEMINI_API_KEY)
        self._model = model
        self._dim = dim
        self._cache_path = cache_path or (config.BASE_DIR / "app" / "data_cache" / "embedding_cache.json")
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[float]] = {}
        if self._cache_path.exists():
            self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))

    def _key(self, text: str, task_type: str) -> str:
        return f"{self._model}:{self._dim}:{task_type}:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _save_cache(self) -> None:
        self._cache_path.write_text(json.dumps(self._cache), encoding="utf-8")

    def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        keys = [self._key(t, task_type) for t in texts]
        missing_idx = [i for i, k in enumerate(keys) if k not in self._cache]
        if missing_idx:
            result = self._client.models.embed_content(
                model=self._model,
                contents=[texts[i] for i in missing_idx],
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dim,
                ),
            )
            for i, emb in zip(missing_idx, result.embeddings, strict=True):
                self._cache[keys[i]] = list(emb.values)
            self._save_cache()
        return [self._cache[k] for k in keys]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], "RETRIEVAL_QUERY")[0]


_WORD_RE = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic hashing embedder for tests / --mock mode. No network,
    no API key. Similar documents get *roughly* similar vectors via
    hashed-bag-of-words, which is enough for unit tests that check plumbing
    (top-k ordering, precedence filtering) rather than semantic quality."""

    def __init__(self, dim: int = 256):
        self._dim = dim

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self._dim, dtype=np.float64)
        for word in _WORD_RE.findall(text.lower()):
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            v[h % self._dim] += 1.0
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        return v.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

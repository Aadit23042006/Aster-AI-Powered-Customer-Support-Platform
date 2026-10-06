from __future__ import annotations

from pathlib import Path

import pytest

from app.embeddings import FakeEmbedder
from app.kb_loader import load_knowledge_base
from app.orders import OrderLookupTool
from app.retriever import Retriever, VectorIndex

REPO_ROOT = Path(__file__).resolve().parent.parent
KB_DIR = REPO_ROOT / "knowledge-base"
ORDERS_PATH = REPO_ROOT / "data" / "orders.json"


@pytest.fixture(scope="session")
def kb_chunks():
    return load_knowledge_base(KB_DIR)


@pytest.fixture(scope="session")
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture(scope="session")
def retriever(kb_chunks, fake_embedder):
    # min_similarity is tuned for FakeEmbedder's score distribution here
    # (its hashed bag-of-words vectors produce lower absolute cosine scores
    # than real Gemini embeddings do) -- the production default in
    # app/config.py (0.45) is calibrated separately for the real embedder.
    # See bug diary entry #3 in the README: too loose a threshold let
    # semantically-unrelated chunks trigger the conflict watchlist by
    # sharing incidental vocabulary.
    index = VectorIndex.build(kb_chunks, fake_embedder)
    return Retriever(index, fake_embedder, top_k=6, min_similarity=0.2)


@pytest.fixture()
def orders_tool():
    return OrderLookupTool(ORDERS_PATH)

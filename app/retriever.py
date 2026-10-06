"""Vector store + retrieval policy.

Three deliberately separate concerns live here:

1. Plain cosine-similarity search over chunk embeddings (`VectorIndex`) --
   the semantic arm of retrieval, unchanged from Phase 1.
2. Keyword/exact search (`app/keyword_search.py::BM25Index`) -- the second
   arm added for Phase 2 Feature 12 (Hybrid RAG).
3. Retrieval *policy* on top of both (`Retriever`): score fusion + a
   precedence boost so active/official chunks outrank superseded or draft
   chunks, reranking, metadata filtering, and a small conflict watchlist
   that flags when two *currently active, official* documents genuinely
   disagree so the agent can surface the conflict instead of silently
   picking one.

The conflict watchlist is a deliberate, documented limitation: detecting
"two documents disagree" in general is an open problem, so instead of
pretending an LLM call will catch it reliably every time, we hard-code the
one conflict this corpus actually contains (product-care vs. the Breeze
Tumbler product card on dishwasher safety) as a regression-testable rule.
Seed new entries here as new conflicting documents are discovered.

Hybrid RAG fusion (Feature 12)
-------------------------------
For every chunk in the corpus we compute two independent scores for the
query -- semantic cosine similarity and BM25 keyword overlap -- convert
each to an absolute-confidence component in [0, 1], then combine them as a
weighted sum before applying the same active/official precedence
multiplier both retrieval arms already used. This runs over the whole
(small) corpus rather than doing two separate top-k searches and merging
afterwards, which avoids "found by only one method" score-missing edge
cases entirely -- every chunk always has both a semantic and a keyword
score to fuse, even if one of them is 0.

Deliberately *not* min-max normalized per query: min-max would rescale
whatever the single best-matching chunk is up to 1.0 for every query,
including ones with only weak, accidental term overlap -- which would
silently defeat the low-confidence fallback below (a "confidence
threshold" only means something if the scale it's measured on is
absolute, not relative to that query's other candidates). Instead:
- the semantic component is the raw cosine similarity, clipped at 0 (the
  same scale the original Phase 1 `MIN_SIMILARITY` threshold was already
  calibrated against);
- the keyword component is a saturating transform of the raw BM25 score,
  `bm25 / (bm25 + KEYWORD_SATURATION_K)`, which maps "no term overlap" to
  exactly 0 and asymptotically approaches 1 only for a genuinely strong,
  multi-term match, rather than rewarding a single incidental token hit
  with a near-maximal score just because nothing else in the corpus
  scored higher.

Sorting the fused, boosted scores and cutting to `top_k` after the
threshold filter is the "reranking" step; there is deliberately no
separate ML reranker model in this repo (see README's "no framework
abstractions at this scale" design choice) -- fusion + the precedence
boost *is* the reranking policy.

If the top fused score for a query falls below `min_similarity`, `hits` is
empty and `RetrievalResult.authoritative_sources` is empty too -- the
existing system prompt in `app/agent.py` already tells the model "No
reference material was retrieved... say the supplied information is
insufficient" in that case, so the "don't invent an answer when retrieval
is weak" safeguard required by Feature 12 falls entirely out of the
*existing*, unmodified agent logic -- Hybrid RAG only changes which/how
many chunks clear that bar, never what happens when none do.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app import config
from app.embeddings import Embedder
from app.keyword_search import BM25Index
from app.kb_loader import AGENT_POLICY_FILES, Chunk, load_knowledge_base

ACTIVE_OFFICIAL_BOOST = 1.15
INACTIVE_PENALTY = 0.85

# Each entry: if chunks from >=2 distinct `source_file`s in this set are
# retrieved together for a query, an active-source conflict is raised.
CONFLICT_WATCHLIST: list[set[str]] = [
    {"11-product-care.md", "12-breeze-tumbler-product-card.md"},
]


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    # Raw (pre-fusion, pre-boost) component scores, kept for the AI Trace
    # Viewer (Feature 17) and for debugging retrieval quality -- never
    # shown to the customer, only to support/admin staff.
    semantic_score: float = 0.0
    keyword_score: float = 0.0


@dataclass
class RetrievalResult:
    hits: list[RetrievedChunk]
    conflict_detected: bool
    conflict_files: list[str]

    @property
    def authoritative_sources(self) -> list[Chunk]:
        """Chunks that are allowed to be cited as the basis of an answer:
        active, official, customer-facing. Order preserved, deduped by
        source_file (one citation entry per document)."""
        seen: set[str] = set()
        out: list[Chunk] = []
        for h in self.hits:
            c = h.chunk
            if c.is_active_official and c.is_customer_facing and c.source_file not in seen:
                seen.add(c.source_file)
                out.append(c)
        return out


def _min_max_normalize(values: np.ndarray) -> np.ndarray:
    """Kept for callers that explicitly want relative, per-query ranking
    normalization (e.g. a future UI that wants a 0-100% "match bar" for
    the top hits) -- NOT used by `Retriever.retrieve()`'s fusion, which
    needs absolute-confidence components instead (see module docstring)."""
    lo, hi = (float(values.min()), float(values.max())) if values.size else (0.0, 0.0)
    if hi - lo < 1e-9:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)


def _semantic_component(sim: np.ndarray) -> np.ndarray:
    """Absolute-scale semantic confidence: raw cosine similarity, clipped
    at 0. Deliberately not normalized against other candidates -- see
    module docstring."""
    return np.clip(sim, 0.0, None)


def _keyword_component(bm25: np.ndarray, k: float) -> np.ndarray:
    """Absolute-scale keyword confidence: a saturating transform so a
    single incidental token match can never masquerade as a strong
    signal just because it happened to be the best of a weak field (see
    module docstring)."""
    return np.where(bm25 > 0, bm25 / (bm25 + k), 0.0)


def _matches_filters(chunk: Chunk, filters: dict[str, Any]) -> bool:
    """Metadata filtering (Feature 12): every (key, value) pair in
    `filters` must match either a front-matter field on the chunk
    (`chunk.metadata[key]`) or one of the chunk's derived fields
    (`category`, `source_file`, `document_id`, `is_active_official`).
    Supports document type/category, product, policy, publication status,
    version, language -- anything present in the front matter -- without
    hard-coding a fixed filter schema, since the front matter schema itself
    is intentionally open-ended (see `app/kb_loader.py`)."""
    derived = {
        "category": chunk.category,
        "source_file": chunk.source_file,
        "document_id": chunk.document_id,
        "is_active_official": chunk.is_active_official,
    }
    for key, expected in filters.items():
        if expected is None:
            continue
        actual = derived.get(key, chunk.metadata.get(key))
        if isinstance(expected, (list, set, tuple)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


class VectorIndex:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray):
        self.chunks = chunks
        self.vectors = vectors  # shape (n, dim), L2-normalized rows

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder) -> "VectorIndex":
        raw = embedder.embed_documents([c.text for c in chunks])
        vecs = np.array(raw, dtype=np.float64)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        return cls(chunks, vecs)

    def save(self, path: Path, metadata: dict[str, Any] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metadata": metadata or {},
            "chunks": [c.to_dict() for c in self.chunks],
            "vectors": self.vectors.tolist(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "VectorIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        chunks = [Chunk(**d) for d in payload["chunks"]]
        vecs = np.array(payload["vectors"], dtype=np.float64)
        return cls(chunks, vecs)

    def similarities(self, query_vec: list[float]) -> np.ndarray:
        """Raw cosine similarity of `query_vec` against every chunk, in
        `self.chunks` order -- the semantic arm's per-chunk scores that
        `Retriever` fuses with the keyword arm's scores."""
        q = np.array(query_vec, dtype=np.float64)
        qn = np.linalg.norm(q)
        if qn > 0:
            q = q / qn
        if self.vectors.size == 0:
            return np.zeros(0)
        return self.vectors @ q

    def search_raw(self, query_vec: list[float], top_k: int) -> list[RetrievedChunk]:
        """Semantic-only search (no keyword fusion), kept as a standalone
        entry point: `Retriever.retrieve()` no longer calls this (it fuses
        both arms instead, see module docstring), but it remains available
        -- and tested -- for anything that only wants the original vector
        search, preserving the "existing vector search still works"
        requirement for Feature 12 verbatim rather than just by side
        effect of the fused path."""
        sims = self.similarities(query_vec)
        scored = []
        for chunk, sim in zip(self.chunks, sims, strict=True):
            boosted = sim * (ACTIVE_OFFICIAL_BOOST if chunk.is_active_official else INACTIVE_PENALTY)
            scored.append(RetrievedChunk(chunk=chunk, score=float(boosted), semantic_score=float(sim)))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    # -- Phase 2, Feature 14 (automatic re-indexing) additions -----------
    # Additive only: nothing above this point is touched. These let the
    # Knowledge Base admin indexing pipeline (app/services/indexing_service.py)
    # add/replace/remove admin-authored document chunks in the *live,
    # already-constructed* index at runtime, the same way `Agent.set_order_tool`
    # swaps in a different order-lookup implementation post-construction
    # without `handle_turn()` needing to know about it.
    def remove_by_source_file(self, source_file: str) -> None:
        keep_idx = [i for i, c in enumerate(self.chunks) if c.source_file != source_file]
        self.chunks = [self.chunks[i] for i in keep_idx]
        self.vectors = self.vectors[keep_idx] if self.vectors.size else self.vectors

    def append(self, chunks: list[Chunk], raw_vectors: list[list[float]]) -> None:
        """Appends already-embedded chunks. `raw_vectors` are un-normalized
        embeddings straight from an `Embedder` -- normalized here the same
        way `VectorIndex.build` normalizes the initial corpus, so cosine
        similarity stays comparable between original and appended chunks."""
        if not chunks:
            return
        new_vecs = np.array(raw_vectors, dtype=np.float64)
        norms = np.linalg.norm(new_vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        new_vecs = new_vecs / norms
        self.chunks = self.chunks + chunks
        self.vectors = np.vstack([self.vectors, new_vecs]) if self.vectors.size else new_vecs


class Retriever:
    def __init__(
        self,
        index: VectorIndex,
        embedder: Embedder,
        keyword_index: BM25Index | None = None,
        top_k: int = config.TOP_K,
        min_similarity: float = config.HYBRID_MIN_SCORE,
        semantic_weight: float = config.SEMANTIC_WEIGHT,
        keyword_weight: float = config.KEYWORD_WEIGHT,
        keyword_saturation_k: float = config.KEYWORD_SATURATION_K,
    ):
        self._index = index
        self._embedder = embedder
        self._keyword_index = keyword_index or BM25Index(index.chunks)
        self._top_k = top_k
        self._min_similarity = min_similarity
        self._semantic_weight = semantic_weight
        self._keyword_weight = keyword_weight
        self._keyword_saturation_k = keyword_saturation_k

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """Hybrid retrieval: fuse semantic + keyword scores over the whole
        corpus, apply the active/official precedence boost, optionally
        restrict to chunks matching `filters` (Feature 12 metadata
        filtering), then take the top `top_k` above `min_similarity`."""
        query_vec = self._embedder.embed_query(query)
        sem_scores = self._index.similarities(query_vec)
        kw_scores = np.array(self._keyword_index.score_all(query), dtype=np.float64)

        n = len(self._index.chunks)
        if n == 0:
            return RetrievalResult(hits=[], conflict_detected=False, conflict_files=[])

        sem_norm = _semantic_component(sem_scores)
        kw_norm = _keyword_component(kw_scores, self._keyword_saturation_k)

        candidates: list[RetrievedChunk] = []
        for i, chunk in enumerate(self._index.chunks):
            if filters and not _matches_filters(chunk, filters):
                continue
            fused = self._semantic_weight * sem_norm[i] + self._keyword_weight * kw_norm[i]
            boosted = fused * (ACTIVE_OFFICIAL_BOOST if chunk.is_active_official else INACTIVE_PENALTY)
            candidates.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=float(boosted),
                    semantic_score=float(sem_scores[i]),
                    keyword_score=float(kw_scores[i]),
                )
            )

        candidates.sort(key=lambda r: r.score, reverse=True)
        hits = [c for c in candidates if c.score >= self._min_similarity][: (top_k or self._top_k)]

        retrieved_files = {h.chunk.source_file for h in hits}
        conflict_files: list[str] = []
        for group in CONFLICT_WATCHLIST:
            if len(group & retrieved_files) >= 2:
                conflict_files = sorted(group & retrieved_files)
                break

        return RetrievalResult(hits=hits, conflict_detected=bool(conflict_files), conflict_files=conflict_files)

    # -- Phase 2, Feature 14 additions (additive; see VectorIndex above) --
    @property
    def embedder(self) -> Embedder:
        """Read access to the retriever's embedder so the indexing pipeline
        embeds new/edited Knowledge Base documents with the *same* model/
        config the live index was built with, without constructing a
        second embedder instance."""
        return self._embedder

    def sync_keyword_index(self) -> None:
        """Rebuilds the BM25 arm from the vector index's current chunk
        list. Cheap at this corpus size (see app/keyword_search.py
        docstring) and necessary after any `VectorIndex` mutation, since
        `BM25Index` precomputes term/document-frequency stats at
        construction time rather than supporting incremental updates."""
        self._keyword_index = BM25Index(self._index.chunks)

    def replace_document_chunks(self, source_file: str, chunks: list[Chunk], raw_vectors: list[list[float]]) -> None:
        """Feature 14's re-indexing hook: atomically remove any existing
        chunks for `source_file` (e.g. a previous version of an
        admin-authored Knowledge Base document) and, if `chunks` is
        non-empty, add the freshly embedded replacement set -- then
        rebuild the keyword arm so both retrieval arms stay in sync.
        Passing an empty `chunks` list (e.g. for an unpublished/archived
        document) removes the document from live retrieval entirely."""
        self._index.remove_by_source_file(source_file)
        if chunks:
            self._index.append(chunks, raw_vectors)
        self.sync_keyword_index()


def _kb_fingerprint(kb_dir: Path) -> str:
    """Stable fingerprint of customer-facing KB source files.

    The cache must be rebuilt when a policy file is added, removed, or edited;
    otherwise a running deployment can silently serve stale policy content.
    """
    digest = hashlib.sha256()
    for path in sorted(kb_dir.glob("*.md")):
        if path.name in AGENT_POLICY_FILES:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _cache_compatible(path: Path, embedder: Embedder, kb_dir: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        vectors = payload.get("vectors", [])
        chunks = payload.get("chunks", [])
        expected_dim = getattr(embedder, "_dim", None)
        if expected_dim is not None:
            if not vectors or len(vectors[0]) != expected_dim:
                return False
        indexed_files = {c.get("source_file") for c in chunks}
        current_files = {p.name for p in kb_dir.glob("*.md") if p.name not in AGENT_POLICY_FILES}
        if indexed_files != current_files:
            return False
        expected_fingerprint = _kb_fingerprint(kb_dir)
        if metadata.get("kb_fingerprint") != expected_fingerprint:
            return False
        expected_model = getattr(embedder, "_model", None)
        if expected_model is not None and metadata.get("embedding_model") != expected_model:
            return False
        if expected_dim is not None and metadata.get("embedding_dim") != expected_dim:
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def build_index(embedder: Embedder, kb_dir: Path = config.KB_DIR,
                 cache_path: Path = config.INDEX_CACHE_PATH, force: bool = False) -> VectorIndex:
    if cache_path.exists() and not force and _cache_compatible(cache_path, embedder, kb_dir):
        return VectorIndex.load(cache_path)
    chunks = load_knowledge_base(kb_dir)
    index = VectorIndex.build(chunks, embedder)
    index.save(
        cache_path,
        metadata={
            "embedding_model": getattr(embedder, "_model", type(embedder).__name__),
            "embedding_dim": int(index.vectors.shape[1]) if index.vectors.ndim == 2 and index.vectors.size else 0,
            "kb_fingerprint": _kb_fingerprint(kb_dir),
        },
    )
    return index

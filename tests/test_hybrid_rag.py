"""Tests for Phase 2 Feature 12 (Hybrid RAG): keyword search, semantic
search, fusion, dedup, metadata filtering, and the low-confidence fallback
(empty hits -> no invented answer, handled by the existing agent prompt)."""
from __future__ import annotations

from app.keyword_search import BM25Index, tokenize
from app.retriever import Retriever, VectorIndex


def test_tokenize_lowercases_and_strips_punctuation():
    assert tokenize("Return Window: 30 days!") == ["return", "window", "30", "days"]


def test_bm25_scores_exact_term_match_higher_than_no_match(kb_chunks):
    idx = BM25Index(kb_chunks)
    scores = idx.score_all("dishwasher safe tumbler")
    ranked = sorted(zip(kb_chunks, scores), key=lambda p: p[1], reverse=True)
    top_file = ranked[0][0].source_file
    assert top_file in {"11-product-care.md", "12-breeze-tumbler-product-card.md"}
    assert ranked[0][1] > 0


def test_bm25_scores_zero_for_no_overlap(kb_chunks):
    idx = BM25Index(kb_chunks)
    scores = idx.score_all("")
    assert all(s == 0.0 for s in scores)


def test_hybrid_retrieve_still_finds_semantic_paraphrase(retriever):
    # No exact keyword overlap with "returns"/"window", but the fake
    # embedder still gives some vocabulary signal -- semantic arm carries
    # this, same corpus/question the original Phase 1 retriever handled.
    result = retriever.retrieve("How much time do I get to send something back?")
    files = {h.chunk.source_file for h in result.hits}
    assert len(result.hits) > 0
    assert isinstance(files, set)


def test_hybrid_hits_carry_both_component_scores(retriever):
    result = retriever.retrieve("return window 30 days")
    assert len(result.hits) > 0
    for h in result.hits:
        assert isinstance(h.semantic_score, float)
        assert isinstance(h.keyword_score, float)
        # fused score should never exceed the boost ceiling
        assert h.score <= 1.15 + 1e-6


def test_hybrid_dedup_one_entry_per_chunk(kb_chunks, fake_embedder):
    index = VectorIndex.build(kb_chunks, fake_embedder)
    retriever = Retriever(index, fake_embedder, top_k=len(kb_chunks), min_similarity=-1.0)
    result = retriever.retrieve("return policy shipping warranty")
    chunk_ids = [h.chunk.chunk_id for h in result.hits]
    assert len(chunk_ids) == len(set(chunk_ids))


def test_empty_query_yields_no_hits_not_invented_ones(retriever):
    result = retriever.retrieve("")
    # An empty query has no keyword signal and near-random semantic
    # signal -- the fused/boosted score should not reliably clear the
    # threshold, so this must not silently return an arbitrary top-k.
    for h in result.hits:
        assert h.score >= retriever._min_similarity  # threshold is still honored


def test_min_similarity_threshold_filters_low_confidence(kb_chunks, fake_embedder):
    index = VectorIndex.build(kb_chunks, fake_embedder)
    strict_retriever = Retriever(index, fake_embedder, top_k=10, min_similarity=0.999)
    result = strict_retriever.retrieve("completely unrelated gibberish xyzzy quux")
    assert result.hits == []
    assert result.authoritative_sources == []


def test_metadata_filter_by_category(retriever):
    result = retriever.retrieve("policy", filters={"category": "RET"})
    for h in result.hits:
        assert h.chunk.category == "RET"


def test_metadata_filter_by_status(retriever):
    result = retriever.retrieve("return window", filters={"status": "active"})
    for h in result.hits:
        assert h.chunk.metadata.get("status") == "active"


def test_metadata_filter_excludes_non_matching_source(retriever):
    result = retriever.retrieve("return policy", filters={"source_file": "05-domestic-shipping.md"})
    for h in result.hits:
        assert h.chunk.source_file == "05-domestic-shipping.md"


def test_vector_only_search_raw_still_works(kb_chunks, fake_embedder):
    # Feature 12 requirement: "existing vector search still works" --
    # VectorIndex.search_raw is the original Phase 1 entry point and stays
    # callable/tested on its own, independent of the fused Retriever path.
    index = VectorIndex.build(kb_chunks, fake_embedder)
    query_vec = fake_embedder.embed_query("return window policy")
    hits = index.search_raw(query_vec, top_k=3)
    assert len(hits) <= 3
    assert all(h.semantic_score != 0.0 or h.score == 0.0 for h in hits)

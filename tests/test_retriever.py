from __future__ import annotations

from app.retriever import CONFLICT_WATCHLIST


def test_breeze_tumbler_conflict_is_detected(retriever):
    result = retriever.retrieve("Can I put the entire Breeze Tumbler in the dishwasher?")
    assert result.conflict_detected is True
    assert set(result.conflict_files) == {"11-product-care.md", "12-breeze-tumbler-product-card.md"}


def test_no_conflict_for_unrelated_query(retriever):
    result = retriever.retrieve("Do you ship internationally?")
    assert result.conflict_detected is False


def test_authoritative_sources_excludes_superseded_and_draft(retriever):
    result = retriever.retrieve("standard return window policy 30 days 45 days 60 days")
    files = {c.source_file for c in result.authoritative_sources}
    assert "02-returns-policy-legacy.md" not in files
    assert "14-internal-content-migration-notes.md" not in files


def test_authoritative_sources_deduped_per_document(retriever):
    result = retriever.retrieve("return policy return window item condition return shipping")
    files = [c.source_file for c in result.authoritative_sources]
    assert len(files) == len(set(files))


def test_conflict_watchlist_is_symmetric_pairs_of_two_or_more():
    for group in CONFLICT_WATCHLIST:
        assert len(group) >= 2


def test_build_index_rebuilds_when_cache_dimension_or_kb_changes(tmp_path):
    from app.retriever import build_index
    from app.embeddings import FakeEmbedder

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "01-policy.md").write_text(
        "---\ndocument_id: T-1\ntitle: Test Policy\nstatus: active\npolicy_authority: official\n---\n# Test Policy\n\n## Rule\n\nOriginal rule.",
        encoding="utf-8",
    )
    cache = tmp_path / "index.json"
    first = build_index(FakeEmbedder(dim=8), kb_dir=kb, cache_path=cache)
    assert first.vectors.shape[1] == 8

    # Different embedding dimension must invalidate the old cache.
    second = build_index(FakeEmbedder(dim=12), kb_dir=kb, cache_path=cache)
    assert second.vectors.shape[1] == 12

    # Editing the source policy must invalidate the cache even when the
    # filename and embedding dimension stay the same.
    (kb / "01-policy.md").write_text(
        "---\ndocument_id: T-1\ntitle: Test Policy\nstatus: active\npolicy_authority: official\n---\n# Test Policy\n\n## Rule\n\nUpdated rule.",
        encoding="utf-8",
    )
    third = build_index(FakeEmbedder(dim=12), kb_dir=kb, cache_path=cache)
    assert "Updated rule." in third.chunks[0].text

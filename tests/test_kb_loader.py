from __future__ import annotations

import json

from app.kb_loader import AGENT_POLICY_FILES, load_agent_policy_text
from tests.conftest import KB_DIR


def test_agent_policy_files_excluded_from_retrieval_index(kb_chunks):
    files = {c.source_file for c in kb_chunks}
    assert files.isdisjoint(AGENT_POLICY_FILES)


def test_agent_policy_text_is_loaded_separately():
    text = load_agent_policy_text(KB_DIR)
    assert "human handoff" in text.lower() or "human assistance" in text.lower()


def test_front_matter_dates_are_json_serializable(kb_chunks):
    for c in kb_chunks:
        # Would raise TypeError before the date->isoformat fix (bug diary #2).
        json.dumps(c.metadata)


def test_active_official_flag(kb_chunks):
    by_file = {c.source_file: c for c in kb_chunks}
    assert by_file["01-returns-policy-current.md"].is_active_official is True
    assert by_file["02-returns-policy-legacy.md"].is_active_official is False
    assert by_file["14-internal-content-migration-notes.md"].is_active_official is False


def test_draft_doc_is_never_customer_facing_authority(kb_chunks):
    draft_chunks = [c for c in kb_chunks if c.source_file == "14-internal-content-migration-notes.md"]
    assert draft_chunks
    for c in draft_chunks:
        assert c.is_active_official is False


def test_chunks_preserve_document_metadata(kb_chunks):
    sample = next(c for c in kb_chunks if c.source_file == "09-trailplus-membership.md")
    assert sample.metadata.get("document_id") == "MEM-2026-01"
    assert sample.metadata.get("policy_authority") == "official"

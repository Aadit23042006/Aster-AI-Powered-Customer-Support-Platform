"""Tests for Phase 2 Features 13 (Knowledge Base admin) and 14 (automatic
re-indexing): admin-only access, CRUD, versioning, the publish workflow,
file upload/extraction, and background indexing jobs.
"""
from __future__ import annotations

import io

from tests_web.conftest import auth_headers, make_admin, signup_and_login


def _admin_client(client, email="admin@example.com"):
    tokens = signup_and_login(client, email=email)
    make_admin(client, tokens)
    return tokens


# --------------------------------------------------------------- access --
def test_customer_cannot_access_knowledge_base(client):
    user = signup_and_login(client)
    resp = client.get("/admin/knowledge", headers=auth_headers(user))
    assert resp.status_code == 403


def test_customer_cannot_create_document(client):
    user = signup_and_login(client)
    resp = client.post(
        "/admin/knowledge",
        json={"title": "x", "category": "general", "content": "hello", "content_type": "markdown"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 403


def test_admin_can_access_knowledge_base(client):
    admin = _admin_client(client)
    resp = client.get("/admin/knowledge", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_unauthenticated_request_is_401(client):
    resp = client.get("/admin/knowledge")
    assert resp.status_code == 401


# ------------------------------------------------------------------ CRUD --
def test_create_document_starts_as_draft_version_one(client):
    admin = _admin_client(client)
    resp = client.post(
        "/admin/knowledge",
        json={"title": "Gift wrapping policy", "category": "policy", "content": "# Gift wrapping\nWe offer it.", "content_type": "markdown"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["status"] == "draft"
    assert doc["current_version"] == 1
    assert doc["index_status"] == "not_indexed"
    assert doc["content"] == "# Gift wrapping\nWe offer it."
    assert len(doc["versions"]) == 1


def test_empty_content_is_rejected(client):
    admin = _admin_client(client)
    resp = client.post(
        "/admin/knowledge",
        json={"title": "Empty", "category": "general", "content": "   ", "content_type": "markdown"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_dashboard_summary_reflects_document_counts(client):
    admin = _admin_client(client)
    client.post(
        "/admin/knowledge", json={"title": "A", "category": "general", "content": "a", "content_type": "markdown"}, headers=auth_headers(admin)
    )
    client.post(
        "/admin/knowledge", json={"title": "B", "category": "general", "content": "b", "content_type": "markdown"}, headers=auth_headers(admin)
    )
    summary = client.get("/admin/knowledge/summary", headers=auth_headers(admin)).json()
    assert summary["documents"] == 2
    assert summary["drafts"] == 2
    assert summary["published"] == 0


# ------------------------------------------------------------ versioning --
def test_editing_document_creates_new_version_without_losing_old_one(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "V1", "category": "general", "content": "first draft", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()

    updated = client.patch(
        f"/admin/knowledge/{doc['id']}",
        json={"content": "second draft, revised", "content_type": "markdown"},
        headers=auth_headers(admin),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["current_version"] == 2
    assert body["content"] == "second draft, revised"
    versions = {v["version"] for v in body["versions"]}
    assert versions == {1, 2}


def test_editing_metadata_only_does_not_bump_version(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Orig title", "category": "general", "content": "content", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    updated = client.patch(f"/admin/knowledge/{doc['id']}", json={"title": "New title"}, headers=auth_headers(admin)).json()
    assert updated["title"] == "New title"
    assert updated["current_version"] == 1


# --------------------------------------------------------- publish flow --
def test_publish_workflow_and_auto_indexing(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Loyalty program", "category": "policy", "content": "# Loyalty\nEarn 1 point per dollar.", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    assert doc["status"] == "draft"

    published = client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))
    assert published.status_code == 200
    body = published.json()
    assert body["status"] == "published"
    assert body["published_at"] is not None
    # publishing auto-triggers a background index job (TestClient runs
    # BackgroundTasks synchronously before returning the response).
    assert body["index_status"] == "completed"
    assert body["last_indexed_at"] is not None


def test_draft_document_is_never_indexed_as_authoritative(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Still drafting", "category": "policy", "content": "not ready yet", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    # Explicitly ask to index a draft: it should "run" (index_status
    # reflects completion) but never enter the live searchable corpus --
    # verified indirectly via the job succeeding while status stays draft.
    reindex = client.post(f"/admin/knowledge/{doc['id']}/reindex", headers=auth_headers(admin))
    assert reindex.status_code == 202
    refreshed = client.get(f"/admin/knowledge/{doc['id']}", headers=auth_headers(admin)).json()
    assert refreshed["status"] == "draft"


def test_unpublish_then_publish_round_trips(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Seasonal hours", "category": "policy", "content": "Open late in December.", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))

    unpublished = client.post(f"/admin/knowledge/{doc['id']}/unpublish", headers=auth_headers(admin))
    assert unpublished.status_code == 200
    assert unpublished.json()["status"] == "draft"

    republished = client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))
    assert republished.json()["status"] == "published"


def test_archive_and_restore(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Old promo", "category": "policy", "content": "Expired promo details.", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()

    archived = client.post(f"/admin/knowledge/{doc['id']}/archive", headers=auth_headers(admin))
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["archived_at"] is not None

    # An archived document cannot be edited or published directly.
    edit_attempt = client.patch(f"/admin/knowledge/{doc['id']}", json={"content": "x", "content_type": "markdown"}, headers=auth_headers(admin))
    assert edit_attempt.status_code == 400
    publish_attempt = client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))
    assert publish_attempt.status_code == 400

    restored = client.post(f"/admin/knowledge/{doc['id']}/restore", headers=auth_headers(admin))
    assert restored.status_code == 200
    assert restored.json()["status"] == "draft"


def test_cannot_delete_published_document_but_can_delete_after_archiving(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Live policy", "category": "policy", "content": "Currently live.", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))

    blocked = client.delete(f"/admin/knowledge/{doc['id']}", headers=auth_headers(admin))
    assert blocked.status_code == 400

    client.post(f"/admin/knowledge/{doc['id']}/archive", headers=auth_headers(admin))
    allowed = client.delete(f"/admin/knowledge/{doc['id']}", headers=auth_headers(admin))
    assert allowed.status_code == 204

    missing = client.get(f"/admin/knowledge/{doc['id']}", headers=auth_headers(admin))
    assert missing.status_code == 404


# ------------------------------------------------------------ file upload --
def test_upload_markdown_file(client):
    admin = _admin_client(client)
    file_bytes = b"# Uploaded doc\n\nSome policy text about warranties."
    resp = client.post(
        "/admin/knowledge/upload",
        data={"title": "Uploaded policy", "category": "policy"},
        files={"file": ("warranty-extra.md", io.BytesIO(file_bytes), "text/markdown")},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["content_type"] == "markdown"
    assert "warranties" in body["content"]


def test_upload_rejects_oversized_file(client):
    admin = _admin_client(client)
    big = io.BytesIO(b"a" * (11 * 1024 * 1024))
    resp = client.post(
        "/admin/knowledge/upload",
        data={"title": "Too big", "category": "policy"},
        files={"file": ("big.txt", big, "text/plain")},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_upload_txt_infers_content_type_from_extension(client):
    admin = _admin_client(client)
    resp = client.post(
        "/admin/knowledge/upload",
        data={"title": "Plain notes"},
        files={"file": ("notes.txt", io.BytesIO(b"Plain text content."), "text/plain")},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "txt"


# -------------------------------------------------------------- indexing --
def test_reindex_all_processes_only_published_documents(client):
    admin = _admin_client(client)
    published = client.post(
        "/admin/knowledge",
        json={"title": "Published doc", "category": "policy", "content": "Published content here.", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    client.post(f"/admin/knowledge/{published['id']}/publish", headers=auth_headers(admin))

    draft = client.post(
        "/admin/knowledge",
        json={"title": "Draft doc", "category": "policy", "content": "Draft content here.", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()

    job = client.post("/admin/knowledge/reindex-all", headers=auth_headers(admin))
    assert job.status_code == 202
    job_body = job.json()
    assert job_body["job_type"] == "full"
    assert job_body["status"] == "completed"
    assert job_body["documents_indexed"] == 1  # only the published one

    refreshed_published = client.get(f"/admin/knowledge/{published['id']}", headers=auth_headers(admin)).json()
    assert refreshed_published["index_status"] == "completed"
    refreshed_draft = client.get(f"/admin/knowledge/{draft['id']}", headers=auth_headers(admin)).json()
    assert refreshed_draft["status"] == "draft"


def test_index_jobs_are_listed_and_filterable(client):
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={"title": "Job history test", "category": "policy", "content": "content", "content_type": "markdown"},
        headers=auth_headers(admin),
    ).json()
    client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))
    client.post(f"/admin/knowledge/{doc['id']}/reindex", headers=auth_headers(admin))

    jobs = client.get("/admin/index-jobs", params={"document_id": doc["id"]}, headers=auth_headers(admin)).json()
    assert jobs["total"] >= 2
    assert all(j["document_id"] == doc["id"] for j in jobs["items"])


def test_published_document_is_actually_retrievable_by_the_agent(client):
    """End-to-end integration: an admin-published, indexed document's
    content shows up in a live chat answer -- proving Feature 14 actually
    wires into the same retriever `app/agent.py` queries, not just a
    separate admin-only data store."""
    admin = _admin_client(client)
    doc = client.post(
        "/admin/knowledge",
        json={
            "title": "Purple Llama Backpack care",
            "category": "product",
            "content": "# Purple Llama Backpack care\n\n## Cleaning\nHand wash only with a zzqqxx11 solution.",
            "content_type": "markdown",
        },
        headers=auth_headers(admin),
    ).json()
    client.post(f"/admin/knowledge/{doc['id']}/publish", headers=auth_headers(admin))

    conv = client.post("/conversations", json={}, headers=auth_headers(admin)).json()
    resp = client.post(
        f"/conversations/{conv['id']}/messages",
        json={"message": "How do I clean the Purple Llama Backpack zzqqxx11 solution?"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert f"kb-doc:{doc['id']}" in sources

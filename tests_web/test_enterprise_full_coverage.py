"""HTTP-level coverage for the six enterprise features that previously had
no route-level tests: Action Center / Tool Calling (1), Support Workspace
(2), RAG Citations v1 (5), AI Support Intelligence (6), Source Explorer v2
(7), and Knowledge Base Versioning (8).

`tests_web/test_enterprise_ai.py` and `tests_web/test_enterprise_7_15.py`
already cover the other nine features (3, 4, 9-15). This file fills the
gap so all 15 enterprise features have at least one route-level test.
"""
from __future__ import annotations

import uuid

from tests_web.conftest import auth_headers, make_admin, signup_and_login


def make_support_agent(client, tokens: dict) -> None:
    """Grant the `support_agent` role, mirroring conftest's make_admin."""
    from app.db.base import SessionLocal
    from app.db.models import Role, UserRole

    user_id = client.get("/auth/me", headers=auth_headers(tokens)).json()["id"]
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.name == "support_agent").first()
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.commit()
    finally:
        db.close()


def _create_conversation_with_reply(client, tokens, question="How long do I have to return a backpack?"):
    """Create a conversation and send one message so it has both a user
    turn and an assistant turn (needed for classification/quality/citation
    features, which all key off the latest messages)."""
    conv_id = client.post("/conversations", json={}, headers=auth_headers(tokens)).json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={"message": question},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200, resp.text
    return conv_id


# ---------------------------------------------------------------------------
# Feature 1: AI Tool Calling + Action Center
# ---------------------------------------------------------------------------
def test_action_center_lists_tools_and_requires_staff(client):
    customer = signup_and_login(client, email="customer1@example.com")
    denied = client.get("/action-center/tools", headers=auth_headers(customer))
    assert denied.status_code == 403

    agent = signup_and_login(client, email="agent1@example.com")
    make_support_agent(client, agent)
    ok = client.get("/action-center/tools", headers=auth_headers(agent))
    assert ok.status_code == 200
    names = {t["name"] for t in ok.json()["tools"]}
    assert "lookup_order" in names and "create_support_ticket" in names


def test_action_center_execute_creates_ticket_and_is_logged(client):
    agent = signup_and_login(client, email="agent2@example.com")
    make_support_agent(client, agent)

    executed = client.post(
        "/action-center/execute",
        json={"tool_name": "create_support_ticket",
              "arguments": {"subject": "Damaged item", "description": "Box arrived crushed", "category": "other"}},
        headers=auth_headers(agent),
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "success"
    assert executed.json()["result"]["ticket_number"]

    actions = client.get("/action-center/actions", headers=auth_headers(agent))
    assert actions.status_code == 200
    assert any(a["tool_name"] == "create_support_ticket" for a in actions.json())


def test_action_center_execute_rejects_unknown_tool(client):
    agent = signup_and_login(client, email="agent3@example.com")
    make_support_agent(client, agent)
    resp = client.post(
        "/action-center/execute",
        json={"tool_name": "delete_everything", "arguments": {}},
        headers=auth_headers(agent),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Feature 2: Human + AI Support Workspace
# ---------------------------------------------------------------------------
def test_support_workspace_lists_and_shows_conversation_detail(client):
    customer = signup_and_login(client, email="customer2@example.com")
    conv_id = _create_conversation_with_reply(client, customer)

    agent = signup_and_login(client, email="agent4@example.com")
    make_support_agent(client, agent)

    listing = client.get("/support-workspace/conversations", headers=auth_headers(agent))
    assert listing.status_code == 200
    assert any(c["id"] == conv_id for c in listing.json())

    detail = client.get(f"/support-workspace/conversations/{conv_id}", headers=auth_headers(agent))
    assert detail.status_code == 200
    body = detail.json()
    assert body["conversation"]["id"] == conv_id
    assert "suggested_reply" in body
    assert isinstance(body["internal_notes"], list)


def test_support_workspace_internal_note_is_staff_only(client):
    customer = signup_and_login(client, email="customer3@example.com")
    conv_id = _create_conversation_with_reply(client, customer)

    agent = signup_and_login(client, email="agent5@example.com")
    make_support_agent(client, agent)

    note = client.post(
        f"/support-workspace/conversations/{conv_id}/notes",
        json={"content": "Customer sounded frustrated, prioritize."},
        headers=auth_headers(agent),
    )
    assert note.status_code == 200
    assert note.json()["content"] == "Customer sounded frustrated, prioritize."

    # A plain customer cannot post internal notes.
    denied = client.post(
        f"/support-workspace/conversations/{conv_id}/notes",
        json={"content": "should not work"},
        headers=auth_headers(customer),
    )
    assert denied.status_code == 403


def test_support_workspace_ticket_assign_escalate_resolve_flow(client):
    customer = signup_and_login(client, email="customer4@example.com")
    ticket_id = client.post(
        "/tickets",
        json={"subject": "Wrong item shipped", "description": "Received the wrong color", "category": "other"},
        headers=auth_headers(customer),
    ).json()["id"]

    agent = signup_and_login(client, email="agent6@example.com")
    make_support_agent(client, agent)
    agent_id = client.get("/auth/me", headers=auth_headers(agent)).json()["id"]

    assigned = client.post(
        f"/support-workspace/tickets/{ticket_id}/assign",
        json={"agent_id": agent_id},
        headers=auth_headers(agent),
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_agent_id"] == agent_id

    escalated = client.post(f"/support-workspace/tickets/{ticket_id}/escalate", headers=auth_headers(agent))
    assert escalated.status_code == 200
    assert escalated.json()["priority"] == "high"

    resolved = client.post(f"/support-workspace/tickets/{ticket_id}/resolve", headers=auth_headers(agent))
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


# ---------------------------------------------------------------------------
# Feature 5: RAG Citation / Source Explorer (v1)
# ---------------------------------------------------------------------------
def test_conversation_citations_are_grounded_and_owner_scoped(client):
    owner = signup_and_login(client, email="citeowner@example.com")
    conv_id = _create_conversation_with_reply(client, owner)

    mine = client.get(f"/conversations/{conv_id}/citations", headers=auth_headers(owner))
    assert mine.status_code == 200
    assert isinstance(mine.json(), list)

    stranger = signup_and_login(client, email="citestranger@example.com")
    denied = client.get(f"/conversations/{conv_id}/citations", headers=auth_headers(stranger))
    assert denied.status_code == 404


# ---------------------------------------------------------------------------
# Feature 6: AI Support Intelligence
# ---------------------------------------------------------------------------
def test_ai_intelligence_dashboard_requires_staff_and_returns_metrics(client):
    customer = signup_and_login(client, email="customer5@example.com")
    _create_conversation_with_reply(client, customer)

    denied = client.get("/analytics/ai-intelligence", headers=auth_headers(customer))
    assert denied.status_code == 403

    agent = signup_and_login(client, email="agent7@example.com")
    make_support_agent(client, agent)
    ok = client.get("/analytics/ai-intelligence", headers=auth_headers(agent))
    assert ok.status_code == 200
    body = ok.json()
    assert "conversations" in body and "quality_decisions" in body


# ---------------------------------------------------------------------------
# Feature 7: RAG Citation / Source Explorer (v2)
# ---------------------------------------------------------------------------
def test_source_explorer_returns_persisted_citations_for_owner_only(client):
    owner = signup_and_login(client, email="explorerowner@example.com")
    conv_id = _create_conversation_with_reply(client, owner)

    # Citations are only persisted once /citations (v1) has been called for
    # this conversation -- that's what turns retrieval hits into rows in
    # conversation_citations. This mirrors how the chat UI's "Sources" link
    # behaves in practice.
    client.get(f"/conversations/{conv_id}/citations", headers=auth_headers(owner))

    mine = client.get(f"/conversations/{conv_id}/source-explorer", headers=auth_headers(owner))
    assert mine.status_code == 200, mine.text
    for row in mine.json():
        # Regression guard for the relevant_passage/"passage" field-name bug:
        # every row must expose passage text without the endpoint 500ing.
        assert "passage" in row

    stranger = signup_and_login(client, email="explorerstranger@example.com")
    denied = client.get(f"/conversations/{conv_id}/source-explorer", headers=auth_headers(stranger))
    assert denied.status_code == 404


# ---------------------------------------------------------------------------
# Feature 8: Knowledge Base Versioning
# ---------------------------------------------------------------------------
def test_kb_versioning_list_diff_and_rollback(client):
    admin = signup_and_login(client, email="kbadmin@example.com")
    make_admin(client, admin)

    created = client.post(
        "/admin/knowledge",
        json={"title": "Return Policy Draft", "category": "returns",
              "content": "Version one content.", "content_type": "markdown"},
        headers=auth_headers(admin),
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]

    edited = client.patch(
        f"/admin/knowledge/{doc_id}",
        json={"content": "Version two content, edited."},
        headers=auth_headers(admin),
    )
    assert edited.status_code == 200, edited.text

    versions = client.get(f"/admin/knowledge/{doc_id}/versions", headers=auth_headers(admin))
    assert versions.status_code == 200
    version_numbers = sorted(v["version"] for v in versions.json()["items"])
    assert version_numbers == [1, 2]

    diff = client.get(
        f"/admin/knowledge/{doc_id}/diff",
        params={"from_version": 1, "to_version": 2},
        headers=auth_headers(admin),
    )
    assert diff.status_code == 200
    assert len(diff.json()["diff"]) > 0

    version_1_id = next(v["id"] for v in versions.json()["items"] if v["version"] == 1)
    rolled_back = client.post(
        f"/admin/knowledge/{doc_id}/rollback/{version_1_id}",
        headers=auth_headers(admin),
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["content"] == "Version one content."
    assert rolled_back.json()["metadata"]["rollback_from_version"] == 1


def test_kb_versioning_requires_admin(client):
    agent = signup_and_login(client, email="kbagent@example.com")
    make_support_agent(client, agent)
    resp = client.get(f"/admin/knowledge/{uuid.uuid4()}/versions", headers=auth_headers(agent))
    assert resp.status_code == 403

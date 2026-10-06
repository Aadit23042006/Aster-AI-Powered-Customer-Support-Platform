from tests_web.conftest import auth_headers, signup_and_login


def test_create_ticket_and_add_customer_message(client):
    user = signup_and_login(client)
    created = client.post(
        "/tickets",
        json={"subject": "Damaged item", "description": "My tumbler arrived cracked.", "category": "damaged_product", "priority": "high"},
        headers=auth_headers(user),
    )
    assert created.status_code == 201
    ticket = created.json()
    assert ticket["status"] == "open"
    assert ticket["ticket_number"].startswith("AR-")

    msg = client.post(f"/tickets/{ticket['id']}/messages", json={"content": "Any update?"}, headers=auth_headers(user))
    assert msg.status_code == 201
    assert msg.json()["author_role"] == "customer"

    detail = client.get(f"/tickets/{ticket['id']}", headers=auth_headers(user)).json()
    assert len(detail["messages"]) == 2  # the initial description + the follow-up


def test_list_tickets_returns_only_the_caller_s_own_for_customers(client):
    user = signup_and_login(client)
    client.post("/tickets", json={"subject": "a", "description": "b", "category": "other"}, headers=auth_headers(user))
    listing = client.get("/tickets", headers=auth_headers(user)).json()
    assert len(listing) == 1


def test_invalid_category_falls_back_to_other_rather_than_erroring(client):
    user = signup_and_login(client)
    resp = client.post(
        "/tickets",
        json={"subject": "x", "description": "y", "category": "not-a-real-category"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    assert resp.json()["category"] == "other"


def test_invalid_status_transition_is_rejected(client):
    from app.db.base import SessionLocal
    from app.db.models import Role, UserRole

    user = signup_and_login(client)
    ticket = client.post("/tickets", json={"subject": "x", "description": "y", "category": "other"}, headers=auth_headers(user)).json()

    agent = signup_and_login(client, email="agent_status@example.com")
    db = SessionLocal()
    try:
        agent_id = client.get("/auth/me", headers=auth_headers(agent)).json()["id"]
        role = db.query(Role).filter(Role.name == "support_agent").first()
        db.add(UserRole(user_id=agent_id, role_id=role.id))
        db.commit()
    finally:
        db.close()

    resp = client.patch(f"/tickets/{ticket['id']}", json={"status": "not_a_real_status"}, headers=auth_headers(agent))
    assert resp.status_code == 400


def test_ai_handoff_automatically_creates_a_ticket_with_conversation_context(client):
    """Integration test for requirement 10 (human handoff): when the
    EXISTING agent's deterministic handoff rules fire (here: an order ID
    that doesn't exist, which app.agent.Agent._apply_deterministic_handoff_rules
    always turns into a forced handoff), the conversation route must open a
    real ticket, tagged with created_by_ai=True and the conversation it
    came from -- not just return a flag the frontend has to act on itself."""
    user = signup_and_login(client, email="handoff_user@example.com")
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]

    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={"message": "What's the status of order ORD-9999999?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["handoff"] is True
    assert body["ticket_number"] is not None

    tickets = client.get("/tickets", headers=auth_headers(user)).json()
    matching = [t for t in tickets if t["ticket_number"] == body["ticket_number"]]
    assert len(matching) == 1
    assert matching[0]["created_by_ai"] is True
    assert matching[0]["handoff_reason"]

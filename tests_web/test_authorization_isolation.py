"""The most important test file in this suite: proves user A can never
reach user B's private data, and that customers can't reach admin-only
endpoints. Every check hits the real API + real DB -- nothing mocked."""
from tests_web.conftest import auth_headers, signup_and_login


def test_user_a_cannot_list_user_bs_conversations(client):
    alice = signup_and_login(client, email="alice@example.com")
    bob = signup_and_login(client, email="bob@example.com")

    resp = client.post("/conversations", json={"title": "Bob's private chat"}, headers=auth_headers(bob))
    assert resp.status_code == 201
    bob_conv_id = resp.json()["id"]

    # Alice's own list must not contain Bob's conversation.
    alice_list = client.get("/conversations", headers=auth_headers(alice)).json()
    assert all(c["id"] != bob_conv_id for c in alice_list)

    # Alice cannot fetch Bob's conversation directly by ID either.
    resp = client.get(f"/conversations/{bob_conv_id}", headers=auth_headers(alice))
    assert resp.status_code == 404


def test_user_a_cannot_read_user_bs_messages(client):
    alice = signup_and_login(client, email="alice2@example.com")
    bob = signup_and_login(client, email="bob2@example.com")

    bob_conv_id = client.post("/conversations", json={}, headers=auth_headers(bob)).json()["id"]

    resp = client.get(f"/conversations/{bob_conv_id}/messages", headers=auth_headers(alice))
    assert resp.status_code == 404


def test_user_a_cannot_rename_or_delete_user_bs_conversation(client):
    alice = signup_and_login(client, email="alice3@example.com")
    bob = signup_and_login(client, email="bob3@example.com")
    bob_conv_id = client.post("/conversations", json={}, headers=auth_headers(bob)).json()["id"]

    assert client.patch(f"/conversations/{bob_conv_id}", json={"title": "hijacked"}, headers=auth_headers(alice)).status_code == 404
    assert client.delete(f"/conversations/{bob_conv_id}", headers=auth_headers(alice)).status_code == 404

    # Bob's conversation is untouched.
    still_there = client.get(f"/conversations/{bob_conv_id}", headers=auth_headers(bob))
    assert still_there.status_code == 200
    assert still_there.json()["title"] != "hijacked"


def test_user_a_cannot_access_user_bs_orders(client, db_session):
    from app.db.models import Order

    alice = signup_and_login(client, email="alice4@example.com")
    bob = signup_and_login(client, email="bob4@example.com")

    alice_id = client.get("/auth/me", headers=auth_headers(alice)).json()["id"]
    bob_id = client.get("/auth/me", headers=auth_headers(bob)).json()["id"]

    bob_order = Order(order_number="ORD-9001", user_id=bob_id, status="shipped")
    db_session.add(bob_order)
    db_session.commit()

    # Alice's order list is empty -- Bob's order never appears in it.
    alice_orders = client.get("/orders", headers=auth_headers(alice)).json()
    assert alice_orders == []

    # Alice cannot fetch Bob's order directly by its (unguessable) ID.
    resp = client.get(f"/orders/{bob_order.id}", headers=auth_headers(alice))
    assert resp.status_code == 404

    # Bob himself can see it fine.
    resp = client.get(f"/orders/{bob_order.id}", headers=auth_headers(bob))
    assert resp.status_code == 200
    assert resp.json()["order_number"] == "ORD-9001"


def test_user_a_cannot_access_user_bs_tickets(client):
    alice = signup_and_login(client, email="alice5@example.com")
    bob = signup_and_login(client, email="bob5@example.com")

    bob_ticket = client.post(
        "/tickets",
        json={"subject": "Bob's issue", "description": "private", "category": "other"},
        headers=auth_headers(bob),
    ).json()

    # Not in Alice's list.
    alice_tickets = client.get("/tickets", headers=auth_headers(alice)).json()
    assert all(t["id"] != bob_ticket["id"] for t in alice_tickets)

    # Not directly fetchable by Alice.
    resp = client.get(f"/tickets/{bob_ticket['id']}", headers=auth_headers(alice))
    assert resp.status_code == 404

    # Alice cannot post a message onto Bob's ticket either.
    resp = client.post(f"/tickets/{bob_ticket['id']}/messages", json={"content": "butting in"}, headers=auth_headers(alice))
    assert resp.status_code == 404


def test_customer_cannot_update_ticket_status_admin_only(client):
    alice = signup_and_login(client, email="alice6@example.com")
    ticket = client.post(
        "/tickets", json={"subject": "x", "description": "y", "category": "other"}, headers=auth_headers(alice)
    ).json()

    resp = client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"}, headers=auth_headers(alice))
    assert resp.status_code == 403


def test_support_agent_can_view_and_update_any_ticket(client):
    from app.db.base import SessionLocal
    from app.db.models import Role, User, UserRole

    alice = signup_and_login(client, email="alice7@example.com")
    ticket = client.post(
        "/tickets", json={"subject": "x", "description": "y", "category": "other"}, headers=auth_headers(alice)
    ).json()

    agent = signup_and_login(client, email="agent1@example.com")
    # Promote this user to support_agent directly via the DB (this is what
    # the seed script / an admin action would do -- there is no
    # self-service "become an agent" endpoint).
    db = SessionLocal()
    try:
        agent_id = client.get("/auth/me", headers=auth_headers(agent)).json()["id"]
        role = db.query(Role).filter(Role.name == "support_agent").first()
        db.add(UserRole(user_id=agent_id, role_id=role.id))
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/tickets/{ticket['id']}", headers=auth_headers(agent))
    assert resp.status_code == 200

    resp = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"}, headers=auth_headers(agent))
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


def test_ownership_is_derived_from_token_not_client_supplied_id(client):
    """Regression test for the exact anti-pattern the spec called out:
    a client cannot widen its own access by passing someone else's ID as a
    query/body parameter -- there IS no user_id parameter on these routes
    at all; identity always comes from the bearer token."""
    import inspect

    from app.api import conversations_routes, orders_routes, tickets_routes

    for module in (conversations_routes, orders_routes, tickets_routes):
        for name, func in vars(module).items():
            if not callable(func) or not hasattr(func, "__annotations__"):
                continue
            # Only check route handlers actually defined in this module --
            # not imported service functions like order_service.get_order_for_user,
            # which legitimately takes a server-derived user_id as an
            # internal Python argument, never as an HTTP parameter.
            if getattr(func, "__module__", None) != module.__name__:
                continue
            sig_params = getattr(func, "__wrapped__", func)
            try:
                params = inspect.signature(sig_params).parameters
            except (TypeError, ValueError):
                continue
            assert "user_id" not in params, f"{module.__name__}.{name} must not accept a client-supplied user_id"

from tests_web.conftest import auth_headers, signup_and_login


def _create_order(db_session, user_id, order_number="ORD-1001", status="shipped"):
    from app.db.models import Order, OrderItem

    order = Order(order_number=order_number, user_id=user_id, status=status, carrier="UPS", tracking_number="1Z999")
    db_session.add(order)
    db_session.flush()
    db_session.add(OrderItem(order_id=order.id, product_id="PACK-RIDGE-BLK", product_name="Ridge Daypack", quantity=1))
    db_session.commit()
    return order


def test_list_own_orders(client, db_session):
    user = signup_and_login(client)
    user_id = client.get("/auth/me", headers=auth_headers(user)).json()["id"]
    _create_order(db_session, user_id)

    resp = client.get("/orders", headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["order_number"] == "ORD-1001"
    assert body[0]["items"][0]["product_name"] == "Ridge Daypack"


def test_retrieve_own_order_by_id(client, db_session):
    user = signup_and_login(client)
    user_id = client.get("/auth/me", headers=auth_headers(user)).json()["id"]
    order = _create_order(db_session, user_id)

    resp = client.get(f"/orders/{order.id}", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["order_number"] == "ORD-1001"


def test_unauthorized_order_access_returns_404_not_403(client, db_session):
    """404 rather than 403 so the response doesn't confirm the order
    exists at all -- see app/api/orders_routes.py."""
    owner = signup_and_login(client, email="owner@example.com")
    intruder = signup_and_login(client, email="intruder@example.com")
    owner_id = client.get("/auth/me", headers=auth_headers(owner)).json()["id"]
    order = _create_order(db_session, owner_id)

    resp = client.get(f"/orders/{order.id}", headers=auth_headers(intruder))
    assert resp.status_code == 404


def test_ai_order_lookup_finds_own_order(client, db_session):
    user = signup_and_login(client, email="shopper@example.com")
    user_id = client.get("/auth/me", headers=auth_headers(user)).json()["id"]
    _create_order(db_session, user_id, order_number="ORD-1001", status="shipped")

    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={"message": "What's the status of order ORD-1001?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    answer = resp.json()["assistant_message"]["content"]
    assert "shipped" in answer.lower() or "ord-1001" in answer.lower()


def test_ai_order_lookup_never_leaks_another_users_order(client, db_session):
    """The core cross-tenant-leak regression test for the AI tool path:
    a customer asking about an order ID that exists but belongs to someone
    else must get a not-found style response, never that order's data."""
    victim = signup_and_login(client, email="victim@example.com")
    attacker = signup_and_login(client, email="attacker@example.com")
    victim_id = client.get("/auth/me", headers=auth_headers(victim)).json()["id"]
    _create_order(db_session, victim_id, order_number="ORD-2002", status="shipped")

    conv_id = client.post("/conversations", json={}, headers=auth_headers(attacker)).json()["id"]
    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={"message": "What's the status of order ORD-2002?"},
        headers=auth_headers(attacker),
    )
    assert resp.status_code == 200
    body = resp.json()
    answer = body["assistant_message"]["content"].lower()
    # Must not have echoed the victim's real tracking/carrier data.
    assert "1z999" not in answer
    assert "ups" not in answer
    # The mock LLM (and the real one, per the system prompt) treats a
    # not-found lookup as handoff-worthy.
    assert body["handoff"] is True

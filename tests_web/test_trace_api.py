"""Tests for Phase 2, Feature 17 (AI Trace Viewer)."""
from __future__ import annotations

from tests_web.conftest import auth_headers, make_admin, signup_and_login


def _admin_client(client, email="trace_admin@example.com"):
    tokens = signup_and_login(client, email=email)
    make_admin(client, tokens)
    return tokens


def _send_message(client, tokens, text="What is your return policy?"):
    conv = client.post("/conversations", json={}, headers=auth_headers(tokens)).json()
    client.post(f"/conversations/{conv['id']}/messages", json={"message": text}, headers=auth_headers(tokens))
    return conv["id"]


def test_customer_cannot_access_traces(client):
    user = signup_and_login(client)
    resp = client.get("/admin/traces", headers=auth_headers(user))
    assert resp.status_code == 403


def test_unauthenticated_is_401(client):
    resp = client.get("/admin/traces")
    assert resp.status_code == 401


def test_admin_sees_trace_after_a_turn(client):
    admin = _admin_client(client)
    conv_id = _send_message(client, admin)

    listing = client.get("/admin/traces", params={"conversation_id": conv_id}, headers=auth_headers(admin))
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 1
    assert body["items"][0]["conversation_id"] == conv_id
    assert "trace_id" in body["items"][0]
    assert "duration_ms" in body["items"][0]


def test_trace_detail_has_timeline_and_never_exposes_system_prompt(client):
    admin = _admin_client(client)
    conv_id = _send_message(client, admin, "Tell me about your return window")

    listing = client.get("/admin/traces", params={"conversation_id": conv_id}, headers=auth_headers(admin)).json()
    trace_id = listing["items"][0]["trace_id"]

    detail = client.get(f"/admin/traces/{trace_id}", headers=auth_headers(admin))
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["timeline"]) >= 4
    assert body["user_message"] == "Tell me about your return window"
    serialized = str(body)
    for forbidden in ("BASE_SYSTEM_PROMPT", "Ground rules", "system_instruction", "API_KEY", "GEMINI_API_KEY"):
        assert forbidden not in serialized


def test_trace_not_found_is_404(client):
    admin = _admin_client(client)
    resp = client.get("/admin/traces/does-not-exist", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_filter_by_handoff(client):
    admin = _admin_client(client)
    # Deterministic handoff trigger: an order ID that doesn't exist.
    conv_id = _send_message(client, admin, "What's the status of order NOTREAL999?")

    handoffs = client.get("/admin/traces", params={"handoff": True}, headers=auth_headers(admin)).json()
    assert handoffs["total"] >= 1
    assert all(item["handoff"] for item in handoffs["items"])
    assert any(item["conversation_id"] == conv_id for item in handoffs["items"])


def test_filter_by_status_answered(client, db_session):
    from app.db.models import Order

    admin = _admin_client(client)
    admin_id = client.get("/auth/me", headers=auth_headers(admin)).json()["id"]
    db_session.add(Order(order_number="ORD-5001", user_id=admin_id, status="shipped", carrier="UPS", tracking_number="1Z1"))
    db_session.commit()

    # The mock LLM (USE_MOCK_LLM=1 in tests) only gives a clean "answered"
    # turn for a successful order lookup -- see app/llm_client.py's
    # MockLLMClient, which is deliberately simple and returns
    # insufficient_information for open-ended policy questions since it
    # has no real language understanding (consistent with the harness's
    # own documented mock-mode limitations).
    _send_message(client, admin, "Where is my order ORD-5001?")

    answered = client.get("/admin/traces", params={"status": "answered"}, headers=auth_headers(admin)).json()
    assert answered["total"] >= 1
    assert all(item["status"] == "answered" for item in answered["items"])


def test_search_by_trace_id_returns_exactly_one(client):
    admin = _admin_client(client)
    conv_id = _send_message(client, admin)
    listing = client.get("/admin/traces", params={"conversation_id": conv_id}, headers=auth_headers(admin)).json()
    trace_id = listing["items"][0]["trace_id"]

    resp = client.get("/admin/traces", params={"trace_id": trace_id}, headers=auth_headers(admin)).json()
    assert resp["total"] == 1
    assert resp["items"][0]["trace_id"] == trace_id


def test_retrieval_outcome_filter(client):
    admin = _admin_client(client)
    _send_message(client, admin, "What is your return policy?")

    success = client.get("/admin/traces", params={"retrieval_outcome": "success"}, headers=auth_headers(admin)).json()
    assert success["total"] >= 1


def test_bad_date_filter_is_400(client):
    admin = _admin_client(client)
    resp = client.get("/admin/traces", params={"date_from": "not-a-date"}, headers=auth_headers(admin))
    assert resp.status_code == 400

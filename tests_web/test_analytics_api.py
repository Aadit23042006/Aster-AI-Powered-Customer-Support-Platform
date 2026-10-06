"""Tests for Phase 2, Feature 16 (AI analytics dashboard)."""
from __future__ import annotations

from tests_web.conftest import auth_headers, make_admin, signup_and_login


def _admin_client(client, email="analytics_admin@example.com"):
    tokens = signup_and_login(client, email=email)
    make_admin(client, tokens)
    return tokens


def test_customer_cannot_access_analytics(client):
    user = signup_and_login(client)
    resp = client.get("/admin/analytics/summary", headers=auth_headers(user))
    assert resp.status_code == 403


def test_unauthenticated_is_401(client):
    resp = client.get("/admin/analytics/summary")
    assert resp.status_code == 401


def test_summary_reflects_real_conversation_and_feedback_data(client):
    admin = _admin_client(client)
    conv = client.post("/conversations", json={}, headers=auth_headers(admin)).json()
    resp = client.post(
        f"/conversations/{conv['id']}/messages", json={"message": "What is your return policy?"}, headers=auth_headers(admin)
    ).json()
    client.post(f"/messages/{resp['assistant_message']['id']}/feedback", json={"rating": "positive"}, headers=auth_headers(admin))

    summary = client.get("/admin/analytics/summary", params={"range": "today"}, headers=auth_headers(admin))
    assert summary.status_code == 200
    body = summary.json()
    assert body["conversations"]["total"] >= 1
    assert body["feedback"]["positive"] >= 1
    assert body["feedback"]["satisfaction_rate"] is not None
    assert body["resolution"]["ai_resolved"] + body["resolution"]["human_handoff"] >= 1


def test_performance_metrics_come_from_trace_log(client):
    admin = _admin_client(client)
    conv = client.post("/conversations", json={}, headers=auth_headers(admin)).json()
    client.post(f"/conversations/{conv['id']}/messages", json={"message": "Hi there"}, headers=auth_headers(admin))

    summary = client.get("/admin/analytics/summary", params={"range": "today"}, headers=auth_headers(admin)).json()
    assert summary["performance"]["average_response_ms"] is not None
    assert summary["performance"]["average_response_ms"] >= 0


def test_invalid_range_is_rejected(client):
    admin = _admin_client(client)
    resp = client.get("/admin/analytics/summary", params={"range": "decade"}, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_custom_range_requires_dates(client):
    admin = _admin_client(client)
    resp = client.get("/admin/analytics/summary", params={"range": "custom"}, headers=auth_headers(admin))
    assert resp.status_code == 400


def test_full_dashboard_endpoint_includes_summary_and_timeseries(client):
    admin = _admin_client(client)
    conv = client.post("/conversations", json={}, headers=auth_headers(admin)).json()
    client.post(f"/conversations/{conv['id']}/messages", json={"message": "Hello"}, headers=auth_headers(admin))

    resp = client.get("/admin/analytics", params={"range": "7d"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body and "timeseries" in body
    assert len(body["timeseries"]["days"]) >= 7
    assert sum(body["timeseries"]["conversations"]) >= 1


def test_metrics_are_scoped_to_date_range(client):
    admin = _admin_client(client)
    conv = client.post("/conversations", json={}, headers=auth_headers(admin)).json()
    client.post(f"/conversations/{conv['id']}/messages", json={"message": "Hello"}, headers=auth_headers(admin))

    far_future = client.get(
        "/admin/analytics/summary",
        params={"range": "custom", "start_date": "2099-01-01", "end_date": "2099-01-02"},
        headers=auth_headers(admin),
    ).json()
    assert far_future["conversations"]["total"] == 0

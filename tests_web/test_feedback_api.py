"""Tests for Phase 2, Feature 15 (customer feedback on AI messages)."""
from __future__ import annotations

from tests_web.conftest import auth_headers, signup_and_login


def _send_and_get_assistant_message(client, tokens, text="What's your return policy?"):
    conv_id = client.post("/conversations", json={}, headers=auth_headers(tokens)).json()["id"]
    resp = client.post(f"/conversations/{conv_id}/messages", json={"message": text}, headers=auth_headers(tokens))
    return conv_id, resp.json()["assistant_message"]["id"]


def test_submit_positive_feedback(client):
    user = signup_and_login(client)
    _, message_id = _send_and_get_assistant_message(client, user)

    resp = client.post(f"/messages/{message_id}/feedback", json={"rating": "positive"}, headers=auth_headers(user))
    assert resp.status_code == 201
    body = resp.json()
    assert body["feedback"]["rating"] == "positive"
    assert body["suggest_handoff"] is False


def test_negative_feedback_with_reason_and_comment(client):
    user = signup_and_login(client)
    _, message_id = _send_and_get_assistant_message(client, user)

    resp = client.post(
        f"/messages/{message_id}/feedback",
        json={"rating": "negative", "reason": "missing_information", "comment": "Didn't mention international orders."},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    body = resp.json()["feedback"]
    assert body["reason"] == "missing_information"
    assert body["comment"] == "Didn't mention international orders."


def test_invalid_rating_is_rejected(client):
    user = signup_and_login(client)
    _, message_id = _send_and_get_assistant_message(client, user)
    resp = client.post(f"/messages/{message_id}/feedback", json={"rating": "meh"}, headers=auth_headers(user))
    assert resp.status_code == 400


def test_invalid_reason_is_rejected(client):
    user = signup_and_login(client)
    _, message_id = _send_and_get_assistant_message(client, user)
    resp = client.post(
        f"/messages/{message_id}/feedback", json={"rating": "negative", "reason": "not_a_real_reason"}, headers=auth_headers(user)
    )
    assert resp.status_code == 400


def test_cannot_leave_feedback_on_own_user_message(client):
    user = signup_and_login(client)
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]
    client.post(f"/conversations/{conv_id}/messages", json={"message": "Hello"}, headers=auth_headers(user))
    history = client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(user)).json()
    user_message_id = next(m["id"] for m in history if m["role"] == "user")

    resp = client.post(f"/messages/{user_message_id}/feedback", json={"rating": "positive"}, headers=auth_headers(user))
    assert resp.status_code == 400


def test_resubmitting_feedback_updates_rather_than_duplicates(client):
    user = signup_and_login(client)
    _, message_id = _send_and_get_assistant_message(client, user)

    first = client.post(f"/messages/{message_id}/feedback", json={"rating": "negative", "reason": "other"}, headers=auth_headers(user))
    second = client.post(f"/messages/{message_id}/feedback", json={"rating": "positive"}, headers=auth_headers(user))
    assert first.json()["feedback"]["id"] == second.json()["feedback"]["id"]
    assert second.json()["feedback"]["rating"] == "positive"

    fetched = client.get(f"/messages/{message_id}/feedback", headers=auth_headers(user))
    assert fetched.status_code == 200
    assert fetched.json()["rating"] == "positive"


def test_feedback_on_another_users_message_is_404(client):
    owner = signup_and_login(client, email="owner_fb@example.com")
    other = signup_and_login(client, email="other_fb@example.com")
    _, message_id = _send_and_get_assistant_message(client, owner)

    resp = client.post(f"/messages/{message_id}/feedback", json={"rating": "positive"}, headers=auth_headers(other))
    assert resp.status_code == 404


def test_unauthenticated_feedback_is_401(client):
    resp = client.post(
        "/messages/00000000-0000-0000-0000-000000000000/feedback",
        json={"rating": "positive"},
    )
    assert resp.status_code == 401


def test_get_feedback_with_none_submitted_returns_null_body(client):
    user = signup_and_login(client)
    _, message_id = _send_and_get_assistant_message(client, user)
    resp = client.get(f"/messages/{message_id}/feedback", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json() is None


def test_repeated_negative_feedback_suggests_handoff(client):
    user = signup_and_login(client)
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]

    msg1 = client.post(f"/conversations/{conv_id}/messages", json={"message": "What's your return policy?"}, headers=auth_headers(user)).json()
    r1 = client.post(f"/messages/{msg1['assistant_message']['id']}/feedback", json={"rating": "negative", "reason": "other"}, headers=auth_headers(user))
    assert r1.json()["suggest_handoff"] is False  # first negative alone doesn't trigger it

    msg2 = client.post(f"/conversations/{conv_id}/messages", json={"message": "What about shipping?"}, headers=auth_headers(user)).json()
    r2 = client.post(f"/messages/{msg2['assistant_message']['id']}/feedback", json={"rating": "negative", "reason": "other"}, headers=auth_headers(user))
    assert r2.json()["suggest_handoff"] is True

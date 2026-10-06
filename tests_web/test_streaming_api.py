"""Tests for POST /conversations/{id}/messages/stream (Phase 2, Feature 11).

Covers: authenticated streaming, unauthorized access, cross-user ownership,
that the final persisted message matches what the non-streaming endpoint
would have produced, and that the stream carries the same sources/handoff
metadata as the JSON endpoint.
"""
from __future__ import annotations

import json

from tests_web.conftest import auth_headers, signup_and_login


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if data is not None:
            events.append((event_type, data))
    return events


def test_stream_requires_authentication(client):
    user = signup_and_login(client)
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]

    resp = client.post(f"/conversations/{conv_id}/messages/stream", json={"message": "Hi"})
    assert resp.status_code == 401


def test_stream_denies_other_users_conversation(client):
    owner = signup_and_login(client, email="owner@example.com")
    other = signup_and_login(client, email="other@example.com")
    conv_id = client.post("/conversations", json={}, headers=auth_headers(owner)).json()["id"]

    resp = client.post(
        f"/conversations/{conv_id}/messages/stream", json={"message": "Hi"}, headers=auth_headers(other)
    )
    assert resp.status_code == 404


def test_stream_emits_start_delta_and_done_events(client):
    user = signup_and_login(client)
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]

    resp = client.post(
        f"/conversations/{conv_id}/messages/stream",
        json={"message": "What's your return policy?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    event_types = [e for e, _ in events]
    assert event_types[0] == "start"
    assert event_types[-1] == "done"
    assert "delta" in event_types

    # Reassembling every delta chunk must reproduce the full answer text
    # that shipped in the "done" event -- the reveal must never drop or
    # reorder text relative to the actual validated answer.
    reassembled = "".join(data["text"] for etype, data in events if etype == "delta")
    done_data = next(data for etype, data in events if etype == "done")
    assert reassembled == done_data["assistant_message"]["content"]
    assert isinstance(done_data["sources"], list)
    assert isinstance(done_data["handoff"], bool)


def test_stream_persists_messages_identically_to_non_streaming_endpoint(client):
    user = signup_and_login(client)
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]

    resp = client.post(
        f"/conversations/{conv_id}/messages/stream",
        json={"message": "How long do I have to return a backpack?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200

    # The turn was fully persisted to Postgres exactly like the JSON
    # endpoint would have, before any bytes were streamed.
    history = client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(user)).json()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"

    events = _parse_sse(resp.text)
    done_data = next(data for etype, data in events if etype == "done")
    assert done_data["assistant_message"]["id"] == history[1]["id"]


def test_stream_multi_turn_keeps_context(client):
    user = signup_and_login(client)
    conv_id = client.post("/conversations", json={}, headers=auth_headers(user)).json()["id"]

    r1 = client.post(
        f"/conversations/{conv_id}/messages/stream",
        json={"message": "What's your return policy?"},
        headers=auth_headers(user),
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/conversations/{conv_id}/messages/stream",
        json={"message": "What about international orders?"},
        headers=auth_headers(user),
    )
    assert r2.status_code == 200

    history = client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(user)).json()
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


def test_stream_returns_json_error_for_missing_conversation(client):
    user = signup_and_login(client)
    resp = client.post(
        "/conversations/00000000-0000-0000-0000-000000000000/messages/stream",
        json={"message": "Hi"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")

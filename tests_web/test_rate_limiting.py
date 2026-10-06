"""Tests for Phase 3 Feature 20 (rate limiting). Unlike the rest of
tests_web/ (which disables rate limiting globally -- see the comment in
conftest.py), these tests explicitly re-enable it and reset the specific
Redis buckets they use, so they don't interfere with each other or with
the disabled-by-default state everywhere else."""
from __future__ import annotations

from app import config
from app.security import rate_limit
from tests_web.conftest import auth_headers, signup_and_login


def _enable_rate_limiting(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)


def test_login_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    _enable_rate_limiting(monkeypatch)
    monkeypatch.setattr(config, "RATE_LIMIT_LOGIN", (3, 60))
    rate_limit.reset("login", "testclient")

    signup_and_login(client, email="ratelimit1@example.com", password="Password123!")
    for _ in range(3):
        resp = client.post("/auth/login", json={"email": "ratelimit1@example.com", "password": "wrong"})
        assert resp.status_code == 401  # under the limit, ordinary auth failure

    resp = client.post("/auth/login", json={"email": "ratelimit1@example.com", "password": "wrong"})
    assert resp.status_code == 429
    body = resp.json()["detail"]
    assert body["error"] == "rate_limit_exceeded"
    assert "retry_after" in body
    assert "Retry-After" in resp.headers
    assert "X-RateLimit-Limit" in resp.headers
    assert resp.headers["X-RateLimit-Remaining"] == "0"


def test_signup_rate_limit_is_separate_from_login(client, monkeypatch):
    """Different endpoints must have independent budgets -- exhausting the
    login bucket must not affect the signup bucket."""
    _enable_rate_limiting(monkeypatch)
    monkeypatch.setattr(config, "RATE_LIMIT_LOGIN", (1, 60))
    monkeypatch.setattr(config, "RATE_LIMIT_SIGNUP", (5, 3600))
    rate_limit.reset("login", "testclient")
    rate_limit.reset("signup", "testclient")

    client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 429

    # signup should be unaffected by the exhausted login bucket
    resp = client.post(
        "/auth/signup",
        json={"full_name": "Still Works", "email": "stillworks@example.com", "password": "Password123!", "confirm_password": "Password123!"},
    )
    assert resp.status_code == 201


def test_authenticated_endpoint_rate_limit_is_per_user_not_global(client, monkeypatch):
    """AI chat rate limiting keys on the authenticated user, not shared
    globally -- user A hitting their limit must not affect user B."""
    _enable_rate_limiting(monkeypatch)
    monkeypatch.setattr(config, "RATE_LIMIT_AI_CHAT", (1, 60))

    tokens_a = signup_and_login(client, email="chatlimit_a@example.com")
    tokens_b = signup_and_login(client, email="chatlimit_b@example.com")
    rate_limit.reset("ai_chat", client.get("/auth/me", headers=auth_headers(tokens_a)).json()["id"])
    rate_limit.reset("ai_chat", client.get("/auth/me", headers=auth_headers(tokens_b)).json()["id"])

    conv_a = client.post("/conversations", json={}, headers=auth_headers(tokens_a)).json()
    conv_b = client.post("/conversations", json={}, headers=auth_headers(tokens_b)).json()

    resp1 = client.post(f"/conversations/{conv_a['id']}/messages", json={"message": "hi"}, headers=auth_headers(tokens_a))
    assert resp1.status_code == 200
    resp2 = client.post(f"/conversations/{conv_a['id']}/messages", json={"message": "hi again"}, headers=auth_headers(tokens_a))
    assert resp2.status_code == 429

    # user B still has their own, untouched budget
    resp3 = client.post(f"/conversations/{conv_b['id']}/messages", json={"message": "hi"}, headers=auth_headers(tokens_b))
    assert resp3.status_code == 200


def test_ticket_creation_rate_limit(client, monkeypatch):
    _enable_rate_limiting(monkeypatch)
    monkeypatch.setattr(config, "RATE_LIMIT_TICKET_CREATE", (2, 3600))
    tokens = signup_and_login(client, email="ticketlimit@example.com")
    user_id = client.get("/auth/me", headers=auth_headers(tokens)).json()["id"]
    rate_limit.reset("ticket_create", user_id)

    for _ in range(2):
        resp = client.post(
            "/tickets", json={"subject": "x", "description": "y", "category": "other"}, headers=auth_headers(tokens)
        )
        assert resp.status_code == 201

    resp = client.post(
        "/tickets", json={"subject": "x", "description": "y", "category": "other"}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 429


def test_rate_limiting_disabled_flag_bypasses_limiter(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(config, "RATE_LIMIT_LOGIN", (1, 60))
    rate_limit.reset("login", "testclient")

    for _ in range(5):
        resp = client.post("/auth/login", json={"email": "nobody2@example.com", "password": "x"})
        assert resp.status_code == 401  # never 429 -- the master switch is off


def test_rate_limiter_fails_open_when_redis_unavailable(monkeypatch):
    """If Redis is unreachable, requests must be allowed through rather
    than the whole API going down -- see the module docstring in
    app/security/rate_limit.py for why this is a deliberate choice."""
    import redis as redis_module

    class _BrokenRedis:
        def eval(self, *a, **kw):
            raise redis_module.RedisError("simulated outage")

    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit, "_get_client", lambda: _BrokenRedis())
    result = rate_limit.hit("login", "1.2.3.4", 1, 60)
    assert result.allowed is True

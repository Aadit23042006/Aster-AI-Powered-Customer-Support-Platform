from tests_web.conftest import auth_headers, signup_and_login


def test_signup_creates_account_and_returns_tokens(client):
    resp = client.post(
        "/auth/signup",
        json={"full_name": "Bob Test", "email": "bob@example.com", "password": "Password123!", "confirm_password": "Password123!"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body and "refresh_token" in body


def test_signup_rejects_mismatched_passwords(client):
    resp = client.post(
        "/auth/signup",
        json={"full_name": "Bob", "email": "bob2@example.com", "password": "Password123!", "confirm_password": "Different123!"},
    )
    assert resp.status_code == 400


def test_signup_rejects_weak_password(client):
    resp = client.post(
        "/auth/signup",
        json={"full_name": "Bob", "email": "bob3@example.com", "password": "weak", "confirm_password": "weak"},
    )
    assert resp.status_code == 400


def test_signup_rejects_duplicate_email(client):
    signup_and_login(client, email="dupe@example.com")
    resp = client.post(
        "/auth/signup",
        json={"full_name": "Someone Else", "email": "dupe@example.com", "password": "Password123!", "confirm_password": "Password123!"},
    )
    assert resp.status_code == 409


def test_login_succeeds_with_correct_credentials(client):
    signup_and_login(client, email="carol@example.com", password="Password123!")
    resp = client.post("/auth/login", json={"email": "carol@example.com", "password": "Password123!"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_fails_with_wrong_password(client):
    signup_and_login(client, email="dave@example.com", password="Password123!")
    resp = client.post("/auth/login", json={"email": "dave@example.com", "password": "WrongPassword1"})
    assert resp.status_code == 401


def test_login_fails_for_unknown_email(client):
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "Password123!"})
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user_with_valid_token(client):
    tokens = signup_and_login(client, email="erin@example.com", full_name="Erin Test")
    resp = client.get("/auth/me", headers=auth_headers(tokens))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "erin@example.com"
    assert body["full_name"] == "Erin Test"
    assert body["roles"] == ["customer"]


def test_protected_route_rejects_garbage_token(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_logout_revokes_refresh_token(client):
    tokens = signup_and_login(client, email="frank@example.com")
    resp = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 204
    # The now-revoked refresh token can no longer mint new access tokens.
    resp2 = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp2.status_code == 401


def test_refresh_issues_new_access_token(client):
    tokens = signup_and_login(client, email="grace@example.com")
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"] != tokens["access_token"]


def test_forgot_password_does_not_leak_account_existence(client):
    signup_and_login(client, email="henry@example.com")
    resp_known = client.post("/auth/forgot-password", json={"email": "henry@example.com"})
    resp_unknown = client.post("/auth/forgot-password", json={"email": "nobody-at-all@example.com"})
    assert resp_known.status_code == resp_unknown.status_code == 202
    assert resp_known.json() == resp_unknown.json()

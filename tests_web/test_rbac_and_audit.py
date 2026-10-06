"""Phase 3 tests: fine-grained RBAC (Feature 19) and audit logs (Feature
21). Reuses the `make_admin` helper from conftest.py; adds a matching
`make_super_admin` for the privilege-escalation tests, since that's the
one distinction Feature 19 explicitly calls out (an admin cannot mint
another admin; only a super_admin can)."""
from __future__ import annotations

from app.db.base import SessionLocal
from app.db.models import Role, UserRole
from tests_web.conftest import auth_headers, make_admin, signup_and_login


def make_super_admin(client, tokens: dict) -> None:
    user_id = client.get("/auth/me", headers=auth_headers(tokens)).json()["id"]
    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.name == "super_admin").first()
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.commit()
    finally:
        db.close()


def _refresh_token_for(client, email, password="Password123!"):
    return client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]


# --- RBAC: permission-gated admin routes ---
def test_customer_cannot_read_audit_logs(client):
    tokens = signup_and_login(client, email="cust_rbac1@example.com")
    resp = client.get("/admin/audit-logs", headers=auth_headers(tokens))
    assert resp.status_code == 403


def test_support_agent_cannot_read_audit_logs_by_default(client):
    """support_agent's default permission set (app/auth/permissions.py)
    does not include audit_logs.read -- only admin/super_admin do."""
    tokens = signup_and_login(client, email="agent_rbac1@example.com")
    db = SessionLocal()
    try:
        user_id = client.get("/auth/me", headers=auth_headers(tokens)).json()["id"]
        role = db.query(Role).filter(Role.name == "support_agent").first()
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.commit()
    finally:
        db.close()
    fresh_token = _refresh_token_for(client, "agent_rbac1@example.com")
    resp = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {fresh_token}"})
    assert resp.status_code == 403


def test_admin_can_read_audit_logs(client):
    tokens = signup_and_login(client, email="admin_rbac1@example.com")
    make_admin(client, tokens)
    fresh_token = _refresh_token_for(client, "admin_rbac1@example.com")
    resp = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {fresh_token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total" in body


def test_audit_log_records_login_success_and_failure(client):
    signup_and_login(client, email="audited@example.com", password="Password123!")
    client.post("/auth/login", json={"email": "audited@example.com", "password": "WrongPassword1"})
    client.post("/auth/login", json={"email": "audited@example.com", "password": "Password123!"})

    admin_tokens = signup_and_login(client, email="admin_rbac2@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac2@example.com")
    resp = client.get(
        "/admin/audit-logs", params={"event_type": "LOGIN_FAILED"}, headers={"Authorization": f"Bearer {fresh}"}
    )
    assert resp.status_code == 200
    events = resp.json()["items"]
    assert any(e["event_type"] == "LOGIN_FAILED" and e["success"] is False for e in events)


def test_audit_log_never_contains_password(client):
    """Regression test for the explicit audit-security requirement: audit
    detail must never contain a password/token, even indirectly."""
    signup_and_login(client, email="secret_check@example.com", password="Password123!")
    admin_tokens = signup_and_login(client, email="admin_rbac3@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac3@example.com")
    resp = client.get("/admin/audit-logs", headers={"Authorization": f"Bearer {fresh}"})
    body_text = resp.text
    assert "Password123!" not in body_text


# --- RBAC: user/role management + privilege escalation prevention ---
def test_customer_cannot_manage_user_roles(client):
    tokens = signup_and_login(client, email="cust_rbac2@example.com")
    target = signup_and_login(client, email="target1@example.com")
    target_id = client.get("/auth/me", headers=auth_headers(target)).json()["id"]
    resp = client.patch(f"/admin/users/{target_id}/role", json={"roles": ["customer"]}, headers=auth_headers(tokens))
    assert resp.status_code == 403


def test_admin_can_promote_customer_to_support_agent(client):
    admin_tokens = signup_and_login(client, email="admin_rbac4@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac4@example.com")

    target = signup_and_login(client, email="target2@example.com")
    target_id = client.get("/auth/me", headers=auth_headers(target)).json()["id"]

    resp = client.patch(
        f"/admin/users/{target_id}/role", json={"roles": ["support_agent"]}, headers={"Authorization": f"Bearer {fresh}"}
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["support_agent"]


def test_admin_cannot_grant_admin_role_privilege_escalation_blocked(client):
    """The critical IDOR/privilege-escalation test: an admin (not
    super_admin) must NOT be able to mint another admin account."""
    admin_tokens = signup_and_login(client, email="admin_rbac5@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac5@example.com")

    target = signup_and_login(client, email="target3@example.com")
    target_id = client.get("/auth/me", headers=auth_headers(target)).json()["id"]

    resp = client.patch(
        f"/admin/users/{target_id}/role", json={"roles": ["admin"]}, headers={"Authorization": f"Bearer {fresh}"}
    )
    assert resp.status_code == 403


def test_super_admin_can_grant_admin_role(client):
    su_tokens = signup_and_login(client, email="su_rbac1@example.com")
    make_super_admin(client, su_tokens)
    fresh = _refresh_token_for(client, "su_rbac1@example.com")

    target = signup_and_login(client, email="target4@example.com")
    target_id = client.get("/auth/me", headers=auth_headers(target)).json()["id"]

    resp = client.patch(
        f"/admin/users/{target_id}/role", json={"roles": ["admin"]}, headers={"Authorization": f"Bearer {fresh}"}
    )
    assert resp.status_code == 200
    assert resp.json()["roles"] == ["admin"]


def test_admin_cannot_change_their_own_roles_self_escalation_blocked(client):
    admin_tokens = signup_and_login(client, email="admin_rbac6@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac6@example.com")
    user_id = client.get("/auth/me", headers={"Authorization": f"Bearer {fresh}"}).json()["id"]

    resp = client.patch(
        f"/admin/users/{user_id}/role", json={"roles": ["super_admin"]}, headers={"Authorization": f"Bearer {fresh}"}
    )
    assert resp.status_code == 403


def test_unknown_role_name_rejected(client):
    admin_tokens = signup_and_login(client, email="admin_rbac7@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac7@example.com")
    target = signup_and_login(client, email="target5@example.com")
    target_id = client.get("/auth/me", headers=auth_headers(target)).json()["id"]

    resp = client.patch(
        f"/admin/users/{target_id}/role", json={"roles": ["superhero"]}, headers={"Authorization": f"Bearer {fresh}"}
    )
    assert resp.status_code == 400


def test_customer_cannot_list_all_users_idor(client):
    """A customer must not be able to enumerate other users via the admin
    listing endpoint (IDOR-adjacent: this endpoint has no per-row ownership
    concept at all, so it must be fully permission-gated)."""
    tokens = signup_and_login(client, email="cust_rbac3@example.com")
    resp = client.get("/admin/users", headers=auth_headers(tokens))
    assert resp.status_code == 403


def test_admin_can_list_users_paginated(client):
    admin_tokens = signup_and_login(client, email="admin_rbac8@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_rbac8@example.com")
    for i in range(3):
        signup_and_login(client, email=f"paguser{i}@example.com")

    resp = client.get("/admin/users", params={"page": 1, "page_size": 2}, headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 4  # admin + 3 paguser accounts



def test_admin_can_delete_customer_user(client):
    admin_tokens = signup_and_login(client, email="admin_delete1@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_delete1@example.com")
    target = signup_and_login(client, email="delete_customer1@example.com")
    target_id = client.get("/auth/me", headers=auth_headers(target)).json()["id"]

    resp = client.delete(f"/admin/users/{target_id}", headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 204
    assert client.get("/auth/me", headers=auth_headers(target)).status_code in {401, 403}


def test_admin_cannot_delete_self_or_super_admin(client):
    admin_tokens = signup_and_login(client, email="admin_delete2@example.com")
    make_admin(client, admin_tokens)
    fresh = _refresh_token_for(client, "admin_delete2@example.com")
    admin_id = client.get("/auth/me", headers={"Authorization": f"Bearer {fresh}"}).json()["id"]

    resp = client.delete(f"/admin/users/{admin_id}", headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 403

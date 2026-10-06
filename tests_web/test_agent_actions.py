"""Feature 1: AI tool calling + Action Center (approval, idempotency, audit)."""
from __future__ import annotations

import uuid

from tests_web.conftest import auth_headers, signup_and_login
from tests_web.test_enterprise_full_coverage import make_support_agent


def _user(db, client, tokens):
    from app.db.models import User
    uid = client.get("/auth/me", headers=auth_headers(tokens)).json()["id"]
    return db.get(User, uuid.UUID(uid)), uid


def _audit_types(db):
    from app.db.models import AuditEvent
    return [e.event_type for e in db.query(AuditEvent).all()]


def _agent(client, email):
    t = signup_and_login(client, email=email)
    make_support_agent(client, t)
    return t


def test_registry_classifies_tools_by_category(client):
    agent = _agent(client, "reg-agent@example.com")
    tools = {t["name"]: t for t in client.get("/action-center/tools", headers=auth_headers(agent)).json()["tools"]}
    assert tools["lookup_order"]["category"] == "read_only"
    assert tools["check_shipment_status"]["category"] == "read_only"
    assert tools["create_support_ticket"]["category"] == "mutating"
    assert tools["notify_customer"]["category"] == "mutating"


def test_staff_direct_execution_is_idempotent_and_audited(client, db_session):
    agent = _agent(client, "idem-agent@example.com")
    body = {"tool_name": "create_support_ticket",
            "arguments": {"subject": "Test", "description": "d", "category": "other", "priority": "low"}}
    first = client.post("/action-center/execute", json=body, headers=auth_headers(agent))
    assert first.status_code == 200 and first.json()["status"] == "success"
    assert first.json()["approval_status"] == "not_required" and first.json()["duplicate"] is False
    again = client.post("/action-center/execute", json=body, headers=auth_headers(agent))
    assert again.json()["duplicate"] is True and again.json()["action_id"] == first.json()["action_id"]
    from app.db.models import Ticket
    assert db_session.query(Ticket).filter(Ticket.subject == "Test").count() == 1
    assert "AI_TOOL_EXECUTED" in _audit_types(db_session)


def test_failed_tool_is_recorded_and_does_not_crash(client, db_session):
    agent = _agent(client, "fail-agent@example.com")
    r = client.post("/action-center/execute", headers=auth_headers(agent),
                    json={"tool_name": "escalate_ticket", "arguments": {"ticket_id": str(uuid.uuid4())}})
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert "AI_TOOL_FAILED" in _audit_types(db_session)
    # the surrounding session is still usable afterwards
    ok = client.get("/action-center/actions", headers=auth_headers(agent))
    assert ok.status_code == 200 and ok.json()[0]["execution_status"] == "failed"


def test_ai_proposed_mutation_waits_for_approval_then_executes_for_customer(client, db_session):
    from app.enterprise import actions
    from app.db.models import Ticket
    customer = signup_and_login(client, email="ai-cust@example.com")
    cust, cust_id = _user(db_session, client, customer)
    proposed = actions.execute(db_session, cust, "create_support_ticket",
                               {"subject": "Delayed", "description": "late", "category": "shipping", "priority": "high"},
                               None, origin="ai", reason="delay detected")
    assert proposed["status"] == "approval_required" and proposed["approval_status"] == "pending"
    assert db_session.query(Ticket).filter(Ticket.subject == "Delayed").count() == 0   # nothing executed yet
    # re-proposing the same thing does not duplicate the pending action
    assert actions.execute(db_session, cust, "create_support_ticket",
                           {"subject": "Delayed", "description": "late", "category": "shipping", "priority": "high"},
                           None, origin="ai")["duplicate"] is True

    # customers can never approve
    assert client.post(f"/action-center/actions/{proposed['action_id']}/approve",
                       headers=auth_headers(customer)).status_code == 403

    agent = _agent(client, "approver@example.com")
    pending = client.get("/action-center/actions?approval_status=pending", headers=auth_headers(agent)).json()
    assert [a["id"] for a in pending] == [proposed["action_id"]]
    done = client.post(f"/action-center/actions/{proposed['action_id']}/approve", headers=auth_headers(agent))
    assert done.status_code == 200 and done.json()["status"] == "success"
    t = db_session.query(Ticket).filter(Ticket.subject == "Delayed").one()
    assert str(t.user_id) == cust_id                       # ticket belongs to the customer, not the approver
    assert client.post(f"/action-center/actions/{proposed['action_id']}/approve",
                       headers=auth_headers(agent)).status_code == 400   # cannot approve twice
    types = _audit_types(db_session)
    assert "AI_TOOL_APPROVAL_REQUIRED" in types and "AI_TOOL_APPROVED" in types and "AI_TOOL_EXECUTED" in types


def test_rejected_action_never_executes(client, db_session):
    from app.enterprise import actions
    from app.db.models import Ticket
    customer = signup_and_login(client, email="rej-cust@example.com")
    cust, _ = _user(db_session, client, customer)
    p = actions.execute(db_session, cust, "create_support_ticket", {"subject": "Nope", "description": "x"}, None, origin="ai")
    agent = _agent(client, "rejecter@example.com")
    r = client.post(f"/action-center/actions/{p['action_id']}/reject", json={"note": "not needed"}, headers=auth_headers(agent))
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["approval_status"] == "rejected"
    assert db_session.query(Ticket).filter(Ticket.subject == "Nope").count() == 0
    assert "AI_TOOL_REJECTED" in _audit_types(db_session)


def test_read_only_tool_from_ai_runs_without_approval(client, db_session):
    from app.enterprise import actions
    customer = signup_and_login(client, email="ro-cust@example.com")
    cust, _ = _user(db_session, client, customer)
    # customers lack orders.read -> permission is enforced on the backend
    try:
        actions.execute(db_session, cust, "check_shipment_status", {"order_id": "ORD-1001"}, None, origin="ai")
        assert False, "expected PermissionError"
    except PermissionError:
        pass
    agent = _agent(client, "ro-agent@example.com")
    ag, _ = _user(db_session, client, agent)
    out = actions.execute(db_session, ag, "check_shipment_status", {"order_id": "ORD-1001"}, None, origin="ai")
    assert out["status"] == "success" and out["approval_status"] == "not_required"


def test_disabled_flag_blocks_actions_but_not_the_rest_of_the_app(client, monkeypatch):
    from app import config
    agent = _agent(client, "flag-agent@example.com")
    monkeypatch.setattr(config, "AI_AGENT_ACTIONS_ENABLED", False)
    r = client.post("/action-center/execute", headers=auth_headers(agent),
                    json={"tool_name": "get_ticket", "arguments": {"ticket_id": str(uuid.uuid4())}})
    assert r.status_code == 403
    assert client.get("/tickets", headers=auth_headers(agent)).status_code == 200


def test_pii_is_redacted_in_stored_action_arguments(client, db_session):
    from app.enterprise import actions
    agent = _agent(client, "pii-agent@example.com")
    ag, _ = _user(db_session, client, agent)
    out = actions.execute(db_session, ag, "create_support_ticket",
                          {"subject": "PII", "description": "reach me at jane.doe@example.com"}, None)
    from app.db.models import AIAction
    row = db_session.get(AIAction, uuid.UUID(out["action_id"]))
    assert "jane.doe@example.com" not in str(row.arguments_sanitized)

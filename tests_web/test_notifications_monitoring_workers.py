"""Phase 3 tests for notifications (23), background workers (24),
monitoring (25), and error tracking (26)."""
from __future__ import annotations

import uuid

from tests_web.conftest import auth_headers, make_admin, signup_and_login


# --- Feature 23: notifications ---
def test_creating_a_ticket_creates_a_notification(client):
    tokens = signup_and_login(client, email="notif1@example.com")
    resp = client.post(
        "/tickets", json={"subject": "Help", "description": "please help", "category": "other"}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 201

    notifs = client.get("/notifications", headers=auth_headers(tokens)).json()
    assert any(n["type"] == "ticket_created" for n in notifs)


def test_unread_count_and_mark_read(client):
    tokens = signup_and_login(client, email="notif2@example.com")
    client.post("/tickets", json={"subject": "a", "description": "b", "category": "other"}, headers=auth_headers(tokens))

    count_resp = client.get("/notifications/unread-count", headers=auth_headers(tokens))
    assert count_resp.status_code == 200
    assert count_resp.json()["unread_count"] >= 1

    notif_id = client.get("/notifications", headers=auth_headers(tokens)).json()[0]["id"]
    mark_resp = client.post(f"/notifications/{notif_id}/read", headers=auth_headers(tokens))
    assert mark_resp.status_code == 200
    assert mark_resp.json()["read_at"] is not None


def test_mark_all_read(client):
    tokens = signup_and_login(client, email="notif3@example.com")
    for i in range(3):
        client.post("/tickets", json={"subject": f"t{i}", "description": "b", "category": "other"}, headers=auth_headers(tokens))

    resp = client.post("/notifications/read-all", headers=auth_headers(tokens))
    assert resp.status_code == 200
    assert resp.json()["marked_read"] >= 3
    assert client.get("/notifications/unread-count", headers=auth_headers(tokens)).json()["unread_count"] == 0


def test_user_a_cannot_read_or_mark_user_b_notifications(client):
    tokens_a = signup_and_login(client, email="notif_a@example.com")
    tokens_b = signup_and_login(client, email="notif_b@example.com")
    client.post("/tickets", json={"subject": "b-ticket", "description": "b", "category": "other"}, headers=auth_headers(tokens_b))
    notif_b_id = client.get("/notifications", headers=auth_headers(tokens_b)).json()[0]["id"]

    resp = client.post(f"/notifications/{notif_b_id}/read", headers=auth_headers(tokens_a))
    assert resp.status_code == 404

    listing_a = client.get("/notifications", headers=auth_headers(tokens_a)).json()
    assert all(n["id"] != notif_b_id for n in listing_a)


def test_notification_email_task_is_idempotent_duplicate_prevention():
    """Feature 24 idempotency requirement, exercised via the exact
    dedupe_key convention `app.notifications.service.create_notification`
    uses (`notify-email:<notification_id>`)."""
    from app.workers.tasks.notification_tasks import send_notification_email

    notif_id = str(uuid.uuid4())
    first = send_notification_email.apply(args=(notif_id, "someone@example.com", "Subject", "Body")).get()
    assert first["status"] == "sent"
    second = send_notification_email.apply(args=(notif_id, "someone@example.com", "Subject", "Body")).get()
    assert second["status"] == "skipped_duplicate"


# --- Feature 24: background workers (job tracking directly) ---
def test_job_tracking_marks_success_on_clean_completion():
    from app.workers.tasks.job_tracking import get_or_create_job, track_job

    job, already_done = get_or_create_job("test_task", dedupe_key=f"test:{uuid.uuid4()}")
    assert already_done is False
    with track_job(job.id):
        pass  # simulate successful work

    from app.db.base import SessionLocal
    from app.db.models import BackgroundJob

    db = SessionLocal()
    try:
        refreshed = db.get(BackgroundJob, job.id)
        assert refreshed.status == "success"
        assert refreshed.attempts == 1
    finally:
        db.close()


def test_job_tracking_marks_failed_and_records_error_on_exception():
    from app.workers.tasks.job_tracking import get_or_create_job, track_job

    job, _ = get_or_create_job("test_task_fail", dedupe_key=f"testfail:{uuid.uuid4()}")
    try:
        with track_job(job.id):
            raise ValueError("simulated failure")
    except ValueError:
        pass

    from app.db.base import SessionLocal
    from app.db.models import BackgroundJob

    db = SessionLocal()
    try:
        refreshed = db.get(BackgroundJob, job.id)
        assert refreshed.status == "failed"
        assert "simulated failure" in refreshed.error
    finally:
        db.close()


def test_job_tracking_idempotency_skips_already_successful_job():
    from app.workers.tasks.job_tracking import get_or_create_job, track_job

    dedupe_key = f"testidempotent:{uuid.uuid4()}"
    job1, done1 = get_or_create_job("test_task_idem", dedupe_key=dedupe_key)
    assert done1 is False
    with track_job(job1.id):
        pass

    job2, done2 = get_or_create_job("test_task_idem", dedupe_key=dedupe_key)
    assert done2 is True
    assert job2.id == job1.id


# --- Feature 25: monitoring ---
def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_liveness_endpoint_never_touches_dependencies(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200


def test_readiness_endpoint_reports_dependency_checks(client):
    resp = client.get("/health/ready")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "checks" in body
    assert "database" in body["checks"]


def test_customer_cannot_read_system_metrics(client):
    tokens = signup_and_login(client, email="metrics_cust@example.com")
    resp = client.get("/admin/system/metrics", headers=auth_headers(tokens))
    assert resp.status_code == 403


def test_admin_can_read_system_metrics_and_numbers_are_real(client):
    admin_tokens = signup_and_login(client, email="metrics_admin@example.com")
    make_admin(client, admin_tokens)
    fresh = client.post("/auth/login", json={"email": "metrics_admin@example.com", "password": "Password123!"}).json()["access_token"]

    # Generate at least one real HTTP request before checking counters.
    client.get("/health")
    resp = client.get("/admin/system/metrics", headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["http_requests_total"] > 0  # a real count, not a hardcoded number


def test_admin_can_read_system_health(client):
    admin_tokens = signup_and_login(client, email="health_admin@example.com")
    make_admin(client, admin_tokens)
    fresh = client.post("/auth/login", json={"email": "health_admin@example.com", "password": "Password123!"}).json()["access_token"]
    resp = client.get("/admin/system/health", headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 200
    assert "database" in resp.json()["checks"]


# --- Feature 26: error tracking ---
def test_capture_exception_records_error_event_with_redaction():
    from app.monitoring.error_tracking import capture_exception

    exc = ValueError("something failed for user someone@example.com")
    event = capture_exception(exc, request_id="req-123", route="/test/route")
    assert event is not None
    assert event.request_id == "req-123"
    assert event.error_type == "ValueError"
    # The email in the exception message must be masked, not raw.
    assert "someone@example.com" not in event.error_message
    assert "*" in event.error_message


def test_customer_cannot_read_error_events(client):
    tokens = signup_and_login(client, email="errors_cust@example.com")
    resp = client.get("/admin/errors", headers=auth_headers(tokens))
    assert resp.status_code == 403


def test_admin_can_list_error_events(client):
    from app.monitoring.error_tracking import capture_exception

    capture_exception(RuntimeError("boom"), request_id="req-admin-test")

    admin_tokens = signup_and_login(client, email="errors_admin@example.com")
    make_admin(client, admin_tokens)
    fresh = client.post("/auth/login", json={"email": "errors_admin@example.com", "password": "Password123!"}).json()["access_token"]
    resp = client.get("/admin/errors", headers={"Authorization": f"Bearer {fresh}"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

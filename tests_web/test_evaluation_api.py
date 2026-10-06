"""Tests for Phase 2, Feature 18 (Evaluation Dashboard).

Runs the *real* evaluation harness (`evaluation/run_eval.py`) in mock-LLM
mode -- these tests are slightly heavier than the rest of the suite since
each triggered run actually executes all matching cases end-to-end through
`app.agent.Agent.handle_turn`.
"""
from __future__ import annotations

from tests_web.conftest import auth_headers, make_admin, signup_and_login


def _admin_client(client, email="eval_admin@example.com"):
    tokens = signup_and_login(client, email=email)
    make_admin(client, tokens)
    return tokens


def test_customer_cannot_access_evaluations(client):
    user = signup_and_login(client)
    resp = client.get("/admin/evaluations", headers=auth_headers(user))
    assert resp.status_code == 403


def test_unauthenticated_is_401(client):
    resp = client.get("/admin/evaluations")
    assert resp.status_code == 401


def test_run_evaluation_with_mock_llm(client):
    admin = _admin_client(client)
    resp = client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin))
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "completed"
    assert body["total_cases"] > 0
    assert body["passed_cases"] + body["failed_cases"] == body["total_cases"]
    assert body["category_breakdown"]
    assert body["run_number"] == 1


def test_run_numbers_increment(client):
    admin = _admin_client(client)
    first = client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin)).json()
    second = client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin)).json()
    assert second["run_number"] == first["run_number"] + 1


def test_run_with_subset_of_case_ids(client):
    admin = _admin_client(client)
    resp = client.post(
        "/admin/evaluations/run", json={"use_mock_llm": True, "case_ids": ["standard-return-window"]}, headers=auth_headers(admin)
    )
    assert resp.status_code == 202
    assert resp.json()["total_cases"] == 1


def test_run_with_unknown_case_id_fails_cleanly(client):
    admin = _admin_client(client)
    resp = client.post(
        "/admin/evaluations/run", json={"use_mock_llm": True, "case_ids": ["not-a-real-case"]}, headers=auth_headers(admin)
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"]


def test_list_runs(client):
    admin = _admin_client(client)
    client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin))
    listing = client.get("/admin/evaluations", headers=auth_headers(admin))
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1


def test_get_run_detail_includes_per_case_results(client):
    admin = _admin_client(client)
    run = client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin)).json()
    detail = client.get(f"/admin/evaluations/{run['id']}", headers=auth_headers(admin))
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["results"]) == body["total_cases"]
    assert "passed" in body["results"][0]
    assert "checks" in body["results"][0]


def test_get_single_case_result(client):
    admin = _admin_client(client)
    run = client.post(
        "/admin/evaluations/run", json={"use_mock_llm": True, "case_ids": ["standard-return-window"]}, headers=auth_headers(admin)
    ).json()
    resp = client.get(f"/admin/evaluations/{run['id']}/results/standard-return-window", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["case_id"] == "standard-return-window"


def test_case_result_not_in_run_is_404(client):
    admin = _admin_client(client)
    run = client.post(
        "/admin/evaluations/run", json={"use_mock_llm": True, "case_ids": ["standard-return-window"]}, headers=auth_headers(admin)
    ).json()
    resp = client.get(f"/admin/evaluations/{run['id']}/results/some-other-case", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_run_not_found_is_404(client):
    admin = _admin_client(client)
    resp = client.get("/admin/evaluations/00000000-0000-0000-0000-000000000000", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_compare_two_runs(client):
    admin = _admin_client(client)
    run_a = client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin)).json()
    run_b = client.post("/admin/evaluations/run", json={"use_mock_llm": True}, headers=auth_headers(admin)).json()

    resp = client.get("/admin/evaluations/compare", params={"run_a": run_a["id"], "run_b": run_b["id"]}, headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_a"]["id"] == run_a["id"]
    assert body["run_b"]["id"] == run_b["id"]
    assert isinstance(body["by_category"], dict)
    assert len(body["by_category"]) > 0

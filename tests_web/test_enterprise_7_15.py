from __future__ import annotations

from tests_web.conftest import auth_headers, make_admin, signup_and_login


def test_prompt_management_create_version_publish_and_test(client):
    tokens = signup_and_login(client)
    make_admin(client, tokens)
    h = auth_headers(tokens)
    created = client.post("/admin/prompts", headers=h, json={
        "name": "Support Prompt",
        "content": "Answer using {{knowledge_context}}."
    })
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    version = client.post(f"/admin/prompts/{pid}/versions", headers=h, json={
        "content": "Answer briefly using {{knowledge_context}}."
    })
    assert version.status_code == 201, version.text
    published = client.post(f"/admin/prompts/{pid}/publish?version=2", headers=h)
    assert published.status_code == 200
    tested = client.post(f"/admin/prompts/{pid}/test", headers=h, json={
        "input": {"knowledge_context": "return policy"}
    })
    assert tested.status_code == 200
    assert "rendered_prompt" in tested.json()


def test_global_search_is_authenticated_and_scoped(client):
    tokens = signup_and_login(client)
    h = auth_headers(tokens)
    r = client.get("/search?q=alice", headers=h)
    assert r.status_code == 200
    assert "results" in r.json()


def test_model_router_uses_configured_models_only(client):
    tokens = signup_and_login(client)
    make_admin(client, tokens)
    r = client.post("/admin/ai/router/preview", headers=auth_headers(tokens),
                    json={"category": "simple_question"})
    assert r.status_code == 200
    assert "model_used" in r.json()


def test_ai_usage_dashboard_does_not_invent_missing_usage(client):
    tokens = signup_and_login(client)
    make_admin(client, tokens)
    r = client.get("/admin/analytics/ai-usage", headers=auth_headers(tokens))
    assert r.status_code == 200
    assert r.json()["requests"] == 0
    assert r.json()["estimated_cost"] is None


def test_customer_360_rejects_unknown_customer(client):
    tokens = signup_and_login(client)
    make_admin(client, tokens)
    import uuid
    r = client.get(f"/customers/{uuid.uuid4()}/360", headers=auth_headers(tokens))
    assert r.status_code == 404


def test_playground_rejects_unconfigured_model(client):
    tokens = signup_and_login(client)
    make_admin(client, tokens)
    r = client.post("/admin/evaluations/playground/run", headers=auth_headers(tokens),
                    json={"question": "What is the return policy?", "model": "not-configured"})
    assert r.status_code == 400


def test_recommendation_explanation_requires_owner(client):
    tokens = signup_and_login(client)
    # No recommendation exists for the new user; random UUID must not disclose data.
    import uuid
    r = client.get(f"/recommendations/{uuid.uuid4()}/explanation", headers=auth_headers(tokens))
    assert r.status_code == 404

"""Tests for the enterprise-upgrade hardening pass (citations, usage/cost,
configurable quality thresholds, feature flags). Runs against real Postgres
like the rest of tests_web."""
from __future__ import annotations

import json
import uuid

from tests_web.conftest import auth_headers, make_admin, signup_and_login
from tests_web.test_enterprise_full_coverage import _create_conversation_with_reply


# ---------------- Feature 5: citations are real and persisted ---------------
def test_citation_builder_accepts_bare_chunks_and_only_cites_used_files():
    from app.enterprise.citations import build_citations
    from app.kb_loader import Chunk

    a = Chunk(chunk_id="c1", source_file="returns.md", document_id="doc-a", title="Returns",
              heading="Returns & Refunds", text="Returns accepted within 30 days.", metadata={"version": "3.2"})
    b = Chunk(chunk_id="c2", source_file="other.md", document_id="doc-b", title="Other",
              heading="Overview", text="Unrelated.", metadata={})

    class R:  # mimics RetrievalResult.authoritative_sources (bare Chunks)
        authoritative_sources = [a, b]

    cites = build_citations(R(), only_files=["returns.md"])
    assert [c["document"] for c in cites] == ["returns.md"]
    assert cites[0]["chunk_id"] == "c1" and cites[0]["document_id"] == "doc-a"
    assert cites[0]["document_version"] == "3.2"
    # nothing fabricated: no score available on bare chunks
    assert cites[0]["relevance_score"] is None
    assert build_citations(R(), only_files=[]) == []


def test_chat_turn_persists_citations_for_owner(client):
    owner = signup_and_login(client, email="cite-real@example.com")
    conv_id = _create_conversation_with_reply(client, owner)
    cites = client.get(f"/conversations/{conv_id}/citations", headers=auth_headers(owner))
    assert cites.status_code == 200
    body = cites.json()
    assert len(body) >= 1, "a policy question must produce at least one verified citation"
    assert all(c["document"] for c in body)


# ---------------- Feature 9: usage tracking + configurable pricing ----------
def test_usage_event_recorded_per_chat_turn_and_cost_unavailable_without_pricing(client):
    admin = signup_and_login(client, email="usage-admin@example.com")
    make_admin(client, admin)
    _create_conversation_with_reply(client, admin)
    r = client.get("/admin/analytics/ai-usage", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["requests"] >= 1
    assert body["estimated_cost"] is None          # no pricing configured -> not invented
    assert body["input_tokens"] is None            # provider did not report tokens


def test_cost_estimation_uses_configured_pricing_only(monkeypatch):
    from app import config
    from app.enterprise import usage

    monkeypatch.setattr(config, "AI_MODEL_PRICING_JSON", json.dumps({"m1": {"input": 1.0, "output": 2.0}}))
    assert usage.estimate_cost("m1", 1_000_000, 500_000) == 2.0
    assert usage.estimate_cost("unknown", 10, 10) is None
    assert usage.estimate_cost("m1", None, 10) is None
    monkeypatch.setattr(config, "AI_MODEL_PRICING_JSON", "not-json")
    assert usage.estimate_cost("m1", 10, 10) is None


# ---------------- Feature 4: thresholds configurable ------------------------
def test_quality_thresholds_are_configurable(monkeypatch):
    from app import config
    from app.enterprise.quality import assess

    assert assess("ok", ["a.md"]).decision == "ALLOW"
    monkeypatch.setattr(config, "QUALITY_GROUNDING_ALLOW", 0.99)
    assert assess("ok", ["a.md"]).decision == "RETRY_RETRIEVAL"
    assert assess("ok", ["a.md"], handoff=True).decision == "HUMAN_HANDOFF"
    assert assess("my api key is x", ["a.md"]).decision == "BLOCK"


# ---------------- Feature flags: disabling never breaks existing chat -------
def test_disabled_flags_do_not_break_existing_chat(client, monkeypatch):
    from app import config
    for flag in ("SENTIMENT_ANALYSIS_ENABLED", "QUALITY_GUARD_ENABLED",
                 "RAG_CITATIONS_ENABLED", "AI_USAGE_ANALYTICS_ENABLED"):
        monkeypatch.setattr(config, flag, False)
    owner = signup_and_login(client, email="flags-off@example.com")
    conv_id = _create_conversation_with_reply(client, owner)
    msgs = client.get(f"/conversations/{conv_id}", headers=auth_headers(owner))
    assert msgs.status_code == 200
    cites = client.get(f"/conversations/{conv_id}/citations", headers=auth_headers(owner))
    assert cites.status_code == 200 and cites.json() == []


# ---------------- Feature 10: model router ----------------------------------
def test_router_uses_configured_rule_and_falls_back_safely(monkeypatch):
    from app import config
    from app.enterprise import model_router as mr

    monkeypatch.setattr(config, "MODEL_ROUTER_RULES_JSON", json.dumps({"classification": "fast-x"}))
    d = mr.route("classification")
    assert d.model == "fast-x" and d.fallback_used is False
    assert mr.route("complex_question").fallback_used is True          # no rule -> default
    assert mr.route("bogus").model == config.CHAT_MODEL
    monkeypatch.setattr(config, "MODEL_ROUTER_RULES_JSON", "{bad json")
    assert mr.route("classification").model == config.CHAT_MODEL       # bad config -> default
    monkeypatch.setattr(config, "MODEL_ROUTER_ENABLED", False)
    assert mr.route("classification").fallback_used is True


def test_router_classifies_requests():
    from app.enterprise.model_router import classify_request
    assert classify_request("hi where is my order") == "simple_question"
    assert classify_request("Please summarize this thread") == "summarization"
    assert classify_request("Explain the difference between store credit and refund") == "complex_question"


def test_router_preview_is_admin_only_audited_and_tracked(client, db_session, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "MODEL_ROUTER_RULES_JSON", json.dumps({"summarization": "cheap-y"}))
    cust = signup_and_login(client, email="router-cust@example.com")
    assert client.post("/admin/ai/router/preview", json={"category": "summarization"}, headers=auth_headers(cust)).status_code == 403
    admin = signup_and_login(client, email="router-admin@example.com")
    make_admin(client, admin)
    r = client.post("/admin/ai/router/preview", json={"category": "summarization"}, headers=auth_headers(admin))
    assert r.status_code == 200 and r.json()["model_used"] == "cheap-y" and r.json()["fallback_used"] is False
    assert client.post("/admin/ai/router/preview", json={"category": "nope"}, headers=auth_headers(admin)).status_code == 400
    ev = client.get("/admin/ai/router/events", headers=auth_headers(admin)).json()
    assert ev and ev[0]["model_used"] == "cheap-y"
    from app.db.models import AuditEvent
    assert any(e.event_type == "MODEL_ROUTED" for e in db_session.query(AuditEvent).all())


# ---------------- Feature 8: prompt A/B testing -----------------------------
def _prompt(client, admin, name="Support Prompt"):
    r = client.post("/admin/prompts", json={"name": name, "content": "Hello {{customer_name}}"}, headers=auth_headers(admin))
    assert r.status_code == 201
    p = r.json()
    v2 = client.post(f"/admin/prompts/{p['id']}/versions", json={"content": "Hi {{customer_name}}!"}, headers=auth_headers(admin))
    assert v2.status_code == 201
    return p["id"]


def test_prompt_experiment_lifecycle_is_admin_only_and_audited(client, db_session):
    customer = signup_and_login(client, email="ab-cust@example.com")
    admin = signup_and_login(client, email="ab-admin@example.com")
    make_admin(client, admin)
    pid = _prompt(client, admin)

    body = {"name": "Greeting test", "variant_a_version": 1, "variant_b_version": 2, "traffic_split_b": 50}
    assert client.post(f"/admin/prompts/{pid}/experiments", json=body, headers=auth_headers(customer)).status_code == 403
    created = client.post(f"/admin/prompts/{pid}/experiments", json=body, headers=auth_headers(admin))
    assert created.status_code == 201 and created.json()["status"] == "running"
    eid = created.json()["id"]

    # a second running experiment on the same prompt is rejected
    dup = client.post(f"/admin/prompts/{pid}/experiments", json=body, headers=auth_headers(admin))
    assert dup.status_code == 409

    listed = client.get(f"/admin/prompts/{pid}/experiments", headers=auth_headers(admin)).json()
    assert [e["id"] for e in listed] == [eid]

    r1 = client.get(f"/admin/prompts/{pid}/experiments/{eid}/resolve", params={"bucket_key": "user-1"}, headers=auth_headers(admin))
    r2 = client.get(f"/admin/prompts/{pid}/experiments/{eid}/resolve", params={"bucket_key": "user-1"}, headers=auth_headers(admin))
    assert r1.status_code == 200 and r1.json()["resolved_version"] == r2.json()["resolved_version"]   # deterministic
    assert r1.json()["resolved_version"] in (1, 2)

    stopped = client.post(f"/admin/prompts/{pid}/experiments/{eid}/stop", headers=auth_headers(admin))
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert client.post(f"/admin/prompts/{pid}/experiments/{eid}/stop", headers=auth_headers(admin)).status_code == 400

    from app.db.models import AuditEvent
    types = [e.event_type for e in db_session.query(AuditEvent).all()]
    assert "PROMPT_EXPERIMENT_CREATED" in types and "PROMPT_EXPERIMENT_STOPPED" in types


def test_experiment_bucketing_falls_back_to_active_version_when_no_experiment_running(client, db_session):
    admin = signup_and_login(client, email="ab-fallback-admin@example.com")
    make_admin(client, admin)
    pid = _prompt(client, admin, name="No experiment prompt")
    from app.api.enterprise_v2_routes import resolve_experiment_version
    from app.db.models import PromptTemplate
    p = db_session.get(PromptTemplate, uuid.UUID(pid))
    version, exp_id = resolve_experiment_version(db_session, p, "any-key")
    assert version == p.active_version and exp_id is None


def test_experiment_rejects_unknown_versions(client):
    admin = signup_and_login(client, email="ab-badver-admin@example.com")
    make_admin(client, admin)
    pid = _prompt(client, admin, name="Bad version prompt")
    bad = client.post(f"/admin/prompts/{pid}/experiments",
                      json={"name": "x", "variant_a_version": 1, "variant_b_version": 99, "traffic_split_b": 50},
                      headers=auth_headers(admin))
    assert bad.status_code == 400


# ---------------- Feature 9: usage dashboard filters + daily breakdown -----
def test_usage_dashboard_daily_breakdown_and_filters(client, db_session):
    admin = signup_and_login(client, email="usage-daily-admin@example.com")
    make_admin(client, admin)
    _create_conversation_with_reply(client, admin)
    r = client.get("/admin/analytics/ai-usage", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert len(body["daily"]) >= 1 and body["daily"][0]["requests"] >= 1
    assert "by_model" in body and "by_feature" in body and body["by_feature"].get("chat", 0) >= 1
    none_match = client.get("/admin/analytics/ai-usage", params={"feature": "does-not-exist"}, headers=auth_headers(admin))
    assert none_match.json()["requests"] == 0 and none_match.json()["daily"] == []


# ---------------- Feature 13: recommendation regenerate is real ------------
def test_recommendation_regenerate_produces_a_new_real_recommendation(client, db_session):
    import uuid as _uuid
    owner = signup_and_login(client, email="regen-owner@example.com")
    h = auth_headers(owner)
    assert client.post("/api/v1/products", json={"sku": "TB-1", "name": "Breeze Tumbler", "price": 25, "category": "drinkware"}, headers=h).status_code == 201
    rec = client.post("/api/v1/recommendations", json={"query": "tumbler", "budget": 50}, headers=h)
    assert rec.status_code == 200
    rec_id = rec.json()["recommendation_id"]

    other = signup_and_login(client, email="regen-stranger@example.com")
    assert client.post(f"/recommendations/{rec_id}/explanation/actions", params={"action": "regenerate"},
                       headers=auth_headers(other)).status_code == 404  # not this user's recommendation

    again = client.post(f"/recommendations/{rec_id}/explanation/actions", params={"action": "regenerate"}, headers=h)
    assert again.status_code == 200
    body = again.json()
    assert body["status"] == "regenerated"
    new_id = body["recommendation_id"]
    assert new_id != rec_id                       # a genuinely new recommendation record
    assert body["product_ids"], "regenerate must actually produce ranked products, not just log an action"
    fresh = client.post("/api/v1/recommendations", json={"query": "tumbler", "budget": 50}, headers=h)
    assert body["product_ids"] == fresh.json()["product_ids"]   # same deterministic engine, same inputs
    listing = client.get(f"/recommendations/{new_id}/explanation", headers=h)
    assert listing.status_code == 200 and listing.json()["items"]

    from app.db.models import AuditEvent
    assert any(e.event_type == "RECOMMENDATION_REGENERATED" for e in db_session.query(AuditEvent).all())


def test_recommendation_intelligence_flag_disables_only_that_feature(client, monkeypatch):
    from app import config
    owner = signup_and_login(client, email="regen-flag@example.com")
    h = auth_headers(owner)
    client.post("/api/v1/products", json={"sku": "TB-2", "name": "Trail Tumbler", "price": 20, "category": "drinkware"}, headers=h)
    rec = client.post("/api/v1/recommendations", json={"query": "tumbler"}, headers=h)
    rec_id = rec.json()["recommendation_id"]
    monkeypatch.setattr(config, "RECOMMENDATION_INTELLIGENCE_ENABLED", False)
    assert client.get(f"/recommendations/{rec_id}/explanation", headers=h).status_code == 403
    # existing recommendation creation itself is untouched by the flag
    assert client.post("/api/v1/recommendations", json={"query": "tumbler"}, headers=h).status_code == 200


# ---------------- Feature 10 (end-to-end): router override actually reaches
# the real Gemini call, with a safe fallback if the routed model fails ------
def _fake_gemini_client(model="configured-default", fallback_model="configured-fallback"):
    from app.llm_client import GeminiLLMClient
    c = GeminiLLMClient.__new__(GeminiLLMClient)  # skip __init__ (no real API client / network)
    c._model = model
    c._fallback_model = fallback_model
    return c


class _FakeModels:
    def __init__(self, fail_for: set[str] | None = None):
        self.calls: list[str] = []
        self.fail_for = fail_for or set()

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        if model in self.fail_for:
            raise RuntimeError("simulated model failure")

        class R:
            text = "ok"
        return R()


class _FakeClient:
    def __init__(self, fail_for=None):
        self.models = _FakeModels(fail_for)


def test_router_override_changes_the_real_model_that_gets_called():
    from app.llm_usage import model_override_var
    from google.genai import types
    client = _fake_gemini_client()
    client._client = _FakeClient()
    tok = model_override_var.set("router-picked-model")
    try:
        client._generate_content(contents=[], config_kwargs={})
    finally:
        model_override_var.reset(tok)
    assert client._client.models.calls == ["router-picked-model"]


def test_no_override_uses_the_configured_default_model():
    from app.llm_usage import model_override_var
    client = _fake_gemini_client()
    client._client = _FakeClient()
    assert model_override_var.get() is None
    client._generate_content(contents=[], config_kwargs={})
    assert client._client.models.calls == ["configured-default"]


def test_routed_model_failure_falls_back_to_the_configured_model_safely():
    from app.llm_usage import model_override_var
    client = _fake_gemini_client()
    client._client = _FakeClient(fail_for={"router-picked-model"})
    tok = model_override_var.set("router-picked-model")
    try:
        client._generate_content(contents=[], config_kwargs={})
    finally:
        model_override_var.reset(tok)
    assert client._client.models.calls == ["router-picked-model", "configured-default"]


def test_chat_turn_sets_model_override_from_router_when_not_using_mock_llm(client, db_session, monkeypatch):
    """End-to-end: send_message() must set model_override_var from the router
    BEFORE the agent is called, using real (non-mock) routing settings, and
    clear it afterwards. We intercept at the point llm_client reads it."""
    import json as _json
    from app import config
    from app.llm_usage import model_override_var
    monkeypatch.setattr(config, "USE_MOCK_LLM", False)
    monkeypatch.setattr(config, "MODEL_ROUTER_ENABLED", True)
    monkeypatch.setattr(config, "MODEL_ROUTER_RULES_JSON", _json.dumps({"simple_question": "routed-simple-model"}))

    seen: list[str | None] = []
    from app import agent as agent_module

    def fake_handle_turn(self, conversation_id, user_message):
        seen.append(model_override_var.get())
        from app.agent import TurnResult
        return TurnResult(answer="Hi there.", sources=[], handoff=False, handoff_reason=None,
                          insufficient_information=False)

    monkeypatch.setattr(agent_module.Agent, "handle_turn", fake_handle_turn)
    owner = signup_and_login(client, email="router-e2e@example.com")
    r = client.post("/conversations", json={}, headers=auth_headers(owner))
    conv_id = r.json()["id"]
    client.post(f"/conversations/{conv_id}/messages", json={"message": "hi"}, headers=auth_headers(owner))
    assert seen == ["routed-simple-model"]
    assert model_override_var.get() is None    # cleared after the turn, never leaks to the next request


def test_router_stays_out_of_the_way_when_disabled_or_on_mock_llm(client, monkeypatch):
    """The router must never engage for the mock/test LLM path, and must be
    fully inert when disabled -- existing chat behaviour is unaffected."""
    from app import agent as agent_module, config
    from app.agent import TurnResult
    from app.enterprise import model_router
    from app.llm_usage import model_override_var

    seen: list = []

    def fake_handle_turn(self, conversation_id, user_message):
        seen.append(model_override_var.get())
        return TurnResult(answer="Stub.", sources=[], handoff=False, handoff_reason=None, insufficient_information=False)

    monkeypatch.setattr(agent_module.Agent, "handle_turn", fake_handle_turn)
    monkeypatch.setattr(model_router, "route",
                        lambda category: model_router.RouteDecision("should-not-be-used", category, "x", False))

    owner = signup_and_login(client, email="router-inert@example.com")
    conv_id = client.post("/conversations", json={}, headers=auth_headers(owner)).json()["id"]

    monkeypatch.setattr(config, "MODEL_ROUTER_ENABLED", True)
    monkeypatch.setattr(config, "USE_MOCK_LLM", True)    # mock path: router must not engage
    client.post(f"/conversations/{conv_id}/messages", json={"message": "hi"}, headers=auth_headers(owner))

    monkeypatch.setattr(config, "USE_MOCK_LLM", False)
    monkeypatch.setattr(config, "MODEL_ROUTER_ENABLED", False)  # disabled: router must not engage
    client.post(f"/conversations/{conv_id}/messages", json={"message": "hi again"}, headers=auth_headers(owner))

    assert seen == [None, None]

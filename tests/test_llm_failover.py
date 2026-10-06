
from __future__ import annotations

import sys
import types as pytypes

import pytest

from app import config
from app.agent import Agent
from app.llm_client import (
    GeminiLLMClient,
    LLMAvailabilityError,
)
from app.llm_usage import UsageCollector, usage_collector_var


class TransientError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"transient {status_code}")


class FakeResponse:
    usage_metadata = None


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


def _client(primary="primary", fallback="fallback", outcomes=()):
    client = GeminiLLMClient.__new__(GeminiLLMClient)
    client._client = FakeClient(outcomes)
    client._model = primary
    client._fallback_model = fallback
    return client


@pytest.fixture
def fake_google_types(monkeypatch):
    """Provide only the tiny SDK surface used by _generate_content."""
    google = pytypes.ModuleType("google")
    genai = pytypes.ModuleType("google.genai")
    types = pytypes.SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: kwargs
    )
    genai.types = types
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


@pytest.fixture
def resilience_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_MODEL", 2)
    monkeypatch.setattr(config, "LLM_RETRY_INITIAL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(config, "LLM_RETRY_MAX_DELAY_SECONDS", 0.0)


def test_transient_failure_retries_same_model_before_success(
    fake_google_types,
    resilience_config,
):
    client = _client(
        outcomes=[TransientError(503), FakeResponse()]
    )
    collector = UsageCollector()
    token = usage_collector_var.set(collector)
    try:
        result = client._generate_content(
            contents=[],
            config_kwargs={},
        )
    finally:
        usage_collector_var.reset(token)

    assert isinstance(result, FakeResponse)
    assert client._client.models.calls == ["primary", "primary"]
    assert collector.attempts == 2
    assert collector.retry_count == 1
    assert collector.fallback_used is False
    assert collector.transient_errors == 1


def test_primary_exhaustion_fails_over_to_secondary_model(
    fake_google_types,
    resilience_config,
):
    client = _client(
        outcomes=[
            TransientError(503),
            TransientError(503),
            FakeResponse(),
        ]
    )
    collector = UsageCollector()
    token = usage_collector_var.set(collector)
    try:
        result = client._generate_content(
            contents=[],
            config_kwargs={},
        )
    finally:
        usage_collector_var.reset(token)

    assert isinstance(result, FakeResponse)
    assert client._client.models.calls == [
        "primary",
        "primary",
        "fallback",
    ]
    assert collector.attempts == 3
    assert collector.retry_count == 1
    assert collector.fallback_used is True
    assert collector.fallback_models == ["fallback"]
    assert collector.transient_errors == 2


def test_routed_model_failover_chain_is_routed_then_primary_then_fallback(
    fake_google_types,
    resilience_config,
    monkeypatch,
):
    client = _client(
        primary="configured-primary",
        fallback="configured-fallback",
        outcomes=[
            TransientError(503),
            TransientError(503),
            TransientError(503),
            TransientError(503),
            FakeResponse(),
        ],
    )
    # _generate_content reads the ContextVar directly, so set it normally
    # rather than relying on the patched getter.
    from app.llm_usage import model_override_var

    override = model_override_var.set("routed-model")
    try:
        result = client._generate_content(
            contents=[],
            config_kwargs={},
        )
    finally:
        model_override_var.reset(override)

    assert isinstance(result, FakeResponse)
    assert client._client.models.calls == [
        "routed-model",
        "routed-model",
        "configured-primary",
        "configured-primary",
        "configured-fallback",
    ]


def test_all_models_exhausted_raises_safe_availability_error(
    fake_google_types,
    resilience_config,
):
    client = _client(
        outcomes=[
            TransientError(503),
            TransientError(503),
            TransientError(503),
            TransientError(503),
        ]
    )

    with pytest.raises(LLMAvailabilityError) as exc_info:
        client._generate_content(
            contents=[],
            config_kwargs={},
        )

    error = exc_info.value
    assert error.status_code == 503
    assert error.attempted_models == ["primary", "fallback"]
    assert error.attempts == 4
    assert client._client.models.calls == [
        "primary",
        "primary",
        "fallback",
        "fallback",
    ]


def test_non_transient_error_is_not_retried_or_failed_over(
    fake_google_types,
    resilience_config,
):
    client = _client(
        outcomes=[TransientError(401)]
    )

    with pytest.raises(TransientError):
        client._generate_content(
            contents=[],
            config_kwargs={},
        )

    assert client._client.models.calls == ["primary"]


def test_agent_turn_converts_total_provider_outage_to_human_handoff():
    class EmptyRetrieval:
        hits = []
        authoritative_sources = []
        conflict_detected = False
        conflict_files = []

    class RetrieverStub:
        def retrieve(self, query):
            return EmptyRetrieval()

    class OrderStub:
        def lookup(self, order_id):
            return {"found": False, "error": "not_found"}

    class FailingLLM:
        def generate_structured_answer(self, system_instruction, contents):
            raise LLMAvailabilityError(
                attempted_models=["primary", "fallback"],
                attempts=4,
            )

        def decide_tool_call(self, system_instruction, contents):
            raise AssertionError("not used by the deterministic order path")

    agent = Agent(
        retriever=RetrieverStub(),
        order_tool=OrderStub(),
        llm_client=FailingLLM(),
        kb_dir=config.KB_DIR,
    )

    result = agent.handle_turn(
        "test-failover-session",
        "What is your return policy?",
    )

    assert result.handoff is True
    assert result.handoff_reason
    assert "AI service" in result.handoff_reason
    assert "temporarily unavailable" in result.handoff_reason

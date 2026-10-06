from __future__ import annotations

import pytest

from app.agent import Agent
from app.llm_client import MockLLMClient
from app.logging_utils import TraceLogger
from app.session import SessionStore
from tests.conftest import ORDERS_PATH


@pytest.fixture()
def agent(retriever, tmp_path):
    from app.orders import OrderLookupTool

    return Agent(
        retriever,
        OrderLookupTool(ORDERS_PATH),
        MockLLMClient(),
        session_store=SessionStore(),
        trace_logger=TraceLogger(tmp_path / "trace.jsonl"),
    )


def test_order_not_found_forces_handoff_regardless_of_model(agent):
    result = agent.handle_turn("s1", "Please check ORD-9999.")
    assert result.handoff is True
    assert "not" in (result.handoff_reason or "").lower() or "could not" in (result.handoff_reason or "").lower()


def test_valid_order_lookup_does_not_force_handoff(agent):
    result = agent.handle_turn("s2", "Where is ORD-1007 and when should it arrive?")
    assert result.handoff is False


def test_exception_status_forces_handoff(agent):
    result = agent.handle_turn("s3", "Where is my order ORD-1010?")
    assert result.handoff is True


def test_missing_order_id_never_executes_a_real_lookup(agent):
    result = agent.handle_turn("s4", "Where is my order?")
    trace = agent._trace.read_all()[-1]  # noqa: SLF001
    for tc in trace["tool_calls"]:
        assert tc["result"].get("found") is not True


def test_deterministic_guard_blocks_tool_call_with_empty_order_id(retriever, tmp_path):
    """Even if the model *tries* to call order_lookup with a blank id (bad
    tool-call arguments), app/agent.py must never let that reach a real
    lookup -- it should ask for the id instead. Uses a tiny stub LLM rather
    than MockLLMClient because MockLLMClient's own heuristic never attempts
    an empty-id call in the first place."""
    from app.llm_client import ToolCallRequest, ToolDecision
    from app.orders import OrderLookupTool
    from app.schemas import AgentAnswer

    class BadToolCallLLM:
        def decide_tool_call(self, system_instruction, contents):
            return ToolDecision(tool_calls=[ToolCallRequest(name="order_lookup", arguments={"order_id": ""})], raw_text=None)

        def generate_structured_answer(self, system_instruction, contents):
            return AgentAnswer(answer="Could you share your order ID?", cited_document_ids=[],
                                insufficient_information=False, handoff_recommended=False, handoff_reason=None)

    agent = Agent(retriever, OrderLookupTool(ORDERS_PATH), BadToolCallLLM(),
                  session_store=SessionStore(), trace_logger=TraceLogger(tmp_path / "trace2.jsonl"))
    result = agent.handle_turn("s7", "Where is my order?")
    trace = agent._trace.read_all()[-1]
    # Order lookup is now deterministic: without an ID, no lookup is
    # executed at all, regardless of what an LLM implementation might try.
    assert trace["tool_calls"] == []
    assert result.handoff is False
    assert "order id" in result.answer.lower()


def test_source_conflict_forces_handoff(agent):
    result = agent.handle_turn("s5", "Can I put the entire Breeze Tumbler in the dishwasher?")
    assert result.handoff is True
    assert set(result.sources) >= {"11-product-care.md", "12-breeze-tumbler-product-card.md"}


def test_sessions_do_not_leak_order_context_into_each_other(agent):
    agent.handle_turn("session-a", "Where is ORD-1007 and when should it arrive?")
    session_a = agent._sessions.get_or_create("session-a")  # noqa: SLF001
    session_b = agent._sessions.get_or_create("session-b")  # noqa: SLF001
    assert session_a.last_order_id == "ORD-1007"
    assert session_b.last_order_id is None


def test_multiturn_follow_up_reuses_order_id_from_session_context(agent):
    agent.handle_turn("s6", "Where is ORD-1007 and when should it arrive?")
    session = agent._sessions.get_or_create("s6")  # noqa: SLF001
    assert session.last_order_id == "ORD-1007"
    instr = agent._build_system_instruction("", session.last_order_id, False, [])  # noqa: SLF001
    assert "ORD-1007" in instr


def test_resolve_sources_ignores_hallucinated_citations(agent):
    from app.kb_loader import Chunk

    fake_authoritative = [
        Chunk(chunk_id="a", source_file="01-returns-policy-current.md", document_id="RET-2026-01",
              title="Returns Policy", heading="x", text="", metadata={"status": "active", "policy_authority": "official"}),
    ]
    resolved = agent._resolve_sources(["02-returns-policy-legacy.md"], fake_authoritative)  # noqa: SLF001
    assert resolved == ["01-returns-policy-current.md"]


def test_transient_llm_outage_still_answers_from_order_data(agent):
    class TransientLLM:
        def generate_structured_answer(self, system_instruction, contents):
            exc = RuntimeError("temporary overload")
            exc.status_code = 503
            raise exc

    agent._llm = TransientLLM()  # noqa: SLF001
    result = agent.handle_turn("s8", "Where is ORD-1007?")
    assert result.handoff is False
    assert "ORD-1007" in result.answer
    assert "shipped" in result.answer.lower()
    assert "UPS" in result.answer


def test_general_knowledge_questions_are_classified_as_general(agent):
    assert agent._looks_like_general_knowledge_question("What is photosynthesis?") is True
    assert agent._looks_like_general_knowledge_question("Explain gravity.") is True
    assert agent._looks_like_general_knowledge_question("What is Python?") is True
    assert agent._looks_like_general_knowledge_question("Where is my order?") is False
    assert agent._looks_like_general_knowledge_question("What is your return policy?") is False

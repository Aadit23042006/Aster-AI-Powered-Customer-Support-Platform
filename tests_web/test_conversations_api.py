from tests_web.conftest import auth_headers, signup_and_login

from app.llm_client import AgentAnswer, MockLLMClient


def test_create_list_and_get_conversation(client):
    user = signup_and_login(client)

    created = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    )

    assert created.status_code == 201

    conv_id = created.json()["id"]

    assert created.json()["title"] == "New conversation"

    listing = client.get(
        "/conversations",
        headers=auth_headers(user),
    ).json()

    assert any(c["id"] == conv_id for c in listing)

    fetched = client.get(
        f"/conversations/{conv_id}",
        headers=auth_headers(user),
    )

    assert fetched.status_code == 200


def test_rename_and_archive_conversation(client):
    user = signup_and_login(client)

    conv_id = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    ).json()["id"]

    renamed = client.patch(
        f"/conversations/{conv_id}",
        json={"title": "Return question"},
        headers=auth_headers(user),
    )

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Return question"

    archived = client.post(
        f"/conversations/{conv_id}/archive",
        headers=auth_headers(user),
    )

    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_delete_conversation_removes_it(client):
    user = signup_and_login(client)

    conv_id = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    ).json()["id"]

    deleted = client.delete(
        f"/conversations/{conv_id}",
        headers=auth_headers(user),
    )

    assert deleted.status_code == 204

    fetched = client.get(
        f"/conversations/{conv_id}",
        headers=auth_headers(user),
    )

    assert fetched.status_code == 404


def test_send_message_uses_existing_agent_and_persists_history(client):
    """
    Critical end-to-end test:

        authenticated request
            -> conversation
            -> EXISTING app.agent.Agent
            -> Mock LLM
            -> real retrieval
            -> persisted user + assistant messages
    """

    user = signup_and_login(client)

    conv_id = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    ).json()["id"]

    resp = client.post(
        f"/conversations/{conv_id}/messages",
        json={
            "message": "How long do I have to return a backpack?"
        },
        headers=auth_headers(user),
    )

    assert resp.status_code == 200

    body = resp.json()

    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["role"] == "assistant"
    assert isinstance(body["sources"], list)
    assert isinstance(body["handoff"], bool)

    history = client.get(
        f"/conversations/{conv_id}/messages",
        headers=auth_headers(user),
    ).json()

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"

    conv = client.get(
        f"/conversations/{conv_id}",
        headers=auth_headers(user),
    ).json()

    assert conv["title"] != "New conversation"


def test_multi_turn_conversation_keeps_context_across_requests(client):
    user = signup_and_login(client)

    conv_id = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    ).json()["id"]

    r1 = client.post(
        f"/conversations/{conv_id}/messages",
        json={
            "message": "What's your return policy?"
        },
        headers=auth_headers(user),
    )

    assert r1.status_code == 200

    r2 = client.post(
        f"/conversations/{conv_id}/messages",
        json={
            "message": "What about international orders?"
        },
        headers=auth_headers(user),
    )

    assert r2.status_code == 200

    history = client.get(
        f"/conversations/{conv_id}/messages",
        headers=auth_headers(user),
    ).json()

    assert [m["role"] for m in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_quality_guard_independently_intercepts_unsafe_llm_output(
    client,
    monkeypatch,
):
    """
    Test 4F-A — Unsafe LLM interception.

    Flow:

        unsafe LLM output
            -> Quality Guard
            -> BLOCK
            -> human_handoff fallback
            -> safe customer-facing response
            -> persisted quality trace
    """

    unsafe_marker = "SECRET_TEST_VALUE"

    def fake_generate_structured_answer(
        self,
        system_instruction,
        contents,
    ):
        return AgentAnswer(
            answer=(
                f"The internal secret is {unsafe_marker}. "
                "This content must never reach the customer."
            ),
            cited_document_ids=[],
            insufficient_information=True,
            handoff_recommended=False,
            handoff_reason=None,
        )

    monkeypatch.setattr(
        MockLLMClient,
        "generate_structured_answer",
        fake_generate_structured_answer,
    )

    user = signup_and_login(client)

    conv_id = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    ).json()["id"]

    response = client.post(
        f"/conversations/{conv_id}/messages",
        json={
            "message": "Tell me the internal secret."
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    body = response.json()

    assistant_content = body["assistant_message"]["content"]

    # Unsafe content must never reach the customer.
    assert unsafe_marker not in assistant_content

    assert (
        "couldn't provide that information safely"
        in assistant_content.lower()
    )

    # Quality Guard must force a human handoff.
    assert body["handoff"] is True

    # Verify persisted conversation history.
    history_response = client.get(
        f"/conversations/{conv_id}/messages",
        headers=auth_headers(user),
    )

    assert history_response.status_code == 200

    messages = history_response.json()

    assistant_messages = [
        message
        for message in messages
        if message["role"] == "assistant"
    ]

    assert assistant_messages

    persisted_answer = assistant_messages[-1]["content"]

    # Unsafe marker must also be absent from persisted response.
    assert unsafe_marker not in persisted_answer

    # Verify persisted Quality Guard trace.
    assistant_meta = (
        assistant_messages[-1].get("meta") or {}
    )

    quality_trace = (
        assistant_meta.get("quality_trace") or {}
    )

    assert quality_trace

    assert (
        quality_trace["initial_decision"]
        == "BLOCK"
    )

    assert (
        quality_trace["fallback_action"]
        == "human_handoff"
    )

    assert (
        quality_trace["final_decision"]
        == "HUMAN_HANDOFF"
    )


def test_quality_guard_retry_wider_retrieval(
    client,
    monkeypatch,
):
    """
    Test 4F-B — Actual retry / wider retrieval.

    Verifies the real conversation-service retry path:

        initial retrieval
            -> Quality Guard RETRY_RETRIEVAL
            -> wider retrieval
            -> Quality Guard reassessment
            -> ALLOW
            -> search_again fallback

    The LLM response is forced to be a normal, non-handoff
    response because the real retry branch requires:

        not result.handoff

    The actual conversation-service retry logic is still executed.
    """

    import app.services.conversation_service as conversation_service

    from app import config
    from app.enterprise.quality import QualityResult
    from app.retriever import RetrievalResult, Retriever

    # ---------------------------------------------------------
    # Create authenticated test user + conversation.
    # ---------------------------------------------------------

    user = signup_and_login(client)

    conv_id = client.post(
        "/conversations",
        json={},
        headers=auth_headers(user),
    ).json()["id"]

    # ---------------------------------------------------------
    # Expected retrieval configuration.
    # ---------------------------------------------------------

    expected_initial_top_k = config.TOP_K

    expected_retry_top_k = (
        config.TOP_K
        * max(
            1,
            config.QUALITY_RETRY_TOP_K_MULTIPLIER,
        )
    )

    assert expected_initial_top_k == 5
    assert expected_retry_top_k == 10

    # ---------------------------------------------------------
    # Force a normal, non-handoff LLM response.
    #
    # This allows the real retry branch to execute.
    # ---------------------------------------------------------

    def fake_generate_structured_answer(
        self,
        system_instruction,
        contents,
    ):
        return AgentAnswer(
            answer=(
                "Order status information can be checked "
                "using the customer's order details."
            ),
            cited_document_ids=[],
            insufficient_information=False,
            handoff_recommended=False,
            handoff_reason=None,
        )

    monkeypatch.setattr(
        MockLLMClient,
        "generate_structured_answer",
        fake_generate_structured_answer,
    )

    # ---------------------------------------------------------
    # Track every actual Retriever.retrieve() call.
    #
    # Do NOT patch Retriever.__init__.
    #
    # Initial retrieval may receive top_k=None.
    # The effective value is then self._top_k.
    # ---------------------------------------------------------

    retrieval_calls = []

    def fake_retrieve(
        self,
        query,
        top_k=None,
        filters=None,
    ):
        effective_top_k = (
            self._top_k
            if top_k is None
            else top_k
        )

        retrieval_calls.append(
            {
                "query": query,
                "requested_top_k": top_k,
                "effective_top_k": effective_top_k,
                "filters": filters,
            }
        )

        return RetrievalResult(
            hits=[],
            conflict_detected=False,
            conflict_files=[],
        )

    monkeypatch.setattr(
        Retriever,
        "retrieve",
        fake_retrieve,
    )

    # ---------------------------------------------------------
    # Force deterministic Quality Guard behavior.
    #
    # First assessment:
    #     RETRY_RETRIEVAL
    #
    # Second assessment:
    #     ALLOW
    # ---------------------------------------------------------

    quality_calls = []

    def fake_assess(
        answer,
        sources,
        handoff,
        *,
        eligible=True,
        question=None,
        evidence=None,
        retrieval_score=None,
        allow_general_knowledge=False,
        **kwargs,
    ):
        """Deterministic Quality Guard mock.

        The production `assess()` function currently accepts
        `allow_general_knowledge`. Keep this mock compatible with that
        interface so the test exercises the real retry path instead of
        failing because of a stale mock signature.

        `**kwargs` also keeps this test resilient to future optional
        Quality Guard keyword arguments.
        """

        quality_calls.append(
            {
                "answer": answer,
                "sources": list(sources or []),
                "handoff": handoff,
                "eligible": eligible,
                "question": question,
                "evidence": list(evidence or []),
                "retrieval_score": retrieval_score,
                "allow_general_knowledge": (
                    allow_general_knowledge
                ),
                "extra_kwargs": kwargs,
            }
        )

        if len(quality_calls) == 1:
            return QualityResult(
                decision="RETRY_RETRIEVAL",
                grounding_score=0.40,
                policy_check="PASS",
                pii_check="PASS",
                confidence="LOW",
                retrieval_score=retrieval_score,
                relevance_score=0.0,
                details={
                    "test": "forced_initial_retry",
                },
            )

        return QualityResult(
            decision="ALLOW",
            grounding_score=0.95,
            policy_check="PASS",
            pii_check="PASS",
            confidence="HIGH",
            retrieval_score=retrieval_score,
            relevance_score=1.0,
            details={
                "test": "forced_retry_success",
            },
        )

    monkeypatch.setattr(
        conversation_service,
        "assess",
        fake_assess,
    )

    # ---------------------------------------------------------
    # Execute the REAL conversation API.
    # ---------------------------------------------------------

    response = client.post(
        f"/conversations/{conv_id}/messages",
        json={
            "message": "How do I check my order status?"
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200

    body = response.json()

    # ---------------------------------------------------------
    # Verify actual retrieval behavior.
    # ---------------------------------------------------------

    assert len(retrieval_calls) == 2, (
        "Expected exactly two retrieval calls: "
        "initial retrieval and one wider retry retrieval."
    )

    first_retrieval = retrieval_calls[0]
    second_retrieval = retrieval_calls[1]

    # Initial retrieval effective top_k must be 5.
    assert (
        first_retrieval["effective_top_k"]
        == expected_initial_top_k
    )

    # Retry must explicitly request 10.
    assert (
        second_retrieval["requested_top_k"]
        == expected_retry_top_k
    )

    assert (
        second_retrieval["effective_top_k"]
        == expected_retry_top_k
    )

    # Both retrieval calls must use the same question.
    assert (
        first_retrieval["query"]
        == second_retrieval["query"]
    )

    assert (
        first_retrieval["query"]
        == "How do I check my order status?"
    )

    # ---------------------------------------------------------
    # Quality Guard must have run exactly twice.
    # ---------------------------------------------------------

    assert len(quality_calls) == 2

    assert (
        quality_calls[0]["eligible"]
        is True
    )

    assert (
        quality_calls[1]["eligible"]
        is True
    )

    assert (
        quality_calls[0]["question"]
        == quality_calls[1]["question"]
    )

    assert (
        quality_calls[0]["question"]
        == "How do I check my order status?"
    )

    # The production service now passes this argument.
    # Verify that the mock received it without imposing a
    # particular value on the application's policy.
    assert isinstance(
        quality_calls[0]["allow_general_knowledge"],
        bool,
    )

    assert isinstance(
        quality_calls[1]["allow_general_knowledge"],
        bool,
    )

    # ---------------------------------------------------------
    # Read persisted conversation history.
    # ---------------------------------------------------------

    history_response = client.get(
        f"/conversations/{conv_id}/messages",
        headers=auth_headers(user),
    )

    assert history_response.status_code == 200

    messages = history_response.json()

    assistant_messages = [
        message
        for message in messages
        if message["role"] == "assistant"
    ]

    assert assistant_messages

    # ---------------------------------------------------------
    # Read persisted Quality Guard trace.
    # ---------------------------------------------------------

    assistant_meta = (
        assistant_messages[-1].get("meta") or {}
    )

    quality_trace = (
        assistant_meta.get("quality_trace") or {}
    )

    assert quality_trace

    # Initial Quality Guard decision.
    assert (
        quality_trace["initial_decision"]
        == "RETRY_RETRIEVAL"
    )

    # Actual retry happened.
    assert (
        quality_trace["retry_attempted"]
        is True
    )

    # Retry reassessment succeeded.
    assert (
        quality_trace["retry_decision"]
        == "ALLOW"
    )

    # Retry path was accepted.
    assert (
        quality_trace["fallback_action"]
        == "search_again"
    )

    # Final Quality Guard decision.
    assert (
        quality_trace["final_decision"]
        == "ALLOW"
    )

    # ---------------------------------------------------------
    # Verify customer-facing response.
    # ---------------------------------------------------------

    assert (
        body["assistant_message"]["role"]
        == "assistant"
    )

    assert body["assistant_message"]["content"]

    assert body["handoff"] is False
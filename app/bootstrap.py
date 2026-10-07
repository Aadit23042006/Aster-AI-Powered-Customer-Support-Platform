"""One place that wires retriever + order tool + LLM client + agent
together, so the CLI, the FastAPI server, and the evaluation harness all
build the exact same agent instead of three slightly different copies.
"""

from __future__ import annotations

from app import config
from app.agent import Agent
from app.db.base import SessionLocal
from app.logging_utils import TraceLogger
from app.retriever import Retriever, build_index
from app.services.order_service import DBOrderLookupTool
from app.session import SessionStore


def build_agent(use_mock_llm: bool | None = None) -> Agent:
    """Build and return the application Agent.

    Mock/evaluation mode uses the JSON-backed OrderLookupTool because the
    standalone evaluation harness does not have an authenticated user
    context.

    Real application mode uses DBOrderLookupTool, which enforces
    authenticated-user ownership against PostgreSQL.
    """

    if use_mock_llm is None:
        use_mock_llm = config.USE_MOCK_LLM

    # ------------------------------------------------------------------
    # Embeddings + RAG index
    # ------------------------------------------------------------------
    if use_mock_llm:
        from app.embeddings import FakeEmbedder

        embedder = FakeEmbedder()

        index = build_index(
            embedder,
            force=True,
        )
    else:
        if not config.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Export it, put it in a .env file "
                "(see .env.example), or run with USE_MOCK_LLM=1 for the "
                "offline demo mode."
            )

        from app.embeddings import GeminiEmbedder

        embedder = GeminiEmbedder()

        index = build_index(embedder)

    retriever = Retriever(
        index,
        embedder,
    )

    # ------------------------------------------------------------------
    # Order lookup
    # ------------------------------------------------------------------
    #
    # Mock/evaluation mode:
    #   Use the JSON-backed OrderLookupTool.
    #
    # The standalone evaluation harness calls Agent.handle_turn() directly
    # and therefore has no authenticated current_user_id_var context.
    # DBOrderLookupTool would consequently reject every order lookup.
    #
    # Real application mode:
    #   Use DBOrderLookupTool with PostgreSQL.
    #
    # FastAPI conversation_service establishes the authenticated user
    # context before Agent.handle_turn() executes.
    #
    if use_mock_llm:
        from app.orders import OrderLookupTool

        orders = OrderLookupTool()
    else:
        orders = DBOrderLookupTool(
            SessionLocal,
        )

    # ------------------------------------------------------------------
    # LLM client
    # ------------------------------------------------------------------
    if use_mock_llm:
        from app.llm_client import MockLLMClient

        llm_client = MockLLMClient()
    else:
        from app.llm_client import GeminiLLMClient

        llm_client = GeminiLLMClient()

    # ------------------------------------------------------------------
    # Session + tracing
    # ------------------------------------------------------------------
    session_store = SessionStore()
    trace_logger = TraceLogger()

    return Agent(
        retriever,
        orders,
        llm_client,
        session_store=session_store,
        trace_logger=trace_logger,
    )

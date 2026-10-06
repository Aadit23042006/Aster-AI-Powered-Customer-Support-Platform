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

    The same wiring is used by the CLI, FastAPI server, and evaluation
    harness.

    Important:
    - RAG uses the configured embedding provider.
    - Order lookups use the authenticated customer's PostgreSQL data.
    - DBOrderLookupTool enforces user ownership through the
      current_user_id_var context set by conversation_service.
    """

    if use_mock_llm is None:
        use_mock_llm = config.USE_MOCK_LLM

    # ------------------------------------------------------------------
    # Embeddings + RAG index
    # ------------------------------------------------------------------
    if use_mock_llm:
        from app.embeddings import FakeEmbedder

        embedder = FakeEmbedder()

        # Fake embeddings are deterministic/offline and are not worth
        # persisting as a production cache.
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

        # Uses the configured Gemini embedding model/dimension and the
        # existing index cache when available.
        index = build_index(embedder)

    retriever = Retriever(
        index,
        embedder,
    )

    # ------------------------------------------------------------------
    # Database-backed customer order lookup
    # ------------------------------------------------------------------
    #
    # IMPORTANT:
    # Do NOT use the legacy:
    #
    #     OrderLookupTool()
    #
    # because that tool reads the old JSON-backed order data.
    #
    # DBOrderLookupTool uses PostgreSQL and applies authenticated-user
    # ownership filtering through current_user_id_var.
    #
    # conversation_service.send_message() sets that context before
    # Agent.handle_turn() executes.
    #
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
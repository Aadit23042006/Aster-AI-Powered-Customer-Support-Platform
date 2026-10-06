"""FastAPI application.

Phase 1 change: this mounts the full multi-user web API
(auth, users, conversations, orders, tickets) alongside the
original single-endpoint `/chat` + `/healthz` surface.

The original `/chat` endpoint remains for backward compatibility.
New code should use the authenticated, persistent,
DB-backed conversation API.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.agent import Agent
from app.bootstrap import build_agent

from app.api import (
    admin_routes,
    analytics_routes,
    auth_routes,
    conversations_routes,
    evaluation_routes,
    feedback_routes,
    kb_routes,
    notifications_routes,
    orders_routes,
    tickets_routes,
    trace_routes,
    users_routes,
    phase4_routes,
    external_routes,
    enterprise_routes,
    enterprise_v2_routes,
)

from app.services.order_service import DBOrderLookupTool


logger = logging.getLogger("aster_row.server")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Aster Support AI",
    description=(
        "Aster Support AI with authentication, "
        "persistent conversations, orders, tickets, analytics, "
        "knowledge base, enterprise AI, and Action Center capabilities."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "enterprise-ai",
            "description": (
                "Enterprise AI capabilities including Action Center, "
                "Support Workspace, Customer Intelligence, "
                "Citation Explorer, AI Quality, and AI Analytics."
            ),
        }
    ],
    swagger_ui_parameters={
        "docExpansion": "list",
        "defaultModelsExpandDepth": -1,
        "persistAuthorization": True,
    },
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request ID + timing + metrics
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_request_id_and_timing(
    request: Request,
    call_next,
):
    request_id = str(uuid.uuid4())
    start = time.time()

    request.state.request_id = request_id

    response = await call_next(request)

    duration_ms = (time.time() - start) * 1000

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(
        round(duration_ms, 1)
    )

    try:
        from app.monitoring.metrics import metrics

        metrics.record_request(
            response.status_code,
            duration_ms,
        )

        if response.status_code == 429:
            metrics.record_rate_limit_event()

        if (
            request.url.path == "/auth/login"
            and response.status_code == 401
        ):
            metrics.record_auth_failure()

    except Exception:
        # Metrics must never break the API response.
        logger.exception(
            "Failed to record request metrics"
        )

    return response


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
):
    request_id = getattr(
        request.state,
        "request_id",
        "unknown",
    )

    logger.exception(
        "Unhandled error [request_id=%s]",
        request_id,
    )

    try:
        from app.monitoring.error_tracking import capture_exception

        capture_exception(
            exc,
            request_id=request_id,
            route=request.url.path,
        )
    except Exception:
        logger.exception(
            "Failed to capture exception"
        )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error.",
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Legacy single-endpoint surface
# ---------------------------------------------------------------------------

_legacy_agent: Agent | None = None


def get_legacy_agent() -> Agent:
    global _legacy_agent

    if _legacy_agent is None:
        _legacy_agent = build_agent()

    return _legacy_agent


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    handoff: bool
    handoff_reason: str | None


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/healthz",
    include_in_schema=True,
)
def healthz() -> dict:
    return {
        "status": "ok",
    }


@app.get(
    "/health",
    include_in_schema=True,
)
def health() -> dict:
    return {
        "status": "ok",
    }


@app.get(
    "/health/live",
    include_in_schema=True,
)
def health_live() -> dict:
    # Liveness never touches external dependencies.
    return {
        "status": "ok",
    }


@app.get(
    "/health/ready",
    include_in_schema=True,
)
def health_ready():
    from fastapi.responses import JSONResponse as _JSONResponse

    from app.monitoring.health import readiness_report

    ready, checks = readiness_report()

    return _JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "degraded",
            "checks": checks,
        },
    )


# ---------------------------------------------------------------------------
# Legacy /chat endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/chat",
    response_model=ChatResponse,
    include_in_schema=True,
)
def chat(req: ChatRequest) -> ChatResponse:
    result = get_legacy_agent().handle_turn(
        req.session_id,
        req.message,
    )

    return ChatResponse(
        answer=result.answer,
        sources=result.sources,
        handoff=result.handoff,
        handoff_reason=result.handoff_reason,
    )


# ---------------------------------------------------------------------------
# Phase 1 multi-user web API
# ---------------------------------------------------------------------------

_web_agent: Agent | None = None


def get_web_agent() -> Agent:
    """Return the shared web Agent instance.

    Uses the same underlying Agent construction as the CLI/legacy
    endpoint, including the same retriever, LLM client, safety rules,
    and handoff rules.

    The web Agent additionally receives the DB-backed,
    per-request user-scoped order lookup tool.
    """

    global _web_agent

    if _web_agent is None:
        from app.db.base import SessionLocal

        _web_agent = build_agent()

        _web_agent.set_order_tool(
            DBOrderLookupTool(
                db_factory=SessionLocal,
            )
        )

    return _web_agent


# ---------------------------------------------------------------------------
# Conversation dependency override
# ---------------------------------------------------------------------------

app.dependency_overrides[
    conversations_routes.get_agent_dependency
] = get_web_agent


# ---------------------------------------------------------------------------
# Core API routers
# ---------------------------------------------------------------------------

app.include_router(
    auth_routes.router,
    include_in_schema=True,
)

app.include_router(
    users_routes.router,
    include_in_schema=True,
)

app.include_router(
    conversations_routes.router,
    include_in_schema=True,
)

app.include_router(
    orders_routes.router,
    include_in_schema=True,
)

app.include_router(
    tickets_routes.router,
    include_in_schema=True,
)

app.include_router(
    feedback_routes.router,
    include_in_schema=True,
)

app.include_router(
    kb_routes.router,
    include_in_schema=True,
)

app.include_router(
    kb_routes.index_jobs_router,
    include_in_schema=True,
)

app.include_router(
    analytics_routes.router,
    include_in_schema=True,
)

app.include_router(
    trace_routes.router,
    include_in_schema=True,
)


app.include_router(
    admin_routes.router,
    include_in_schema=True,
)

app.include_router(
    notifications_routes.router,
    include_in_schema=True,
)

app.include_router(
    phase4_routes.router,
    include_in_schema=True,
)

app.include_router(
    external_routes.router,
    include_in_schema=True,
)


# ---------------------------------------------------------------------------
# Enterprise AI routes
# ---------------------------------------------------------------------------
#
# IMPORTANT:
# Keep the Enterprise AI router registered exactly once.
#
# enterprise_routes.router contains:
#
#   /action-center/tools
#   /action-center/execute
#   /action-center/actions
#   /action-center/actions/{action_id}
#   /action-center/actions/{action_id}/approve
#   /action-center/actions/{action_id}/reject
#
# plus:
#
#   Support Workspace
#   Customer Intelligence
#   Citation Explorer
#   AI Quality
#   AI Analytics
#
# Explicit include_in_schema=True ensures these routes appear
# in FastAPI's OpenAPI/Swagger schema.
# ---------------------------------------------------------------------------

app.include_router(
    enterprise_routes.router,
    include_in_schema=True,
)


# ---------------------------------------------------------------------------
# Enterprise V2 routes
# ---------------------------------------------------------------------------
#
# IMPORTANT ROUTE ORDER:
#
# enterprise_v2_routes contains static routes such as:
#
#   /admin/evaluations/test-cases
#   /admin/evaluations/test-cases/run
#   /admin/evaluations/test-cases/{case_id}
#
# evaluation_routes contains a dynamic route:
#
#   /admin/evaluations/{run_id}
#
# FastAPI route matching is order-sensitive. Therefore the V2 router
# MUST be registered before evaluation_routes so that:
#
#   /admin/evaluations/test-cases
#
# is not incorrectly interpreted as:
#
#   /admin/evaluations/{run_id}
#
# which previously caused:
#
#   422 Unprocessable Entity
#   uuid_parsing
#
# for the literal value "test-cases".
# ---------------------------------------------------------------------------

app.include_router(
    enterprise_v2_routes.router,
    include_in_schema=True,
)


# ---------------------------------------------------------------------------
# Evaluation routes
# ---------------------------------------------------------------------------
#
# Register this AFTER enterprise_v2_routes.
#
# This preserves the dynamic:
#
#   /admin/evaluations/{run_id}
#
# route while allowing the static V2 test-case routes to match first.
# ---------------------------------------------------------------------------

app.include_router(
    evaluation_routes.router,
    include_in_schema=True,
)
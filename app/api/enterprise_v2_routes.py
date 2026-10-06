"""Additive enterprise AI features 7-15.

This module deliberately sits beside the existing APIs. It reuses existing
authentication, organization scoping, KB, evaluation, product, ticket and
conversation records instead of replacing them.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import config
from app.api.conversations_routes import get_agent_dependency
from app.auth.deps import get_current_user, require_roles
from app.db.base import get_db
from app.db.models import (
    AIUsageEvent,
    Conversation,
    ConversationCitation,
    ConversationClassification,
    EvaluationPlaygroundRun,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    Message,
    ModelRoutingEvent,
    Order,
    OrganizationMember,
    Product,
    ProductRecommendation,
    RecommendationExplanation,
    Ticket,
    PromptTemplate,
    PromptVersion,
    PromptExperiment,
    User,
)
from app.phase4 import get_current_org
from app.services import kb_service


router = APIRouter(tags=["enterprise-ai-7-15"])


_STAFF = require_roles(
    "support_agent",
    "admin",
    "super_admin",
)


_ADMIN = require_roles(
    "admin",
    "super_admin",
)


_VARIABLE_RE = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}"
)


def _now():
    return datetime.now(timezone.utc)


def _is_org_member(
    db: Session,
    org_id,
    user_id,
) -> bool:
    return (
        db.query(OrganizationMember.id)
        .filter_by(
            organization_id=org_id,
            user_id=user_id,
            status="active",
        )
        .first()
        is not None
    )


# ===========================================================================
# Knowledge Base Versioning
# ===========================================================================


class KBVersionOut(BaseModel):
    id: str
    document_id: str
    version: int
    content: str
    content_type: str
    source_filename: str | None = None
    status: str
    metadata: dict[str, Any] | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    published_at: datetime | None = None


class KBVersionsResponse(BaseModel):
    items: list[KBVersionOut]


class KBDiffResponse(BaseModel):
    document_id: str
    from_version: int
    to_version: int
    diff: list[str]


def _kb_version_out(
    v: KnowledgeDocumentVersion,
) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "document_id": str(v.document_id),
        "version": v.version,
        "content": v.content,
        "content_type": v.content_type,
        "source_filename": v.source_filename,
        "status": getattr(
            v,
            "status",
            "draft",
        ),
        "metadata": getattr(
            v,
            "metadata_json",
            None,
        ),
        "created_by": (
            str(v.created_by)
            if v.created_by
            else None
        ),
        "created_at": v.created_at,
        "published_at": getattr(
            v,
            "published_at",
            None,
        ),
    }


# ---------------------------------------------------------------------------
# Feature 8: KB Versioning
# ---------------------------------------------------------------------------


@router.get(
    "/admin/knowledge/{document_id}/versions",
    response_model=KBVersionsResponse,
    summary="List Knowledge Base Versions",
    description=(
        "Returns the complete historical version list for a "
        "knowledge-base document. Historical versions are preserved."
    ),
)
def kb_versions(
    document_id: uuid.UUID,
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
):
    doc = db.get(
        KnowledgeDocument,
        document_id,
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    return {
        "items": [
            _kb_version_out(v)
            for v in kb_service.list_versions(
                db,
                doc,
            )
        ]
    }


@router.get(
    "/admin/knowledge/{document_id}/versions/{version_id}",
    response_model=KBVersionOut,
    summary="Get Knowledge Base Version",
    description=(
        "Returns one specific historical knowledge-base version."
    ),
)
def kb_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
):
    row = (
        db.query(KnowledgeDocumentVersion)
        .filter_by(
            id=version_id,
            document_id=document_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Version not found.",
        )

    return _kb_version_out(row)


@router.get(
    "/admin/knowledge/{document_id}/diff",
    response_model=KBDiffResponse,
    summary="Compare Knowledge Base Versions",
    description=(
        "Returns a line-by-line unified diff between two "
        "knowledge-base versions."
    ),
)
def kb_diff(
    document_id: uuid.UUID,
    from_version: int = Query(
        ...,
        ge=1,
        description="Original version number.",
    ),
    to_version: int = Query(
        ...,
        ge=1,
        description="Comparison version number.",
    ),
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(KnowledgeDocumentVersion)
        .filter(
            KnowledgeDocumentVersion.document_id
            == document_id,
            KnowledgeDocumentVersion.version.in_(
                [
                    from_version,
                    to_version,
                ]
            ),
        )
        .all()
    )

    by_ver = {
        r.version: r
        for r in rows
    }

    if (
        from_version not in by_ver
        or to_version not in by_ver
    ):
        raise HTTPException(
            status_code=404,
            detail="One or both versions not found.",
        )

    diff = list(
        difflib.unified_diff(
            by_ver[from_version]
            .content
            .splitlines(),
            by_ver[to_version]
            .content
            .splitlines(),
            fromfile=f"v{from_version}",
            tofile=f"v{to_version}",
            lineterm="",
        )
    )

    return {
        "document_id": str(document_id),
        "from_version": from_version,
        "to_version": to_version,
        "diff": diff,
    }


def _kb_doc_and_version(
    db: Session,
    document_id,
    version_id,
):
    doc = db.get(
        KnowledgeDocument,
        document_id,
    )

    v = (
        db.query(KnowledgeDocumentVersion)
        .filter_by(
            id=version_id,
            document_id=document_id,
        )
        .first()
    )

    if not doc or not v:
        raise HTTPException(
            status_code=404,
            detail="Document or version not found.",
        )

    return doc, v


def _kb_audit(
    db,
    user,
    event,
    doc,
    v,
    extra=None,
):
    from app.services.audit_service import log_event

    log_event(
        db,
        event_type=event,
        user=user,
        resource_type="knowledge_document_version",
        resource_id=str(v.id),
        detail={
            "document_id": str(doc.id),
            "version": v.version,
            **(extra or {}),
        },
    )


def _sync_document_publication_state(
    db: Session,
    doc: KnowledgeDocument,
) -> KnowledgeDocumentVersion | None:
    """Keep document-level publication state consistent with versions.

    Invariant:

    - If a published version exists, document.status == "published"
      and document.current_version points to that published version.
    - If no published version exists, document.status == "draft".
    - Historical versions are never deleted.

    The latest version number remains in doc.current_version only when
    it is the published/live version. If there is no published version,
    current_version remains unchanged because it represents the latest
    version created by the existing KB service.
    """

    published = (
        db.query(KnowledgeDocumentVersion)
        .filter(
            KnowledgeDocumentVersion.document_id == doc.id,
            KnowledgeDocumentVersion.status == "published",
        )
        .order_by(
            KnowledgeDocumentVersion.version.desc()
        )
        .first()
    )

    if published:
        doc.status = "published"
        doc.current_version = published.version
        doc.published_at = published.published_at
    else:
        doc.status = "draft"
        doc.published_at = None

    return published


@router.post(
    "/admin/knowledge/{document_id}/rollback/{version_id}",
    response_model=KBVersionOut,
    summary="Rollback Knowledge Base Version",
    description=(
        "Creates a new version using the selected historical "
        "version and publishes the new version. Historical "
        "versions are never deleted or overwritten."
    ),
)
def kb_rollback(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent=Depends(get_agent_dependency),
):
    """History-preserving rollback.

    The selected historical version is copied into a NEW version.
    The new version is then published.

    No historical version is deleted or overwritten.
    """

    if not config.KB_VERSIONING_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Knowledge base versioning is disabled.",
        )

    doc, source = _kb_doc_and_version(
        db,
        document_id,
        version_id,
    )

    try:
        new = kb_service.add_version(
            db,
            doc,
            content=source.content,
            content_type=source.content_type,
            source_filename=source.source_filename,
            created_by=user.id,
        )
    except kb_service.KBError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    new.status = "draft"

    new.metadata_json = {
        "rollback_from_version": source.version,
    }

    _kb_audit(
        db,
        user,
        "KB_VERSION_CREATED",
        doc,
        new,
        {
            "rollback_from_version": source.version,
        },
    )

    _kb_audit(
        db,
        user,
        "KB_VERSION_ROLLBACK",
        doc,
        new,
        {
            "rollback_from_version": source.version,
        },
    )

    db.commit()
    db.refresh(new)

    return kb_version_publish(
        document_id=document_id,
        version_id=new.id,
        user=user,
        db=db,
        agent=agent,
    )


@router.post(
    "/admin/knowledge/{document_id}/versions/{version_id}/publish",
    response_model=KBVersionOut,
    summary="Publish Knowledge Base Version",
    description=(
        "Publishes the selected version and archives the "
        "previously published version."
    ),
)
def kb_version_publish(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent=Depends(get_agent_dependency),
):
    """Make exactly this version the live version.

    The previously published version is archived, not deleted.
    """

    if not config.KB_VERSIONING_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Knowledge base versioning is disabled.",
        )

    doc, v = _kb_doc_and_version(
        db,
        document_id,
        version_id,
    )

    if doc.status == "archived":
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot publish a version of an archived "
                "document. Restore the document first."
            ),
        )

    if (
        v.status == "published"
        and doc.current_version == v.version
        and doc.status == "published"
    ):
        return _kb_version_out(v)

    # There must be exactly one published version.
    for old in (
        db.query(KnowledgeDocumentVersion)
        .filter(
            KnowledgeDocumentVersion.document_id
            == doc.id,
            KnowledgeDocumentVersion.status
            == "published",
            KnowledgeDocumentVersion.id
            != v.id,
        )
        .all()
    ):
        old.status = "archived"

    now = _now()

    v.status = "published"
    v.published_at = now

    doc.current_version = v.version
    doc.status = "published"
    doc.published_at = now
    doc.index_status = "not_indexed"
    doc.index_error = None

    _kb_audit(
        db,
        user,
        "KB_VERSION_PUBLISHED",
        doc,
        v,
    )

    db.commit()

    from app.api.kb_routes import (
        _reindex_after_status_change,
    )

    _reindex_after_status_change(
        db,
        doc,
        agent,
    )

    db.refresh(v)

    return _kb_version_out(v)


@router.post(
    "/admin/knowledge/{document_id}/versions/{version_id}/archive",
    response_model=KBVersionOut,
    summary="Archive Knowledge Base Version",
    description=(
        "Archives a knowledge-base version without deleting it. "
        "If the archived version was the last published version, "
        "the document is automatically moved back to draft."
    ),
)
def kb_version_archive(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
):
    """Archive a version while preserving history.

    Important consistency rule:

    If this operation removes the LAST published version,
    the parent document must no longer remain published.

    Example:

        v1 = archived
        v2 = published
        v3 = draft

    archive(v2)

    becomes:

        v1 = archived
        v2 = archived
        v3 = draft

    and the document becomes:

        status = draft
        published_at = None

    Historical rows are never deleted.
    """

    if not config.KB_VERSIONING_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Knowledge base versioning is disabled.",
        )

    doc, v = _kb_doc_and_version(
        db,
        document_id,
        version_id,
    )

    # If this is the document's currently published version,
    # do not allow the document to lose its live version through
    # this endpoint. The intended workflow is to publish another
    # version first, unless the version is not actually the current
    # live version.
    if (
        v.version == doc.current_version
        and v.status == "published"
        and doc.status == "published"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The live version cannot be archived directly. "
                "Publish another version first."
            ),
        )

    # Archive the selected historical version.
    v.status = "archived"

    # Recalculate the document-level publication state.
    #
    # This is the critical fix for 6C:
    # if there are no published versions left, the document
    # becomes draft instead of remaining incorrectly published.
    remaining_published = (
        db.query(KnowledgeDocumentVersion)
        .filter(
            KnowledgeDocumentVersion.document_id == doc.id,
            KnowledgeDocumentVersion.status == "published",
            KnowledgeDocumentVersion.id != v.id,
        )
        .order_by(
            KnowledgeDocumentVersion.version.desc()
        )
        .first()
    )

    if remaining_published:
        doc.status = "published"
        doc.current_version = remaining_published.version
        doc.published_at = (
            remaining_published.published_at
        )
    else:
        doc.status = "draft"
        doc.published_at = None

    doc.index_status = "not_indexed"
    doc.index_error = None

    _kb_audit(
        db,
        user,
        "KB_VERSION_ARCHIVED",
        doc,
        v,
        {
            "remaining_published_version": (
                str(remaining_published.id)
                if remaining_published
                else None
            ),
            "document_status_after_archive": (
                doc.status
            ),
        },
    )

    db.commit()
    db.refresh(v)

    return _kb_version_out(v)


@router.post(
    "/admin/knowledge/{document_id}/versions/{version_id}/restore",
    response_model=KBVersionOut,
    summary="Restore Knowledge Base Version",
    description=(
        "Copies an archived historical version into a NEW "
        "version and publishes the new version. The original "
        "archived version remains preserved."
    ),
)
def kb_version_restore(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user=Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent=Depends(get_agent_dependency),
):
    """History-preserving restore.

    An archived historical version is copied into a NEW version.
    The new version is published.

    The archived source version remains untouched.
    """

    if not config.KB_VERSIONING_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Knowledge base versioning is disabled.",
        )

    doc, source = _kb_doc_and_version(
        db,
        document_id,
        version_id,
    )

    if source.status != "archived":
        raise HTTPException(
            status_code=400,
            detail="Only an archived version can be restored.",
        )

    try:
        new = kb_service.add_version(
            db,
            doc,
            content=source.content,
            content_type=source.content_type,
            source_filename=source.source_filename,
            created_by=user.id,
        )
    except kb_service.KBError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    new.status = "draft"

    new.metadata_json = {
        "restored_from_version": source.version,
    }

    _kb_audit(
        db,
        user,
        "KB_VERSION_CREATED",
        doc,
        new,
        {
            "restored_from_version": source.version,
        },
    )

    _kb_audit(
        db,
        user,
        "KB_VERSION_RESTORED",
        doc,
        new,
        {
            "restored_from_version": source.version,
        },
    )

    db.commit()
    db.refresh(new)

    return kb_version_publish(
        document_id=document_id,
        version_id=new.id,
        user=user,
        db=db,
        agent=agent,
    )


# ===========================================================================
# Feature 9: Evaluation Playground
# ===========================================================================


class PlaygroundRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=10000,
    )
    expected_answer: str | None = Field(
        default=None,
        max_length=10000,
    )
    model: str | None = None
    prompt_version: str | None = None
    retrieval_configuration: dict[str, Any] | None = None
    use_live_agent: bool = False


def _configured_models() -> list[str]:
    vals = [
        getattr(
            config,
            "CHAT_MODEL",
            None,
        ),
        getattr(
            config,
            "CHAT_FALLBACK_MODEL",
            None,
        ),
    ]

    return [
        v
        for v in vals
        if v
    ]


@router.get(
    "/admin/evaluations/playground/models"
)
def playground_models(
    user=Depends(_ADMIN),
):
    return {
        "models": _configured_models()
    }


def _run_out(r):
    return {
        "id": str(r.id),
        "question": r.question,
        "expected_answer": r.expected_answer,
        "answer": r.answer,
        "model": r.model,
        "prompt_version": r.prompt_version,
        "metrics": r.metrics,
        "retrieved_sources": r.retrieved_sources,
        "latency_ms": (
            float(r.latency_ms)
            if r.latency_ms is not None
            else None
        ),
        "token_usage": r.token_usage,
        "evaluator_version": r.evaluator_version,
        "comparison_id": r.comparison_id,
        "retrieval_configuration": (
            r.retrieval_configuration
        ),
        "status": r.status,
        "error": r.error,
        "created_at": r.created_at,
    }


def _persist_run(
    db,
    org,
    user,
    *,
    question,
    expected,
    res,
    model,
    prompt_version=None,
    retrieval_configuration=None,
    comparison_id=None,
):
    from app.enterprise.evaluation import (
        EVALUATOR_VERSION,
    )

    row = EvaluationPlaygroundRun(
        organization_id=org.id,
        created_by=user.id,
        question=question,
        expected_answer=expected,
        model=model,
        prompt_version=prompt_version,
        retrieval_configuration=(
            retrieval_configuration
        ),
        metrics=res["metrics"],
        retrieved_sources=res["sources"],
        latency_ms=res["latency_ms"],
        answer=res["answer"],
        token_usage=res["token_usage"],
        evaluator_version=EVALUATOR_VERSION,
        comparison_id=comparison_id,
        status=(
            "failed"
            if res["error"]
            else "completed"
        ),
        error=res["error"],
    )

    db.add(row)
    db.flush()

    return row


def _playground_guard():
    if not config.EVALUATION_PLAYGROUND_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Evaluation playground is disabled.",
        )


@router.post(
    "/admin/evaluations/playground/run"
)
def playground_run(
    payload: PlaygroundRequest,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    _playground_guard()

    from app.enterprise.evaluation import run_case
    from app.server import get_web_agent

    if (
        payload.model
        and payload.model
        not in _configured_models()
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Model is not configured in this project."
            ),
        )

    chosen = (
        payload.model
        or getattr(
            config,
            "CHAT_MODEL",
            None,
        )
        or "configured-model"
    )

    top_k = (
        payload.retrieval_configuration
        or {}
    ).get("top_k")

    res = run_case(
        get_web_agent(),
        payload.question,
        payload.expected_answer,
        model=chosen,
        top_k=(
            int(top_k)
            if top_k
            else None
        ),
        generate=payload.use_live_agent,
    )

    row = _persist_run(
        db,
        org,
        user,
        question=payload.question,
        expected=payload.expected_answer,
        res=res,
        model=(
            res["model_used"]
            if payload.use_live_agent
            else chosen
        ),
        prompt_version=payload.prompt_version,
        retrieval_configuration=(
            payload.retrieval_configuration
        ),
    )

    db.commit()
    db.refresh(row)

    return _run_out(row)


class CompareRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=10000,
    )
    expected_answer: str | None = Field(
        default=None,
        max_length=10000,
    )
    kind: str = Field(
        pattern="^(models|prompts|retrieval)$"
    )
    models: list[str] | None = None
    prompt_versions: (
        list[dict[str, Any]] | None
    ) = None
    top_k_values: list[int] | None = None


@router.post(
    "/admin/evaluations/compare"
)
def playground_compare(
    payload: CompareRequest,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Compare models, prompts, or retrieval settings."""

    _playground_guard()

    from app.enterprise.evaluation import run_case
    from app.server import get_web_agent

    agent = get_web_agent()

    cid = (
        f"cmp_{uuid.uuid4().hex[:12]}"
    )

    runs = []

    if payload.kind == "models":
        models = (
            payload.models
            or _configured_models()
        )

        if (
            len(models) < 2
            or len(models) > 5
            or any(
                m not in _configured_models()
                for m in models
            )
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Provide 2-5 models that are "
                    "configured in this project."
                ),
            )

        for m in models:
            res = run_case(
                agent,
                payload.question,
                payload.expected_answer,
                model=m,
            )

            runs.append(
                _persist_run(
                    db,
                    org,
                    user,
                    question=payload.question,
                    expected=payload.expected_answer,
                    res=res,
                    model=m,
                    comparison_id=cid,
                )
            )

    elif payload.kind == "prompts":
        specs = (
            payload.prompt_versions
            or []
        )

        if (
            len(specs) < 2
            or len(specs) > 5
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Provide 2-5 prompt versions "
                    "to compare."
                ),
            )

        for sp in specs:
            try:
                pid = uuid.UUID(
                    str(
                        sp.get("prompt_id")
                    )
                )
                ver = int(
                    sp.get("version")
                )
            except (
                TypeError,
                ValueError,
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Each prompt version needs "
                        "prompt_id and version."
                    ),
                )

            p = (
                db.query(PromptTemplate)
                .filter_by(
                    id=pid,
                    organization_id=org.id,
                )
                .first()
            )

            v = (
                db.query(PromptVersion)
                .filter_by(
                    prompt_id=pid,
                    version=ver,
                )
                .first()
                if p
                else None
            )

            if not v:
                raise HTTPException(
                    status_code=404,
                    detail="Prompt version not found.",
                )

            vals = {
                "customer_message": (
                    payload.question
                ),
                "customer_name": (
                    "the customer"
                ),
                "order_status": "unknown",
                "knowledge_context": "",
            }

            rendered = _VARIABLE_RE.sub(
                lambda m: str(
                    vals.get(
                        m.group(1),
                        m.group(0),
                    )
                ),
                v.content,
            )

            res = run_case(
                agent,
                payload.question,
                payload.expected_answer,
                prompt_text=rendered,
            )

            runs.append(
                _persist_run(
                    db,
                    org,
                    user,
                    question=payload.question,
                    expected=payload.expected_answer,
                    res=res,
                    model=res["model_used"],
                    prompt_version=(
                        f"{p.name}@v{ver}"
                    ),
                    comparison_id=cid,
                )
            )

    else:
        ks = (
            payload.top_k_values
            or [3, 5, 8]
        )

        if (
            len(ks) < 2
            or len(ks) > 5
            or any(
                k < 1 or k > 20
                for k in ks
            )
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Provide 2-5 top_k values "
                    "between 1 and 20."
                ),
            )

        for k in ks:
            res = run_case(
                agent,
                payload.question,
                payload.expected_answer,
                top_k=k,
            )

            runs.append(
                _persist_run(
                    db,
                    org,
                    user,
                    question=payload.question,
                    expected=payload.expected_answer,
                    res=res,
                    model=res["model_used"],
                    retrieval_configuration={
                        "top_k": k
                    },
                    comparison_id=cid,
                )
            )

    db.commit()

    return {
        "comparison_id": cid,
        "kind": payload.kind,
        "runs": [
            _run_out(r)
            for r in runs
        ],
    }


@router.get(
    "/admin/evaluations/playground/runs"
)
def playground_runs(
    page: int = 1,
    page_size: int = 25,
    comparison_id: str | None = None,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    page_size = max(
        1,
        min(page_size, 100),
    )

    q = (
        db.query(EvaluationPlaygroundRun)
        .filter(
            EvaluationPlaygroundRun.organization_id
            == org.id
        )
    )

    if comparison_id:
        q = q.filter(
            EvaluationPlaygroundRun.comparison_id
            == comparison_id
        )

    total = q.count()

    rows = (
        q.order_by(
            EvaluationPlaygroundRun.created_at.desc()
        )
        .offset(
            (max(page, 1) - 1)
            * page_size
        )
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            _run_out(r)
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


class EvalCaseCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=150,
    )
    question: str = Field(
        min_length=1,
        max_length=10000,
    )
    expected_answer: str | None = Field(
        default=None,
        max_length=10000,
    )


def _case_out(c):
    return {
        "id": str(c.id),
        "name": c.name,
        "question": c.question,
        "expected_answer": c.expected_answer,
        "created_at": c.created_at,
    }


@router.post(
    "/admin/evaluations/test-cases",
    status_code=201,
)
def create_eval_case(
    payload: EvalCaseCreate,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    from app.db.models import (
        EvaluationTestCase,
    )

    c = EvaluationTestCase(
        organization_id=org.id,
        name=payload.name.strip(),
        question=payload.question,
        expected_answer=(
            payload.expected_answer
        ),
        created_by=user.id,
    )

    db.add(c)
    db.commit()
    db.refresh(c)

    return _case_out(c)


@router.get(
    "/admin/evaluations/test-cases"
)
def list_eval_cases(
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    from app.db.models import (
        EvaluationTestCase,
    )

    return [
        _case_out(c)
        for c in (
            db.query(EvaluationTestCase)
            .filter_by(
                organization_id=org.id
            )
            .order_by(
                EvaluationTestCase.created_at.desc()
            )
            .all()
        )
    ]


@router.delete(
    "/admin/evaluations/test-cases/{case_id}",
    status_code=204,
)
def delete_eval_case(
    case_id: uuid.UUID,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    from app.db.models import (
        EvaluationTestCase,
    )

    c = (
        db.query(EvaluationTestCase)
        .filter_by(
            id=case_id,
            organization_id=org.id,
        )
        .first()
    )

    if not c:
        raise HTTPException(
            status_code=404,
            detail="Test case not found.",
        )

    db.delete(c)
    db.commit()


@router.post(
    "/admin/evaluations/test-cases/run"
)
def run_eval_cases(
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    _playground_guard()

    from app.db.models import (
        EvaluationTestCase,
    )
    from app.enterprise.evaluation import (
        run_case,
    )
    from app.server import get_web_agent

    cases = (
        db.query(EvaluationTestCase)
        .filter_by(
            organization_id=org.id
        )
        .order_by(
            EvaluationTestCase.created_at.asc()
        )
        .limit(50)
        .all()
    )

    if not cases:
        raise HTTPException(
            status_code=400,
            detail="No test cases to run.",
        )

    cid = (
        f"suite_{uuid.uuid4().hex[:12]}"
    )

    agent = get_web_agent()

    runs = []

    for c in cases:
        res = run_case(
            agent,
            c.question,
            c.expected_answer,
        )

        runs.append(
            _persist_run(
                db,
                org,
                user,
                question=c.question,
                expected=c.expected_answer,
                res=res,
                model=res["model_used"],
                comparison_id=cid,
            )
        )

    db.commit()

    def avg(key):
        values = [
            r.metrics.get(key)
            for r in runs
            if r.metrics
            and r.metrics.get(key)
            is not None
        ]

        return (
            round(
                sum(values)
                / len(values),
                4,
            )
            if values
            else None
        )

    return {
        "comparison_id": cid,
        "cases": len(runs),
        "averages": {
            k: avg(k)
            for k in (
                "groundedness",
                "answer_relevance",
                "faithfulness",
            )
        },
        "runs": [
            _run_out(r)
            for r in runs
        ],
    }


# ===========================================================================
# Feature 10: Prompt Management
# ===========================================================================


class PromptCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=150,
    )
    description: str | None = None
    content: str = Field(
        min_length=1,
        max_length=100000,
    )


class PromptVersionCreate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=100000,
    )


class PromptVersionUpdate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=100000,
    )


class PromptTest(BaseModel):
    input: dict[str, Any] = Field(
        default_factory=dict
    )


def _prompt_out(
    p,
    versions=None,
):
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "active_version": p.active_version,
        "created_by": (
            str(p.created_by)
            if p.created_by
            else None
        ),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "versions": (
            versions
            if versions is not None
            else []
        ),
    }


@router.get("/admin/prompts")
def prompts(
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(PromptTemplate)
        .filter(
            PromptTemplate.organization_id
            == org.id
        )
        .order_by(
            PromptTemplate.updated_at.desc()
        )
        .all()
    )

    return [
        _prompt_out(p)
        for p in rows
    ]


@router.post(
    "/admin/prompts",
    status_code=201,
)
def create_prompt(
    payload: PromptCreate,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    if (
        db.query(PromptTemplate)
        .filter_by(
            organization_id=org.id,
            name=payload.name.strip(),
        )
        .first()
    ):
        raise HTTPException(
            status_code=409,
            detail="Prompt name already exists.",
        )

    p = PromptTemplate(
        organization_id=org.id,
        name=payload.name.strip(),
        description=payload.description,
        created_by=user.id,
    )

    db.add(p)
    db.flush()

    v = PromptVersion(
        prompt_id=p.id,
        version=1,
        content=payload.content,
        status="draft",
        variables=sorted(
            set(
                _VARIABLE_RE.findall(
                    payload.content
                )
            )
        ),
        created_by=user.id,
    )

    db.add(v)

    p.active_version = 1

    db.commit()
    db.refresh(p)

    return _prompt_out(
        p,
        [
            _prompt_version_out(v)
        ],
    )


def _prompt_version_out(v):
    return {
        "id": str(v.id),
        "prompt_id": str(v.prompt_id),
        "version": v.version,
        "content": v.content,
        "status": v.status,
        "variables": v.variables or [],
        "created_by": (
            str(v.created_by)
            if v.created_by
            else None
        ),
        "created_at": v.created_at,
        "published_at": v.published_at,
    }


@router.get(
    "/admin/prompts/{prompt_id}"
)
def prompt_detail(
    prompt_id: uuid.UUID,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    versions = (
        db.query(PromptVersion)
        .filter_by(
            prompt_id=p.id
        )
        .order_by(
            PromptVersion.version.desc()
        )
        .all()
    )

    return _prompt_out(
        p,
        [
            _prompt_version_out(v)
            for v in versions
        ],
    )


@router.post(
    "/admin/prompts/{prompt_id}/versions",
    status_code=201,
)
def prompt_version(
    prompt_id: uuid.UUID,
    payload: PromptVersionCreate,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    last = (
        db.query(
            func.max(
                PromptVersion.version
            )
        )
        .filter_by(
            prompt_id=p.id
        )
        .scalar()
        or 0
    )

    v = PromptVersion(
        prompt_id=p.id,
        version=last + 1,
        content=payload.content,
        status="draft",
        variables=sorted(
            set(
                _VARIABLE_RE.findall(
                    payload.content
                )
            )
        ),
        created_by=user.id,
    )

    db.add(v)

    # Creating a draft must not change the active/production version.
    # Only the explicit publish endpoint changes active_version.

    db.commit()
    db.refresh(v)

    return _prompt_version_out(v)


@router.patch(
    "/admin/prompts/{prompt_id}/versions/{version}"
)
def update_prompt_version(
    prompt_id: uuid.UUID,
    version: int,
    payload: PromptVersionUpdate,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Update a non-production prompt version in-place.

    Production versions are immutable. To change production content,
    create a new draft version and publish it explicitly.
    """
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    v = (
        db.query(PromptVersion)
        .filter_by(
            prompt_id=p.id,
            version=version,
        )
        .first()
    )

    if not v:
        raise HTTPException(
            status_code=404,
            detail="Prompt version not found.",
        )

    if v.status == "production":
        raise HTTPException(
            status_code=409,
            detail=(
                "Production prompt versions cannot be edited. "
                "Create a new version instead."
            ),
        )

    content = payload.content.strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Prompt version content cannot be empty.",
        )

    v.content = content
    v.variables = sorted(
        set(_VARIABLE_RE.findall(content))
    )

    db.commit()
    db.refresh(v)

    return _prompt_version_out(v)


@router.delete(
    "/admin/prompts/{prompt_id}/versions/{version}"
)
def delete_prompt_version(
    prompt_id: uuid.UUID,
    version: int,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Delete a non-production prompt version.

    Production versions are immutable. At least one version must remain.
    If the deleted version is active, the highest remaining production
    version is preferred; otherwise the highest remaining version is used.
    """
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    v = (
        db.query(PromptVersion)
        .filter_by(
            prompt_id=p.id,
            version=version,
        )
        .first()
    )

    if not v:
        raise HTTPException(
            status_code=404,
            detail="Prompt version not found.",
        )

    if v.status == "production":
        raise HTTPException(
            status_code=409,
            detail=(
                "Production prompt versions cannot be deleted. "
                "Create a new version instead."
            ),
        )

    remaining = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == p.id,
            PromptVersion.id != v.id,
        )
        .order_by(PromptVersion.version.desc())
        .all()
    )

    if not remaining:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the last prompt version.",
        )

    deleted_version = v.version
    was_active = p.active_version == deleted_version

    db.delete(v)

    if was_active:
        production = next(
            (row for row in remaining if row.status == "production"),
            None,
        )
        p.active_version = (
            production.version
            if production is not None
            else remaining[0].version
        )

    db.commit()

    return {
        "deleted": True,
        "prompt_id": str(p.id),
        "deleted_version": deleted_version,
        "active_version": p.active_version,
    }


@router.post(
    "/admin/prompts/{prompt_id}/publish"
)
def publish_prompt(
    prompt_id: uuid.UUID,
    version: int | None = None,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    q = (
        db.query(PromptVersion)
        .filter_by(
            prompt_id=p.id
        )
    )

    v = (
        q.filter_by(
            version=version
        ).first()
        if version
        else q.order_by(
            PromptVersion.version.desc()
        ).first()
    )

    if not v:
        raise HTTPException(
            status_code=404,
            detail="Prompt version not found.",
        )

    for old in q.filter(
        PromptVersion.status == "production"
    ).all():
        old.status = "archived"

    v.status = "production"
    v.published_at = _now()
    p.active_version = v.version

    db.commit()
    db.refresh(v)

    return _prompt_version_out(v)


@router.post(
    "/admin/prompts/{prompt_id}/rollback/{version}"
)
def rollback_prompt(
    prompt_id: uuid.UUID,
    version: int,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    source = (
        db.query(PromptVersion)
        .filter_by(
            prompt_id=p.id,
            version=version,
        )
        .first()
    )

    if not source:
        raise HTTPException(
            status_code=404,
            detail="Prompt version not found.",
        )

    # Rollback restores the selected historical version in-place.
    # No new PromptVersion row is created and no historical version is deleted.
    # The currently active production version is archived, while the selected
    # historical version becomes production and active immediately.
    # This makes 8E deterministic: v1 -> Rollback => active v1, v2 archived.

    if source.status == "production" and p.active_version == source.version:
        return _prompt_version_out(source)

    production_versions = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == p.id,
            PromptVersion.status == "production",
            PromptVersion.id != source.id,
        )
        .all()
    )

    for old in production_versions:
        old.status = "archived"

    source.status = "production"
    source.published_at = _now()
    p.active_version = source.version

    db.commit()
    db.refresh(source)

    return _prompt_version_out(source)


@router.get(
    "/admin/prompts/{prompt_id}/diff"
)
def prompt_diff(
    prompt_id: uuid.UUID,
    from_version: int,
    to_version: int,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    rows = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.prompt_id == p.id,
            PromptVersion.version.in_(
                [
                    from_version,
                    to_version,
                ]
            ),
        )
        .all()
    )

    by = {
        r.version: r
        for r in rows
    }

    if (
        from_version not in by
        or to_version not in by
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "One or both prompt versions "
                "not found."
            ),
        )

    return {
        "from_version": from_version,
        "to_version": to_version,
        "diff": list(
            difflib.unified_diff(
                by[from_version]
                .content
                .splitlines(),
                by[to_version]
                .content
                .splitlines(),
                fromfile=f"v{from_version}",
                tofile=f"v{to_version}",
                lineterm="",
            )
        ),
    }


@router.post(
    "/admin/prompts/{prompt_id}/test"
)
def test_prompt(
    prompt_id: uuid.UUID,
    payload: PromptTest,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    v = (
        db.query(PromptVersion)
        .filter_by(
            prompt_id=p.id,
            version=p.active_version,
        )
        .first()
    )

    if not v:
        raise HTTPException(
            status_code=404,
            detail="Prompt version not found.",
        )

    vars_found = set(
        v.variables or []
    )

    missing = sorted(
        k
        for k in vars_found
        if k not in payload.input
    )

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Prompt variables missing.",
                "missing_variables": missing,
            },
        )

    rendered = _VARIABLE_RE.sub(
        lambda m: str(
            payload.input[m.group(1)]
        ),
        v.content,
    )

    return {
        "prompt_version": v.version,
        "rendered_prompt": rendered,
        "model": getattr(
            config,
            "CHAT_MODEL",
            None,
        ),
        "output": (
            "Prompt rendering test completed. "
            "No hidden reasoning is exposed."
        ),
    }


# ===========================================================================
# Feature 8b: Prompt A/B Testing
# ===========================================================================


class ExperimentCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=150,
    )
    variant_a_version: int
    variant_b_version: int
    traffic_split_b: int = Field(
        default=50,
        ge=1,
        le=99,
    )


def _experiment_out(e):
    return {
        "id": str(e.id),
        "prompt_id": str(e.prompt_id),
        "name": e.name,
        "variant_a_version": e.variant_a_version,
        "variant_b_version": e.variant_b_version,
        "traffic_split_b": e.traffic_split_b,
        "status": e.status,
        "created_by": (
            str(e.created_by)
            if e.created_by
            else None
        ),
        "created_at": e.created_at,
        "stopped_at": e.stopped_at,
    }


def _experiment_prompt(
    db,
    org,
    prompt_id,
) -> PromptTemplate:
    p = (
        db.query(PromptTemplate)
        .filter_by(
            id=prompt_id,
            organization_id=org.id,
        )
        .first()
    )

    if not p:
        raise HTTPException(
            status_code=404,
            detail="Prompt not found.",
        )

    return p


@router.post(
    "/admin/prompts/{prompt_id}/experiments",
    status_code=201,
)
def create_experiment(
    prompt_id: uuid.UUID,
    payload: ExperimentCreate,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Create a prompt A/B experiment."""

    if not config.PROMPT_MANAGEMENT_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Prompt management is disabled.",
        )

    p = _experiment_prompt(
        db,
        org,
        prompt_id,
    )

    existing = {
        v.version
        for v in (
            db.query(PromptVersion.version)
            .filter_by(
                prompt_id=p.id
            )
            .all()
        )
    }

    if (
        payload.variant_a_version
        not in existing
        or payload.variant_b_version
        not in existing
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Both variants must be existing "
                "versions of this prompt."
            ),
        )

    if (
        db.query(PromptExperiment)
        .filter_by(
            prompt_id=p.id,
            status="running",
        )
        .first()
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This prompt already has a running "
                "experiment. Stop it first."
            ),
        )

    e = PromptExperiment(
        organization_id=org.id,
        prompt_id=p.id,
        name=payload.name.strip(),
        variant_a_version=(
            payload.variant_a_version
        ),
        variant_b_version=(
            payload.variant_b_version
        ),
        traffic_split_b=(
            payload.traffic_split_b
        ),
        created_by=user.id,
    )

    db.add(e)
    db.flush()

    from app.services.audit_service import (
        log_event,
    )

    log_event(
        db,
        event_type="PROMPT_EXPERIMENT_CREATED",
        user=user,
        resource_type="prompt_experiment",
        resource_id=str(e.id),
        detail={
            "prompt_id": str(p.id),
            "a": e.variant_a_version,
            "b": e.variant_b_version,
        },
    )

    db.commit()
    db.refresh(e)

    return _experiment_out(e)


@router.get(
    "/admin/prompts/{prompt_id}/experiments"
)
def list_experiments(
    prompt_id: uuid.UUID,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = _experiment_prompt(
        db,
        org,
        prompt_id,
    )

    rows = (
        db.query(PromptExperiment)
        .filter_by(
            prompt_id=p.id
        )
        .order_by(
            PromptExperiment.created_at.desc()
        )
        .all()
    )

    return [
        _experiment_out(e)
        for e in rows
    ]


@router.post(
    "/admin/prompts/{prompt_id}/experiments/{experiment_id}/stop"
)
def stop_experiment(
    prompt_id: uuid.UUID,
    experiment_id: uuid.UUID,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = _experiment_prompt(
        db,
        org,
        prompt_id,
    )

    e = (
        db.query(PromptExperiment)
        .filter_by(
            id=experiment_id,
            prompt_id=p.id,
        )
        .first()
    )

    if not e:
        raise HTTPException(
            status_code=404,
            detail="Experiment not found.",
        )

    if e.status != "running":
        raise HTTPException(
            status_code=400,
            detail="Experiment is not running.",
        )

    e.status = "stopped"
    e.stopped_at = _now()

    from app.services.audit_service import (
        log_event,
    )

    log_event(
        db,
        event_type="PROMPT_EXPERIMENT_STOPPED",
        user=user,
        resource_type="prompt_experiment",
        resource_id=str(e.id),
    )

    db.commit()
    db.refresh(e)

    return _experiment_out(e)


def resolve_experiment_version(
    db: Session,
    prompt: PromptTemplate,
    bucket_key: str,
) -> tuple[int, str | None]:
    """Deterministic A/B assignment."""

    try:
        exp = (
            db.query(PromptExperiment)
            .filter_by(
                prompt_id=prompt.id,
                status="running",
            )
            .first()
        )

        if not exp:
            return (
                prompt.active_version,
                None,
            )

        bucket = (
            int(
                hashlib.sha256(
                    f"{exp.id}:{bucket_key}".encode()
                ).hexdigest(),
                16,
            )
            % 100
        )

        version = (
            exp.variant_b_version
            if bucket < exp.traffic_split_b
            else exp.variant_a_version
        )

        return (
            version,
            str(exp.id),
        )

    except Exception:
        return (
            prompt.active_version,
            None,
        )


@router.get(
    "/admin/prompts/{prompt_id}/experiments/{experiment_id}/resolve"
)
def preview_experiment_bucket(
    prompt_id: uuid.UUID,
    experiment_id: uuid.UUID,
    bucket_key: str,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    p = _experiment_prompt(
        db,
        org,
        prompt_id,
    )

    e = (
        db.query(PromptExperiment)
        .filter_by(
            id=experiment_id,
            prompt_id=p.id,
        )
        .first()
    )

    if not e:
        raise HTTPException(
            status_code=404,
            detail="Experiment not found.",
        )

    version, exp_id = resolve_experiment_version(
        db,
        p,
        bucket_key,
    )

    return {
        "bucket_key": bucket_key,
        "resolved_version": version,
        "experiment_id": exp_id,
        "variant": (
            "b"
            if version == e.variant_b_version
            else "a"
        ),
    }


# ===========================================================================
# Feature 11: AI Usage
# ===========================================================================


@router.get(
    "/admin/analytics/ai-usage"
)
def ai_usage(
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
    days: int = Query(
        30,
        ge=1,
        le=365,
    ),
    model: str | None = None,
    feature: str | None = None,
    endpoint: str | None = None,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
):
    since = (
        _now().timestamp()
        - days * 86400
    )

    start = datetime.fromtimestamp(
        since,
        tz=timezone.utc,
    )

    member_ids = (
        db.query(
            OrganizationMember.user_id
        )
        .filter_by(
            organization_id=org.id,
            status="active",
        )
    )

    q = (
        db.query(AIUsageEvent)
        .filter(
            or_(
                AIUsageEvent.organization_id
                == org.id,
                AIUsageEvent.user_id.in_(
                    member_ids
                ),
            ),
            AIUsageEvent.created_at >= start,
        )
    )

    if model:
        q = q.filter(
            AIUsageEvent.model == model
        )

    if feature:
        q = q.filter(
            AIUsageEvent.feature == feature
        )

    if endpoint:
        q = q.filter(
            AIUsageEvent.endpoint == endpoint
        )

    if user_id:
        q = q.filter(
            AIUsageEvent.user_id == user_id
        )

    if conversation_id:
        q = q.filter(
            AIUsageEvent.conversation_id
            == conversation_id
        )

    rows = q.all()

    def total(attr):
        vals = [
            getattr(r, attr)
            for r in rows
            if getattr(r, attr) is not None
        ]

        return (
            sum(vals)
            if vals
            else None
        )

    by_day: dict[str, list] = {}

    for r in rows:
        by_day.setdefault(
            r.created_at.date().isoformat(),
            [],
        ).append(r)

    daily = [
        {
            "date": d,
            "requests": len(rs),
            "total_tokens": (
                sum(
                    x.total_tokens
                    for x in rs
                    if x.total_tokens is not None
                )
                or None
                if any(
                    x.total_tokens is not None
                    for x in rs
                )
                else None
            ),
            "estimated_cost": (
                float(
                    sum(
                        (x.estimated_cost or 0)
                        for x in rs
                    )
                )
                if any(
                    x.estimated_cost is not None
                    for x in rs
                )
                else None
            ),
        }
        for d, rs in sorted(
            by_day.items()
        )
    ]

    latency_values = [
        float(r.latency_ms)
        for r in rows
        if r.latency_ms is not None
    ]

    resilience_events = [
        (r.metadata_json or {})
        for r in rows
        if isinstance(r.metadata_json, dict)
    ]

    fallback_events = sum(
        1
        for meta in resilience_events
        if meta.get("llm_fallback_used") is True
    )
    failover_exhausted_events = sum(
        1
        for meta in resilience_events
        if meta.get("llm_failover_exhausted") is True
    )
    retry_count = sum(
        int(meta.get("llm_retry_count") or 0)
        for meta in resilience_events
    )

    return {
        "requests": len(rows),
        "resilience": {
            "fallback_events": fallback_events,
            "failover_exhausted_events": failover_exhausted_events,
            "retry_count": retry_count,
        },
        "input_tokens": total(
            "input_tokens"
        ),
        "output_tokens": total(
            "output_tokens"
        ),
        "total_tokens": total(
            "total_tokens"
        ),
        "estimated_cost": (
            float(
                sum(
                    (r.estimated_cost or 0)
                    for r in rows
                )
            )
            if any(
                r.estimated_cost is not None
                for r in rows
            )
            else None
        ),
        "average_latency_ms": (
            sum(latency_values)
            / len(latency_values)
            if latency_values
            else None
        ),
        "error_rate": (
            sum(
                1
                for r in rows
                if r.status
                not in {"success", "ok"}
            )
            / len(rows)
            if rows
            else 0
        ),
        "daily": daily,
        "by_model": {
            m: len(
                [
                    r
                    for r in rows
                    if r.model == m
                ]
            )
            for m in sorted(
                {
                    r.model
                    for r in rows
                    if r.model
                }
            )
        },
        "by_feature": {
            f: len(
                [
                    r
                    for r in rows
                    if r.feature == f
                ]
            )
            for f in sorted(
                {
                    r.feature
                    for r in rows
                    if r.feature
                }
            )
        },
    }


# ===========================================================================
# Feature 12: Model Router
# ===========================================================================


class RouteRequest(BaseModel):
    category: str = Field(
        min_length=1,
        max_length=50,
    )
    reason: str | None = None
    user_id: uuid.UUID | None = None


@router.post(
    "/admin/ai/router/preview"
)
def router_preview(
    payload: RouteRequest,
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    from app.enterprise.model_router import (
        CATEGORIES,
        route,
    )
    from app.services.audit_service import (
        log_event,
    )

    category = (
        payload.category
        .strip()
        .lower()
    )

    if category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported routing category.",
        )

    d = route(category)

    reason = (
        payload.reason
        or d.reason
    )

    event = ModelRoutingEvent(
        organization_id=org.id,
        user_id=user.id,
        routing_category=category,
        model_used=d.model,
        routing_reason=reason,
        success=True,
    )

    db.add(event)
    db.flush()

    log_event(
        db,
        event_type="MODEL_ROUTED",
        user=user,
        resource_type="model_routing_event",
        resource_id=str(event.id),
        detail={
            "category": category,
            "model": d.model,
            "fallback_used": d.fallback_used,
        },
    )

    db.commit()

    return {
        "model_used": d.model,
        "routing_category": category,
        "routing_reason": reason,
        "fallback_used": d.fallback_used,
        "fallback_configured": bool(
            getattr(
                config,
                "CHAT_FALLBACK_MODEL",
                None,
            )
        ),
        "event_id": str(event.id),
    }


@router.get(
    "/admin/ai/router/events"
)
def router_events(
    user=Depends(_ADMIN),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
    limit: int = Query(
        50,
        ge=1,
        le=200,
    ),
):
    rows = (
        db.query(ModelRoutingEvent)
        .filter(
            ModelRoutingEvent.organization_id
            == org.id
        )
        .order_by(
            ModelRoutingEvent.created_at.desc()
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "id": str(r.id),
            "routing_category": (
                r.routing_category
            ),
            "model_used": r.model_used,
            "routing_reason": (
                r.routing_reason
            ),
            "latency_ms": r.latency_ms,
            "success": r.success,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ===========================================================================
# Feature 13: Customer 360
# ===========================================================================


@router.get(
    "/customers/{customer_id}/360"
)
def customer_360(
    customer_id: uuid.UUID,
    user=Depends(_STAFF),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    if not _is_org_member(
        db,
        org.id,
        customer_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    target = db.get(
        User,
        customer_id,
    )

    if not target:
        raise HTTPException(
            status_code=404,
            detail="Customer not found.",
        )

    if (
        "customer" in target.role_names
        and target.id != user.id
    ):
        if (
            "support_agent"
            not in user.role_names
            and not (
                user.role_names
                & {
                    "admin",
                    "super_admin",
                }
            )
        ):
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions.",
            )

    orders = (
        db.query(Order)
        .filter(
            Order.user_id == target.id
        )
        .order_by(
            Order.created_at.desc()
        )
        .limit(50)
        .all()
    )

    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.user_id == target.id
        )
        .order_by(
            Ticket.updated_at.desc()
        )
        .limit(50)
        .all()
    )

    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.user_id
            == target.id
        )
        .order_by(
            Conversation.updated_at.desc()
        )
        .limit(50)
        .all()
    )

    classes = (
        db.query(
            ConversationClassification
        )
        .join(
            Conversation,
            ConversationClassification.conversation_id
            == Conversation.id,
        )
        .filter(
            Conversation.user_id
            == target.id
        )
        .order_by(
            ConversationClassification.created_at.desc()
        )
        .limit(20)
        .all()
    )

    messages = (
        db.query(Message)
        .join(
            Conversation,
            Message.conversation_id
            == Conversation.id,
        )
        .filter(
            Conversation.user_id
            == target.id
        )
        .order_by(
            Message.created_at.desc()
        )
        .limit(30)
        .all()
    )

    timeline = []

    for x in messages:
        timeline.append(
            {
                "type": "message",
                "id": str(x.id),
                "at": x.created_at,
                "label": (
                    f"{x.role.title()} message"
                ),
            }
        )

    for x in tickets:
        timeline.append(
            {
                "type": "ticket",
                "id": str(x.id),
                "at": x.created_at,
                "label": (
                    f"Ticket {x.ticket_number} "
                    "created"
                ),
            }
        )

    timeline.sort(
        key=lambda x: x["at"],
        reverse=True,
    )

    latest = (
        classes[0]
        if classes
        else None
    )

    return {
        "customer": {
            "id": str(target.id),
            "name": target.full_name,
            "email": target.email,
        },
        "orders": [
            {
                "id": str(o.id),
                "order_number": o.order_number,
                "status": o.status,
                "placed_at": o.placed_at,
                "estimated_delivery": (
                    o.estimated_delivery
                ),
                "customer_safe_message": (
                    o.customer_safe_message
                ),
            }
            for o in orders
        ],
        "tickets": [
            {
                "id": str(t.id),
                "ticket_number": t.ticket_number,
                "status": t.status,
                "category": t.category,
                "priority": t.priority,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tickets
        ],
        "conversations": [
            {
                "id": str(c.id),
                "title": c.title,
                "status": c.status,
                "updated_at": c.updated_at,
            }
            for c in conversations
        ],
        "intelligence": (
            {
                "intent": latest.intent,
                "sentiment": latest.sentiment,
                "priority": latest.priority,
                "topic": latest.topic,
                "confidence": latest.confidence,
            }
            if latest
            else None
        ),
        "last_interaction": (
            messages[0].created_at
            if messages
            else None
        ),
        "timeline": timeline[:50],
    }


# ===========================================================================
# Feature 14: Global Search
# ===========================================================================


@router.get("/search")
def global_search(
    q: str = Query(
        ...,
        min_length=1,
        max_length=200,
    ),
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    term = q.strip()

    if not term:
        return {
            "query": q,
            "results": [],
        }

    results = []

    staff = bool(
        user.role_names
        & {
            "support_agent",
            "admin",
            "super_admin",
        }
    )

    allowed_user_ids = [
        m.user_id
        for m in (
            db.query(
                OrganizationMember
            )
            .filter_by(
                organization_id=org.id,
                status="active",
            )
            .all()
        )
    ]

    scope_user_ids = (
        allowed_user_ids
        if staff
        else [user.id]
    )

    oq = (
        db.query(Order)
        .filter(
            Order.user_id.in_(
                scope_user_ids
            ),
            or_(
                Order.order_number.ilike(
                    f"%{term}%"
                ),
                Order.status.ilike(
                    f"%{term}%"
                ),
            ),
        )
        .limit(10)
        .all()
    )

    results += [
        {
            "type": "order",
            "id": str(x.id),
            "title": x.order_number,
            "subtitle": x.status,
        }
        for x in oq
    ]

    tq = (
        db.query(Ticket)
        .filter(
            Ticket.user_id.in_(
                scope_user_ids
            ),
            or_(
                Ticket.ticket_number.ilike(
                    f"%{term}%"
                ),
                Ticket.subject.ilike(
                    f"%{term}%"
                ),
            ),
        )
        .limit(10)
        .all()
    )

    results += [
        {
            "type": "ticket",
            "id": str(x.id),
            "title": x.ticket_number,
            "subtitle": x.subject,
        }
        for x in tq
    ]

    cq = (
        db.query(Conversation)
        .filter(
            Conversation.user_id.in_(
                scope_user_ids
            ),
            Conversation.title.ilike(
                f"%{term}%"
            ),
        )
        .limit(10)
        .all()
    )

    results += [
        {
            "type": "conversation",
            "id": str(x.id),
            "title": x.title,
            "subtitle": x.status,
        }
        for x in cq
    ]

    uq = (
        db.query(User)
        .filter(
            User.id.in_(
                scope_user_ids
            ),
            or_(
                User.full_name.ilike(
                    f"%{term}%"
                ),
                User.email.ilike(
                    f"%{term}%"
                ),
            ),
        )
        .limit(10)
        .all()
    )

    results += [
        {
            "type": "customer",
            "id": str(x.id),
            "title": x.full_name,
            "subtitle": x.email,
        }
        for x in uq
    ]

    if staff:
        kbrows = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.status
                == "published",
                KnowledgeDocument.title.ilike(
                    f"%{term}%"
                ),
            )
            .limit(10)
            .all()
        )

        results += [
            {
                "type": "knowledge_base",
                "id": str(x.id),
                "title": x.title,
                "subtitle": x.category,
            }
            for x in kbrows
        ]

    prows = (
        db.query(Product)
        .filter(
            Product.organization_id
            == org.id,
            Product.active.is_(True),
            or_(
                Product.name.ilike(
                    f"%{term}%"
                ),
                Product.sku.ilike(
                    f"%{term}%"
                ),
                Product.category.ilike(
                    f"%{term}%"
                ),
            ),
        )
        .limit(10)
        .all()
    )

    results += [
        {
            "type": "product",
            "id": str(x.id),
            "title": x.name,
            "subtitle": x.sku,
        }
        for x in prows
    ]

    return {
        "query": q,
        "results": results[:60],
    }


# ===========================================================================
# Feature 15: Recommendation Explanations
# ===========================================================================


@router.get(
    "/recommendations/{recommendation_id}/explanation"
)
def recommendation_explanation(
    recommendation_id: uuid.UUID,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    if not config.RECOMMENDATION_INTELLIGENCE_ENABLED:
        raise HTTPException(
            status_code=403,
            detail=(
                "Recommendation intelligence "
                "is disabled."
            ),
        )

    rec = (
        db.query(ProductRecommendation)
        .filter_by(
            id=recommendation_id,
            organization_id=org.id,
            user_id=user.id,
        )
        .first()
    )

    if not rec:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not found.",
        )

    ids = []

    for pid in rec.product_ids or []:
        try:
            ids.append(
                uuid.UUID(str(pid))
            )
        except ValueError:
            continue

    products = (
        db.query(Product)
        .filter(
            Product.organization_id
            == org.id,
            Product.id.in_(ids),
            Product.active.is_(True),
        )
        .all()
        if ids
        else []
    )

    out = []

    qtokens = set(
        re.findall(
            r"[a-z0-9]+",
            rec.query.lower(),
        )
    )

    for p in products:
        reasons = []

        name = (
            p.name or ""
        ).lower()

        cat = (
            p.category or ""
        ).lower()

        desc = (
            p.description or ""
        ).lower()

        matched = [
            t
            for t in qtokens
            if len(t) > 2
            and (
                t in name
                or t in cat
                or t in desc
            )
        ]

        if matched:
            reasons.append(
                {
                    "type": "query_match",
                    "evidence": sorted(
                        matched
                    ),
                }
            )

        if (
            rec.query
            and p.category
            and p.category.lower()
            in rec.query.lower()
        ):
            reasons.append(
                {
                    "type": "same_category",
                    "evidence": p.category,
                }
            )

        exp = (
            db.query(
                RecommendationExplanation
            )
            .filter_by(
                recommendation_id=rec.id,
                product_id=p.id,
            )
            .first()
        )

        if not exp:
            exp = RecommendationExplanation(
                recommendation_id=rec.id,
                organization_id=org.id,
                user_id=user.id,
                product_id=p.id,
                reasons=reasons,
                confidence=None,
                model=None,
            )

            db.add(exp)
        else:
            exp.reasons = reasons

        out.append(
            {
                "product": {
                    "id": str(p.id),
                    "name": p.name,
                    "sku": p.sku,
                    "price": float(p.price),
                },
                "reasons": reasons,
                "confidence": None,
                "confidence_label": (
                    "Confidence unavailable"
                ),
            }
        )

    db.commit()

    return {
        "recommendation_id": str(
            rec.id
        ),
        "query": rec.query,
        "items": out,
    }


@router.post(
    "/recommendations/{recommendation_id}/explanation/actions"
)
def recommendation_action(
    recommendation_id: uuid.UUID,
    product_id: uuid.UUID | None = None,
    action: str = Query(
        ...,
        pattern="^(save|delete|share|regenerate)$",
    ),
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Record actions taken on recommendation explanations."""

    if not config.RECOMMENDATION_INTELLIGENCE_ENABLED:
        raise HTTPException(
            status_code=403,
            detail=(
                "Recommendation intelligence "
                "is disabled."
            ),
        )

    if action == "regenerate":
        rec = (
            db.query(ProductRecommendation)
            .filter_by(
                id=recommendation_id,
                organization_id=org.id,
                user_id=user.id,
            )
            .first()
        )

        if not rec:
            raise HTTPException(
                status_code=404,
                detail="Recommendation not found.",
            )

        from app.api.phase4_routes import (
            _run_recommendation,
        )

        new_rec, _products = _run_recommendation(
            db,
            org,
            user,
            query=rec.query,
            limit=max(
                len(
                    rec.product_ids or []
                ),
                1,
            )
            or 6,
        )

        from app.services.audit_service import (
            log_event,
        )

        log_event(
            db,
            event_type=(
                "RECOMMENDATION_REGENERATED"
            ),
            user=user,
            resource_type=(
                "product_recommendation"
            ),
            resource_id=str(
                new_rec.id
            ),
            detail={
                "source_recommendation_id": (
                    str(rec.id)
                )
            },
        )

        db.commit()

        return {
            "status": "regenerated",
            "action": action,
            "recommendation_id": (
                str(new_rec.id)
            ),
            "product_ids": (
                new_rec.product_ids
            ),
        }

    if product_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "product_id is required "
                "for this action."
            ),
        )

    exp = (
        db.query(
            RecommendationExplanation
        )
        .filter_by(
            recommendation_id=recommendation_id,
            product_id=product_id,
            organization_id=org.id,
            user_id=user.id,
        )
        .first()
    )

    if not exp:
        raise HTTPException(
            status_code=404,
            detail=(
                "Recommendation explanation "
                "not found."
            ),
        )

    exp.action = action

    db.commit()

    return {
        "status": "recorded",
        "action": action,
    }


# ===========================================================================
# Feature 7: Citation / Source Explorer
# ===========================================================================


@router.get(
    "/conversations/{conversation_id}/source-explorer"
)
def source_explorer(
    conversation_id: uuid.UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = (
        db.query(Conversation)
        .filter_by(
            id=conversation_id,
            user_id=user.id,
        )
        .first()
    )

    if not conv:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    rows = (
        db.query(ConversationCitation)
        .filter_by(
            conversation_id=conversation_id
        )
        .order_by(
            ConversationCitation.created_at.desc()
        )
        .all()
    )

    return [
        {
            "id": str(r.id),
            "document": r.document_name,
            "title": getattr(
                r,
                "title",
                None,
            ),
            "heading": r.heading,
            "passage": r.relevant_passage,
            "document_version": getattr(
                r,
                "document_version",
                None,
            ),
            "source_type": getattr(
                r,
                "source_type",
                None,
            ),
            "updated_at": getattr(
                r,
                "updated_at",
                None,
            ),
            "relevance_score": getattr(
                r,
                "relevance_score",
                None,
            ),
        }
        for r in rows
    ]
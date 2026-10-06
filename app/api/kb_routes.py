"""Admin-only Knowledge Base routes (Phase 2, Features 13 & 14).

Every route here requires the `admin` (or `super_admin`) role -- see the
Phase 2 brief's Role Protection section ("Admin-only: /admin/knowledge...").
A customer or support_agent-only account gets a 403, enforced server-side
via `require_roles`, never by the frontend hiding a nav link (same pattern
`app/auth/deps.py` already documents for Phase 1 routes).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agent import Agent
from app.api.conversations_routes import get_agent_dependency
from app import config
from app.auth.deps import require_roles
from app.security.rate_limit_deps import rate_limit_by_user
from app.api.web_schemas import (
    KBDashboardOut,
    KBDocumentCreateRequest,
    KBDocumentDetailOut,
    KBDocumentOut,
    KBDocumentUpdateRequest,
    KBIndexJobOut,
)
from app.db.base import get_db
from app.db.models import KnowledgeDocument, KnowledgeIndexJob, User
from app.services import kb_service
from app.services.indexing_service import ExtractionError, extract_text, run_full_reindex, run_single_document_index

router = APIRouter(prefix="/admin/knowledge", tags=["knowledge-base"])

_ADMIN = require_roles("admin", "super_admin")

_EXT_TO_CONTENT_TYPE = {".md": "markdown", ".markdown": "markdown", ".txt": "text/plain", ".pdf": "pdf", ".docx": "docx"}


def _infer_content_type(filename: str, given: str | None) -> str:
    if given:
        return given
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mapped = _EXT_TO_CONTENT_TYPE.get(ext)
    if mapped == "text/plain":
        return "txt"
    return mapped or "txt"


def _document_detail(db: Session, document: KnowledgeDocument) -> KBDocumentDetailOut:
    version = kb_service.get_current_version(db, document)
    versions = kb_service.list_versions(db, document)
    payload = KBDocumentOut.model_validate(document).model_dump()
    payload["content"] = version.content if version else ""
    payload["content_type"] = version.content_type if version else "markdown"
    payload["versions"] = versions
    return KBDocumentDetailOut.model_validate(payload)


def _get_document_or_404(document_id: uuid.UUID, db: Session) -> KnowledgeDocument:
    doc = db.get(KnowledgeDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@router.get("/summary", response_model=KBDashboardOut)
def summary(user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> KBDashboardOut:
    return KBDashboardOut(**kb_service.dashboard_summary(db))


@router.get("", response_model=dict)
def list_documents(
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
) -> dict:
    page_size = min(max(page_size, 1), 100)
    rows, total = kb_service.list_documents(db, status=status, category=category, search=search, page=page, page_size=page_size)
    return {
        "items": [KBDocumentOut.model_validate(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=KBDocumentDetailOut, status_code=201)
def create_document(
    payload: KBDocumentCreateRequest, user: User = Depends(_ADMIN), db: Session = Depends(get_db)
) -> KBDocumentDetailOut:
    try:
        doc = kb_service.create_document(
            db,
            title=payload.title,
            category=payload.category,
            content=payload.content,
            content_type=payload.content_type,
            source_filename=None,
            author_id=user.id,
        )
    except kb_service.KBError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(doc)
    return _document_detail(db, doc)


@router.post(
    "/upload",
    response_model=KBDocumentDetailOut,
    status_code=201,
    dependencies=[Depends(rate_limit_by_user("kb_upload", "RATE_LIMIT_KB_UPLOAD"))],
)
async def upload_document(
    title: str = Form(...),
    category: str = Form("general"),
    file: UploadFile = File(...),
    content_type: str | None = Form(None),
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
) -> KBDocumentDetailOut:
    raw = await file.read()
    # Basic file validation (Feature 13 security requirements: file size,
    # type). 10 MB is generous for the Markdown/TXT/PDF/DOCX policy
    # documents this feature is meant for.
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (10 MB limit).")
    resolved_type = _infer_content_type(file.filename or "", content_type)
    try:
        text = extract_text(raw, resolved_type)
        doc = kb_service.create_document(
            db,
            title=title,
            category=category,
            content=text,
            content_type=resolved_type,
            source_filename=file.filename,
            author_id=user.id,
        )
    except (kb_service.KBError, ExtractionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(doc)
    return _document_detail(db, doc)


@router.get("/{document_id}", response_model=KBDocumentDetailOut)
def get_document(document_id: uuid.UUID, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> KBDocumentDetailOut:
    doc = _get_document_or_404(document_id, db)
    return _document_detail(db, doc)


@router.patch("/{document_id}", response_model=KBDocumentDetailOut)
def update_document(
    document_id: uuid.UUID, payload: KBDocumentUpdateRequest, user: User = Depends(_ADMIN), db: Session = Depends(get_db)
) -> KBDocumentDetailOut:
    doc = _get_document_or_404(document_id, db)
    if payload.title is not None:
        doc.title = payload.title.strip()[:200]
    if payload.category is not None:
        doc.category = payload.category.strip()[:60] or "general"
    if payload.content is not None:
        try:
            kb_service.add_version(
                db,
                doc,
                content=payload.content,
                content_type=payload.content_type or "markdown",
                source_filename=None,
                created_by=user.id,
            )
        except kb_service.KBError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(doc)
    return _document_detail(db, doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> None:
    doc = _get_document_or_404(document_id, db)
    try:
        kb_service.delete_document(db, doc)
    except kb_service.KBError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return None


def _reindex_after_status_change(db: Session, doc: KnowledgeDocument, agent: Agent) -> None:
    """Publishing, unpublishing, and archiving all change whether a
    document's chunks should be in the live index, so each one kicks off
    a single-document re-index job automatically (Feature 13's publishing
    workflow diagram: Publish -> Index -> Available to RAG).

    Runs the job function synchronously rather than deferring it via
    FastAPI `BackgroundTasks`: Starlette executes background tasks *after*
    the response body has already been serialized, so a deferred job could
    never be reflected in this same response's `index_status` -- and since
    this app's indexing pipeline embeds with a deterministic in-process
    embedder (no real network call, see app/embeddings.py), running it
    inline adds negligible latency. `run_single_document_index` /
    `run_full_reindex` are still separate, independently callable
    functions with their own DB session, so swapping this one call site
    for `background_tasks.add_task(...)` (true deferred execution, for a
    slower real embedding backend) is a one-line change, not a redesign.
    """
    job = KnowledgeIndexJob(document_id=doc.id, job_type="single", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    run_single_document_index(agent, job.id)


@router.post("/{document_id}/publish", response_model=KBDocumentDetailOut)
def publish_document(
    document_id: uuid.UUID,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> KBDocumentDetailOut:
    doc = _get_document_or_404(document_id, db)
    try:
        kb_service.publish(doc)
    except kb_service.KBError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    _reindex_after_status_change(db, doc, agent)
    db.refresh(doc)
    return _document_detail(db, doc)


@router.post("/{document_id}/unpublish", response_model=KBDocumentDetailOut)
def unpublish_document(
    document_id: uuid.UUID,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> KBDocumentDetailOut:
    doc = _get_document_or_404(document_id, db)
    try:
        kb_service.unpublish(doc)
    except kb_service.KBError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    _reindex_after_status_change(db, doc, agent)
    db.refresh(doc)
    return _document_detail(db, doc)


@router.post("/{document_id}/archive", response_model=KBDocumentDetailOut)
def archive_document(
    document_id: uuid.UUID,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> KBDocumentDetailOut:
    doc = _get_document_or_404(document_id, db)
    kb_service.archive(doc)
    db.commit()
    _reindex_after_status_change(db, doc, agent)
    db.refresh(doc)
    return _document_detail(db, doc)


@router.post("/{document_id}/restore", response_model=KBDocumentDetailOut)
def restore_document(document_id: uuid.UUID, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> KBDocumentDetailOut:
    doc = _get_document_or_404(document_id, db)
    try:
        kb_service.restore_to_draft(doc)
    except kb_service.KBError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(doc)
    return _document_detail(db, doc)


@router.post("/{document_id}/reindex", response_model=KBIndexJobOut, status_code=202)
def reindex_document(
    document_id: uuid.UUID,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> KBIndexJobOut:
    doc = _get_document_or_404(document_id, db)
    job = KnowledgeIndexJob(document_id=doc.id, job_type="single", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    run_single_document_index(agent, job.id)
    db.refresh(job)
    return KBIndexJobOut.model_validate(job)


@router.post("/reindex-all", response_model=KBIndexJobOut, status_code=202)
def reindex_all(
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> KBIndexJobOut:
    job = KnowledgeIndexJob(document_id=None, job_type="full", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    run_full_reindex(agent, job.id)
    db.refresh(job)
    return KBIndexJobOut.model_validate(job)


# --- index jobs (separate prefix: GET /admin/index-jobs, per Feature 14) --
index_jobs_router = APIRouter(prefix="/admin/index-jobs", tags=["knowledge-base"])


@index_jobs_router.get("", response_model=dict)
def list_index_jobs(
    document_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
) -> dict:
    page_size = min(max(page_size, 1), 100)
    query = db.query(KnowledgeIndexJob)
    if document_id is not None:
        query = query.filter(KnowledgeIndexJob.document_id == document_id)
    if status is not None:
        query = query.filter(KnowledgeIndexJob.status == status)
    total = query.count()
    rows = query.order_by(KnowledgeIndexJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [KBIndexJobOut.model_validate(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@index_jobs_router.get("/{job_id}", response_model=KBIndexJobOut)
def get_index_job(job_id: uuid.UUID, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> KBIndexJobOut:
    job = db.get(KnowledgeIndexJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Index job not found.")
    return KBIndexJobOut.model_validate(job)

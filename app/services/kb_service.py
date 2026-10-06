"""Knowledge Base admin: document CRUD, versioning, and the publish
workflow (Phase 2, Feature 13).

Design notes:
- Editing a document never mutates an existing `KnowledgeDocumentVersion`
  row -- every save creates a new version and repoints
  `KnowledgeDocument.current_version` at it (Feature 13: "Do not silently
  overwrite historical versions.").
- A document only participates in live retrieval once it is *published
  and successfully indexed* -- see `app/services/indexing_service.py`.
  Creating/editing a document alone never makes it authoritative
  (Feature 13: "A draft should NOT automatically become authoritative
  knowledge.").
- Deleting is only allowed for documents that are `draft` or already
  `archived`; a `published` document must be archived first. This keeps
  a real "someone can permanently erase what customers were told" action
  from being one click, while still allowing genuine cleanup of drafts/
  archived material (Feature 13 lists both "archive" and "delete" as
  distinct actions).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import KnowledgeDocument, KnowledgeDocumentVersion

ALLOWED_CONTENT_TYPES = {"markdown", "txt", "pdf", "docx"}


class KBError(Exception):
    """Raised for invalid Knowledge Base admin operations (bad status
    transitions, unsupported file types, etc). Routes translate this to a
    400 response."""


def create_document(
    db: Session,
    *,
    title: str,
    category: str,
    content: str,
    content_type: str,
    source_filename: str | None,
    author_id: uuid.UUID,
) -> KnowledgeDocument:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise KBError(f"Unsupported content type: {content_type}")
    if not content.strip():
        raise KBError("Document content is empty.")

    doc = KnowledgeDocument(title=title.strip()[:200], category=(category or "general").strip()[:60], author_id=author_id)
    db.add(doc)
    db.flush()

    version = KnowledgeDocumentVersion(
        document_id=doc.id,
        version=1,
        content=content,
        content_type=content_type,
        source_filename=source_filename,
        created_by=author_id,
    )
    db.add(version)
    doc.current_version = 1
    db.flush()
    return doc


def add_version(
    db: Session,
    document: KnowledgeDocument,
    *,
    content: str,
    content_type: str,
    source_filename: str | None,
    created_by: uuid.UUID,
) -> KnowledgeDocumentVersion:
    if document.status == "archived":
        raise KBError("Cannot edit an archived document. Restore it to draft first.")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise KBError(f"Unsupported content type: {content_type}")
    if not content.strip():
        raise KBError("Document content is empty.")

    next_version = document.current_version + 1
    version = KnowledgeDocumentVersion(
        document_id=document.id,
        version=next_version,
        content=content,
        content_type=content_type,
        source_filename=source_filename,
        created_by=created_by,
    )
    db.add(version)
    document.current_version = next_version
    # New, not-yet-indexed content -- a stale index for the old version
    # must never be reported as "completed" for the new one.
    document.index_status = "not_indexed"
    db.flush()
    return version


def get_current_version(db: Session, document: KnowledgeDocument) -> KnowledgeDocumentVersion | None:
    return (
        db.query(KnowledgeDocumentVersion)
        .filter(
            KnowledgeDocumentVersion.document_id == document.id,
            KnowledgeDocumentVersion.version == document.current_version,
        )
        .first()
    )


def list_versions(db: Session, document: KnowledgeDocument) -> list[KnowledgeDocumentVersion]:
    return (
        db.query(KnowledgeDocumentVersion)
        .filter(KnowledgeDocumentVersion.document_id == document.id)
        .order_by(KnowledgeDocumentVersion.version.desc())
        .all()
    )


def publish(document: KnowledgeDocument) -> None:
    if document.status == "archived":
        raise KBError("Cannot publish an archived document. Restore it to draft first.")
    document.status = "published"
    document.published_at = datetime.now(timezone.utc)


def unpublish(document: KnowledgeDocument) -> None:
    if document.status != "published":
        raise KBError("Document is not published.")
    document.status = "draft"


def archive(document: KnowledgeDocument) -> None:
    document.status = "archived"
    document.archived_at = datetime.now(timezone.utc)


def restore_to_draft(document: KnowledgeDocument) -> None:
    if document.status != "archived":
        raise KBError("Only an archived document can be restored.")
    document.status = "draft"
    document.archived_at = None


def delete_document(db: Session, document: KnowledgeDocument) -> None:
    if document.status == "published":
        raise KBError("Archive a published document before deleting it.")
    db.delete(document)  # cascades to versions/index jobs via ORM cascade


def list_documents(
    db: Session,
    *,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[KnowledgeDocument], int]:
    query = db.query(KnowledgeDocument)
    if status:
        query = query.filter(KnowledgeDocument.status == status)
    if category:
        query = query.filter(KnowledgeDocument.category == category)
    if search:
        query = query.filter(KnowledgeDocument.title.ilike(f"%{search}%"))
    total = query.with_entities(func.count(KnowledgeDocument.id)).scalar() or 0
    rows = (
        query.order_by(KnowledgeDocument.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def dashboard_summary(db: Session) -> dict:
    total = db.query(func.count(KnowledgeDocument.id)).scalar() or 0
    published = db.query(func.count(KnowledgeDocument.id)).filter(KnowledgeDocument.status == "published").scalar() or 0
    drafts = db.query(func.count(KnowledgeDocument.id)).filter(KnowledgeDocument.status == "draft").scalar() or 0
    archived = db.query(func.count(KnowledgeDocument.id)).filter(KnowledgeDocument.status == "archived").scalar() or 0
    failed_index = db.query(func.count(KnowledgeDocument.id)).filter(KnowledgeDocument.index_status == "failed").scalar() or 0
    last_indexed = db.query(func.max(KnowledgeDocument.last_indexed_at)).scalar()
    return {
        "documents": total,
        "published": published,
        "drafts": drafts,
        "archived": archived,
        "failed_index": failed_index,
        "index_healthy": failed_index == 0,
        "last_indexed_at": last_indexed,
    }

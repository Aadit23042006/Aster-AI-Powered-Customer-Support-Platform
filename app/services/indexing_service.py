"""Feature 14: automatic re-indexing.

Extracts text from an uploaded file, chunks it (reusing
`app.kb_loader.chunks_from_body`, the exact same chunker the original
Markdown corpus uses -- see that function's docstring), embeds the chunks
with the *live* retriever's own embedder, and adds/replaces/removes them in
the live `Retriever` (see the Feature 14 additions in `app/retriever.py`).

Runs via FastAPI `BackgroundTasks`, not a new queue system: Phase 1 has no
Celery/Redis worker to integrate with instead (see module docstring in
`app/db/models.py::KnowledgeIndexJob` and the Phase 2 brief's own
"if Redis/Celery exists, integrate with it rather than creating another
queue system" instruction -- neither exists here). Each job gets its own DB
session (`SessionLocal`, not the request-scoped one) since it keeps running
after the HTTP response has already been returned to the client.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent import Agent
from app.db.base import SessionLocal
from app.db.models import (
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexJob,
)
from app.kb_loader import Chunk, chunks_from_body
from app.services import kb_service


class ExtractionError(Exception):
    """A file's text could not be extracted.

    Corrupt files, unsupported encodings, and unsupported content types are
    reported as clean indexing failures rather than HTTP 500 errors.
    """


def extract_text(raw: bytes, content_type: str) -> str:
    """Best-effort text extraction for the four Feature 13 file types.

    Markdown/TXT are decoded directly as UTF-8.
    PDF/DOCX use pypdf/python-docx.
    """
    if content_type in ("markdown", "txt"):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtractionError(
                f"Could not decode file as UTF-8 text: {exc}"
            ) from exc

    if content_type == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise ExtractionError(
                "PDF support requires the 'pypdf' package "
                "(see requirements.txt)."
            ) from exc

        try:
            reader = PdfReader(io.BytesIO(raw))

            return "\n\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError(
                f"Could not parse PDF: {exc}"
            ) from exc

    if content_type == "docx":
        try:
            import docx
        except ImportError as exc:  # pragma: no cover
            raise ExtractionError(
                "DOCX support requires the 'python-docx' package "
                "(see requirements.txt)."
            ) from exc

        try:
            document = docx.Document(io.BytesIO(raw))

            return "\n\n".join(
                paragraph.text
                for paragraph in document.paragraphs
            )
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError(
                f"Could not parse DOCX: {exc}"
            ) from exc

    raise ExtractionError(
        f"Unsupported content type: {content_type}"
    )


def source_file_for(document_id: uuid.UUID) -> str:
    """Return the unique live-index source key for an admin KB document.

    Admin-authored documents use a `kb-doc:` namespace so their chunks
    cannot collide with the original Markdown corpus filenames such as
    `01-returns-policy-current.md`.
    """
    return f"kb-doc:{document_id}"


def chunks_for_document(
    document: KnowledgeDocument,
    version: KnowledgeDocumentVersion,
) -> list[Chunk]:
    """Build retriever chunks for one knowledge-base document version.

    The chunks intentionally use the same metadata shape expected by
    `app.kb_loader.py` for active/official/customer-facing content.

    In addition, citation metadata is copied into every chunk so that
    `app.enterprise.citations.build_citations()` can persist complete
    Source Explorer information without needing another database lookup.

    Specifically:

    - `version`               -> KB version number
    - `document_version`      -> string representation of the version
    - `updated_at`            -> best available authoritative timestamp
    - `published_at`          -> publication timestamp when available
    """
    # Prefer the actual version publication timestamp. If that is not
    # available, use the document-level publication timestamp. For a draft
    # or unpublished version, fall back to the document/version update/create
    # timestamps so citation metadata still has a real timestamp.
    metadata_timestamp = (
        version.published_at
        or document.published_at
        or document.updated_at
        or version.created_at
    )

    metadata = {
        # Existing retrieval / authorization metadata.
        "status": (
            "active"
            if document.status == "published"
            else "draft"
        ),
        "policy_authority": "official",
        "audience": "customer",
        "customer_answering": True,

        # Document identity.
        "document_id": str(document.id),
        "category": document.category,

        # Version metadata.
        #
        # `build_citations()` already reads `version` first, so retaining
        # this field preserves compatibility with the existing citation
        # implementation.
        "version": version.version,
        "document_version": str(version.version),

        # Timestamp metadata used by Source Explorer.
        "updated_at": (
            metadata_timestamp.isoformat()
            if metadata_timestamp is not None
            else None
        ),
        "published_at": (
            version.published_at.isoformat()
            if version.published_at is not None
            else (
                document.published_at.isoformat()
                if document.published_at is not None
                else None
            )
        ),

        # Identifies this as an admin-created KB document.
        "kb_source": "admin",
    }

    return chunks_from_body(
        source_file=source_file_for(document.id),
        document_id=str(document.id),
        title=document.title,
        body=version.content,
        metadata=metadata,
    )


def _mark_job(
    db: Session,
    job: KnowledgeIndexJob,
    *,
    status: str,
    error: str | None = None,
    documents_indexed: int | None = None,
) -> None:
    """Update and persist an indexing-job status."""
    job.status = status

    if error is not None:
        job.error = error[:2000]

    if documents_indexed is not None:
        job.documents_indexed = documents_indexed

    if status == "processing" and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)

    if status in ("completed", "failed"):
        job.completed_at = datetime.now(timezone.utc)

    db.commit()


def run_single_document_index(
    agent: Agent,
    job_id: uuid.UUID,
) -> None:
    """Background-task entry point for indexing/re-indexing one document.

    A document is only added to live customer retrieval when its status is
    `published`.

    Draft and archived documents have their previous live chunks removed so
    stale published content cannot remain searchable.
    """
    db = SessionLocal()

    try:
        job = db.get(
            KnowledgeIndexJob,
            job_id,
        )

        if job is None:
            return

        document = db.get(
            KnowledgeDocument,
            job.document_id,
        )

        if document is None:
            _mark_job(
                db,
                job,
                status="failed",
                error="Document no longer exists.",
            )
            return

        _mark_job(
            db,
            job,
            status="processing",
        )

        document.index_status = "processing"
        db.commit()

        try:
            version = kb_service.get_current_version(
                db,
                document,
            )

            if version is None:
                raise ExtractionError(
                    "Document has no content version to index."
                )

            # Only published documents are placed into the live searchable
            # retrieval index.
            chunks = (
                chunks_for_document(
                    document,
                    version,
                )
                if document.status == "published"
                else []
            )

            source_file = source_file_for(
                document.id,
            )

            if chunks:
                texts = [
                    chunk.text
                    for chunk in chunks
                ]

                raw_vectors = (
                    agent.retriever.embedder.embed_documents(
                        texts
                    )
                )

                agent.retriever.replace_document_chunks(
                    source_file,
                    chunks,
                    raw_vectors,
                )
            else:
                # Draft/archived documents must not remain searchable.
                agent.retriever.replace_document_chunks(
                    source_file,
                    [],
                    [],
                )

            document.index_status = "completed"
            document.index_error = None
            document.last_indexed_at = datetime.now(
                timezone.utc
            )

            db.commit()

            _mark_job(
                db,
                job,
                status="completed",
                documents_indexed=1,
            )

        except Exception as exc:  # noqa: BLE001
            # Roll back the failed transaction before loading the job/document
            # again.
            db.rollback()

            job = db.get(
                KnowledgeIndexJob,
                job_id,
            )

            document = (
                db.get(
                    KnowledgeDocument,
                    job.document_id,
                )
                if job
                else None
            )

            if document is not None:
                document.index_status = "failed"
                document.index_error = str(exc)[:2000]
                db.commit()

            if job is not None:
                _mark_job(
                    db,
                    job,
                    status="failed",
                    error=str(exc),
                )

    finally:
        db.close()


def run_full_reindex(
    agent: Agent,
    job_id: uuid.UUID,
) -> None:
    """Background-task entry point for a full admin KB re-index.

    Rebuilds only the admin-authored portion of the live index.

    The original Markdown corpus remains untouched because only source keys
    beginning with `kb-doc:` are replaced or removed.
    """
    db = SessionLocal()

    try:
        job = db.get(
            KnowledgeIndexJob,
            job_id,
        )

        if job is None:
            return

        _mark_job(
            db,
            job,
            status="processing",
        )

        indexed = 0

        try:
            documents = (
                db.query(
                    KnowledgeDocument
                ).all()
            )

            for document in documents:
                source_file = source_file_for(
                    document.id,
                )

                # Draft/archived documents must not have stale live chunks.
                if document.status != "published":
                    agent.retriever.replace_document_chunks(
                        source_file,
                        [],
                        [],
                    )

                    if document.index_status not in (
                        "not_indexed",
                    ):
                        if document.status == "draft":
                            document.index_status = "not_indexed"

                    continue

                version = kb_service.get_current_version(
                    db,
                    document,
                )

                if version is None:
                    continue

                document.index_status = "processing"
                db.commit()

                try:
                    chunks = chunks_for_document(
                        document,
                        version,
                    )

                    texts = [
                        chunk.text
                        for chunk in chunks
                    ]

                    raw_vectors = (
                        agent.retriever.embedder.embed_documents(
                            texts
                        )
                        if texts
                        else []
                    )

                    agent.retriever.replace_document_chunks(
                        source_file,
                        chunks,
                        raw_vectors,
                    )

                    document.index_status = "completed"
                    document.index_error = None
                    document.last_indexed_at = datetime.now(
                        timezone.utc
                    )

                    indexed += 1

                except Exception as doc_exc:  # noqa: BLE001
                    # One bad document must not abort the entire re-index.
                    document.index_status = "failed"
                    document.index_error = str(doc_exc)[:2000]

                db.commit()

            _mark_job(
                db,
                job,
                status="completed",
                documents_indexed=indexed,
            )

        except Exception as exc:  # noqa: BLE001
            db.rollback()

            job = db.get(
                KnowledgeIndexJob,
                job_id,
            )

            if job is not None:
                _mark_job(
                    db,
                    job,
                    status="failed",
                    error=str(exc),
                    documents_indexed=indexed,
                )

    finally:
        db.close()
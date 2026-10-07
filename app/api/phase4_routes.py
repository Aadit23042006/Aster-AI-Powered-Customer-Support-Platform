from __future__ import annotations

import base64
import io
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.base import get_db
from app.services import conversation_service
from app.db.models import *
from app.phase4 import *


router = APIRouter(prefix="/api/v1", tags=["phase4"])

logger = logging.getLogger(__name__)


# ============================================================================
# Webhook events
# ============================================================================

BASE_WEBHOOK_EVENTS = set(WEBHOOK_EVENTS)

SUPPORTED_WEBHOOK_EVENTS = BASE_WEBHOOK_EVENTS | {
    # Tickets
    "ticket.created",
    "ticket.updated",
    "ticket.resolved",
    "ticket.closed",
    "ticket.reopened",

    # Orders
    "order.created",
    "order.updated",
    "order.shipped",
    "order.delivered",
    "order.cancelled",

    # Returns / refunds
    "return.created",
    "return.updated",
    "refund.created",
    "refund.updated",

    # Conversations / support
    "conversation.created",
    "conversation.updated",
    "conversation.closed",

    # Human handoff
    "handoff.created",
    "handoff.updated",

    # Knowledge base
    "knowledge_base.created",
    "knowledge_base.updated",
    "knowledge_base.published",

    # AI / feedback
    "feedback.created",
}


# ============================================================================
# Request models
# ============================================================================

class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class MemberCreate(BaseModel):
    user_id: UUID
    role: str = "member"


class LanguagePatch(BaseModel):
    preferred_language: str


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: str | None = None
    category: str | None = None
    price: float = Field(ge=0)
    currency: str = "USD"
    inventory_status: str = "in_stock"
    attributes: dict | None = None
    image_url: str | None = None


class RecommendationQuery(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=500,
    )
    budget: float | None = Field(
        default=None,
        ge=0,
    )
    category: str | None = Field(
        default=None,
        max_length=100,
    )
    limit: int = Field(
        default=6,
        ge=1,
        le=20,
    )


class PersonaCreate(BaseModel):
    name: str
    description: str | None = None
    tone: str = "friendly"
    style: str = "professional"
    formality: str = "neutral"
    response_length: str = "concise"
    language: str = "en"
    brand_voice: str | None = None
    greeting: str | None = None
    closing: str | None = None
    custom_instructions: str | None = None


class PersonaPatch(PersonaCreate):
    pass


class KBCreate(BaseModel):
    name: str
    description: str | None = None
    visibility: str = "private"


class LinkDoc(BaseModel):
    document_id: UUID


class APIKeyCreate(BaseModel):
    name: str
    scopes: list[str] = []
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
    )


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(min_length=1)


# ============================================================================
# Helpers
# ============================================================================

def _org(db, user):
    return get_or_create_default_org(db, user)


def _normalize_webhook_events(events: list[str]) -> list[str]:
    normalized: list[str] = []

    for event in events:
        if not isinstance(event, str):
            continue

        value = event.strip().lower()

        if value and value not in normalized:
            normalized.append(value)

    return normalized


def _validate_webhook_events(events: list[str]) -> list[str]:
    normalized = _normalize_webhook_events(events)

    if not normalized:
        raise HTTPException(
            status_code=400,
            detail="At least one webhook event is required",
        )

    unsupported = [
        event
        for event in normalized
        if event not in SUPPORTED_WEBHOOK_EVENTS
    ]

    if unsupported:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Unsupported webhook event",
                "unsupported_events": unsupported,
                "supported_events": sorted(SUPPORTED_WEBHOOK_EVENTS),
            },
        )

    return normalized


# ============================================================================
# Organizations
# ============================================================================

@router.get("/organizations")
def organizations(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Organization, OrganizationMember.role)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
        .all()
    )

    if not rows:
        rows = [(_org(db, user), "owner")]

    return [
        {
            "id": str(o.id),
            "name": o.name,
            "slug": o.slug,
            "status": o.status,
            "plan": o.plan,
            "role": role,
        }
        for o, role in rows
    ]


@router.post("/organizations", status_code=201)
def create_org(
    p: OrgCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    slug = slugify(p.name)
    base = slug
    i = 2

    while db.query(Organization).filter_by(slug=slug).first():
        slug = f"{base}-{i}"
        i += 1

    organization = Organization(
        name=p.name.strip(),
        slug=slug,
    )

    db.add(organization)
    db.flush()

    db.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role="owner",
        )
    )

    db.commit()

    return {
        "id": str(organization.id),
        "name": organization.name,
        "slug": organization.slug,
        "role": "owner",
    }


@router.post("/organizations/{org_id}/members", status_code=201)
def add_member(
    org_id: UUID,
    p: MemberCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, org_id)

    if not organization:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    admin = (
        db.query(OrganizationMember)
        .filter_by(
            organization_id=org_id,
            user_id=user.id,
            status="active",
        )
        .first()
    )

    if not admin or admin.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    target = db.get(User, p.user_id)

    if not target:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if p.role not in {"member", "admin"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid organization role",
        )

    existing = (
        db.query(OrganizationMember)
        .filter_by(
            organization_id=org_id,
            user_id=p.user_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="User is already a member",
        )

    member = OrganizationMember(
        organization_id=org_id,
        user_id=p.user_id,
        role=p.role,
    )

    db.add(member)
    db.commit()

    return {
        "id": str(member.id),
        "user_id": str(member.user_id),
        "role": member.role,
    }


@router.get("/organizations/{org_id}/members")
def list_members(
    org_id: UUID,
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    if org.id != org_id:
        raise HTTPException(
            status_code=403,
            detail="Wrong organization context",
        )

    rows = (
        db.query(OrganizationMember, User)
        .join(
            User,
            User.id == OrganizationMember.user_id,
        )
        .filter(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.status == "active",
        )
        .all()
    )

    return [
        {
            "user_id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": member.role,
        }
        for member, user in rows
    ]


# ============================================================================
# Languages
# ============================================================================

@router.get("/languages")
def languages():
    return SUPPORTED_LANGUAGES


@router.post("/languages/detect")
def language_detect(payload: dict):
    text = str(payload.get("text", ""))

    code = detect_language(text)

    return {
        "language": code,
        "name": SUPPORTED_LANGUAGES[code],
    }


@router.patch("/users/me/preferences/language")
def set_language(
    p: LanguagePatch,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if p.preferred_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported language",
        )

    preference = (
        db.query(UserLanguagePreference)
        .filter_by(user_id=user.id)
        .first()
    )

    if not preference:
        preference = UserLanguagePreference(
            user_id=user.id,
            preferred_language=p.preferred_language,
        )
        db.add(preference)
    else:
        preference.preferred_language = p.preferred_language

    db.commit()

    return {
        "preferred_language": preference.preferred_language,
    }


@router.get("/users/me/preferences/language")
def get_language(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    preference = (
        db.query(UserLanguagePreference)
        .filter_by(user_id=user.id)
        .first()
    )

    return {
        "preferred_language": (
            preference.preferred_language
            if preference
            else "en"
        )
    }


# Feature 29 (Voice) has been retired.

# ============================================================================
# Chat attachments
# ============================================================================

CHAT_ATTACHMENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

CHAT_ATTACHMENT_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".pdf", ".doc", ".docx",
    ".txt", ".csv", ".md", ".json",
    ".xls", ".xlsx",
}


def _attachment_public_meta(row: MediaAttachment) -> dict:
    return {
        "id": str(row.id),
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "analysis": row.analysis_text,
        "analysis_status": row.analysis_status,
        "conversation_id": (
            str(row.conversation_id)
            if row.conversation_id
            else None
        ),
        "message_id": (
            str(row.message_id)
            if row.message_id
            else None
        ),
        "url": f"/api/v1/chat/attachments/{row.id}/content",
    }


def _extract_text_attachment(raw: bytes, content_type: str, filename: str) -> str:
    """Extract safe text context from common support-chat documents."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if content_type == "application/pdf" or suffix == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        chunks: list[str] = []
        for page in reader.pages[:50]:
            chunks.append(page.extract_text() or "")
        return "\n\n".join(chunks).strip()[:30000]

    if (
        content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or suffix == "docx"
    ):
        from docx import Document

        doc = Document(io.BytesIO(raw))
        return "\n".join(
            paragraph.text
            for paragraph in doc.paragraphs
            if paragraph.text.strip()
        ).strip()[:30000]

    if suffix in {"xlsx", "xls"} or content_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        from openpyxl import load_workbook

        workbook = load_workbook(
            io.BytesIO(raw),
            read_only=True,
            data_only=True,
        )
        lines: list[str] = []
        for sheet in workbook.worksheets[:10]:
            lines.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(
                min_row=1,
                max_row=200,
                values_only=True,
            ):
                values = [
                    str(value).strip()
                    for value in row
                    if value is not None and str(value).strip()
                ]
                if values:
                    lines.append(" | ".join(values))
        return "\n".join(lines).strip()[:30000]

    if content_type.startswith("text/") or suffix in {
        "txt", "csv", "md", "json"
    }:
        return raw.decode("utf-8", errors="replace").strip()[:30000]

    return ""


@router.get("/chat/attachments")
def list_chat_attachments(
    conversation_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List every attachment belonging to a caller-owned conversation.

    This endpoint is intentionally separate from messages because an attachment
    can be uploaded before the user asks a question. Such an attachment must
    still be visible after refresh/reopen, even before a Message row exists.
    """
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    rows = (
        db.query(MediaAttachment)
        .filter(
            MediaAttachment.conversation_id == conversation_id,
            MediaAttachment.user_id == user.id,
        )
        .order_by(MediaAttachment.created_at.asc())
        .all()
    )
    return [_attachment_public_meta(row) for row in rows]


@router.post("/chat/attachments", status_code=201)
async def chat_attachment(
    file: UploadFile = File(...),
    conversation_id: UUID | None = Form(None),
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Upload a secure chat attachment and keep it visible in the conversation."""
    from app import config

    filename = (file.filename or "attachment").strip()[:255]

    suffix = (
        f".{filename.rsplit('.', 1)[-1].lower()}"
        if "." in filename
        else ""
    )

    content_type = (
        file.content_type
        or "application/octet-stream"
    )

    # Phase 4 chat attachments must be images.
    # Reject PDFs, TXT, DOCX, CSV, JSON, spreadsheets, etc.
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Only image attachments are supported.",
        )

    raw = await file.read()

    max_size = (
        config.CHAT_ATTACHMENT_MAX_SIZE_MB * 1024 * 1024
    )

    if len(raw) > max_size:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File exceeds the maximum size of "
                f"{config.CHAT_ATTACHMENT_MAX_SIZE_MB} MB"
            ),
        )

    if not raw:
        raise HTTPException(
            status_code=400,
            detail="The attached file is empty.",
        )

    # Conversation ownership / automatic conversation creation.
    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter_by(
                id=conversation_id,
                user_id=user.id,
            )
            .first()
        )

        if not conversation:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )
    else:
        conversation = conversation_service.create_conversation(
            db,
            user_id=user.id,
            title="File question",
        )
        conversation_id = conversation.id

    row = MediaAttachment(
        user_id=user.id,
        organization_id=org.id,
        conversation_id=conversation_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(raw),
        file_data=raw,
        analysis_status="pending",
    )

    db.add(row)
    db.flush()

    try:
        is_image = content_type.startswith("image/") or suffix in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }

        if is_image:
            if not config.IMAGE_SUPPORT_ENABLED:
                row.analysis_text = (
                    "Image attached. Image analysis is currently disabled, "
                    "but the original image remains available in this conversation."
                )

            elif len(raw) > config.MAX_IMAGE_SIZE_MB * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Image exceeds the maximum size of "
                        f"{config.MAX_IMAGE_SIZE_MB} MB"
                    ),
                )

            else:
                from app.phase4.providers import GeminiVisionProvider

                if not config.GEMINI_API_KEY:
                    raise RuntimeError(
                        "GEMINI_API_KEY is not configured"
                    )

                models = [config.CHAT_MODEL]

                fallback_model = getattr(
                    config,
                    "CHAT_FALLBACK_MODEL",
                    "",
                )

                if (
                    fallback_model
                    and fallback_model not in models
                ):
                    models.append(fallback_model)

                analysis = ""
                last_error: Exception | None = None

                for model_name in models:
                    try:
                        provider = GeminiVisionProvider(
                            config.GEMINI_API_KEY,
                            model_name,
                        )

                        analysis = provider.analyze(
                            raw,
                            mime_type=content_type,
                            prompt=(
                                "Analyze this customer-support image. "
                                "Describe only visible, relevant facts. "
                                "Do not infer private information or make "
                                "claims not supported by the image."
                            ),
                        )

                        if analysis:
                            break

                    except Exception as exc:
                        last_error = exc

                        logger.warning(
                            "Vision analysis failed with model %s; "
                            "trying fallback: %s",
                            model_name,
                            exc,
                        )

                if analysis:
                    row.analysis_text = analysis[:10000]

                else:
                    row.analysis_text = (
                        "Image attached successfully. Automatic image "
                        "analysis is temporarily unavailable; the original "
                        "image remains available in this conversation."
                    )

                    if last_error:
                        logger.error(
                            "All configured vision models failed for %s: %s",
                            filename,
                            last_error,
                        )

        row.analysis_status = "completed"

        db.commit()
        db.refresh(row)

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Chat attachment processing failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "The attachment could not be saved. Please try again "
                "or use a supported image file."
            ),
        ) from exc

    return _attachment_public_meta(row)


@router.get("/chat/attachments/{attachment_id}/content")
def get_chat_attachment_content(
    attachment_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return an attachment only to its owner."""
    row = (
        db.query(MediaAttachment)
        .filter(
            MediaAttachment.id == attachment_id,
            MediaAttachment.user_id == user.id,
        )
        .first()
    )
    if not row or row.file_data is None:
        raise HTTPException(
            status_code=404,
            detail="Attachment not found",
        )

    from fastapi.responses import Response

    disposition = (
        "inline"
        if row.content_type.startswith("image/")
        or row.content_type == "application/pdf"
        else "attachment"
    )

    safe_name = (
        row.filename
        .replace("\r", "")
        .replace("\n", "")
        .replace('"', "")
    )

    return Response(
        content=row.file_data,
        media_type=row.content_type,
        headers={
            "Content-Disposition": (
                f'{disposition}; filename="{safe_name}"'
            ),
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/chat/attachments/{attachment_id}", status_code=204)
def delete_chat_attachment(
    attachment_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an uploaded chat attachment owned by the caller."""
    row = (
        db.query(MediaAttachment)
        .filter(
            MediaAttachment.id == attachment_id,
            MediaAttachment.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail="Attachment not found",
        )
    db.delete(row)
    db.commit()
    return None


# Products
# ============================================================================

@router.post("/products", status_code=201)
def create_product(
    p: ProductCreate,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    admin = (
        db.query(OrganizationMember)
        .filter_by(
            organization_id=org.id,
            user_id=user.id,
            status="active",
        )
        .first()
    )

    if not admin or admin.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    if (
        db.query(Product)
        .filter_by(
            organization_id=org.id,
            sku=p.sku,
        )
        .first()
    ):
        raise HTTPException(
            status_code=409,
            detail="SKU already exists",
        )

    row = Product(
        organization_id=org.id,
        **p.model_dump(),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return _product(row)


def _product(p):
    return {
        "id": str(p.id),
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "price": float(p.price),
        "currency": p.currency,
        "inventory_status": p.inventory_status,
        "attributes": p.attributes,
        "image_url": p.image_url,
        "active": p.active,
    }


@router.get("/products")
def list_products(
    q: str | None = None,
    category: str | None = None,
    limit: int = 50,
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Product)
        .filter(
            Product.organization_id == org.id,
            Product.active.is_(True),
        )
    )

    if q:
        query = query.filter(
            (Product.name.ilike(f"%{q}%"))
            | (Product.description.ilike(f"%{q}%"))
            | (Product.sku.ilike(f"%{q}%"))
        )

    if category:
        query = query.filter(
            Product.category == category
        )

    return [
        _product(product)
        for product in (
            query
            .order_by(Product.created_at.desc())
            .limit(min(limit, 100))
            .all()
        )
    ]


# ============================================================================
# Product Recommendations
# ============================================================================

# Common English stop words that should never contribute to a
# product-relevance score.
_RECOMMENDATION_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "from",
    "get",
    "give",
    "have",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "need",
    "of",
    "on",
    "or",
    "please",
    "the",
    "to",
    "want",
    "with",
    "would",
    "you",
    "your",
}


# Conservative aliases for the current Aster & Row catalog.
#
# These are intentionally small. The recommendation engine should not
# aggressively guess product intent because that can create false positives.
_RECOMMENDATION_ALIASES = {
    "bag": {
        "bag",
        "bags",
        "backpack",
        "backpacks",
        "daypack",
        "daypacks",
    },
    "bags": {
        "bag",
        "bags",
        "backpack",
        "backpacks",
        "daypack",
        "daypacks",
    },
    "backpack": {
        "bag",
        "bags",
        "backpack",
        "backpacks",
        "daypack",
        "daypacks",
    },
    "backpacks": {
        "bag",
        "bags",
        "backpack",
        "backpacks",
        "daypack",
        "daypacks",
    },
    "daypack": {
        "bag",
        "bags",
        "backpack",
        "backpacks",
        "daypack",
        "daypacks",
    },
    "daypacks": {
        "bag",
        "bags",
        "backpack",
        "backpacks",
        "daypack",
        "daypacks",
    },

    "bottle": {
        "bottle",
        "bottles",
        "drinkware",
    },
    "bottles": {
        "bottle",
        "bottles",
        "drinkware",
    },
    "drinkware": {
        "bottle",
        "bottles",
        "drinkware",
    },

    "camera": {
        "camera",
        "cameras",
        "photography",
    },
    "cameras": {
        "camera",
        "cameras",
        "photography",
    },
    "photography": {
        "camera",
        "cameras",
        "photography",
    },

    "travel": {
        "travel",
        "travelling",
        "traveling",
    },

    "commuting": {
        "commuting",
        "commute",
    },
    "commute": {
        "commuting",
        "commute",
    },

    "lightweight": {
        "lightweight",
        "light",
    },
}


def _recommendation_tokens(value: object) -> set[str]:
    """
    Convert text into meaningful exact-match tokens.

    This deliberately does NOT use substring matching.

    Example:
        "I need a backpack for commuting."

    becomes approximately:
        {"backpack", "commuting"}

    rather than:
        {"i", "need", "a", "backpack", "for", "commuting"}
    """
    if value is None:
        return set()

    text = str(value).lower()

    tokens = set(
        re.findall(
            r"[a-z0-9]+",
            text,
        )
    )

    return {
        token
        for token in tokens
        if token not in _RECOMMENDATION_STOP_WORDS
        and len(token) >= 2
    }


def _recommendation_expanded_tokens(
    tokens: set[str],
) -> set[str]:
    """
    Expand only known product-intent aliases.

    Unknown words remain exact tokens and are never guessed.
    """
    expanded = set(tokens)

    for token in tokens:
        expanded.update(
            _RECOMMENDATION_ALIASES.get(
                token,
                set(),
            )
        )

    return expanded


def _recommendation_product_text(
    product: Product,
) -> dict[str, set[str]]:
    """
    Tokenize product fields independently.

    Keeping fields separate allows us to distinguish primary product
    evidence from weak attribute evidence.
    """

    name_tokens = _recommendation_tokens(
        product.name
    )

    category_tokens = _recommendation_tokens(
        product.category
    )

    description_tokens = _recommendation_tokens(
        product.description
    )

    attribute_tokens: set[str] = set()

    if product.attributes:
        try:
            attributes_json = json.dumps(
                product.attributes,
                ensure_ascii=False,
            )
        except (
            TypeError,
            ValueError,
        ):
            attributes_json = str(
                product.attributes
            )

        attribute_tokens = _recommendation_tokens(
            attributes_json
        )

    return {
        "name": name_tokens,
        "category": category_tokens,
        "description": description_tokens,
        "attributes": attribute_tokens,
    }


def _recommendation_score(
    product: Product,
    query_tokens: set[str],
) -> tuple[int, int]:
    """
    Calculate a deterministic product relevance score.

    Returns:
        (primary_score, total_score)

    Primary evidence:
        - product name
        - product category
        - product description

    Secondary evidence:
        - product attributes

    Important:
        Attribute-only matches are NOT enough to recommend a product.

    This prevents a product such as:

        Ridge Daypack
        attributes = {"water_resistant": True}

    from being recommended for:

        "I need a water bottle"

    merely because the JSON attribute contains the word "water".
    """

    if not query_tokens:
        return 0, 0

    product_fields = _recommendation_product_text(
        product
    )

    name_tokens = product_fields["name"]
    category_tokens = product_fields["category"]
    description_tokens = product_fields["description"]
    attribute_tokens = product_fields["attributes"]

    expanded_query_tokens = (
        _recommendation_expanded_tokens(
            query_tokens
        )
    )

    # ------------------------------------------------------------------------
    # Exact query-token matches
    # ------------------------------------------------------------------------

    name_matches = (
        query_tokens & name_tokens
    )

    category_matches = (
        query_tokens & category_tokens
    )

    description_matches = (
        query_tokens & description_tokens
    )

    attribute_matches = (
        query_tokens & attribute_tokens
    )

    # ------------------------------------------------------------------------
    # Alias matches
    #
    # Example:
    # "bag" query should recognize a product categorized as "backpacks".
    # ------------------------------------------------------------------------

    alias_name_matches = (
        expanded_query_tokens & name_tokens
    ) - query_tokens

    alias_category_matches = (
        expanded_query_tokens & category_tokens
    ) - query_tokens

    # ------------------------------------------------------------------------
    # Weighted scoring
    #
    # Name is strongest.
    # Category is next strongest.
    # Description provides supporting evidence.
    # Attributes are deliberately weak.
    # ------------------------------------------------------------------------

    name_score = (
        len(name_matches) * 10
        + len(alias_name_matches) * 3
    )

    category_score = (
        len(category_matches) * 8
        + len(alias_category_matches) * 4
    )

    description_score = (
        len(description_matches) * 4
    )

    attribute_score = (
        len(attribute_matches) * 1
    )

    primary_score = (
        name_score
        + category_score
        + description_score
    )

    total_score = (
        primary_score
        + attribute_score
    )

    return primary_score, total_score


def _recommendation_rank_key(
    item: tuple[Product, int, int],
):
    """
    Deterministic ranking.

    Higher relevance first.
    Lower price wins ties.
    Product name is the final deterministic tie-breaker.
    """
    product, primary_score, total_score = item

    return (
        -total_score,
        -primary_score,
        float(product.price),
        (product.name or "").lower(),
    )


def _recommendation_response(
    recommendation: ProductRecommendation,
    products: list[Product],
):
    """
    Convert a saved recommendation into the API response format.

    Only products belonging to the same organization are allowed to be
    hydrated. This prevents a recommendation record from ever exposing a
    product belonging to another tenant.
    """
    return {
        "id": str(recommendation.id),
        "recommendation_id": str(recommendation.id),
        "query": recommendation.query,
        "products": [
            _product(product)
            for product in products
        ],
        "product_ids": [
            str(product.id)
            for product in products
        ],
        "created_at": recommendation.created_at,
    }


def _run_recommendation(db: Session, org, user, *, query: str, budget: float | None = None,
                        category: str | None = None, limit: int = 5) -> "ProductRecommendation":
    """Runs the existing deterministic ranking engine and persists a new
    ProductRecommendation. Used by POST /recommendations AND by the
    recommendation-intelligence "Regenerate" action -- one engine, no
    competing duplicate implementation."""
    dbquery = (
        db.query(Product)
        .filter(
            Product.organization_id == org.id,
            Product.active.is_(True),
            Product.inventory_status.in_(
                ["in_stock", "limited"]
            ),
        )
    )

    if budget is not None:
        dbquery = dbquery.filter(
            Product.price <= budget
        )

    if category:
        category_value = category.strip()

        if category_value:
            dbquery = dbquery.filter(
                Product.category.ilike(
                    category_value
                )
            )

    rows = (
        dbquery
        .order_by(Product.created_at.desc())
        .limit(100)
        .all()
    )

    query_tokens = _recommendation_tokens(
        query
    )

    scored: list[
        tuple[Product, int, int]
    ] = []

    for product in rows:
        primary_score, total_score = (
            _recommendation_score(
                product,
                query_tokens,
            )
        )

        if primary_score <= 0:
            continue

        scored.append(
            (
                product,
                primary_score,
                total_score,
            )
        )

    scored.sort(
        key=_recommendation_rank_key
    )

    ranked_products = [
        product
        for product, _, _ in scored[
            :limit
        ]
    ]

    recommendation = ProductRecommendation(
        organization_id=org.id,
        user_id=user.id,
        product_ids=[
            str(product.id)
            for product in ranked_products
        ],
        query=query,
    )

    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return recommendation, ranked_products


@router.post("/recommendations")
def recommend(
    p: RecommendationQuery,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Recommend organization-scoped products for the current user.

    Recommendation behavior:

    1. Only active products from the current organization are considered.
    2. Only in-stock/limited products are considered.
    3. Optional budget and category filters are applied first.
    4. Query text is tokenized using exact word boundaries.
    5. Stop words are removed.
    6. Conservative product aliases are expanded.
    7. Product name/category/description receive primary relevance weight.
    8. Attributes provide only weak secondary evidence.
    9. Attribute-only matches are rejected.
    10. Results are ranked deterministically.
    11. Only the requested number of relevant products is returned.
    12. The recommendation is saved with organization + user ownership.
    """
    recommendation, ranked_products = _run_recommendation(
        db, org, user, query=p.query, budget=p.budget, category=p.category, limit=p.limit,
    )

    return {
        "query": p.query,
        "products": [
            _product(product)
            for product in ranked_products
        ],
        "recommendation_id": str(
            recommendation.id
        ),
        "id": str(recommendation.id),
        "product_ids": [
            str(product.id)
            for product in ranked_products
        ],
        "created_at": recommendation.created_at,
    }

@router.get("/recommendations")
def list_recommendations(
    limit: int = 20,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Return saved recommendation history for the current user and
    organization.

    Scoped by both organization_id and user_id.
    """

    limit = max(
        1,
        min(limit, 100),
    )

    recommendations = (
        db.query(ProductRecommendation)
        .filter(
            ProductRecommendation.organization_id == org.id,
            ProductRecommendation.user_id == user.id,
        )
        .order_by(
            ProductRecommendation.created_at.desc()
        )
        .limit(limit)
        .all()
    )

    response = []

    for recommendation in recommendations:
        product_ids = recommendation.product_ids or []

        if not product_ids:
            products = []

        else:
            valid_ids = []

            for product_id in product_ids:
                if not product_id:
                    continue

                try:
                    valid_ids.append(
                        UUID(str(product_id))
                    )
                except (
                    ValueError,
                    TypeError,
                ):
                    continue

            if not valid_ids:
                products = []

            else:
                products = (
                    db.query(Product)
                    .filter(
                        Product.organization_id == org.id,
                        Product.id.in_(valid_ids),
                        Product.active.is_(True),
                    )
                    .all()
                )

                # Preserve original recommendation order.
                product_map = {
                    str(product.id): product
                    for product in products
                }

                products = [
                    product_map[str(product_id)]
                    for product_id in product_ids
                    if str(product_id) in product_map
                ]

        response.append(
            _recommendation_response(
                recommendation,
                products,
            )
        )

    return response


@router.delete("/recommendations/{recommendation_id}", status_code=204)
def delete_recommendation(
    recommendation_id: UUID,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Delete one saved recommendation owned by the current user/org."""
    recommendation = (
        db.query(ProductRecommendation)
        .filter(
            ProductRecommendation.id == recommendation_id,
            ProductRecommendation.organization_id == org.id,
            ProductRecommendation.user_id == user.id,
        )
        .first()
    )

    if not recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    db.delete(recommendation)
    db.commit()
    return None


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(
    recommendation_id: UUID,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Return one saved recommendation.

    The lookup is tenant + user scoped.
    """

    recommendation = (
        db.query(ProductRecommendation)
        .filter(
            ProductRecommendation.id == recommendation_id,
            ProductRecommendation.organization_id == org.id,
            ProductRecommendation.user_id == user.id,
        )
        .first()
    )

    if not recommendation:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not found",
        )

    product_ids = recommendation.product_ids or []

    products = []

    if product_ids:
        valid_ids = []

        for product_id in product_ids:
            if not product_id:
                continue

            try:
                valid_ids.append(
                    UUID(str(product_id))
                )
            except (
                ValueError,
                TypeError,
            ):
                continue

        if valid_ids:
            rows = (
                db.query(Product)
                .filter(
                    Product.organization_id == org.id,
                    Product.id.in_(valid_ids),
                    Product.active.is_(True),
                )
                .all()
            )

            product_map = {
                str(product.id): product
                for product in rows
            }

            products = [
                product_map[str(product_id)]
                for product_id in product_ids
                if str(product_id) in product_map
            ]

    return _recommendation_response(
        recommendation,
        products,
    )


# ============================================================================
# AI Personas
# ============================================================================

@router.get("/personas")
def list_personas(
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    return [
        _persona(persona)
        for persona in (
            db.query(AIPersona)
            .filter_by(
                organization_id=org.id
            )
            .order_by(
                AIPersona.updated_at.desc()
            )
            .all()
        )
    ]


def _persona(p):
    data = persona_snapshot(p)

    data.update(
        {
            "id": str(p.id),
            "status": p.status,
            "active_version": p.active_version,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
    )

    return data


@router.post("/personas", status_code=201)
def create_persona(
    p: PersonaCreate,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    snapshot = p.model_dump()

    if not persona_safe(snapshot):
        raise HTTPException(
            status_code=400,
            detail=(
                "Persona contains a forbidden "
                "safety override"
            ),
        )

    row = AIPersona(
        organization_id=org.id,
        **snapshot,
    )

    db.add(row)
    db.flush()

    db.add(
        AIPersonaVersion(
            persona_id=row.id,
            version=1,
            snapshot=snapshot,
            status="draft",
        )
    )

    db.commit()
    db.refresh(row)

    return _persona(row)


@router.patch("/personas/{persona_id}")
def update_persona(
    persona_id: UUID,
    p: PersonaPatch,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    row = (
        db.query(AIPersona)
        .filter_by(
            id=persona_id,
            organization_id=org.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Persona not found",
        )

    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    snapshot = p.model_dump()

    if not persona_safe(snapshot):
        raise HTTPException(
            status_code=400,
            detail=(
                "Persona contains a forbidden "
                "safety override"
            ),
        )

    for key, value in snapshot.items():
        setattr(row, key, value)

    row.active_version += 1

    db.add(
        AIPersonaVersion(
            persona_id=row.id,
            version=row.active_version,
            snapshot=snapshot,
            status="draft",
        )
    )

    db.commit()
    db.refresh(row)

    return _persona(row)


@router.post("/personas/{persona_id}/publish")
def publish_persona(
    persona_id: UUID,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    row = (
        db.query(AIPersona)
        .filter_by(
            id=persona_id,
            organization_id=org.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Persona not found",
        )

    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
            OrganizationMember.status == "active",
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    row.status = "published"

    db.commit()

    return _persona(row)


# ============================================================================
# Knowledge Bases
# ============================================================================

@router.get("/knowledge-bases")
def list_kbs(
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    return [
        {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "visibility": kb.visibility,
            "status": kb.status,
        }
        for kb in (
            db.query(KnowledgeBase)
            .filter_by(
                organization_id=org.id
            )
            .all()
        )
    ]


@router.post("/knowledge-bases", status_code=201)
def create_kb(
    p: KBCreate,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
            OrganizationMember.status == "active",
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    row = KnowledgeBase(
        organization_id=org.id,
        name=p.name,
        description=p.description,
        visibility=p.visibility,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "visibility": row.visibility,
        "status": row.status,
    }


@router.post("/knowledge-bases/{kb_id}/documents")
def link_kb(
    kb_id: UUID,
    p: LinkDoc,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    kb = (
        db.query(KnowledgeBase)
        .filter_by(
            id=kb_id,
            organization_id=org.id,
        )
        .first()
    )

    doc = db.get(
        KnowledgeDocument,
        p.document_id,
    )

    if not kb or not doc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Knowledge base or document "
                "not found"
            ),
        )

    existing = (
        db.query(KnowledgeBaseDocumentLink)
        .filter_by(
            knowledge_base_id=kb.id,
            document_id=doc.id,
        )
        .first()
    )

    if not existing:
        db.add(
            KnowledgeBaseDocumentLink(
                knowledge_base_id=kb.id,
                document_id=doc.id,
            )
        )
        db.commit()

    return {
        "knowledge_base_id": str(kb.id),
        "document_id": str(doc.id),
    }


# ============================================================================
# API Keys
# ============================================================================

@router.get("/api-keys")
def list_api_keys(
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(APIKey)
        .filter_by(
            organization_id=org.id
        )
        .order_by(
            APIKey.created_at.desc()
        )
        .all()
    )

    return [
        {
            "id": str(key.id),
            "name": key.name,
            "prefix": key.prefix,
            "scopes": key.scopes,
            "expires_at": key.expires_at,
            "revoked_at": key.revoked_at,
            "last_used_at": key.last_used_at,
            "created_at": key.created_at,
        }
        for key in rows
    ]


@router.post("/api-keys", status_code=201)
def create_api_key(
    p: APIKeyCreate,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
            OrganizationMember.status == "active",
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    scopes = list(
        dict.fromkeys(p.scopes)
    )

    if not set(scopes) <= API_SCOPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid API scope",
        )

    raw = create_api_secret()

    expires = None

    if p.expires_in_days:
        expires = (
            datetime.now(timezone.utc)
            + timedelta(
                days=p.expires_in_days
            )
        )

    row = APIKey(
        organization_id=org.id,
        name=p.name,
        secret_hash=hash_secret(raw),
        prefix=raw[:16],
        scopes=scopes,
        expires_at=expires,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "id": str(row.id),
        "name": row.name,
        "prefix": row.prefix,
        "scopes": row.scopes,
        "expires_at": row.expires_at,
        "secret": raw,
    }


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: UUID,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    row = (
        db.query(APIKey)
        .filter_by(
            id=key_id,
            organization_id=org.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="API key not found",
        )

    row.revoked_at = datetime.now(
        timezone.utc
    )

    db.commit()

    return {
        "status": "revoked"
    }


# ============================================================================
# Webhooks
# ============================================================================

@router.get("/webhooks/events")
def list_webhook_events():
    return {
        "events": sorted(
            SUPPORTED_WEBHOOK_EVENTS
        )
    }


@router.get("/webhooks")
def list_webhooks(
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WebhookEndpoint)
        .filter_by(
            organization_id=org.id
        )
        .order_by(
            WebhookEndpoint.created_at.desc()
        )
        .all()
    )

    return [
        {
            "id": str(webhook.id),
            "url": webhook.url,
            "events": webhook.events,
            "active": webhook.active,
            "created_at": webhook.created_at,
        }
        for webhook in rows
    ]


@router.post("/webhooks", status_code=201)
def create_webhook(
    p: WebhookCreate,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    events = _validate_webhook_events(
        p.events
    )

    parsed = urlparse(
        str(p.url)
    )

    if parsed.scheme not in {
        "http",
        "https",
    } or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook URL",
        )

    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
            OrganizationMember.status == "active",
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    secret = secrets.token_urlsafe(32)

    row = WebhookEndpoint(
        organization_id=org.id,
        url=str(p.url),
        secret_hash=hash_secret(secret),
        secret_encrypted=encrypt_secret(secret),
        events=events,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "id": str(row.id),
        "url": row.url,
        "events": row.events,
        "active": row.active,
        "secret": secret,
    }


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: UUID,
    user=Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    row = (
        db.query(WebhookEndpoint)
        .filter_by(
            id=webhook_id,
            organization_id=org.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Webhook not found",
        )

    admin = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_(
                ["owner", "admin"]
            ),
            OrganizationMember.status == "active",
        )
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Organization admin access required",
        )

    db.delete(row)
    db.commit()

    return {
        "status": "deleted"
    }


@router.get("/webhooks/deliveries")
def webhook_deliveries(
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(
            WebhookDelivery,
            WebhookEndpoint,
            WebhookEvent,
        )
        .join(
            WebhookEndpoint,
            WebhookEndpoint.id
            == WebhookDelivery.endpoint_id,
        )
        .join(
            WebhookEvent,
            WebhookEvent.id
            == WebhookDelivery.event_id,
        )
        .filter(
            WebhookEndpoint.organization_id
            == org.id
        )
        .order_by(
            WebhookDelivery.created_at.desc()
        )
        .limit(100)
        .all()
    )

    return [
        {
            "id": str(delivery.id),
            "event_id": str(event.id),
            "event": event.event_type,
            "status": delivery.status,
            "status_code": delivery.status_code,
            "retry_count": delivery.attempt,
            "response_time_ms": (
                float(delivery.response_time_ms)
                if delivery.response_time_ms
                else None
            ),
            "created_at": delivery.created_at,
        }
        for delivery, _, event in rows
    ]
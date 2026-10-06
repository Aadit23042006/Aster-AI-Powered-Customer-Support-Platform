
"""Phase 4 platform services and tenant context."""
from __future__ import annotations
import hashlib, hmac, json, re, secrets, time
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, require_permission
from app.db.base import get_db
from app.db.models import (
    User, Organization, OrganizationMember, UserLanguagePreference, Product,
    ProductRecommendation, AIPersona, AIPersonaVersion, KnowledgeBase,
    KnowledgeBaseDocumentLink, APIKey, WebhookEndpoint, WebhookEvent,
    WebhookDelivery, MediaAttachment
)

SUPPORTED_LANGUAGES = {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German"}
WEBHOOK_EVENTS = {
    "conversation.created","conversation.completed","ticket.created","ticket.updated",
    "ticket.closed","order.created","order.updated","human_handoff.created",
    "knowledge_document.indexed","knowledge_document.failed","evaluation.completed",
    "recommendation.created","notification.created"
}
API_SCOPES = {
    "orders:read","orders:write","tickets:read","tickets:write","conversations:read",
    "conversations:write","products:read","recommendations:read","knowledge:read",
    "knowledge:write","webhooks:manage"
}

def _now(): return datetime.now(timezone.utc)

def slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s[:110] or "organization"

def get_or_create_default_org(db: Session, user: User) -> Organization:
    member = db.query(OrganizationMember).filter_by(user_id=user.id, status="active").first()
    if member:
        return db.get(Organization, member.organization_id)
    base = slugify(user.full_name)
    slug = base
    i = 2
    while db.query(Organization).filter_by(slug=slug).first():
        slug = f"{base}-{i}"; i += 1
    org = Organization(name=f"{user.full_name}'s Organization", slug=slug)
    db.add(org); db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    db.commit(); db.refresh(org)
    return org

def get_current_org(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    organization_id: str | None = Header(default=None, alias="X-Organization-ID"),
) -> Organization:
    if organization_id:
        try: oid = UUID(organization_id)
        except ValueError: raise HTTPException(400, "Invalid organization ID")
        m = db.query(OrganizationMember).filter_by(organization_id=oid, user_id=user.id, status="active").first()
        if not m: raise HTTPException(403, "You are not a member of this organization")
        org = db.get(Organization, oid)
        if not org or org.status != "active": raise HTTPException(404, "Organization not found")
        return org
    return get_or_create_default_org(db, user)

def require_org_admin(
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    m = db.query(OrganizationMember).filter_by(organization_id=org.id, user_id=user.id, status="active").first()
    if not m or m.role not in {"owner","admin"}:
        raise HTTPException(403, "Organization admin access required")
    return user

def _fernet() -> Fernet:
    import os, base64
    raw=os.environ.get("WEBHOOK_ENCRYPTION_KEY","")
    if raw:
        return Fernet(raw.encode())
    seed=hashlib.sha256((os.environ.get("JWT_SECRET","aster-row-phase4-dev-secret")).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(seed))

def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()

def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()

def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

def create_api_secret() -> str:
    return "ar_live_" + secrets.token_urlsafe(32)

def validate_api_key(db: Session, raw: str, required_scope: str | None = None):
    if not raw or not raw.startswith("ar_live_"):
        raise HTTPException(401, "Invalid API key")
    hashed = hash_secret(raw)
    key = db.query(APIKey).filter_by(secret_hash=hashed, revoked_at=None).first()
    if not key or (key.expires_at and key.expires_at <= _now()):
        raise HTTPException(401, "Invalid or expired API key")
    if required_scope and required_scope not in set(key.scopes or []):
        raise HTTPException(403, "API key scope is insufficient")
    key.last_used_at = _now()
    return key

def detect_language(text: str) -> str:
    if not text.strip(): return "en"
    if re.search(r"[\u0900-\u097F]", text): return "hi"
    # Lightweight deterministic fallback; provider-specific detection can be
    # added without changing the API contract.
    lower = text.lower()
    if any(w in lower.split() for w in ("hola","gracias","pedido","dónde")): return "es"
    if any(w in lower.split() for w in ("bonjour","merci","commande")): return "fr"
    if any(w in lower.split() for w in ("hallo","danke","bestellung")): return "de"
    return "en"

def persona_snapshot(p: AIPersona) -> dict:
    return {k:getattr(p,k) for k in ("name","description","tone","style","formality","response_length","language","brand_voice","greeting","closing","custom_instructions")}

def persona_safe(snapshot: dict) -> bool:
    text = json.dumps(snapshot).lower()
    forbidden = ("reveal system prompt","ignore safety","bypass permission","expose secrets","fabricate orders","fabricate products")
    return not any(x in text for x in forbidden)

def dispatch_webhook(db: Session, org_id: UUID, event_type: str, payload: dict):
    if event_type not in WEBHOOK_EVENTS: return
    event = WebhookEvent(organization_id=org_id, event_type=event_type, payload=payload)
    db.add(event); db.flush()
    endpoints = db.query(WebhookEndpoint).filter_by(organization_id=org_id, active=True).all()
    body = json.dumps({"id": str(event.id), "type": event_type, "created_at": _now().isoformat(), "data": payload}, separators=(",",":"))
    for ep in endpoints:
        if event_type not in set(ep.events or []): continue
        delivery = WebhookDelivery(event_id=event.id, endpoint_id=ep.id)
        db.add(delivery); db.flush()
        # Delivery is attempted immediately for development and remains
        # persisted so a worker can retry it in production.
        start=time.perf_counter()
        try:
            secret = decrypt_secret(ep.secret_encrypted)
            sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            with httpx.Client(timeout=5.0) as client:
                r=client.post(ep.url, content=body, headers={"Content-Type":"application/json","X-Aster-Signature":sig,"X-Aster-Event-ID":str(event.id)})
            delivery.status_code=r.status_code
            delivery.response_time_ms=(time.perf_counter()-start)*1000
            delivery.status="delivered" if 200 <= r.status_code < 300 else "retrying"
            if delivery.status!="delivered": delivery.error=f"HTTP {r.status_code}"
            if delivery.status=="delivered": delivery.delivered_at=_now()
        except Exception as exc:
            delivery.status="retrying"; delivery.error=str(exc)[:500]
            delivery.response_time_ms=(time.perf_counter()-start)*1000
    db.commit()

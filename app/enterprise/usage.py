"""AI usage recording + cost estimation. Prices are configuration-only."""
from __future__ import annotations
import json
import logging
import uuid
from sqlalchemy.orm import Session
from app import config
from app.db.models import AIUsageEvent, OrganizationMember

logger = logging.getLogger("aster_row.usage")


def _pricing() -> dict:
    if not config.AI_MODEL_PRICING_JSON:
        return {}
    try:
        data = json.loads(config.AI_MODEL_PRICING_JSON)
        return data if isinstance(data, dict) else {}
    except ValueError:
        logger.warning("AI_MODEL_PRICING_JSON is not valid JSON; costs stay unavailable")
        return {}


def estimate_cost(model: str | None, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """USD estimate, or None when the model has no configured price or the
    provider did not report token counts (never fabricated)."""
    price = _pricing().get(model or "")
    if not price or input_tokens is None or output_tokens is None:
        return None
    return round((input_tokens * float(price.get("input", 0)) + output_tokens * float(price.get("output", 0))) / 1_000_000, 8)


def record_usage(db: Session, *, user_id, conversation_id, model, feature: str, endpoint: str | None,
                 latency_ms: float, status: str = "success", input_tokens=None, output_tokens=None,
                 request_id: str | None = None, metadata: dict | None = None) -> None:
    """Best-effort: must never break the chat flow."""
    if not config.AI_USAGE_ANALYTICS_ENABLED:
        return
    try:
        org_id = None
        if user_id:
            m = db.query(OrganizationMember.organization_id).filter_by(user_id=user_id, status="active").first()
            org_id = m[0] if m else None
        known = [t for t in (input_tokens, output_tokens) if t is not None]
        total = sum(known) if known else None
        with db.begin_nested():
            db.add(AIUsageEvent(
                organization_id=org_id, user_id=user_id, conversation_id=conversation_id,
                request_id=request_id or str(uuid.uuid4()), model=model, feature=feature, endpoint=endpoint,
                input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total,
                latency_ms=round(latency_ms, 2), status=status,
                estimated_cost=estimate_cost(model, input_tokens, output_tokens), metadata_json=metadata,
            ))
    except Exception:  # noqa: BLE001
        logger.exception("usage recording failed (ignored)")

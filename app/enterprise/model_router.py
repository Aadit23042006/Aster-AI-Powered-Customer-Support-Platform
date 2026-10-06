"""Configurable model router. Never a single point of failure: any problem
(disabled, bad config, unknown category) falls back to the existing CHAT_MODEL."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app import config

logger = logging.getLogger("aster_row.router")

CATEGORIES = {"simple_question", "complex_question", "classification", "summarization", "retrieval", "tool_call"}


@dataclass
class RouteDecision:
    model: str | None
    category: str
    reason: str
    fallback_used: bool


def _rules() -> dict[str, str]:
    if not config.MODEL_ROUTER_RULES_JSON:
        return {}
    try:
        data = json.loads(config.MODEL_ROUTER_RULES_JSON)
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v} if isinstance(data, dict) else {}
    except ValueError:
        logger.warning("MODEL_ROUTER_RULES_JSON is not valid JSON; using default model")
        return {}


def classify_request(text: str) -> str:
    """Cheap heuristic complexity classification (no LLM call)."""
    t = (text or "").lower()
    words = len(t.split())
    if any(k in t for k in ("summarize", "summary", "tl;dr")):
        return "summarization"
    if any(k in t for k in ("why", "compare", "explain", "difference", "step by step")) or words > 60:
        return "complex_question"
    return "simple_question"


def route(category: str) -> RouteDecision:
    default = getattr(config, "CHAT_MODEL", None)
    try:
        if not config.MODEL_ROUTER_ENABLED:
            return RouteDecision(default, category, "Router disabled; default model used.", True)
        if category not in CATEGORIES:
            return RouteDecision(default, category, "Unknown category; default model used.", True)
        chosen = _rules().get(category)
        if chosen:
            return RouteDecision(chosen, category, f"Configured rule for {category.replace('_', ' ')}.", False)
        return RouteDecision(default, category, "No rule configured; default model used.", True)
    except Exception:  # noqa: BLE001
        logger.exception("router failed; falling back")
        return RouteDecision(default, category, "Router error; default model used.", True)

"""Central configuration. Everything tunable lives here so behaviour
changes (thresholds, model names) don't get scattered through the code."""
from __future__ import annotations

import os
from pathlib import Path

# Load a .env file if python-dotenv is available. This is optional so the
# app still runs if the file is simply exported as real env vars (Docker,
# CI, etc).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is a small optional convenience
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Gemini ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")
# Fallback used when the primary Gemini model is temporarily unavailable.
# Gemini currently recommends newer models for new projects; keeping this
# configurable lets the app recover from transient 5xx capacity errors.
CHAT_FALLBACK_MODEL = os.environ.get("CHAT_FALLBACK_MODEL", "gemini-3.5-flash-lite")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))

# Set to "1" to run the agent against a small deterministic fake LLM instead
# of calling the real Gemini API. Used by the offline unit tests and by
# `evaluation/run_eval.py --mock` so the harness can be exercised without an
# API key / network access. Never used for the real evaluation numbers that
# belong in the README.
USE_MOCK_LLM = os.environ.get("USE_MOCK_LLM", "0") == "1"

# --- Retrieval ---
KB_DIR = BASE_DIR / "knowledge-base"
INDEX_CACHE_PATH = BASE_DIR / "app" / "data_cache" / "kb_index.json"
TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "5"))
MIN_SIMILARITY = float(os.environ.get("RETRIEVAL_MIN_SIMILARITY", "0.45"))

# --- Hybrid RAG (Phase 2, Feature 12) ---
# Fusion weights for combining the semantic (vector) and keyword (BM25)
# arms -- both scores are min-max normalized to [0, 1] per query before
# these weights are applied, so they're comparable regardless of the
# embedder's raw score scale. Semantic search carries more weight by
# default since it's what actually understands paraphrase/synonyms; the
# keyword arm mainly rescues exact-term queries (SKUs, error codes, policy
# names) that a hashed or lightly-tuned embedding can under-rank.
SEMANTIC_WEIGHT = float(os.environ.get("RETRIEVAL_SEMANTIC_WEIGHT", "0.65"))
KEYWORD_WEIGHT = float(os.environ.get("RETRIEVAL_KEYWORD_WEIGHT", "0.35"))
# Saturation constant for the keyword component's bm25/(bm25+K) transform
# -- see app/retriever.py module docstring. Lower K makes a single strong
# term match saturate towards 1.0 faster; higher K requires broader/
# stronger overlap before the keyword arm carries much weight.
KEYWORD_SATURATION_K = float(os.environ.get("RETRIEVAL_KEYWORD_SATURATION_K", "2.5"))
# Threshold on the *fused, boosted* score (not a raw cosine similarity
# anymore) below which a chunk is dropped -- see app/retriever.py module
# docstring for why an empty result set here is exactly what makes the
# agent's existing "insufficient information" fallback fire.
HYBRID_MIN_SCORE = float(os.environ.get("RETRIEVAL_HYBRID_MIN_SCORE", "0.22"))

# --- Orders ---
ORDERS_PATH = BASE_DIR / "data" / "orders.json"

# --- Session ---
# How many prior turns (user+assistant pairs) get replayed into the model's
# context window on each new turn.
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))
# Sessions idle longer than this are dropped from the in-memory store so one
# customer's conversation can never bleed into another's.
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "1800"))

# --- Logging ---
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "trace.jsonl"

# --- Phase 3: Redis (rate limiting, background workers, caching) ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# --- Phase 3, Feature 20: rate limiting ---
# A single master switch, plus per-bucket (requests, window_seconds) pairs.
# All configurable via env vars rather than hardcoded at each call site --
# see app/security/rate_limit.py for how these are applied.
RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false"


def _limit_pair(env_prefix: str, default_count: int, default_window_s: int) -> tuple[int, int]:
    count = int(os.environ.get(f"{env_prefix}_COUNT", str(default_count)))
    window = int(os.environ.get(f"{env_prefix}_WINDOW_SECONDS", str(default_window_s)))
    return count, window


RATE_LIMIT_LOGIN = _limit_pair("RATE_LIMIT_LOGIN", 10, 60)                 # 10 / minute / IP
RATE_LIMIT_SIGNUP = _limit_pair("RATE_LIMIT_SIGNUP", 5, 3600)              # 5 / hour / IP
RATE_LIMIT_AI_CHAT = _limit_pair("RATE_LIMIT_AI_CHAT", 30, 60)             # 30 / minute / user
RATE_LIMIT_TICKET_CREATE = _limit_pair("RATE_LIMIT_TICKET_CREATE", 10, 3600)   # 10 / hour / user
RATE_LIMIT_FEEDBACK = _limit_pair("RATE_LIMIT_FEEDBACK", 30, 3600)         # 30 / hour / user
RATE_LIMIT_KB_UPLOAD = _limit_pair("RATE_LIMIT_KB_UPLOAD", 20, 3600)       # 20 / hour / admin
RATE_LIMIT_ANALYTICS = _limit_pair("RATE_LIMIT_ANALYTICS", 60, 60)         # 60 / minute / user
RATE_LIMIT_GENERAL = _limit_pair("RATE_LIMIT_GENERAL", 120, 60)            # 120 / minute / user-or-IP

# --- Phase 3, Feature 22: PII protection ---
PII_REDACTION_ENABLED = os.environ.get("PII_REDACTION_ENABLED", "true").lower() != "false"

# --- Phase 3, Feature 23: notifications ---
NOTIFICATIONS_ENABLED = os.environ.get("NOTIFICATIONS_ENABLED", "true").lower() != "false"
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "console")  # console | smtp
EMAIL_FROM = os.environ.get("EMAIL_FROM", "support@asterandrow.example")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# --- Phase 3, Feature 24: background workers ---
WORKERS_ENABLED = os.environ.get("WORKERS_ENABLED", "true").lower() != "false"
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or REDIS_URL
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL

# --- Phase 3, Feature 25: monitoring ---
MONITORING_ENABLED = os.environ.get("MONITORING_ENABLED", "true").lower() != "false"

# --- Phase 3, Feature 26: error tracking ---
ERROR_TRACKING_ENABLED = os.environ.get("ERROR_TRACKING_ENABLED", "false").lower() == "true"
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# --- Phase 4: advanced multimodal / SaaS features ---
IMAGE_SUPPORT_ENABLED = os.environ.get("IMAGE_SUPPORT_ENABLED", "false").lower() != "false"
MAX_IMAGE_SIZE_MB = int(os.environ.get("MAX_IMAGE_SIZE_MB", "10"))
CHAT_ATTACHMENT_MAX_SIZE_MB = int(
    os.environ.get("CHAT_ATTACHMENT_MAX_SIZE_MB", "20")
)
MULTILINGUAL_ENABLED = os.environ.get("MULTILINGUAL_ENABLED", "true").lower() != "false"
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "en")
RECOMMENDATIONS_ENABLED = os.environ.get("RECOMMENDATIONS_ENABLED", "true").lower() != "false"
MULTI_TENANT_ENABLED = os.environ.get("MULTI_TENANT_ENABLED", "true").lower() != "false"
WEBHOOKS_ENABLED = os.environ.get("WEBHOOKS_ENABLED", "true").lower() != "false"
WEBHOOK_MAX_RETRIES = int(os.environ.get("WEBHOOK_MAX_RETRIES", "3"))
API_KEYS_ENABLED = os.environ.get("API_KEYS_ENABLED", "true").lower() != "false"


# --- Production account access ---------------------------------------------
# Self-registration is disabled for the GitHub-ready deployment. Only these
# canonical accounts are allowed to authenticate when the allowlist is on.
SELF_SIGNUP_ENABLED = os.environ.get("SELF_SIGNUP_ENABLED", "false").lower() == "true"
LOGIN_ALLOWLIST_ENABLED = os.environ.get("LOGIN_ALLOWLIST_ENABLED", "true").lower() != "false"
ALLOWED_LOGIN_EMAILS = {
    email.strip().lower()
    for email in os.environ.get(
        "ALLOWED_LOGIN_EMAILS",
        "admin@example.com,support@example.com,customer@example.com",
    ).split(",")
    if email.strip()
}


# --- Enterprise AI upgrade: feature flags (all default ON so existing
# deployments keep today's behaviour; set to "false" to disable a feature
# without touching any pre-existing functionality) ---
def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"false", "0", "no", "off"}


AI_AGENT_ACTIONS_ENABLED = _flag("AI_AGENT_ACTIONS_ENABLED")
SUPPORT_WORKSPACE_ENABLED = _flag("SUPPORT_WORKSPACE_ENABLED")
SENTIMENT_ANALYSIS_ENABLED = _flag("SENTIMENT_ANALYSIS_ENABLED")
QUALITY_GUARD_ENABLED = _flag("QUALITY_GUARD_ENABLED")
RAG_CITATIONS_ENABLED = _flag("RAG_CITATIONS_ENABLED")
KB_VERSIONING_ENABLED = _flag("KB_VERSIONING_ENABLED")
EVALUATION_PLAYGROUND_ENABLED = _flag("EVALUATION_PLAYGROUND_ENABLED")
PROMPT_MANAGEMENT_ENABLED = _flag("PROMPT_MANAGEMENT_ENABLED")
AI_USAGE_ANALYTICS_ENABLED = _flag("AI_USAGE_ANALYTICS_ENABLED")
MODEL_ROUTER_ENABLED = _flag("MODEL_ROUTER_ENABLED")
CUSTOMER_360_ENABLED = _flag("CUSTOMER_360_ENABLED")
GLOBAL_SEARCH_ENABLED = _flag("GLOBAL_SEARCH_ENABLED")
RECOMMENDATION_INTELLIGENCE_ENABLED = _flag("RECOMMENDATION_INTELLIGENCE_ENABLED")

# --- Quality guard thresholds (grounding is a 0..1 score) ---
QUALITY_GROUNDING_ALLOW = float(os.environ.get("QUALITY_GROUNDING_ALLOW", "0.75"))
QUALITY_GROUNDING_HIGH = float(os.environ.get("QUALITY_GROUNDING_HIGH", "0.85"))
QUALITY_GROUNDING_MEDIUM = float(os.environ.get("QUALITY_GROUNDING_MEDIUM", "0.65"))

# --- AI usage cost: USD per 1M tokens, JSON keyed by model name, e.g.
# {"gemini-2.5-flash": {"input": 0.30, "output": 2.50}}. Empty by default:
# without a configured price the cost stays "unavailable" (never invented).
AI_MODEL_PRICING_JSON = os.environ.get("AI_MODEL_PRICING_JSON", "")

# Mutating/external AI actions proposed by the AI (origin="ai") wait for a
# staff approval when this is true. Staff-initiated actions from the Action
# Center are unchanged (the staff member is the human decision-maker).
AI_ACTION_APPROVAL_REQUIRED = _flag("AI_ACTION_APPROVAL_REQUIRED")

# Model router rules: JSON mapping routing category -> model name, e.g.
# {"classification": "fast-model", "complex_question": "strong-model"}.
# Empty => every category uses CHAT_MODEL (existing behaviour).
MODEL_ROUTER_RULES_JSON = os.environ.get("MODEL_ROUTER_RULES_JSON", "")

# Quality guard fallbacks
QUALITY_RETRY_TOP_K_MULTIPLIER = int(os.environ.get("QUALITY_RETRY_TOP_K_MULTIPLIER", "2"))
QUALITY_CLARIFY_MAX_WORDS = int(os.environ.get("QUALITY_CLARIFY_MAX_WORDS", "4"))
# --- AI provider resilience / failover -------------------------------------
# Maximum provider attempts for each configured model. A value of 2 means
# one normal attempt plus one retry after a transient provider failure.
LLM_MAX_ATTEMPTS_PER_MODEL = max(
    1,
    int(os.environ.get("LLM_MAX_ATTEMPTS_PER_MODEL", "2")),
)
# Exponential backoff between attempts. Keep these small enough for a
# customer-facing API while still absorbing short 429/5xx spikes.
LLM_RETRY_INITIAL_DELAY_SECONDS = max(
    0.0,
    float(os.environ.get("LLM_RETRY_INITIAL_DELAY_SECONDS", "0.5")),
)
LLM_RETRY_MAX_DELAY_SECONDS = max(
    0.0,
    float(os.environ.get("LLM_RETRY_MAX_DELAY_SECONDS", "2.0")),
)
# When every provider/model attempt is exhausted, the agent returns a
# deterministic safe response and creates a human handoff instead of exposing
# provider errors to the customer.
LLM_FAILOVER_HUMAN_HANDOFF = _flag("LLM_FAILOVER_HUMAN_HANDOFF")


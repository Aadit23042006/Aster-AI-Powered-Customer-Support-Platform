"""Pydantic models for the HTTP API. Deliberately separate from
`app/schemas.py`, which is the AI agent's own structured-output contract
(`AgentAnswer`) -- these are unrelated concerns."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# --- auth ---
class SignupRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


# --- conversations ---
class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreateRequest(BaseModel):
    title: str | None = None


class ConversationRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    meta: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    # Exact attachment IDs uploaded for this question. Optional for backward compatibility.
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class EditMessageRequest(BaseModel):
    message: str = Field(min_length=1)


class SendMessageResponse(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
    sources: list[str]
    handoff: bool
    handoff_reason: str | None
    ticket_number: str | None = None


# --- orders ---
class OrderItemOut(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    price: float | None
    final_sale: bool

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    status: str
    placed_at: datetime
    shipped_at: datetime | None
    delivered_at: datetime | None
    carrier: str | None
    tracking_number: str | None
    estimated_delivery: datetime | None
    total_amount: float | None
    currency: str
    items: list[OrderItemOut]

    model_config = {"from_attributes": True}


# --- tickets ---
class TicketCreateRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    category: str
    priority: str = "medium"
    order_id: uuid.UUID | None = None


class TicketMessageCreateRequest(BaseModel):
    content: str = Field(min_length=1)


class TicketMessageOut(BaseModel):
    id: uuid.UUID
    author_role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketOut(BaseModel):
    id: uuid.UUID
    ticket_number: str
    subject: str
    description: str
    category: str
    priority: str
    status: str
    created_by_ai: bool
    handoff_reason: str | None
    order_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketDetailOut(TicketOut):
    messages: list[TicketMessageOut]


class TicketStatusUpdateRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    assigned_agent_id: uuid.UUID | None = None


# --- knowledge base (Feature 13/14) ---
class KBVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    content_type: str
    source_filename: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class KBDocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    status: str
    current_version: int
    index_status: str
    index_error: str | None
    last_indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    archived_at: datetime | None

    model_config = {"from_attributes": True}


class KBDocumentDetailOut(KBDocumentOut):
    content: str
    content_type: str
    versions: list[KBVersionOut]


class KBDashboardOut(BaseModel):
    documents: int
    published: int
    drafts: int
    archived: int
    failed_index: int
    index_healthy: bool
    last_indexed_at: datetime | None


class KBDocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = "general"
    content: str = Field(min_length=1)
    content_type: str = "markdown"


class KBDocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = None
    content: str | None = None
    content_type: str | None = None


class KBIndexJobOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    job_type: str
    status: str
    error: str | None
    documents_indexed: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- feedback (Feature 15) ---
FEEDBACK_REASONS = {"incorrect_answer", "didnt_solve_problem", "missing_information", "needed_human", "other"}


class FeedbackCreateRequest(BaseModel):
    rating: str  # positive|negative
    reason: str | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    rating: str
    reason: str | None
    comment: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeedbackSubmitResponse(BaseModel):
    feedback: FeedbackOut
    suggest_handoff: bool


# --- Phase 3: RBAC / audit / notifications / admin (Features 19,21,23,25,26) ---
class AuditEventOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    actor_role: str | None
    event_type: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    success: bool
    detail: dict | None
    request_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAuditEvents(BaseModel):
    items: list[AuditEventOut]
    total: int
    page: int
    page_size: int


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAdminUsers(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    page_size: int


class RoleUpdateRequest(BaseModel):
    roles: list[str] = Field(min_length=1)


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    message: str
    data: dict | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCountOut(BaseModel):
    unread_count: int


class SystemHealthOut(BaseModel):
    status: str
    checks: dict[str, str]


class SystemMetricsOut(BaseModel):
    http_requests_total: int
    http_5xx_total: int
    http_4xx_total: int
    average_latency_ms: float
    ai_requests_total: int
    ai_average_latency_ms: float
    rate_limit_events_total: int
    auth_failures_total: int
    worker_queue_depth: int
    worker_tasks_total: int
    worker_task_failures_total: int
    notification_failures_total: int


class ErrorEventOut(BaseModel):
    id: uuid.UUID
    request_id: str | None
    service: str
    environment: str
    route: str | None
    error_type: str
    error_message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedErrorEvents(BaseModel):
    items: list[ErrorEventOut]
    total: int
    page: int
    page_size: int

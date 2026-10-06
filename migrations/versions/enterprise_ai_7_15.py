"""enterprise AI features 7-15 additive

Revision ID: enterprise_ai_7_15
Revises: 5b1e_enterprise_ai
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "enterprise_ai_7_15"
down_revision = "5b1e_enterprise_ai"
branch_labels = None
depends_on = None

def _uuid():
    return postgresql.UUID(as_uuid=True)

def upgrade():
    # Existing KB version table: add metadata/status without replacing history.
    op.add_column("knowledge_document_versions", sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"))
    op.add_column("knowledge_document_versions", sa.Column("metadata", sa.JSON(), nullable=True))
    op.add_column("knowledge_document_versions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "prompt_templates",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organization_id", _uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_prompt_template_org_name"),
    )
    op.create_index("ix_prompt_templates_org", "prompt_templates", ["organization_id"])

    op.create_table(
        "prompt_versions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("prompt_id", _uuid(), sa.ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("variables", sa.JSON(), nullable=True),
        sa.Column("created_by", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("prompt_id", "version", name="uq_prompt_version"),
    )
    op.create_index("ix_prompt_versions_prompt", "prompt_versions", ["prompt_id"])

    op.create_table(
        "ai_usage_events",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organization_id", _uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", _uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("model", sa.String(150), nullable=True),
        sa.Column("provider", sa.String(80), nullable=True),
        sa.Column("feature", sa.String(100), nullable=True),
        sa.Column("endpoint", sa.String(200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Numeric(12,2), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="success"),
        sa.Column("estimated_cost", sa.Numeric(16,8), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, cols in [
        ("ix_ai_usage_org", ["organization_id"]), ("ix_ai_usage_user", ["user_id"]),
        ("ix_ai_usage_conversation", ["conversation_id"]), ("ix_ai_usage_request", ["request_id"]),
        ("ix_ai_usage_model", ["model"]), ("ix_ai_usage_feature", ["feature"]),
        ("ix_ai_usage_status", ["status"]), ("ix_ai_usage_created", ["created_at"]),
    ]:
        op.create_index(name, "ai_usage_events", cols)

    op.create_table(
        "model_routing_events",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organization_id", _uuid(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", _uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        sa.Column("routing_category", sa.String(50), nullable=False),
        sa.Column("model_used", sa.String(150), nullable=True),
        sa.Column("routing_reason", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Numeric(12,2), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, cols in [
        ("ix_model_routing_org", ["organization_id"]), ("ix_model_routing_user", ["user_id"]),
        ("ix_model_routing_conversation", ["conversation_id"]), ("ix_model_routing_trace", ["trace_id"]),
        ("ix_model_routing_created", ["created_at"]),
    ]:
        op.create_index(name, "model_routing_events", cols)

    op.create_table(
        "recommendation_explanations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("recommendation_id", _uuid(), sa.ForeignKey("product_recommendations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", _uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", _uuid(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(6,4), nullable=True),
        sa.Column("model", sa.String(150), nullable=True),
        sa.Column("action", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recommendation_id", "product_id", name="uq_recommendation_explanation"),
    )
    for name, cols in [
        ("ix_rec_expl_rec", ["recommendation_id"]), ("ix_rec_expl_org", ["organization_id"]),
        ("ix_rec_expl_user", ["user_id"]), ("ix_rec_expl_product", ["product_id"]),
    ]:
        op.create_index(name, "recommendation_explanations", cols)

    op.create_table(
        "evaluation_playground_runs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organization_id", _uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("model", sa.String(150), nullable=True),
        sa.Column("prompt_version", sa.String(100), nullable=True),
        sa.Column("retrieval_configuration", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("retrieved_sources", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Numeric(12,2), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_eval_playground_org", "evaluation_playground_runs", ["organization_id"])
    op.create_index("ix_eval_playground_created", "evaluation_playground_runs", ["created_at"])

def downgrade():
    # This migration is additive. Downgrade is safe for newly-created objects;
    # it does not touch historical application tables/data beyond its columns.
    op.drop_table("evaluation_playground_runs")
    op.drop_table("recommendation_explanations")
    op.drop_table("model_routing_events")
    op.drop_table("ai_usage_events")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
    op.drop_column("knowledge_document_versions", "published_at")
    op.drop_column("knowledge_document_versions", "metadata")
    op.drop_column("knowledge_document_versions", "status")

"""add ai_actions table

Revision ID: add_ai_actions
Revises: 3f4a_phase4
Create Date: 2026-09-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "add_ai_actions"
down_revision = "enterprise_ai_7_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_actions"):
        return  # already created by 5b1e_enterprise_ai (fresh installs)
    op.create_table(
        "ai_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("arguments_sanitized", sa.JSON(), nullable=True),
        sa.Column("permission_result", sa.String(length=30), nullable=False),
        sa.Column("execution_status", sa.String(length=30), nullable=False),
        sa.Column("result_sanitized", sa.JSON(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="LOW"),
        sa.Column("duration_ms", sa.Numeric(12, 2), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_ai_actions_conversation_id", "ai_actions", ["conversation_id"])
    op.create_index("ix_ai_actions_user_id", "ai_actions", ["user_id"])
    op.create_index("ix_ai_actions_tool_name", "ai_actions", ["tool_name"])
    op.create_index("ix_ai_actions_created_at", "ai_actions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_actions_created_at", table_name="ai_actions")
    op.drop_index("ix_ai_actions_tool_name", table_name="ai_actions")
    op.drop_index("ix_ai_actions_user_id", table_name="ai_actions")
    op.drop_index("ix_ai_actions_conversation_id", table_name="ai_actions")
    op.drop_table("ai_actions")

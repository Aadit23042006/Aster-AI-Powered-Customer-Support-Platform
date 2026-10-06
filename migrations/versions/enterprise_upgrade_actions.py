"""AI action approval workflow, categories and idempotency (additive)

Revision ID: enterprise_upgrade_actions
Revises: add_ai_actions
Create Date: 2026-09-28

Purely additive and idempotent: 5b1e_enterprise_ai creates tables from the
current ORM models, so on fresh installs these columns may already exist.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "enterprise_upgrade_actions"
down_revision = "add_ai_actions"
branch_labels = None
depends_on = None

_COLS = [
    ("category", lambda: sa.Column("category", sa.String(20), nullable=True)),
    ("origin", lambda: sa.Column("origin", sa.String(20), nullable=True)),
    ("reason", lambda: sa.Column("reason", sa.Text(), nullable=True)),
    ("approval_status", lambda: sa.Column("approval_status", sa.String(20), nullable=True)),
    ("approved_by", lambda: sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)),
    ("approved_at", lambda: sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)),
    ("idempotency_key", lambda: sa.Column("idempotency_key", sa.String(80), nullable=True)),
    ("ticket_id", lambda: sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=True)),
    ("order_number", lambda: sa.Column("order_number", sa.String(50), nullable=True)),
]
_INDEXES = [("ix_ai_actions_approval_status", "approval_status"), ("ix_ai_actions_idempotency_key", "idempotency_key")]


def upgrade():
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns("ai_actions")}
    for name, make in _COLS:
        if name not in existing:
            op.add_column("ai_actions", make())
    have_ix = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("ai_actions")}
    for ix, col in _INDEXES:
        if ix not in have_ix:
            op.create_index(ix, "ai_actions", [col])


def downgrade():
    insp = sa.inspect(op.get_bind())
    have_ix = {i["name"] for i in insp.get_indexes("ai_actions")}
    for ix, _ in _INDEXES:
        if ix in have_ix:
            op.drop_index(ix, table_name="ai_actions")
    existing = {c["name"] for c in insp.get_columns("ai_actions")}
    for name, _ in reversed(_COLS):
        if name in existing:
            op.drop_column("ai_actions", name)

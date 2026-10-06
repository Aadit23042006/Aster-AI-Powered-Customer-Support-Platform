"""Ensure persistent chat attachments have message/file storage columns.

Revision ID: 20261006_chat_file_attachments
Revises: 20261006_core_account_protection

The phase-4 migration creates ``media_attachments`` from the ORM model.  The
current model already contains ``message_id`` and ``file_data``, so this
follow-up migration must be safe on a fresh database as well as on databases
created from an older version of the phase-4 migration.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261006_chat_file_attachments"
down_revision = "20261006_core_account_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Older phase-4 databases may have the table without these two columns;
    # fresh databases already have them because phase4 creates the table from
    # the current MediaAttachment ORM model.
    columns = {column["name"] for column in inspector.get_columns("media_attachments")}
    if "message_id" not in columns:
        op.add_column(
            "media_attachments",
            sa.Column("message_id", sa.Uuid(), nullable=True),
        )
    if "file_data" not in columns:
        op.add_column(
            "media_attachments",
            sa.Column("file_data", sa.LargeBinary(), nullable=True),
        )

    # The ORM model creates the index on fresh databases.  Avoid trying to
    # create it twice, while still repairing older databases if necessary.
    indexes = {index["name"] for index in inspector.get_indexes("media_attachments")}
    if "ix_media_attachments_message_id" not in indexes:
        op.create_index(
            "ix_media_attachments_message_id",
            "media_attachments",
            ["message_id"],
            unique=False,
        )

    # Likewise, the ORM model creates this FK on fresh databases. Compare the
    # constrained/referred columns so the migration works with either an
    # automatically generated FK name or the explicit repair-migration name.
    foreign_keys = inspector.get_foreign_keys("media_attachments")
    has_message_fk = any(
        fk.get("referred_table") == "messages"
        and fk.get("constrained_columns") == ["message_id"]
        for fk in foreign_keys
    )
    if not has_message_fk:
        op.create_foreign_key(
            "fk_media_attachments_message_id_messages",
            "media_attachments",
            "messages",
            ["message_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    # This is a repair migration. The columns/index/FK are part of the
    # canonical phase-4 schema on fresh databases, so removing them here
    # could destroy valid schema objects that this migration did not create.
    pass

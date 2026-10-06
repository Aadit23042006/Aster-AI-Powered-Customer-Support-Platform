"""retire Feature 29 voice support

Revision ID: 4a2c_retire_voice
Revises: 3f4a_phase4
"""
from alembic import op

revision = "4a2c_retire_voice"
down_revision = "3f4a_phase4"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("voice_sessions", if_exists=True)


def downgrade():
    # Voice Support is intentionally retired. Recreating the old table on
    # downgrade would require restoring historical voice-session metadata.
    pass

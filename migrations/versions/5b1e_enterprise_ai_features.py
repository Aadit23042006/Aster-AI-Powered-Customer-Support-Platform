"""additive enterprise AI support features
Revision ID: 5b1e_enterprise_ai
Revises: 4a2c_retire_voice
"""
from alembic import op
from app.db.models import AIAction, ConversationClassification, AIQualityCheck, ConversationCitation, InternalNote
revision="5b1e_enterprise_ai"
down_revision="4a2c_retire_voice"
branch_labels=None
depends_on=None

TABLES=[AIAction.__table__,ConversationClassification.__table__,AIQualityCheck.__table__,ConversationCitation.__table__,InternalNote.__table__]
def upgrade():
    bind=op.get_bind()
    for table in TABLES: table.create(bind=bind,checkfirst=True)
def downgrade():
    bind=op.get_bind()
    for table in reversed(TABLES): table.drop(bind=bind,checkfirst=True)

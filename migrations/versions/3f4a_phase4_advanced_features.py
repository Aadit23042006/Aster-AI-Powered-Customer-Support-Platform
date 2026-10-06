"""phase4 advanced multimodal SaaS features

Revision ID: 3f4a_phase4
Revises: 8d7efbd80366
"""
from alembic import op
import sqlalchemy as sa
from app.db.models import (
    Organization, OrganizationMember, UserLanguagePreference,
    MediaAttachment, Product, ProductRecommendation, AIPersona,
    AIPersonaVersion, KnowledgeBase, KnowledgeBaseDocumentLink, APIKey,
    WebhookEndpoint, WebhookEvent, WebhookDelivery,
)
revision = "3f4a_phase4"
down_revision = "8d7efbd80366"
branch_labels = None
depends_on = None

TABLES = [
    Organization.__table__, OrganizationMember.__table__, UserLanguagePreference.__table__,
    MediaAttachment.__table__, Product.__table__,
    ProductRecommendation.__table__, AIPersona.__table__, AIPersonaVersion.__table__,
    KnowledgeBase.__table__, KnowledgeBaseDocumentLink.__table__, APIKey.__table__,
    WebhookEndpoint.__table__, WebhookEvent.__table__, WebhookDelivery.__table__,
]

def upgrade():
    bind=op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)

def downgrade():
    bind=op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)

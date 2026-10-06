"""Enterprise upgrade part 2: classification/quality/playground columns, prompt A/B + test cases (additive)

Revision ID: enterprise_upgrade_2
Revises: enterprise_upgrade_actions
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "enterprise_upgrade_2"
down_revision = "enterprise_upgrade_actions"
branch_labels = None
depends_on = None

_COLUMNS = {
    "conversation_classifications": [
        ("model_version", lambda: sa.Column("model_version", sa.String(50), nullable=True)),
        ("source", lambda: sa.Column("source", sa.String(20), nullable=True)),
    ],
    "ai_quality_checks": [
        ("retrieval_score", lambda: sa.Column("retrieval_score", sa.Numeric(6, 4), nullable=True)),
        ("relevance_score", lambda: sa.Column("relevance_score", sa.Numeric(6, 4), nullable=True)),
        ("fallback_action", lambda: sa.Column("fallback_action", sa.String(30), nullable=True)),
        ("details", lambda: sa.Column("details", sa.JSON(), nullable=True)),
    ],
    "evaluation_playground_runs": [
        ("answer", lambda: sa.Column("answer", sa.Text(), nullable=True)),
        ("token_usage", lambda: sa.Column("token_usage", sa.JSON(), nullable=True)),
        ("evaluator_version", lambda: sa.Column("evaluator_version", sa.String(40), nullable=True)),
        ("comparison_id", lambda: sa.Column("comparison_id", sa.String(60), nullable=True)),
    ],
}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, cols in _COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for name, make in cols:
            if name not in have:
                op.add_column(table, make())
    if "comparison_id" not in {i["column_names"][0] for i in insp.get_indexes("evaluation_playground_runs") if i["column_names"]}:
        op.create_index("ix_evaluation_playground_runs_comparison_id", "evaluation_playground_runs", ["comparison_id"])
    from app.db.models import PromptExperiment, PromptTestCase, EvaluationTestCase
    for t in (PromptExperiment.__table__, PromptTestCase.__table__, EvaluationTestCase.__table__):
        t.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    from app.db.models import PromptExperiment, PromptTestCase, EvaluationTestCase
    for t in (EvaluationTestCase.__table__, PromptTestCase.__table__, PromptExperiment.__table__):
        t.drop(bind=bind, checkfirst=True)
    insp = sa.inspect(bind)
    if "ix_evaluation_playground_runs_comparison_id" in {i["name"] for i in insp.get_indexes("evaluation_playground_runs")}:
        op.drop_index("ix_evaluation_playground_runs_comparison_id", table_name="evaluation_playground_runs")
    for table, cols in _COLUMNS.items():
        have = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for name, _ in reversed(cols):
            if name in have:
                op.drop_column(table, name)

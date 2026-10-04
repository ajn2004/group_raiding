"""Persist candidate insights and independent surfacing decisions.

Revision ID: dal75insight01
Revises: dal72session001
"""
from alembic import op
import sqlalchemy as sa

revision = "dal75insight01"
down_revision = "dal72session001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coaching_sessions", sa.Column("candidate_insights", sa.JSON(), nullable=True))
    op.add_column("coaching_sessions", sa.Column("insight_gate_decisions", sa.JSON(), nullable=True))
    op.add_column("coaching_sessions", sa.Column("displayed_insight_ids", sa.JSON(), nullable=True))
    op.add_column("coaching_sessions", sa.Column("insight_provenance", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("coaching_sessions", "insight_provenance")
    op.drop_column("coaching_sessions", "displayed_insight_ids")
    op.drop_column("coaching_sessions", "insight_gate_decisions")
    op.drop_column("coaching_sessions", "candidate_insights")

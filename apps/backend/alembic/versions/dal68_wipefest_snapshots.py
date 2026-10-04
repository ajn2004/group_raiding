"""Store complete immutable Wipefest fight source snapshots.

Revision ID: dal68wf001
Revises: dal46pc001
"""
from alembic import op
import sqlalchemy as sa

revision = "dal68wf001"
down_revision = "dal46pc001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wipefest_fight_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("report_code", sa.String(255), nullable=False),
        sa.Column("fight_id", sa.String(100), nullable=False),
        sa.Column("group_id", sa.String(100), nullable=False),
        sa.Column("request_url", sa.String(), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_etag", sa.String(500), nullable=True),
        sa.UniqueConstraint("provider", "report_code", "fight_id", "group_id", "fingerprint",
                            name="uq_wipefest_snapshot_version"),
    )


def downgrade() -> None:
    op.drop_table("wipefest_fight_snapshots")

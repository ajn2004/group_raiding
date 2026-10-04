"""Persist reproducible coaching sessions and ordered conversation turns.

Revision ID: dal72session001
Revises: dal70coach001
"""
from alembic import op
import sqlalchemy as sa

revision = "dal72session001"
down_revision = "dal70coach001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coaching_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("wipefest_fight_snapshots.id"), nullable=False),
        sa.Column("report_code", sa.String(255), nullable=False),
        sa.Column("fight_id", sa.String(100), nullable=False),
        sa.Column("encounter_id", sa.String(255), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("target_player_id", sa.String(255)),
        sa.Column("target_player_name", sa.String(255)),
        sa.Column("context_schema_version", sa.String(100), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_context", sa.JSON(), nullable=False),
        sa.Column("profile_revision_id", sa.Integer(), sa.ForeignKey("coaching_profile_revisions.id"), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("requested_model", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("provider_response_id", sa.String(255)),
        sa.Column("actual_model", sa.String(255)),
        sa.Column("usage", sa.JSON()),
        sa.Column("cost", sa.JSON()),
        sa.Column("structured_response", sa.JSON()),
        sa.Column("raw_response", sa.JSON()),
        sa.Column("error", sa.JSON()),
        sa.CheckConstraint("audience IN ('raid', 'player')", name="ck_coaching_session_audience"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed', 'invalid_output')", name="ck_coaching_session_status"),
        sa.CheckConstraint("(audience = 'raid' AND target_player_id IS NULL) OR (audience = 'player' AND target_player_id IS NOT NULL)", name="ck_coaching_session_target"),
    )
    op.create_index("ix_coaching_sessions_snapshot", "coaching_sessions", ["snapshot_id"])
    op.create_index("ix_coaching_sessions_fight", "coaching_sessions", ["report_code", "fight_id", "created_at"])
    op.create_table(
        "coaching_session_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("coaching_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "sequence", name="uq_coaching_session_message_sequence"),
        sa.CheckConstraint("role IN ('system', 'user', 'assistant')", name="ck_coaching_session_message_role"),
        sa.CheckConstraint("sequence >= 0", name="ck_coaching_session_message_sequence"),
    )


def downgrade() -> None:
    op.drop_table("coaching_session_messages")
    op.drop_index("ix_coaching_sessions_fight", table_name="coaching_sessions")
    op.drop_index("ix_coaching_sessions_snapshot", table_name="coaching_sessions")
    op.drop_table("coaching_sessions")

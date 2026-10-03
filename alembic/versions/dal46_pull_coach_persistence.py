"""Persist Pull Coach reports, pulls, analyses and evidence.

Revision ID: dal46pc001
Revises: 3462650e10c1
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "dal46pc001"
down_revision = "3462650e10c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pull_coach_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("report_code", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("scope", "provider", "report_code", name="uq_pc_report_scope_provider_code"),
    )
    op.create_table(
        "pull_coach_pulls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("pull_coach_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encounter_id", sa.String(255), nullable=False),
        sa.Column("encounter_name", sa.String(255), nullable=False),
        sa.Column("fight_id", sa.String(255), nullable=False),
        sa.Column("pull_number", sa.Integer(), nullable=False),
        sa.Column("start_timestamp", sa.Integer(), nullable=False),
        sa.Column("end_timestamp", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(50), nullable=False),
        sa.Column("boss_percent", sa.Float(), nullable=True),
        sa.UniqueConstraint("report_id", "fight_id", name="uq_pc_pull_report_fight"),
    )
    op.create_table(
        "pull_coach_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pull_id", sa.Integer(), sa.ForeignKey("pull_coach_pulls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analyzer_name", sa.String(255), nullable=False),
        sa.Column("analyzer_version", sa.String(255), nullable=False),
        sa.Column("result_fingerprint", sa.String(64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("mechanic_observations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("pull_id", "analyzer_name", "analyzer_version", "result_fingerprint", name="uq_pc_analysis_identity"),
    )
    op.create_table(
        "pull_coach_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("pull_coach_analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.String(255), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(50), nullable=False),
        sa.Column("fact", sa.JSON(), nullable=False),
        sa.Column("mechanic_id", sa.String(255), nullable=True),
        sa.Column("actor_ids", sa.JSON(), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("related_finding_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("analysis_id", "finding_id", name="uq_pc_finding_analysis_id"),
    )
    op.create_table(
        "pull_coach_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_row_id", sa.Integer(), sa.ForeignKey("pull_coach_findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.String(255), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.UniqueConstraint("finding_row_id", "evidence_id", name="uq_pc_evidence_finding_id"),
    )
    op.create_table(
        "pull_coach_coaching_outputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("pull_coach_analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generator", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("template_version", sa.String(255), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("rendered_output", sa.String(), nullable=True),
    )
    op.create_index("ix_pc_pull_encounter_order", "pull_coach_pulls", ["encounter_id", "pull_number", "start_timestamp"])


def downgrade() -> None:
    op.drop_index("ix_pc_pull_encounter_order", table_name="pull_coach_pulls")
    op.drop_table("pull_coach_coaching_outputs")
    op.drop_table("pull_coach_evidence")
    op.drop_table("pull_coach_findings")
    op.drop_table("pull_coach_analyses")
    op.drop_table("pull_coach_pulls")
    op.drop_table("pull_coach_reports")

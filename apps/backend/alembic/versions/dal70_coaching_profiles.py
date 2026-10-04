"""Persist versioned coaching profiles and seed initial purposes.

Revision ID: dal70coach001
 Revises: dal68wf001
"""
from alembic import op
import sqlalchemy as sa

revision = "dal70coach001"
down_revision = "dal68wf001"
branch_labels = None
depends_on = None

SYSTEM_PROMPT = (
    "You are a grounded raid coach. Use only the supplied coaching context and cited evidence. "
    "Do not invent events, mechanics, player behavior, or causes. Be concise and actionable."
)
USER_TEMPLATE = "Use the supplied coaching input and return only data matching the configured output schema."


def upgrade() -> None:
    op.create_table(
        "coaching_profiles",
        sa.Column("purpose", sa.String(100), primary_key=True),
        sa.Column("active_revision_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "coaching_profile_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_purpose", sa.String(100), sa.ForeignKey("coaching_profiles.purpose", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_slug", sa.String(255), nullable=False),
        sa.Column("system_prompt", sa.String(), nullable=False),
        sa.Column("user_prompt_template", sa.String(), nullable=False),
        sa.Column("output_schema_version", sa.String(100), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_options", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.UniqueConstraint("profile_purpose", "revision", name="uq_coaching_profile_revision"),
    )
    with op.batch_alter_table("coaching_profiles") as batch:
        batch.create_foreign_key(
            "fk_coaching_profile_active_revision",
            "coaching_profile_revisions",
            ["active_revision_id"],
            ["id"],
        )
    # SQLite/PostgreSQL both support adding this nullable FK column.
    with op.batch_alter_table("pull_coach_coaching_outputs") as batch:
        batch.add_column(sa.Column("profile_revision_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_coaching_output_profile_revision",
                                 "coaching_profile_revisions", ["profile_revision_id"], ["id"])
    connection = op.get_bind()
    profiles = sa.table("coaching_profiles", sa.column("purpose", sa.String),
                         sa.column("active_revision_id", sa.Integer))
    revisions = sa.table("coaching_profile_revisions", sa.column("id", sa.Integer),
                         sa.column("profile_purpose", sa.String), sa.column("revision", sa.Integer),
                         sa.column("provider", sa.String), sa.column("model_slug", sa.String),
                         sa.column("system_prompt", sa.String), sa.column("user_prompt_template", sa.String),
                         sa.column("output_schema_version", sa.String), sa.column("temperature", sa.Float),
                         sa.column("max_output_tokens", sa.Integer), sa.column("provider_options", sa.JSON),
                         sa.column("created_by", sa.String))
    for purpose, model, schema in (
        ("raid_coach", "openai/gpt-4o-mini", "coaching-selection-v1"),
        ("player_coach", "openai/gpt-4o-mini", "player-coaching-v1"),
        ("insight_gate", "openai/gpt-4o-mini", "candidate-insight-gate-v1"),
    ):
        connection.execute(profiles.insert().values(purpose=purpose))
        revision_id = connection.execute(revisions.insert().values(
            profile_purpose=purpose, revision=1, provider="openrouter", model_slug=model,
            system_prompt=SYSTEM_PROMPT, user_prompt_template=USER_TEMPLATE,
            output_schema_version=schema, temperature=0.2, max_output_tokens=512,
            provider_options={}, created_by="system").returning(revisions.c.id)).scalar_one()
        connection.execute(profiles.update().where(profiles.c.purpose == purpose).values(
            active_revision_id=revision_id))


def downgrade() -> None:
    with op.batch_alter_table("pull_coach_coaching_outputs") as batch:
        batch.drop_constraint("fk_coaching_output_profile_revision", type_="foreignkey")
        batch.drop_column("profile_revision_id")
    with op.batch_alter_table("coaching_profiles") as batch:
        batch.drop_constraint("fk_coaching_profile_active_revision", type_="foreignkey")
    op.drop_table("coaching_profile_revisions")
    op.drop_table("coaching_profiles")

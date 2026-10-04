"""Add the core player and character tables to fresh migrated databases."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "dal91playerchar"
# DAL-92 joins the DAL-75 and DAL-89 branches. Keep the core-table bridge after
# that merge so the combined history has one head.
down_revision = "dal92merge01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These pre-existing guild tables predate Alembic. Preserve installations
    # where they were created by the legacy schema setup while adding them to
    # fresh databases.
    existing = set(inspect(op.get_bind()).get_table_names())
    if "players" not in existing:
        op.create_table(
            "players",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(80), nullable=False, unique=True),
            sa.Column("discord_id", sa.BigInteger()),
            sa.Column("piter_death_tokens", sa.Integer()),
            sa.Column("tokens_spent", sa.Integer(), server_default="0"),
            sa.Column("tokens_received", sa.Integer(), server_default="0"),
        )
    if "characters" not in existing:
        op.create_table(
            "characters",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("class_name", sa.String(50), nullable=False),
            sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
            sa.Column("mainAlt", sa.Boolean(), server_default=sa.false()),
        )


def downgrade() -> None:
    # Do not remove legacy durable player/character data on downgrade. These
    # tables may have existed before this bridge revision was introduced.
    pass

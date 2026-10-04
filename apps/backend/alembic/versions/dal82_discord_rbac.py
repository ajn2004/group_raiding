"""Map Discord community role IDs to application capabilities.

Revision ID: dal82rbac001
Revises: dal91playerchar
"""
from alembic import op
import sqlalchemy as sa

revision = "dal82rbac001"
down_revision = "dal91playerchar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_communities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("discord_guild_id", sa.String(100), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "discord_role_capabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("discord_communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("discord_role_id", sa.String(100), nullable=False),
        sa.Column("capability", sa.String(100), nullable=False),
        sa.UniqueConstraint("community_id", "discord_role_id", "capability", name="uq_discord_role_capability"),
    )
    op.create_index("ix_discord_role_capabilities_community", "discord_role_capabilities", ["community_id"])
    op.add_column("web_sessions", sa.Column("discord_access_token_ciphertext", sa.String(4096), nullable=True))
    op.add_column("web_sessions", sa.Column("discord_refresh_token_ciphertext", sa.String(4096), nullable=True))
    op.add_column("web_sessions", sa.Column("discord_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("web_sessions", sa.Column("community_guild_id", sa.String(100), nullable=True))
    op.add_column("web_sessions", sa.Column("membership_status", sa.String(32), nullable=False, server_default="unknown"))
    op.add_column("web_sessions", sa.Column("member_role_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("web_sessions", sa.Column("membership_refreshed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("web_sessions", "membership_refreshed_at")
    op.drop_column("web_sessions", "member_role_ids")
    op.drop_column("web_sessions", "membership_status")
    op.drop_column("web_sessions", "community_guild_id")
    op.drop_column("web_sessions", "discord_token_expires_at")
    op.drop_column("web_sessions", "discord_refresh_token_ciphertext")
    op.drop_column("web_sessions", "discord_access_token_ciphertext")
    op.drop_index("ix_discord_role_capabilities_community", table_name="discord_role_capabilities")
    op.drop_table("discord_role_capabilities")
    op.drop_table("discord_communities")

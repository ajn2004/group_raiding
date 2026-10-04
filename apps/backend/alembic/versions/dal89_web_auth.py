"""Move web authentication persistence into the shared relational database."""
from alembic import op
import sqlalchemy as sa

revision = "dal89webauth01"
down_revision = "dal72session001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("discord_user_id", sa.String(100), nullable=False, unique=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("avatar_url", sa.String(500)),
    )
    op.create_table(
        "web_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("web_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_web_sessions_expires_at", "web_sessions", ["expires_at"])
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("return_to", sa.String(2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_states_expires_at", "oauth_states", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_oauth_states_expires_at", table_name="oauth_states")
    op.drop_table("oauth_states")
    op.drop_index("ix_web_sessions_expires_at", table_name="web_sessions")
    op.drop_table("web_sessions")
    op.drop_table("web_identities")

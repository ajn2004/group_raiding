"""Merge the coaching insight and web-auth migration branches."""

revision = "dal92merge01"
down_revision = ("dal75insight01", "dal89webauth01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

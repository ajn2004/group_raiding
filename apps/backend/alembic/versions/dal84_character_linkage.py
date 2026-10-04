"""Allow unlinked observed characters and retain Wipefest provenance."""
from alembic import op
import sqlalchemy as sa

revision = "dal84linkage"
down_revision = "dal82rbac001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("characters") as batch:
        batch.alter_column("player_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("server", sa.String(100), nullable=True))
        batch.add_column(sa.Column("region", sa.String(32), nullable=True))
    op.create_table("character_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("wipefest_fight_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.String(100)),
        sa.UniqueConstraint("character_id", "snapshot_id", name="uq_character_observation_source"))
    op.create_index("ix_character_observations_character_id", "character_observations", ["character_id"])
    op.create_index("ix_character_observations_snapshot_id", "character_observations", ["snapshot_id"])


def downgrade():
    bind = op.get_bind()
    unlinked_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM characters WHERE player_id IS NULL")
    ).scalar_one()
    if unlinked_count:
        raise RuntimeError(
            "Cannot downgrade character linkage while unlinked characters exist"
        )
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("region")
        batch.drop_column("server")
        batch.alter_column("player_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("character_observations")

"""initialization

Revision ID: 73427d0ad7c9
Revises: 
Create Date: 2023-11-10 12:27:47.468286

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73427d0ad7c9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # These tables predate Alembic. Existing installations already marked this
    # revision as applied, so this establishes them only on fresh databases.
    op.create_table(
        'players',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False, unique=True),
        sa.Column('discord_id', sa.BigInteger()),
        sa.Column('piter_death_tokens', sa.Integer()),
        sa.Column('tokens_spent', sa.Integer(), default=0),
        sa.Column('tokens_received', sa.Integer(), default=0),
    )
    op.create_table(
        'characters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('class_name', sa.String(length=50), nullable=False),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('mainAlt', sa.Boolean(), default=False),
    )
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=50), nullable=False),
    )
    op.create_table(
        'specializations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.id'), nullable=False),
        sa.Column('gearscore', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), sa.ForeignKey('characters.id'), nullable=False),
    )
    op.create_table(
        'buffs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('raidscore', sa.Integer()),
        sa.Column('specialization_id', sa.Integer(), sa.ForeignKey('specializations.id'), nullable=False),
    )
    op.create_table(
        'usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('command', sa.String(length=100)),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id')),
        sa.Column('timestamp', sa.DateTime()),
    )
    op.create_index('ix_usage_timestamp', 'usage', ['timestamp'])
    op.create_table(
        'schedule',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('available', sa.Integer(), default=0),
    )


def downgrade() -> None:
    # Legacy baseline tables predate Alembic. Preserve the historical
    # downgrade semantics for already-migrated installations.
    pass

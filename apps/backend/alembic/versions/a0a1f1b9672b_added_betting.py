"""added betting

Revision ID: a0a1f1b9672b
Revises: 73427d0ad7c9
Create Date: 2023-11-10 12:28:29.861780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0a1f1b9672b'
down_revision: Union[str, None] = '73427d0ad7c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bet_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('eventName', sa.String(length=80), nullable=False),
        sa.Column('expiration', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'bet_outcomes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('betEvent', sa.Integer(), sa.ForeignKey('bet_events.id'), nullable=False),
        sa.Column('outNumber', sa.Integer(), nullable=False),
    )
    # The following historical revision adds the outcome FK.
    op.create_table(
        'bet',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('eventID', sa.Integer(), sa.ForeignKey('bet_events.id'), nullable=False),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('outcome', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('resolved', sa.Boolean(), default=False),
    )


def downgrade() -> None:
    op.drop_table('bet')
    op.drop_table('bet_outcomes')
    op.drop_table('bet_events')

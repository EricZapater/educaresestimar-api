"""add_is_blocked_and_block_reason_to_slots

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-16 11:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('available_slots', sa.Column('is_blocked', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('available_slots', sa.Column('block_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('available_slots', 'block_reason')
    op.drop_column('available_slots', 'is_blocked')

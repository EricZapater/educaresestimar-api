"""add_reservation_slots_table

Revision ID: c2a3b4d5e6f7
Revises: bc141127f8b8
Create Date: 2026-04-16 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c2a3b4d5e6f7'
down_revision: Union[str, None] = 'bc141127f8b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reservation_slots',
    sa.Column('reservation_id', sa.UUID(as_uuid=True), nullable=False),
    sa.Column('slot_id', sa.UUID(as_uuid=True), nullable=False),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['slot_id'], ['available_slots.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('reservation_id', 'slot_id')
    )

def downgrade() -> None:
    op.drop_table('reservation_slots')

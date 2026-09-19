"""add_session_type_and_reservation_shared_fields

Revision ID: d4e5f6a7b8c9
Revises: c2a3b4d5e6f7
Create Date: 2026-09-19 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c2a3b4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_shared, max_clients, description to session_types
    op.add_column('session_types', sa.Column('is_shared', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('session_types', sa.Column('max_clients', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.add_column('session_types', sa.Column('description', sa.Text(), nullable=True))

    # Add is_shared to reservations
    op.add_column('reservations', sa.Column('is_shared', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('reservations', 'is_shared')
    op.drop_column('session_types', 'description')
    op.drop_column('session_types', 'max_clients')
    op.drop_column('session_types', 'is_shared')

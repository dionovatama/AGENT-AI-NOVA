"""create agents table

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-11-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f607'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('os', sa.String(length=50), nullable=True),
    sa.Column('agent_version', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('connection_id', sa.UUID(), nullable=True),
    sa.Column('worker_id', sa.String(length=100), nullable=True),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_disconnected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_agents_owner_name')
    )
    op.create_index(op.f('ix_agents_owner_id'), 'agents', ['owner_id'], unique=False)
    op.create_index('ix_agents_status_last_heartbeat', 'agents', ['status', 'last_heartbeat_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agents_status_last_heartbeat', table_name='agents')
    op.drop_index(op.f('ix_agents_owner_id'), table_name='agents')
    op.drop_table('agents')

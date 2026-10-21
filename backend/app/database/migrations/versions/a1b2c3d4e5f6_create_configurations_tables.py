"""create_configurations_and_configuration_versions_tables

Revision ID: a1b2c3d4e5f6
Revises: 52ec33d4d8da
Create Date: 2026-10-21 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '52ec33d4d8da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create configurations table
    op.create_table(
        'configurations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('risk_level', sa.String(length=50), nullable=False),
        sa.Column('change_set', sa.JSON(), nullable=False),
        sa.Column('plan_hash', sa.String(length=64), nullable=False),
        sa.Column('state_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_configurations_owner_id'), 'configurations', ['owner_id'], unique=False)
    op.create_index(op.f('ix_configurations_device_id'), 'configurations', ['device_id'], unique=False)
    op.create_index(op.f('ix_configurations_status'), 'configurations', ['status'], unique=False)
    op.create_index(op.f('ix_configurations_created_at'), 'configurations', ['created_at'], unique=False)

    # 2. Create configuration_versions table
    op.create_table(
        'configuration_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('configuration_id', sa.UUID(), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('backup_ref', sa.JSON(), nullable=True),
        sa.Column('state_before', sa.JSON(), nullable=False),
        sa.Column('state_after', sa.JSON(), nullable=True),
        sa.Column('operation_results', sa.JSON(), nullable=True),
        sa.Column('verification_results', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['configuration_id'], ['configurations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_configuration_versions_configuration_id'), 'configuration_versions', ['configuration_id'], unique=False)
    op.create_index(op.f('ix_configuration_versions_owner_id'), 'configuration_versions', ['owner_id'], unique=False)
    op.create_index(op.f('ix_configuration_versions_device_id'), 'configuration_versions', ['device_id'], unique=False)
    op.create_index(op.f('ix_configuration_versions_created_at'), 'configuration_versions', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_configuration_versions_created_at'), table_name='configuration_versions')
    op.drop_index(op.f('ix_configuration_versions_device_id'), table_name='configuration_versions')
    op.drop_index(op.f('ix_configuration_versions_owner_id'), table_name='configuration_versions')
    op.drop_index(op.f('ix_configuration_versions_configuration_id'), table_name='configuration_versions')
    op.drop_table('configuration_versions')

    op.drop_index(op.f('ix_configurations_created_at'), table_name='configurations')
    op.drop_index(op.f('ix_configurations_status'), table_name='configurations')
    op.drop_index(op.f('ix_configurations_device_id'), table_name='configurations')
    op.drop_index(op.f('ix_configurations_owner_id'), table_name='configurations')
    op.drop_table('configurations')

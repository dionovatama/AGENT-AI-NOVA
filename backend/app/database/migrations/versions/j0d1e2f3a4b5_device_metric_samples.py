"""Store sanitized MikroTik metric samples.

Revision ID: j0d1e2f3a4b5
Revises: i9c0d1e2f3a4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "j0d1e2f3a4b5"
down_revision: Union[str, None] = "i9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_metric_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_load_percent", sa.Float(), nullable=True),
        sa.Column("memory_used_percent", sa.Float(), nullable=True),
        sa.Column("storage_used_percent", sa.Float(), nullable=True),
        sa.Column("interfaces", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_device_metric_samples_device_collected",
        "device_metric_samples", ["device_id", sa.text("collected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_device_metric_samples_device_collected", table_name="device_metric_samples")
    op.drop_table("device_metric_samples")

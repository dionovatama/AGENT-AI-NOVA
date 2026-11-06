"""Create relay_targets (backend side of the Agent TCP allow-list).

Revision ID: e5f607182930
Revises: d4e5f6071829
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f607182930"
down_revision: Union[str, None] = "d4e5f6071829"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "relay_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("ports", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "name", name="uq_relay_targets_agent_name"),
    )
    op.create_index("ix_relay_targets_owner_id", "relay_targets", ["owner_id"])
    op.create_index("ix_relay_targets_agent_id", "relay_targets", ["agent_id"])
    op.create_index("ix_relay_targets_device_id", "relay_targets", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_relay_targets_device_id", table_name="relay_targets")
    op.drop_index("ix_relay_targets_agent_id", table_name="relay_targets")
    op.drop_index("ix_relay_targets_owner_id", table_name="relay_targets")
    op.drop_table("relay_targets")

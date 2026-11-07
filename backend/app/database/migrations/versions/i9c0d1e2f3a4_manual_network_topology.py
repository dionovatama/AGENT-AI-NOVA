"""Persist manually arranged network topology nodes and links.

Revision ID: i9c0d1e2f3a4
Revises: h8b9c0d1e2f3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "i9c0d1e2f3a4"
down_revision: Union[str, None] = "h8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "topology_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False, server_default="other"),
        sa.Column("x", sa.Float(), nullable=False, server_default="80"),
        sa.Column("y", sa.Float(), nullable=False, server_default="80"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "device_id", name="uq_topology_nodes_owner_device"),
    )
    op.create_index("ix_topology_nodes_owner_id", "topology_nodes", ["owner_id"])
    op.create_index("ix_topology_nodes_device_id", "topology_nodes", ["device_id"])
    op.create_index("ix_topology_nodes_owner", "topology_nodes", ["owner_id"])

    op.create_table(
        "topology_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("connection_type", sa.String(30), nullable=False, server_default="ethernet"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "source_node_id", "target_node_id", name="uq_topology_link_pair"),
    )
    op.create_index("ix_topology_links_owner_id", "topology_links", ["owner_id"])
    op.create_index("ix_topology_links_owner", "topology_links", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_topology_links_owner", table_name="topology_links")
    op.drop_index("ix_topology_links_owner_id", table_name="topology_links")
    op.drop_table("topology_links")
    op.drop_index("ix_topology_nodes_owner", table_name="topology_nodes")
    op.drop_index("ix_topology_nodes_device_id", table_name="topology_nodes")
    op.drop_index("ix_topology_nodes_owner_id", table_name="topology_nodes")
    op.drop_table("topology_nodes")

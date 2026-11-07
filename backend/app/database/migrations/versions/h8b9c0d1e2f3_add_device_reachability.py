"""Add devices.reachability / last_checked_at / last_check_detail (Phase 6).

Hasil probe jangkauan lewat Remote Agent. Terpisah dari devices.status (status admin,
mis. "active"). Nilai awal "unknown" untuk semua baris lama.

Revision ID: h8b9c0d1e2f3
Revises: g7a8b9c0d1e2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "h8b9c0d1e2f3"
down_revision: Union[str, None] = "g7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("reachability", sa.String(length=20),
                                       nullable=False, server_default="unknown"))
    op.add_column("devices", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("last_check_detail", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "last_check_detail")
    op.drop_column("devices", "last_checked_at")
    op.drop_column("devices", "reachability")

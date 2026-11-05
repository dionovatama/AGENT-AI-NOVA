"""Add Remote Agent hostname metadata.

Revision ID: d4e5f6071829
Revises: c3d4e5f60718
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6071829"
down_revision: Union[str, None] = "c3d4e5f60718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("hostname", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "hostname")

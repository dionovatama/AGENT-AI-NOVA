"""Add relay_targets.tls_fingerprint (SHA-256 pin of the router API-SSL certificate).

Nullable on purpose: existing targets keep working for non-TLS use, but the MikroTik
remote path refuses a target without a pin (fail closed).

Revision ID: f60718293041
Revises: e5f607182930
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f60718293041"
down_revision: Union[str, None] = "e5f607182930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("relay_targets", sa.Column("tls_fingerprint", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("relay_targets", "tls_fingerprint")

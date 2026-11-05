"""Add authenticated-encryption columns for stored credentials.

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f60718"
down_revision: Union[str, None] = "b2c3d4e5f607"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("credentials", sa.Column("encrypted_secret", sa.Text(), nullable=True))
    op.add_column("credentials", sa.Column("encryption_nonce", sa.String(length=32), nullable=True))
    op.add_column("credentials", sa.Column("encryption_key_id", sa.String(length=100), nullable=True))
    # Keep the legacy column temporarily so existing rows can be migrated explicitly.
    with op.batch_alter_table("credentials") as batch_op:
        batch_op.alter_column("secret_reference", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Refuse silent loss of encrypted values when rolling back.
    bind = op.get_bind()
    encrypted_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM credentials WHERE encrypted_secret IS NOT NULL")
    ).scalar_one()
    if encrypted_count:
        raise RuntimeError(
            "Cannot downgrade: encrypted credentials exist. Export/re-encrypt them before downgrade."
        )
    with op.batch_alter_table("credentials") as batch_op:
        batch_op.alter_column("secret_reference", existing_type=sa.String(length=255), nullable=False)
        batch_op.drop_column("encryption_key_id")
        batch_op.drop_column("encryption_nonce")
        batch_op.drop_column("encrypted_secret")

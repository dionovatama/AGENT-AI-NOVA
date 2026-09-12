"""
Database models — Milestone 1 hanya berisi User.

Model Device, Credential, ToolExecution, AuditLog, dll akan ditambahkan
pada milestone berikutnya sesuai roadmap. Jangan menambahkan model
di luar scope milestone ini.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.database.session import Base


class User(Base):
    __tablename__ = "users"

    # UUID, bukan sequential integer — mencegah enumerasi user antar tenant.
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Hanya hash yang disimpan. Password plaintext tidak pernah menyentuh DB.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        # Sengaja tidak menampilkan hashed_password di repr untuk mencegah
        # kebocoran tidak sengaja lewat log/debug output.
        return f"<User id={self.id} email={self.email}>"

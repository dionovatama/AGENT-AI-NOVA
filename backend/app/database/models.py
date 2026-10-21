"""
Database models — N.O.V.A Foundation Models.

Tabel:
- User: Pengguna dan kredensial akses API/JWT.
- Credential: Abstraksi referensi secret (SSH key, token, dll), tidak menyimpan plaintext secret.
- Device: Perangkat target yang dikelola (Linux, Windows, MikroTik, Cisco) dengan isolasi owner.
- AuditLog: Catatan audit persisten atas semua lifecycle eksekusi tool/tindakan sistem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

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


class Credential(Base):
    """
    Abstraksi referensi credential aman.

    PENTING:
    - Tidak menyimpan password/private key plaintext di dalam kolom ini.
    - 'secret_reference' adalah referensi ke secret manager/keystore terkontrol
      (misal: path file yang diproteksi atau ID vault).
    - Konten credential tidak pernah dikirim ke LLM.
    """
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # ssh_key, password, api_token
    secret_reference: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Credential id={self.id} name={self.name} type={self.type} owner_id={self.owner_id}>"


class Device(Base):
    """
    Model database untuk perangkat target yang dikelola.
    Mendukung tenant/owner isolation: setiap device dimiliki oleh owner_id spesifik.
    """
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # linux, windows, mikrotik, cisco
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    connection_type: Mapped[str] = mapped_column(String(50), default="ssh", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)

    # Kolom di DB bernama "metadata", atribut Python bernama device_metadata
    # karena nama 'metadata' di kelas model adalah atribut khusus MetaData SQLAlchemy.
    device_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Device id={self.id} name={self.name} platform={self.platform} host={self.host}>"


class AuditLog(Base):
    """
    Catatan audit persisten atas tool execution dan operasi sistem.
    Semua request_metadata disanitasi sebelum disimpan (Zero Secret Exposure).
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True
    )

    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    permission: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    request_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_status: Mapped[str] = mapped_column(String(50), nullable=False)  # REQUESTED, AUTHORIZED, DENIED, SUCCESS, FAILED, TIMEOUT
    verification_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} tool={self.tool_name} status={self.result_status}>"


class Configuration(Base):
    """
    Model database untuk proposal dan lifecycle konfigurasi perangkat jaringan
    (PRD section 19-23, 33: Network Configuration Engine & Rollback).
    Mendukung tenant isolation (owner_id).
    """
    __tablename__ = "configurations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, default="DRAFT"
    )

    risk_level: Mapped[str] = mapped_column(String(50), nullable=False, default="LOW")

    change_set: Mapped[dict] = mapped_column(JSON, nullable=False)

    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Configuration id={self.id} device_id={self.device_id} status={self.status} risk={self.risk_level}>"


class ConfigurationVersion(Base):
    """
    Riwayat eksekusi, backup fisik/native, snapshot state, dan bukti verifikasi
    per configuration plan (PRD section 22, 33).
    """
    __tablename__ = "configuration_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    configuration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )

    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # backup_ref: {"path": str, "sha256": str, "size_bytes": int, "backup_type": str}
    backup_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # State nyata sebelum dan setelah perubahan (ter-sanitasi, zero secret exposure)
    state_before: Mapped[dict] = mapped_column(JSON, nullable=False)
    state_after: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Hasil per operasi (termasuk ID objek di RouterOS untuk rollback terbalik)
    operation_results: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Hasil verifikasi paska-apply/paska-rollback dari state nyata perangkat
    verification_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<ConfigurationVersion id={self.id} config_id={self.configuration_id} version={self.version_number}>"

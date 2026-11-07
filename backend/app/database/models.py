"""
Database models — N.O.V.A Foundation Models.

Tabel:
- User: Pengguna dan kredensial akses API/JWT.
- Credential: Abstraksi referensi secret (SSH key, token, dll), tidak menyimpan plaintext secret.
- Device: Perangkat target yang dikelola (Linux, Windows, MikroTik, Cisco) dengan isolasi owner.
- AuditLog: Catatan audit persisten atas semua lifecycle eksekusi tool/tindakan sistem.
- Agent: Remote Agent di jaringan lokal user (Phase A) -- identitas, hash token, dan state koneksi.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, desc
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
    - Secret baru disimpan sebagai ciphertext AES-256-GCM.
    - secret_reference hanya dipertahankan nullable untuk migrasi data lama.
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
    # Kolom legacy; harus NULL setelah migrasi. Tidak digunakan untuk eksekusi.
    secret_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_nonce: Mapped[str | None] = mapped_column(String(32), nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

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

    # Hasil probe jangkauan lewat Remote Agent (Phase 6). BUKAN status admin di atas.
    # reachability: online | offline | unknown. Data bisa basi -> lihat last_checked_at.
    reachability: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown", nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)

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


class DeviceMetricSample(Base):
    """Sanitized time-series metrics only; never stores raw RouterOS payloads."""
    __tablename__ = "device_metric_samples"
    __table_args__ = (
        Index("ix_device_metric_samples_device_collected", "device_id", desc("collected_at")),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cpu_load_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_used_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_used_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    interfaces: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


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


class Agent(Base):
    """
    Remote Agent (Phase A) -- jembatan aman NOVA Cloud <-> jaringan lokal user.

    State koneksi disimpan di DB (bukan dict memori) supaya semua worker
    backend melihat kebenaran yang sama:
    - 'connection_id' = kepemilikan koneksi saat ini. Semua penulisan state
      oleh handler WebSocket kondisional pada kolom ini, sehingga koneksi
      lama / worker lain tidak bisa menimpa koneksi baru.
    - 'status' hanyalah klaim terakhir pemilik koneksi; status yang
      ditampilkan dihitung lewat app.agents.states.effective_status()
      (kesegaran 'last_heartbeat_at').
    - Hanya HASH token yang disimpan; token plaintext tampil sekali saat
      dibuat/di-rotate.
    """
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_agents_owner_name"),
        Index("ix_agents_status_last_heartbeat", "status", "last_heartbeat_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="offline")
    connection_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
        # Sengaja tanpa token_hash.
        return f"<Agent id={self.id} name={self.name} status={self.status} owner_id={self.owner_id}>"


class RelayTarget(Base):
    """
    Tujuan TCP yang boleh dijangkau lewat Remote Agent (Phase 4/5).

    'id' adalah target_id yang dikirim di OPEN_TUNNEL. Backend TIDAK pernah
    mengirim host/IP ke Agent; Agent memetakan target_id ke host dari config
    lokalnya sendiri (allow-list). Baris ini adalah sisi backend dari daftar
    yang sama: siapa pemiliknya, lewat Agent mana, port apa saja.
    """
    __tablename__ = "relay_targets"
    __table_args__ = (
        UniqueConstraint("agent_id", "name", name="uq_relay_targets_agent_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    ports: Mapped[list] = mapped_column(JSON, nullable=False)
    # SHA-256 (64 hex, huruf kecil) sertifikat API-SSL router. Dipakai backend untuk
    # memin TLS lewat relay; jalur remote MikroTik menolak target tanpa pin.
    tls_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Conversation(Base):
    """A conversation owned by one authenticated account."""
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_updated", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class ConversationMessage(Base):
    """Persisted chat message; metadata contains JSON-safe display attributes only."""
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_conversation_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )


class TopologyNode(Base):
    """Node yang digambar admin pada manual network topology."""
    __tablename__ = "topology_nodes"
    __table_args__ = (
        Index("ix_topology_nodes_owner", "owner_id"),
        UniqueConstraint("owner_id", "device_id", name="uq_topology_nodes_owner_device"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    x: Mapped[float] = mapped_column(Float, nullable=False, default=80)
    y: Mapped[float] = mapped_column(Float, nullable=False, default=80)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class TopologyLink(Base):
    """Koneksi manual antar node; bukan hasil discovery/scanning."""
    __tablename__ = "topology_links"
    __table_args__ = (
        Index("ix_topology_links_owner", "owner_id"),
        UniqueConstraint("owner_id", "source_node_id", "target_node_id", name="uq_topology_link_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    connection_type: Mapped[str] = mapped_column(String(30), nullable=False, default="ethernet")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

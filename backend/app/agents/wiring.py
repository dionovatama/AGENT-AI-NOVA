"""Perakitan instance produksi: settings + SqlAgentStore + audit DB."""

from __future__ import annotations

import asyncio
import uuid

from app.agents.manager import AgentConnectionManager, AgentRuntimeConfig
from app.agents.sql_store import SqlAgentStore
from app.config import settings
from app.security.audit import record_audit_event


def build_runtime_config() -> AgentRuntimeConfig:
    require_tls = settings.agent_require_tls
    if require_tls is None:
        # Secure by default: wajib TLS di production, longgar di development.
        require_tls = settings.app_env.lower() == "production"
    return AgentRuntimeConfig(
        auth_timeout_seconds=settings.agent_auth_timeout_seconds,
        heartbeat_interval_seconds=settings.agent_heartbeat_interval_seconds,
        heartbeat_timeout_seconds=settings.agent_heartbeat_timeout_seconds,
        max_message_bytes=settings.agent_max_message_bytes,
        require_tls=require_tls,
        heartbeat_min_db_interval_seconds=settings.agent_heartbeat_min_db_interval_seconds,
        sweep_interval_seconds=settings.agent_sweep_interval_seconds,
        auth_fail_limit=settings.agent_auth_fail_limit,
        auth_fail_window_seconds=settings.agent_auth_fail_window_seconds,
        max_pending_auth_per_ip=settings.agent_max_pending_auth_per_ip,
        max_messages_per_window=settings.agent_max_messages_per_window,
        message_window_seconds=settings.agent_message_window_seconds,
    )


async def _audit_to_db(*, action, result_status, owner_id, agent_id: uuid.UUID, metadata, error=None) -> None:
    await asyncio.to_thread(
        record_audit_event,
        action=action,
        result_status=result_status,
        user_id=owner_id,
        request_metadata={"agent_id": str(agent_id), **metadata},
        error_message=error,
    )


# Dibuat saat import: validasi konfigurasi gagal-cepat (ValueError) ketika
# aplikasi start, bukan saat agent pertama connect.
agent_manager = AgentConnectionManager(
    store=SqlAgentStore(),
    cfg=build_runtime_config(),
    audit=_audit_to_db,
)

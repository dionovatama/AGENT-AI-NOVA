"""
N.O.V.A Backend — Entry Point
Milestone 4: Linux Executor (SSH) + Phase 5: MikroTik (diagnostic, READ-only)

Client → FastAPI → Auth → PostgreSQL
                  → AI Gateway (OpenRouter)
                  → Tool Manager → Executor (ping, linux.*, web.*, mikrotik.*)
"""

import asyncio
import logging
import sys
from app.api import auth, chat, configurations, devices, tools, mikrotik_generator, images, linux_generator, agent, agents, agent_targets, conversations, network, mikrotik_monitoring

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, validate_production_settings
from app.security.http_hardening import HttpHardeningMiddleware
from app.tools.manager import tool_manager
from app.tools.network import ping_tool
from app.tools.linux import (
    system_info_tool,
    network_info_tool,
    disk_info_tool,
    memory_info_tool,
    service_status_tool,
    process_status_tool,
    docker_status_tool,
    log_check_tool,
)
from app.tools.mikrotik import (
    system_resource_tool,
    interface_status_tool,
    ip_address_tool,
    route_table_tool,
    arp_table_tool,
    dhcp_leases_tool,
    firewall_rules_tool,
)
from app.tools.web import web_search_tool, web_read_page_tool
from app.tools.diagram import diagram_create_tool
from app.security.audit_retention import audit_retention_loop
from app.agents.wiring import agent_manager
from app.agents.worker_guard import validate_single_worker_relay
from app.network.device_executor import shutdown_device_executor

logger = logging.getLogger("nova.startup")
_audit_retention_task: asyncio.Task | None = None

app = FastAPI(
    title=settings.app_name,
    description="Nexus Operation Virtual Assistant — Backend API",
    version="0.4.0-milestone4",
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(network.router)  # Phase 6: topology nyata + refresh status device
app.include_router(mikrotik_monitoring.router)  # Read-only RouterOS v6/v7 live monitoring
app.include_router(tools.router)
app.include_router(devices.router)
app.include_router(configurations.router)
app.include_router(mikrotik_generator.router)
app.include_router(linux_generator.router)
app.include_router(images.router)
app.include_router(agent.router)   # legacy Phase 1 static-token gateway (/agent/ws), unchanged
app.include_router(agent_targets.router)  # Phase 4: relay target allow-list per agent
app.include_router(agents.router)  # Phase A: DB-backed agents (REST /agents + WS /ws/agent/{id})

tool_manager.register(ping_tool)
tool_manager.register(system_info_tool)
tool_manager.register(network_info_tool)
tool_manager.register(disk_info_tool)
tool_manager.register(memory_info_tool)
tool_manager.register(service_status_tool)
tool_manager.register(process_status_tool)
tool_manager.register(docker_status_tool)
tool_manager.register(log_check_tool)
tool_manager.register(web_search_tool)
tool_manager.register(web_read_page_tool)
tool_manager.register(diagram_create_tool)

# MikroTik (Phase 5) — diagnostic READ-only, semuanya requires_device=True:
# request WAJIB menyertakan device_id (device platform 'mikrotik' milik user,
# didaftarkan lewat POST /devices + POST /credentials). Sengaja TIDAK masuk
# _CATEGORY_TOOL_ALLOWLIST di app/ai/tool_calling.py — LLM belum boleh
# memanggil tool berbasis device lewat /chat; hanya lewat POST /tools/execute.
tool_manager.register(system_resource_tool)
tool_manager.register(interface_status_tool)
tool_manager.register(ip_address_tool)
tool_manager.register(route_table_tool)
tool_manager.register(arp_table_tool)
tool_manager.register(dhcp_leases_tool)
tool_manager.register(firewall_rules_tool)

# Tool Konfigurasi MikroTik (internal_only=True) — dieksekusi hanya oleh Orchestrator
from app.tools.mikrotik_config import mikrotik_config_apply_tool
tool_manager.register(mikrotik_config_apply_tool)

# Linux configuration writer is internal-only and can only be called by the orchestrator.
from app.tools.linux_config import linux_config_apply_tool
tool_manager.register(linux_config_apply_tool)


@app.on_event("startup")
async def start_background_tasks():
    """
    Retention policy audit_logs (PRD section 32/33) — purge otomatis
    baris lebih tua dari AUDIT_LOG_RETENTION_DAYS, jalan di background
    selama aplikasi hidup. Lihat app/security/audit_retention.py untuk
    rasional kenapa ini otomatis, bukan tombol hapus manual.
    """
    global _audit_retention_task
    validate_production_settings(settings)
    validate_single_worker_relay()
    if settings.app_env.lower() == "production" and settings.allow_unpinned_local_tls:
        logger.warning("SECURITY: ALLOW_UNPINNED_LOCAL_TLS is enabled; local MikroTik API-SSL peers are not certificate-pinned.")
    _audit_retention_task = asyncio.create_task(audit_retention_loop(), name="nova-audit-retention")
    # Remote Agent Phase A: sweeper untuk status agent basi (idempoten, per worker).
    agent_manager.start()


@app.on_event("shutdown")
async def stop_agent_manager():
    """Tutup koneksi Agent, hentikan background task, dan drain executor."""
    global _audit_retention_task
    await agent_manager.shutdown()
    if _audit_retention_task is not None:
        _audit_retention_task.cancel()
        await asyncio.gather(_audit_retention_task, return_exceptions=True)
        _audit_retention_task = None
    await asyncio.to_thread(shutdown_device_executor, True)


@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint — memverifikasi service backend hidup."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


# Wrap the complete ASGI application (rather than only adding an inner
# middleware) so CORS headers are also present on unhandled error responses.
# Include both common local frontend hostnames; credentials remain enabled
# for the Bearer-authenticated API and future cookie-based auth.
# Instance FastAPI asli tetap dapat diakses (dependency_overrides untuk tes, dsb.);
# `app` di bawah adalah pembungkus ASGI, bukan FastAPI.
app.add_middleware(HttpHardeningMiddleware)
fastapi_app = app
app = CORSMiddleware(
    app,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

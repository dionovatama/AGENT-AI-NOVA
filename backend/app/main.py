"""
N.O.V.A Backend — Entry Point
Milestone 4: Linux Executor (SSH) + Phase 5: MikroTik (diagnostic, READ-only)

Client → FastAPI → Auth → PostgreSQL
                  → AI Gateway (OpenRouter)
                  → Tool Manager → Executor (ping, linux.*, web.*, mikrotik.*)
"""

import asyncio
import sys
from app.api import auth, chat, configurations, devices, tools, mikrotik_generator, images, linux_generator, bind9_generator

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import auth, chat, configurations, devices, tools, mikrotik_generator
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

app = FastAPI(
    title=settings.app_name,
    description="Nexus Operation Virtual Assistant — Backend API",
    version="0.4.0-milestone4",
)

# CORS — diperlukan agar console frontend (Next.js, localhost:3000) bisa
# memanggil backend ini dari browser. Tanpa ini browser menolak request
# lintas-origin sebelum sempat sampai ke endpoint mana pun.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(tools.router)
app.include_router(devices.router)
app.include_router(configurations.router)
app.include_router(mikrotik_generator.router)
app.include_router(linux_generator.router)
app.include_router(bind9_generator.router)
app.include_router(images.router)

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
    asyncio.create_task(audit_retention_loop())


@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint — memverifikasi service backend hidup."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
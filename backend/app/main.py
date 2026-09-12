"""
N.O.V.A Backend — Entry Point
Milestone 4: Linux Executor (SSH)

Client → FastAPI → Auth → PostgreSQL
                  → AI Gateway (OpenRouter)
                  → Tool Manager → Executor (ping, linux.*)
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI

from app.config import settings
from app.api import auth, chat, tools
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

app = FastAPI(
    title=settings.app_name,
    description="Nexus Operation Virtual Assistant — Backend API",
    version="0.4.0-milestone4",
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(tools.router)

tool_manager.register(ping_tool)
tool_manager.register(system_info_tool)
tool_manager.register(network_info_tool)
tool_manager.register(disk_info_tool)
tool_manager.register(memory_info_tool)
tool_manager.register(service_status_tool)
tool_manager.register(process_status_tool)
tool_manager.register(docker_status_tool)
tool_manager.register(log_check_tool)


@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint — memverifikasi service backend hidup."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
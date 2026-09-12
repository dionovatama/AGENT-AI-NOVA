"""
N.O.V.A Backend — Entry Point
Milestone 1: Backend Foundation

Client → FastAPI → Auth → PostgreSQL

Belum ada di sini: OpenRouter, Tool Manager, executor apa pun.
"""

from fastapi import FastAPI

from app.config import settings
from app.api import auth, chat

app = FastAPI(
    title=settings.app_name,
    description="Nexus Operation Virtual Assistant — Backend API",
    version="0.2.0-milestone2",
)

app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint — memverifikasi service backend hidup."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }

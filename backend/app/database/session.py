"""
Database session management.

Database URL diambil dari environment melalui app.config.settings,
bukan hardcoded di source code.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

_engine_options = {"pool_pre_ping": True}
if not settings.database_url.lower().startswith("sqlite"):
    _engine_options.update({
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
    })
engine = create_engine(settings.database_url, **_engine_options)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class untuk seluruh ORM model NOVA."""
    pass


def get_db():
    """
    FastAPI dependency untuk mendapatkan DB session per-request.
    Session selalu ditutup setelah request selesai, termasuk saat error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

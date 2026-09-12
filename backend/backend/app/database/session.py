"""
Database session management.

Database URL diambil dari environment melalui app.config.settings,
bukan hardcoded di source code.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

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

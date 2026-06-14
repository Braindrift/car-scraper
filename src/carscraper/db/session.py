"""SQLAlchemy engine, session factory, and declarative base.

This module owns *how* we connect to the database. It contains no business
logic and no model definitions (those live in `db/models.py`).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from carscraper.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _connect_args(database_url: str) -> dict[str, object]:
    """SQLite needs `check_same_thread=False` for use across threads/sessions."""
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for the given (or configured) database URL."""
    url = database_url or settings.database_url
    return create_engine(url, connect_args=_connect_args(url))


# Module-level engine/session factory used by the application at large.
engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a `Session`, closing it on exit.

    Usage:
        with get_session() as session:
            session.add(obj)
            session.commit()
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

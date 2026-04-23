"""Async SQLAlchemy session factory.

``engine`` and ``async_sessionmaker`` are created lazily so unit tests
can override them before the real DB is touched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from grabarr.core.config import get_settings

__all__ = [
    "get_engine",
    "get_sessionmaker",
    "session_scope",
    "close_engine",
    "reset_engine",
]


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _database_url() -> str:
    """Build the SQLite URL from :func:`grabarr.core.config.get_settings`."""
    settings = get_settings()
    data_dir = Path(settings.server.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir}/grabarr.db"


def get_engine() -> AsyncEngine:
    """Return the process-wide ``AsyncEngine``, creating on first call."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(_database_url(), pool_pre_ping=True, future=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Commit-on-exit, rollback-on-exception session context."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Dispose the engine (called on app shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def reset_engine() -> None:
    """Test-only: clear the cached engine/sessionmaker."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
